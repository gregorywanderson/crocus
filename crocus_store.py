"""
crocus_store.py

Build and read a static, precomputed 5-minute archive of historic CROCUS
weather (WXT) and air-quality (AQT) data.

Why this module exists
----------------------
Historic WXT data on Sage/Waggle was sampled at >1 Hz. Querying it over long
temporal baselines is prohibitively slow. This module backfills that historic
data ONCE into per-site, per-instrument NetCDF files at a consistent 5-minute
resolution, so that students and collaborators can load and study it quickly
without ever touching the slow raw query.

For genuinely recent data (post-transition, already 5-min on Sage), use the
fast standard queries in sage_utils (query_wxt / query_aqt) instead. This
archive is intentionally a frozen historic product, not a living store.

The (time, statistic) tensor
----------------------------
Each physical variable (temp, humidity, ...) is stored as an xarray data
variable with dimensions (time, statistic), where statistic is the labeled
coordinate ['mean', 'count', 'std']:

  - mean  : the 5-minute average (the value most analyses want)
  - count : number of raw samples that fell in the bin
  - std   : standard deviation of raw samples within the bin

`count` is the key QC field. A healthy historic WXT bin has ~3000 samples;
a bin built from a handful of samples is a telemetry gap or sensor problem
that would otherwise be invisible. `count` over time also reveals the
>1Hz -> 5-min transition date directly, per node, from fast local data:
plot count vs time and look for the cliff from ~3000 to ~1.

File naming
-----------
    {abbr}_{instrument}_5min.nc      e.g.  NEIU_wxt_5min.nc

One site, one instrument per file. WXT is the priority product (it is the
data that *must* be precomputed). AQT is included for convenience but can be
skipped per node.

Usage
-----
    from crocus_sites import NEIU, ALL_SITES
    import crocus_store as cs

    # --- Build (one-time backfill) ---
    cs.build_site(NEIU, instrument='wxt', outdir=DEFAULT_OUTDIR)
    # or the whole network:
    for site in ALL_SITES:
        cs.build_site(site, instrument='wxt', outdir=DEFAULT_OUTDIR)

    # --- Read (what students/collaborators call) ---
    ds = cs.load(NEIU, 'wxt', start='2024-06-01', end='2024-09-01',
                 outdir=DEFAULT_OUTDIR)
    temp = ds['temp'].sel(statistic='mean').to_series()   # a clean pandas Series
"""

# Standard library
import datetime as dt
import logging
import os
import time
from urllib.error import HTTPError

# Third party
import numpy as np
import pandas as pd
import xarray as xr
import sage_data_client

# Local
from sage_utils import SAGE_MISSING
from crocus_sites import TEROS_DEPTHS  # noqa: F401  (kept for parity / future use)

DEFAULT_OUTDIR = 'data/sage_resampled'

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

RESAMPLE_INTERVAL = '5min'
STATISTICS = ['mean', 'count', 'std']   # the statistic axis, shared by all vars

# Outage handling for build_site (see its docstring). A single failing chunk is
# treated as an isolated bad window (skipped, logged, retried on a later run).
# But OUTAGE_CONSECUTIVE failures in a row are read as a Sage service outage:
# the build then sleeps OUTAGE_WAIT_SECONDS and retries the SAME chunk, rather
# than burning through the backlog marking good data as failed. It keeps doing
# this until a fetch succeeds (which resets everything) or until the total time
# spent waiting since the last success reaches OUTAGE_GIVEUP_SECONDS, at which
# point it exits cleanly so the run can be resumed later.

OUTAGE_CONSECUTIVE = 3
OUTAGE_WAIT_SECONDS = 30 * 60          # 30 minutes
OUTAGE_GIVEUP_SECONDS = 12 * 60 * 60   # 12 hours

# Module logger. build_site routes progress here so an unattended run has a
# single timestamped record (chunks, warnings, outage waits) instead of split
# print()/logging output. Callers that configure logging (e.g. the CLI) will
# see these; if nothing is configured, a NullHandler keeps it quiet.
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Per-instrument column definitions. The 'names' filter is the raw Sage query
# (NO resampling — we want every high-frequency sample so we can compute count
# and std honestly). 'columns' maps the pivoted Sage variable names to the
# tidy output names, in order. 'units' documents each output variable.
INSTRUMENTS = {
    
    'wxt': {
        'filter': (
            'wxt.env.humidity|wxt.env.pressure|wxt.env.temp|'
            'wxt.rain.accumulation|wxt.wind.direction|wxt.wind.speed'
        ),
        # pivot sorts columns alphabetically by Sage name; map accordingly
        'columns': {
            'wxt.env.humidity':       'humidity',
            'wxt.env.pressure':       'pressure',
            'wxt.env.temp':           'temp',
            'wxt.rain.accumulation':  'rain',
            'wxt.wind.direction':     'wind_dir',
            'wxt.wind.speed':         'wind_speed',
        },
        'units': {
            'humidity':   'percent',
            'pressure':   'hPa',
            'temp':       'degree_Celsius',
            'rain':       'mm',
            'wind_speed': 'm s-1',
            'wind_u':     'm s-1',
            'wind_v':     'm s-1',
        },
        'has_flag': 'has_wxt',
    },
    
    'aqt': {
        'filter': 'aqt.*',
        'columns': {
            'aqt.env.humidity':   'humidity',
            'aqt.env.pressure':   'pressure',
            'aqt.env.temp':       'temp',
            'aqt.gas.co':         'co',
            'aqt.gas.no':         'no',
            'aqt.gas.no2':        'no2',
            'aqt.gas.ozone':      'o3',
            'aqt.particle.pm1':   'pm1',
            'aqt.particle.pm10':  'pm10',
            'aqt.particle.pm2.5': 'pm25',
        },
        'units': {
            'humidity': 'percent',
            'pressure': 'hPa',
            'temp':     'degree_Celsius',
            'co':       'ppm',
            'no':       'ppm',
            'no2':      'ppm',
            'o3':       'ppm',
            'pm1':      'ug m-3',
            'pm10':     'ug m-3',
            'pm25':     'ug m-3',
        },
        # exclude housekeeping fields that 'aqt.*' would otherwise sweep in
        'exclude': {'aqt.house.datetime', 'aqt.house.uptime'},
        'has_flag': 'has_aqt',
    },
}


# ---------------------------------------------------------------------------
# Rain accumulation helper
# ---------------------------------------------------------------------------

def _rain_increment(rain_raw, time_index, resample=RESAMPLE_INTERVAL):
    """Per-bin rainfall (mm) from a cumulative-counter rain series.

    The WXT reports rain as a running total, so the rainfall in a bin is the
    rise of the counter across that bin, NOT the mean of the counter. We diff
    the raw monotone series and sum only the positive increments into each
    bin: this captures rain that falls across bin seams and treats any counter
    reset (negative diff, e.g. rollover or power cycle) as contributing zero
    rather than a large negative step. This matches the .diff().clip(lower=0)
    convention used downstream in crocus_precip, so the stored value is the
    already-differenced per-bin increment (do not diff it again on read).

    Returns a Series indexed like time_index (left-labeled bins), reindexed to
    match so it slots straight into the tensor.
    """
    inc = rain_raw.sort_index().diff()
    inc = inc.where(inc > 0, 0.0)          # drop resets / noise-negative steps
    binned = inc.resample(resample).sum()
    return binned.reindex(time_index)


# ---------------------------------------------------------------------------
# Stage 1 — raw fetch (no resampling)
# ---------------------------------------------------------------------------

def fetch_raw(site, instrument, start, end):
    """
    Query RAW (unsampled) instrument data for one site and time window.

    Unlike sage_utils.query_wxt/query_aqt, this does NOT resample — we need
    every high-frequency sample so aggregate_bins can compute honest count
    and std per bin.

    Returns a long-format DataFrame as returned by sage_data_client (columns
    include 'timestamp', 'name', 'value', plus meta.*), or an empty DataFrame.

    Transient server errors (HTTP 5xx) are retried with exponential backoff,
    since a long backfill issues many queries and Sage occasionally returns a
    500 for reasons unrelated to the request. A zero-width window (start ==
    end) is itself a 500 from Sage; callers should avoid issuing those.
    """
    spec = INSTRUMENTS[instrument]
    max_retries = 4
    for attempt in range(max_retries):
        try:
            df = sage_data_client.query(
                start=start,
                end=end,
                filter={'name': spec['filter'], 'vsn': site.vsn},
            )
            break
        except HTTPError as e:
            # Retry only transient server-side errors; re-raise client errors.
            if e.code >= 500 and attempt < max_retries - 1:
                wait = 2 ** attempt          # 1, 2, 4 seconds
                time.sleep(wait)
                continue
            raise
    if df.empty:
        return df
    if 'exclude' in spec:
        df = df[~df['name'].isin(spec['exclude'])]
    return df


# ---------------------------------------------------------------------------
# Stage 2 — aggregate to 5-min (time, statistic) tensor   [pure function]
# ---------------------------------------------------------------------------

def aggregate_bins(df_raw, instrument, resample=RESAMPLE_INTERVAL):
    """
    Aggregate raw long-format Sage data into a 5-minute (time x statistic)
    tensor as an xarray.Dataset.

    Pure function: no I/O, no network. This is the testable core.

    For each physical variable, computes mean / count / std over the raw
    samples in each 5-minute bin. count is computed on the RAW values (after
    the SAGE_MISSING -> NaN replacement) so it reflects genuine valid samples.

    Returns
    -------
    xr.Dataset with:
        dim   time       (5-min, left-labeled, UTC)
        dim   statistic  ['mean','count','std']
        vars  one per physical variable, each dims (time, statistic)
    Returns an empty Dataset if df_raw is empty.
    """
    spec = INSTRUMENTS[instrument]

    if df_raw.empty:
        return xr.Dataset()

    # Long -> wide, one column per physical variable
    df_wide = df_raw.pivot_table(
        index='timestamp', columns='name', values='value', aggfunc='mean'
    ).astype(float)
    df_wide = df_wide.replace(SAGE_MISSING, float('nan'))
    df_wide.index = pd.to_datetime(df_wide.index, utc=True)

    # Keep only known columns, rename to tidy names, order deterministically
    keep = [c for c in spec['columns'] if c in df_wide.columns]
    df_wide = df_wide[keep].rename(columns=spec['columns'])

    # Wind: decompose raw paired (speed, direction) into linear u/v components
    # so the bin statistics are honest. Direction itself has no valid scalar
    # mean/std (it wraps at 360), so we drop it and store u/v instead; mean
    # wind speed and mean direction are recovered on read from u_mean/v_mean.
    if {'wind_speed', 'wind_dir'}.issubset(df_wide.columns):
        _drd = np.deg2rad(df_wide['wind_dir'])
        df_wide['wind_u'] = -df_wide['wind_speed'] * np.sin(_drd)
        df_wide['wind_v'] = -df_wide['wind_speed'] * np.cos(_drd)
        df_wide = df_wide.drop(columns='wind_dir')

    # Resample once, then pull each statistic off the same grouper
    grouper = df_wide.resample(resample)
    means  = grouper.mean(numeric_only=True)
    counts = grouper.count()
    stds   = grouper.std(numeric_only=True)

    # Assemble the (time, statistic) tensor, one data variable per column
    time_index = means.index
    data_vars = {}
    for col in means.columns:
        stacked = np.stack(
            [means[col].values, counts[col].values, stds[col].values],
            axis=-1,
        )  # shape (n_time, 3)
        da = xr.DataArray(
            stacked,
            dims=('time', 'statistic'),
            coords={'time': time_index.values, 'statistic': STATISTICS},
            name=col,
        )
        da.attrs['units'] = spec['units'].get(col, '')
        data_vars[col] = da

    ds = xr.Dataset(data_vars)

    # Rain is a cumulative counter, not an instantaneous reading: its honest
    # 5-min value is the counter's rise across the bin, so we overwrite the
    # naive mean/count/std triple. Increment -> 'mean' slot; 'count' keeps the
    # raw-sample QC count already computed; 'std' is undefined for an
    # accumulation and is set to NaN.
    if 'rain' in ds.data_vars and 'rain' in df_wide.columns:
        inc = _rain_increment(df_wide['rain'], means.index, resample=resample)
        ds['rain'].loc[{'statistic': 'mean'}] = inc.values
        ds['rain'].loc[{'statistic': 'std'}] = np.nan
        ds['rain'].attrs['note'] = (
            "mean slot = 5-min accumulated rainfall (mm), from counter "
            "rise (already diff().clip(lower=0)-style); std is undefined "
            "(NaN); count = raw samples in bin"
        )

    ds['statistic'].attrs['description'] = (
        "mean = 5-min average; count = number of raw samples in bin; "
        "std = standard deviation of raw samples in bin"
    )
    return ds


# ---------------------------------------------------------------------------
# Deployment-date probing
# ---------------------------------------------------------------------------

def find_first_data(site, instrument, search_start='2023-01-01',
                    search_end=None, step_days=30):
    """
    Find the approximate first date a node reported data for an instrument by
    probing forward in coarse steps with cheap head=1 queries.

    Returns a pandas.Timestamp (UTC, floored to the day) of the first month
    in which data appears, or None if no data found in the search range.

    Coarse by design (month granularity): the backfill starts at the floor of
    this date, so a slightly early start just produces empty leading bins,
    which is harmless.
    """
    spec = INSTRUMENTS[instrument]
    start = pd.Timestamp(search_start, tz='UTC')
    end = (pd.Timestamp(search_end, tz='UTC') if search_end
           else pd.Timestamp.now(tz='UTC'))

    probe = start
    while probe < end:
        probe_end = probe + pd.Timedelta(days=step_days)
        df = sage_data_client.query(
            start=probe.strftime('%Y-%m-%dT%H:%M:%SZ'),
            end=probe_end.strftime('%Y-%m-%dT%H:%M:%SZ'),
            filter={'name': spec['filter'], 'vsn': site.vsn},
            head=1,
        )
        if not df.empty:
            return probe.floor('D')
        probe = probe_end
    return None


# ---------------------------------------------------------------------------
# Stage 3 — write (with welded-on provenance metadata)
# ---------------------------------------------------------------------------

def _filename(site, instrument, resample=RESAMPLE_INTERVAL):
    res = resample.replace('min', 'min')  # already e.g. '5min'
    return f"{site.abbr}_{instrument}_{res}.nc"


def write_store(ds, site, instrument, outdir=DEFAULT_OUTDIR,
                first_data=None, source_start=None, source_end=None,
                resample=RESAMPLE_INTERVAL):
    """
    Write the aggregated Dataset to NetCDF with provenance welded into the
    file's global attributes, so the archive is self-describing and survives
    being copied or handed to someone with no other context.
    """
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, _filename(site, instrument, resample))

    ds = ds.copy()
    ds.attrs.update({
        'title':            f'CROCUS {instrument.upper()} 5-minute archive — {site.abbr}',
        'site_abbr':        site.abbr,
        'site_full_name':   site.full_name,
        'vsn':              site.vsn,
        'latitude':         site.lat,
        'longitude':        site.lon,
        'instrument':       instrument,
        'resample_interval': resample,
        'resample_label':   'left edge, UTC',
        'statistics':       ', '.join(STATISTICS),
        'source':           'Sage/Waggle via sage_data_client (raw, unsampled)',
        'generated_utc':    dt.datetime.now(dt.timezone.utc).isoformat(),
        'generated_by':     'crocus_store.build_site',
        'first_data_utc':   '' if first_data is None else str(first_data),
        'source_query_start': '' if source_start is None else str(source_start),
        'source_query_end':   '' if source_end is None else str(source_end),
        'note': (
            'Static historic archive. For recent (post-transition, native '
            '5-min) data use sage_utils.query_wxt / query_aqt against Sage. '
            'Per-bin count reveals the >1Hz->5min transition: a cliff from '
            '~thousands of samples to ~1 marks the changeover for this node.'
        ),
    })

    # Sensible on-disk encoding: compress, store time as int64 since epoch
    encoding = {v: {'zlib': True, 'complevel': 4} for v in ds.data_vars}
    ds.to_netcdf(path, encoding=encoding)
    return path


# ---------------------------------------------------------------------------
# Driver — build one site/instrument end to end, in resumable monthly chunks
# ---------------------------------------------------------------------------

def _chunk_dir(outdir, site, instrument):
    """Directory holding per-chunk checkpoint files for one site/instrument."""
    return os.path.join(outdir, '_chunks', f"{site.abbr}_{instrument}")


def _chunk_path(outdir, site, instrument, c_start, c_end):
    """Deterministic checkpoint filename for a single chunk.

    Keyed by the chunk's start/end so a resumed run with the SAME chunk_days
    recomputes identical names and finds prior work. The presence of this file
    is the sole signal that the chunk completed cleanly: it is written ONLY
    after a fully successful fetch+aggregate, never for a failed or empty
    chunk, so resume safely re-attempts anything missing.
    """
    tag = (f"{c_start.strftime('%Y%m%dT%H%M%SZ')}"
           f"_{c_end.strftime('%Y%m%dT%H%M%SZ')}")
    return os.path.join(_chunk_dir(outdir, site, instrument), f"{tag}.nc")


def build_site(site, instrument='wxt', outdir=DEFAULT_OUTDIR,
               start=None, end=None, resample=RESAMPLE_INTERVAL,
               chunk_days=3, verbose=True):
    """
    Backfill one site + instrument into a NetCDF archive file.

    Iterates crocus_sites-style CROCUSSite objects, so it generalizes to the
    whole network by looping ALL_SITES.

    Parameters
    ----------
    site : CROCUSSite
    instrument : {'wxt', 'aqt'}
    outdir : str
        Directory for the .nc file.
    start : str or None
        Backfill start. If None, find_first_data() probes for it.
    end : str or None
        Backfill end. If None, now (UTC).
    resample : str
        Output resolution. Default '5min'.
    chunk_days : int
        Width (in days) of each raw fetch chunk. Default 3. Historic WXT data
        is very dense (~5-6 million rows/day at >1Hz), and large single queries
        spanning a long window have been observed to return only the dominant
        channel (e.g. humidity) while silently omitting minority channels such
        as temp/wind, even though the full time span is covered. Querying in
        small day-scale chunks keeps each request well within the size where
        all channels return reliably. Tune down for very dense nodes, up for
        sparse ones.

    Returns
    -------
    str path to the written file, or None if the site lacks the instrument
    or no data was found.

    Notes
    -----
    Queries in fixed-width day chunks and concatenates, so a single bad chunk
    is easy to isolate and re-run, long baselines don't ride on one giant
    query, and no single channel can crowd out the others in an over-large
    response.

    Resumable. Each chunk is checkpointed to a small NetCDF under
    {outdir}/_chunks/{abbr}_{instrument}/ as soon as it completes. Re-running
    the same build skips any chunk whose checkpoint already exists, so an
    interrupted backfill (dropped connection, killed kernel, machine sleep)
    picks up where it left off instead of restarting. A checkpoint is written
    ONLY after a fully successful fetch+aggregate, so a missing checkpoint
    always means "not done — retry me," never "done but corrupt." Keep the
    same chunk_days across runs of the same build: changing it shifts the
    chunk boundaries and prior checkpoints will not be reused. The per-chunk
    files are retained after the final archive is assembled; they are scratch
    and may be deleted once the archive exists.

    Fault tolerance. A single failing chunk (Sage error after the per-query
    retries in fetch_raw are exhausted) is treated as an isolated bad window:
    it is logged as CHUNK FAILED, left un-checkpointed, skipped, and retried on
    a later run. But OUTAGE_CONSECUTIVE (3) failures in a row are read as a
    Sage service outage; the build then sleeps OUTAGE_WAIT_SECONDS (30 min) and
    retries the SAME chunk, repeating until a fetch succeeds or until the time
    waited since the last success reaches OUTAGE_GIVEUP_SECONDS (12 h), at which
    point it exits cleanly (no archive assembled) so it can be resumed later.
    This lets an unattended multi-day run ride out overnight outages without
    crashing and without marking good data as failed. Progress is emitted via
    the module logger, so configure logging (the CLI does) to capture it.
    """
    spec = INSTRUMENTS[instrument]
    if not getattr(site, spec['has_flag'], False):
        if verbose:
            log.info("%s: no %s configured — skipping", site.abbr, instrument)
        return None

    # Resolve start
    if start is None:
        if verbose:
            log.info("%s/%s: probing for first data...", site.abbr, instrument)
        first = find_first_data(site, instrument)
        if first is None:
            if verbose:
                log.info("%s/%s: no data found in search range",
                         site.abbr, instrument)
            return None
        start_ts = first
    else:
        start_ts = pd.Timestamp(start, tz='UTC')
    end_ts = (pd.Timestamp(end, tz='UTC') if end
              else pd.Timestamp.now(tz='UTC'))

    if verbose:
        log.info("%s/%s: backfilling %s -> %s",
                 site.abbr, instrument, start_ts.date(), end_ts.date())

    # Fixed-width day-chunk fetch + aggregate, collect per-chunk tensors.
    # Day-scale chunks avoid the large-query failure where minority channels
    # are dropped from an over-large multi-channel response.
    # NOTE: we do NOT accumulate chunk datasets in memory. Every chunk is
    # checkpointed to disk as it completes; the final archive is assembled by
    # streaming those checkpoint files back from disk after the loop. Holding
    # all chunks in RAM caused unbounded memory growth (tens of GB) on long,
    # dense backfills and on resume (which re-loaded every cached chunk).
    # We track only whether any usable chunk was produced.
    any_chunk = False
    expected_channels = set(spec['columns'].keys())
    ckpt_dir = _chunk_dir(outdir, site, instrument)
    os.makedirs(ckpt_dir, exist_ok=True)

    chunk_edges = pd.date_range(
        start_ts.floor('D'), end_ts, freq=f'{chunk_days}D', tz='UTC'
    )
    # ensure the leading partial chunk and the trailing edge are covered
    if len(chunk_edges) == 0 or chunk_edges[0] > start_ts:
        chunk_edges = chunk_edges.insert(0, start_ts)
    if chunk_edges[-1] < end_ts:
        chunk_edges = chunk_edges.insert(len(chunk_edges), end_ts)

    # Outage-tracking state. consecutive_failures counts chunk failures in a
    # row; waited_seconds is total sleep since the last success (the 12h budget,
    # which resets on any successful fetch). Both reset to 0 on success.
    consecutive_failures = 0
    waited_seconds = 0

    i = 0
    n_edges = len(chunk_edges)
    while i < n_edges - 1:
        c_start = chunk_edges[i]
        c_end = chunk_edges[i + 1]
        # Skip degenerate / zero-width chunks: Sage returns HTTP 500 when
        # start is not strictly before end.
        if c_start >= c_end:
            i += 1
            continue

        label = f"{c_start.date()}..{c_end.date()}"
        ckpt = _chunk_path(outdir, site, instrument, c_start, c_end)

        # Resume: if this chunk is already checkpointed, note it and skip the
        # fetch. Do NOT load it into memory — it will be streamed from disk at
        # final assembly. We only peek at the time count for the log line.
        if os.path.exists(ckpt):
            any_chunk = True
            if verbose:
                try:
                    with xr.open_dataset(ckpt) as ds_peek:
                        n = ds_peek.sizes.get('time', 0)
                except Exception:
                    n = 0
                log.info("    %s: %d bins (cached, skipped)", label, n)
            i += 1
            continue

        # Attempt the fetch. fetch_raw does its own short per-query retries
        # (Tier 1); a raised exception here means those were exhausted.
        try:
            df_raw = fetch_raw(
                site, instrument,
                c_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                c_end.strftime('%Y-%m-%dT%H:%M:%SZ'),
            )
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures < OUTAGE_CONSECUTIVE:
                # Isolated failure: treat as a bad window. Do NOT checkpoint, so
                # a later resume retries it. Skip ahead and keep going.
                log.warning("    %s: CHUNK FAILED (%s) — skipping, will retry "
                            "on a later run [%d consecutive]",
                            label, e, consecutive_failures)
                i += 1
                continue
            # Threshold reached: treat as a service outage. Wait and retry the
            # SAME chunk (do not advance i), unless we've waited past the budget.
            if waited_seconds >= OUTAGE_GIVEUP_SECONDS:
                log.error("%s/%s: Sage appears down — %d consecutive failures, "
                          "waited %.1f h since last success. Exiting cleanly; "
                          "re-run the same command to resume.",
                          site.abbr, instrument, consecutive_failures,
                          waited_seconds / 3600.0)
                return None
            log.warning("    %s: outage suspected (%d consecutive failures); "
                        "sleeping %d min then retrying this chunk "
                        "(%.1f h of %.0f h budget used)",
                        label, consecutive_failures,
                        OUTAGE_WAIT_SECONDS // 60, waited_seconds / 3600.0,
                        OUTAGE_GIVEUP_SECONDS / 3600.0)
            time.sleep(OUTAGE_WAIT_SECONDS)
            waited_seconds += OUTAGE_WAIT_SECONDS
            continue   # retry same chunk

        # Fetch succeeded: any outage is over. Reset the trackers.
        consecutive_failures = 0
        waited_seconds = 0

        if df_raw.empty:
            # No data: do NOT checkpoint, so a later run re-attempts this span
            # (the gap may be transient telemetry rather than a true absence).
            if verbose:
                log.info("    %s: (no data)", label)
            i += 1
            continue

        # Channel-completeness check: warn if the response is missing channels
        # that the instrument is expected to report. This surfaces partial /
        # dominant-channel-only responses instead of silently writing a file
        # with fewer variables than intended.
        got_channels = set(df_raw['name'].unique())
        missing = expected_channels - got_channels
        if missing and verbose:
            log.warning("    %s: missing channels %s (got %s)",
                        label, sorted(missing), sorted(got_channels))

        ds_chunk = aggregate_bins(df_raw, instrument, resample=resample)

        # Checkpoint ONLY after a fully successful fetch+aggregate. Write to a
        # temp file then atomically rename, so an interruption mid-write can
        # never leave a truncated checkpoint that resume would trust.
        tmp = ckpt + '.tmp'
        ds_chunk.to_netcdf(tmp)
        os.replace(tmp, ckpt)

        any_chunk = True
        if verbose:
            n = ds_chunk.sizes.get('time', 0)
            log.info("    %s: %d bins", label, n)
        # Release this chunk's memory immediately; it now lives on disk as the
        # checkpoint and will be streamed back at final assembly.
        ds_chunk.close()
        del ds_chunk
        i += 1

    if not any_chunk:
        if verbose:
            log.info("%s/%s: no data in window", site.abbr, instrument)
        return None

    # Assemble the final archive from the on-disk checkpoints rather than from
    # memory. Open them lazily and concatenate; this keeps peak memory bounded
    # by (roughly) the final archive size instead of the sum of all chunks.
    ckpt_files = sorted(
        os.path.join(ckpt_dir, f)
        for f in os.listdir(ckpt_dir)
        if f.endswith('.nc')
    )
    if not ckpt_files:
        if verbose:
            log.info("%s/%s: no checkpoint files to assemble", site.abbr, instrument)
        return None

    parts = []
    for f in ckpt_files:
        with xr.open_dataset(f) as _ds:
            parts.append(_ds.load())
    ds_all = xr.concat(parts, dim='time')
    for _ds in parts:
        _ds.close()
    del parts
    ds_all = ds_all.sortby('time')
    # drop any duplicate bins at chunk seams
    _, keep_idx = np.unique(ds_all['time'].values, return_index=True)
    ds_all = ds_all.isel(time=np.sort(keep_idx))

    path = write_store(
        ds_all, site, instrument, outdir=outdir,
        first_data=start_ts, source_start=start_ts, source_end=end_ts,
        resample=resample,
    )
    if verbose:
        log.info("%s/%s: wrote %s (%d bins)",
                 site.abbr, instrument, path, ds_all.sizes['time'])
    return path


# ---------------------------------------------------------------------------
# Stage 4 — read (what students / collaborators call)
# ---------------------------------------------------------------------------

def load(site, instrument='wxt', start=None, end=None, outdir=DEFAULT_OUTDIR):
    """
    Load a site+instrument archive as an xarray.Dataset, optionally sliced to
    a time range. Reads ONLY the local NetCDF file — never touches Sage.

    Parameters
    ----------
    site : CROCUSSite (or str abbreviation)
    instrument : {'wxt','aqt'}
    start, end : str or None
        Optional time slice, e.g. '2024-06-01'.
    outdir : str

    Returns
    -------
    xr.Dataset with dims (time, statistic).

    Examples
    --------
    >>> ds = load(NEIU, 'wxt', '2024-06-01', '2024-09-01')
    >>> temp_mean = ds['temp'].sel(statistic='mean').to_series()
    >>> # mask bins built from too few samples
    >>> good = ds['temp'].sel(statistic='mean').where(
    ...     ds['temp'].sel(statistic='count') > 100)
    """
    abbr = site if isinstance(site, str) else site.abbr
    res = RESAMPLE_INTERVAL
    path = os.path.join(outdir, f"{abbr}_{instrument}_{res}.nc")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No archive at {path}. Build it first with build_site()."
        )
    ds = xr.open_dataset(path)
    if start is not None or end is not None:
        ds = ds.sel(time=slice(start, end))
    return ds
