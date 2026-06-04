# functions for assessing CROCUS data coverage

# Standard library
import datetime as dt
import os

# Third party
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sage_data_client
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from sage_utils import SAGE_MISSING, last_n_hours
import crocus_sites
import sage_manifest

# Canary variables for each sensor type
CANARY_VARIABLES = {
    'wxt':       'wxt.env.temp',
    'aqt_gas':   'aqt.gas.ozone',
    'aqt_pm':    'aqt.particle.pm2.5',
    'bme680':    'env.temperature',
    'raingauge': 'env.raingauge.rint',
    'sapflow':   'uncorrected_inner',
    'mfr':       'air_temperature',
}

# Map sensor key to CROCUSSite attribute name
SENSOR_FLAGS = {
    'wxt':       'has_wxt',
    'aqt_gas':   'has_aqt',
    'aqt_pm':    'has_aqt',
    'bme680':    'has_bme680',
    'raingauge': 'has_raingauge',
    'sapflow':   'has_sapflow',
    'mfr':       'has_mfr',
}


def check_status(vsn, start, end=None, sensor='wxt'):
    """
    Check data availability for a single node and sensor type.

    Makes one lightweight API call per day (head=10) to determine
    whether the sensor was reporting. Returns a binary daily Series
    suitable for plotting as a calendar heatmap with calplot.

    Binary presence/absence is used rather than row counts, making
    the result robust to the >1Hz to 5-minute frequency change in
    April 2026.
    """
    if sensor not in CANARY_VARIABLES:
        raise ValueError(
            f"Unknown sensor '{sensor}'. "
            f"Choose from: {list(CANARY_VARIABLES.keys())}"
        )

    canary = CANARY_VARIABLES[sensor]
    end    = end or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    start_dt = pd.Timestamp(start).floor('D')
    if start_dt.tzinfo is None:
        start_dt = start_dt.tz_localize('UTC')
    end_dt = pd.Timestamp(end).floor('D')
    if end_dt.tzinfo is None:
        end_dt = end_dt.tz_localize('UTC')

    date_index = pd.date_range(start=start_dt, end=end_dt, freq='D', tz='UTC')
    coverage   = pd.Series(0, index=date_index)

    for day in date_index:
        day_start = day.strftime('%Y-%m-%dT00:00:00Z')
        day_end   = day.strftime('%Y-%m-%dT23:59:59Z')
        df = sage_data_client.query(
            start=day_start,
            end=day_end,
            filter={
                'name': canary,
                'vsn':  vsn,
            },
            head=3
        )
        if not df.empty:
            values = pd.to_numeric(df['value'], errors='coerce')
            values = values.replace(SAGE_MISSING, float('nan'))
            if values.notna().any() and (values.dropna() != 0).any():
                coverage[day] = 1

    return coverage


def plot_node_status(vsn, hours=24, bin_minutes=60):
    """
    Recreate the Sage portal App History plot for a single node.

    Parameters
    ----------
    vsn : str
        Node ID, e.g. VSN
    hours : int
        How many hours back to query. Default 24.
    bin_minutes : int
        Time bin width in minutes. Default 60.
    """
    start, end = last_n_hours(hours)

    df = sage_data_client.query(
        start=start,
        end=end,
        filter={'vsn': vsn},
        head=50000
    )

    if df.empty:
        print(f'No data returned for {vsn}')
        return

    df['timestamp']    = pd.to_datetime(df['timestamp'], utc=True)
    df['bin']          = df['timestamp'].dt.floor(f'{bin_minutes}min')
    df['plugin_short'] = (df['meta.plugin']
                          .str.split('/').str[-1]   # drop registry prefix
                          .str.split(':').str[0])   # drop version tag

    counts = df.groupby(['plugin_short', 'bin']).size().unstack(fill_value=0)

# Normalize counts to 0-1 range per plugin so each fits in its row
    counts_norm = counts.div(counts.max(axis=1) + 1e-9, axis=0)

    fig, ax = plt.subplots(figsize=(14, len(counts) * 0.8 + 1))

    for i, plugin in enumerate(counts.index):
        ax.bar(counts.columns, counts_norm.loc[plugin],
               bottom=i,
               width=pd.Timedelta(minutes=bin_minutes * 0.9),
               color='steelblue', alpha=0.7)
        ax.axhline(y=i, color='lightgray', linewidth=0.8)

    ax.set_yticks([i + 0.5 for i in range(len(counts))])
    ax.set_yticklabels(
        [p[-30:] for p in counts.index],  # truncate long names
        fontsize=8
    )
    ax.set_ylim(0, len(counts))
    ax.set_xlabel('Time (UTC)')
    ax.set_title(f'Node {vsn} — App History — Last {hours} hours')
    fig.tight_layout()
    plt.show()


def check_network_status(sites, hours=6, rg15_hours=24, raingauge_window_min=30):
    """
    Check current sensor status across all CROCUS sites.

    Makes one lightweight API call per site × sensor combination.
    Total calls = n_sites × n_sensors — typically completes in under
    a minute for the full network.

    Parameters
    ----------
    sites : list of CROCUSSite
        Sites to check, e.g. ALL_SITES from crocus_sites.py
    hours : int
        Lookback window for continuous sensors (WXT, AQT, BME, SAP, MFR).
        Default 6 hours.
    rg15_hours : int
        Lookback window for RG-15 — longer since it only reports during
        rain events. Default 24 hours.

    Returns
    -------
    pd.DataFrame with sites as rows and sensor types as columns.
    Values:
         1 = sensor present at site and reporting
         0 = sensor present at site but not reporting
        -1 = sensor not configured at this site
    """
    sensors    = list(CANARY_VARIABLES.keys())
    site_abbrs = [s.abbr for s in sites]
    status     = pd.DataFrame(-1, index=site_abbrs, columns=sensors)

    start_cont, end = last_n_hours(hours)
    start_rg15, _   = last_n_hours(rg15_hours)

    for site in sites:
        print(f"  Checking {site.abbr} ({site.vsn})...", end=' ', flush=True)
        for sensor in sensors:
            flag = SENSOR_FLAGS[sensor]
            if not getattr(site, flag, False):
                continue   # sensor not at this site — leave as -1

            start = start_rg15 if sensor == 'raingauge' else start_cont

            # Build filter — bme680 needs sensor tag to avoid picking up
            # other sources of env.temperature on the same node
            query_filter = {
                'name': CANARY_VARIABLES[sensor],
                'vsn':  site.vsn,
            }
            if sensor == 'bme680':
                query_filter['sensor'] = 'bme680'

            # The raingauge reports rain intensity, which is legitimately 0
            # during dry periods. So for it, "reporting" = any recent reading
            # arrived (recency-based), NOT a nonzero value — matching the Sage
            # portal. We use a SHORT window with head=5 (cheap) rather than
            # tail over the long rg15 window (tail forces the server to scan
            # the whole window and can time out). A live gauge reports ~2/min,
            # so a short window has ample rows, and head over a short window
            # is recent enough to answer "is it reporting now?". For all other
            # sensors we keep the nonzero check, where a stuck zero may
            # indicate a fault.
            if sensor == 'raingauge':
                rg_start, _ = last_n_hours(raingauge_window_min / 60.0)
                df = sage_data_client.query(
                    start=rg_start, end=end, filter=query_filter, head=5
                )
                if not df.empty:
                    values = pd.to_numeric(df['value'], errors='coerce')
                    values = values.replace(SAGE_MISSING, float('nan'))
                    # valid if ANY real reading arrived (zero is fine)
                    is_valid = values.notna().any()
                    status.loc[site.abbr, sensor] = 1 if is_valid else 0
                else:
                    status.loc[site.abbr, sensor] = 0
                continue

            df = sage_data_client.query(
                start=start,
                end=end,
                filter=query_filter,
                head=5
            )
            if not df.empty:
                values = pd.to_numeric(df['value'], errors='coerce')
                values = values.replace(SAGE_MISSING, float('nan'))
                is_valid = values.notna().any() and (values.dropna() != 0).any()
                status.loc[site.abbr, sensor] = 1 if is_valid else 0
            else:
                status.loc[site.abbr, sensor] = 0
        print('done')

    return status



def plot_network_status(status, hours=6, rg15_hours=24):
    """
    Plot current sensor status across all CROCUS sites as a color grid.

    Parameters
    ----------
    status : pd.DataFrame
        Output of check_network_status().
    hours : int
        Lookback window used — for title only.
    rg15_hours : int
        RG-15 lookback window used — for title only.
    """
    # Column display labels
    col_labels = {
        'wxt':       'WXT',
        'aqt_gas':   'AQT\ngas',
        'aqt_pm':    'AQT\nPM',
        'bme680':    'BME\n680',
        'raingauge': 'RG-15',
        'sapflow':   'Sap\nflow',
        'mfr':       'MFR',
    }

    grid = status.values.astype(float)
    # Remap: -1 → 0 (gray), 0 → 1 (red), 1 → 2 (green)
    display = np.where(grid == -1, 0, np.where(grid == 0, 1, 2))

    cmap             = ListedColormap(['#d3d3d3', '#d73027', '#1a9850'])
    n_rows, n_cols   = display.shape

    fig, ax = plt.subplots(figsize=(n_cols * 1.2 + 1, n_rows * 0.7 + 2))
    ax.imshow(display, cmap=cmap, vmin=0, vmax=2, aspect='auto')

    # Grid lines
    ax.set_xticks(np.arange(-0.5, n_cols, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows, 1), minor=True)
    ax.grid(which='minor', color='white', linewidth=2)
    ax.tick_params(which='minor', size=0)

    # Labels
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(
        [col_labels.get(c, c) for c in status.columns],
        fontsize=9
    )
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(status.index, fontsize=10)
    ax.xaxis.tick_top()

    # VSN labels on right side
    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks(range(n_rows))
    ax2.set_yticklabels(status.index, fontsize=8, color='0.5')

    # Legend
    legend_elements = [
        Patch(facecolor='#1a9850', label='Reporting'),
        Patch(facecolor='#d73027', label='Not reporting'),
        Patch(facecolor='#d3d3d3', label='Not configured'),
    ]
    ax.legend(handles=legend_elements, loc='lower right',
              bbox_to_anchor=(1.0, -0.12), ncol=3, fontsize=8)

    now_str = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    ax.set_title(
        f'CROCUS Network Status  |  {now_str}\n'
        f'Continuous sensors: last {hours}h  |  RG-15: last {rg15_hours}h',
        fontsize=11, pad=15
    )

    fig.tight_layout()
    plt.savefig('figures/network_status.png', dpi=150, bbox_inches='tight')
    plt.show()


# ---------------------------------------------------------------------------
# Node compute-host health (liveness)
# ---------------------------------------------------------------------------
#
# This is a SEPARATE stratum from the sensor status grid above. It answers
# "is each compute host (chip) reporting?" — NOT "are the sensors good?".
# The two are independent: a host can be alive and reporting system metrics
# while sensors attached to it are long dead (e.g. NEIU's rpi reports uptime
# continuously while its BME680/RG-15 have been dark for years). Read this
# strip ABOVE the sensor grid: hosts alive? -> then, separately, which
# sensors report?
#
# Liveness only, by design. A host's last `sys.uptime` timestamp tells us the
# chip is powered and the low-level metrics agent is running. It deliberately
# does NOT claim the host is "healthy" in the k3s/sanity sense — that is a
# different signal (sys.sanity_status.*) whose codes are not yet decoded, and
# folding an undecoded code into a health verdict would risk false confidence.
# A sanity/health overlay can be added as a separate pass once decoded.

# Liveness canary: every compute host emits sys.uptime (verified across
# nxcore / rpi / rpi.lorawan / nxagent on multiple nodes).
NODE_LIVENESS_CANARY = 'sys.uptime'

# ---------------------------------------------------------------------------
# Manifest-joined, role-labeled liveness  (reproduces the Sage portal)
# ---------------------------------------------------------------------------
#
# The portal labels each compute host by role (nxcore / rpi / rpi.lorawan /
# nxagent) by joining the node-manifest endpoint to sys.uptime data by serial
# number. We do the same. The manifest's per-compute `is_active` + role `name`
# is the AUTHORITATIVE roster — it replaces the hand-maintained `has_lorawan`
# flag and the old "count rpi hosts vs expected" heuristic (kept below as
# _check_node_health_count_based for the manifest-unreachable fallback).
#
# Portal-matched parameters (from sage-gui source):
#   - query sys.uptime over a 30-DAY window, newest sample per host (tail=1)
#   - elapsed thresholds: FAIL > 6 min, WARNING > 3 min  (else fresh/green)
#   - computes with is_active == false are skipped (not expected to report)
#
# Time-window note: per the standing rule, we pass ABSOLUTE timestamps to
# sage_data_client (via last_n_hours), never a relative '-30d' string —
# pandas 3.x mis-parses relative strings and the query 500s. 30 days = 720h.

NODE_STATUS_HOURS = 24 * 30          # portal's -30d window, as absolute hours
ELAPSED_WARN_MIN  = 3.0              # portal warning threshold (minutes)
ELAPSED_FAIL_MIN  = 6.0              # portal fail threshold (minutes)

# Display order for known roles; any other role names sort after these.
_ROLE_ORDER = ['nxcore', 'rpi', 'rpi.lorawan', 'nxagent']

# Process-lifetime cache of the last good manifest, so a transient manifest
# outage doesn't blank the dashboard (see check_node_health fallback).
_MANIFEST_CACHE = {}     # vsn -> list of compute dicts (name/serial_no/is_active)


def _role_sort_key(role):
    try:
        return (0, _ROLE_ORDER.index(role))
    except ValueError:
        return (1, role or '')


def _load_manifest_computes(sites):
    """Load compute rosters for the given sites, with caching.

    Tries a single all-nodes fetch first (one HTTP call for the whole
    network), falling back to per-vsn fetches, falling back to the
    process cache. Updates the cache with every fresh result.

    Returns (result, cached_vsns):
        result      : {vsn: [compute, ...]} — whatever could be assembled;
                      vsns with no manifest (fresh or cached) are absent.
        cached_vsns : set of vsns whose roster came from the cache because a
                      fresh fetch failed (used to flag staleness downstream).
    """
    wanted = {s.vsn for s in sites}
    result = {}
    cached_vsns = set()

    # Attempt 1: one bulk call.
    try:
        allnodes = sage_manifest.get_all_nodes()
        for vsn in wanted:
            if vsn in allnodes:
                computes = allnodes[vsn]['computes']
                result[vsn] = computes
                _MANIFEST_CACHE[vsn] = computes
    except sage_manifest.ManifestError as exc:
        print(f"  [manifest] bulk fetch failed ({exc}); trying per-node...")

    # Attempt 2: per-vsn for anything still missing.
    missing = wanted - result.keys()
    for vsn in missing:
        try:
            node = sage_manifest.get_node(vsn)
            result[vsn] = node['computes']
            _MANIFEST_CACHE[vsn] = node['computes']
        except sage_manifest.ManifestError:
            pass

    # Attempt 3: cache for anything STILL missing.
    still_missing = wanted - result.keys()
    for vsn in still_missing:
        if vsn in _MANIFEST_CACHE:
            print(f"  [manifest] using cached roster for {vsn}")
            result[vsn] = _MANIFEST_CACHE[vsn]
            cached_vsns.add(vsn)

    return result, cached_vsns


def check_node_health(sites, manifest=None):
    """
    Check compute-host liveness across CROCUS sites, role-labeled via the
    node-manifest endpoint — reproducing the Sage portal.

    For each site we query sys.uptime over a 30-day window, take the newest
    sample per host, then join hosts to the manifest's compute roster by
    serial number. Each ACTIVE compute is reported by its manifest role
    (nxcore / rpi / rpi.lorawan / nxagent), with minutes since it last
    reported. This is a LIVENESS check (is the chip reporting?), independent
    of sensor status.

    Parameters
    ----------
    sites : list of CROCUSSite
        e.g. ALL_SITES from crocus_sites.
    manifest : dict, optional
        Pre-fetched {vsn: [compute, ...]} (as from sage_manifest). If None,
        fetched here (bulk, then per-node, then cache on failure).

    Returns
    -------
    pd.DataFrame, one row per (site, role), with columns:
        abbr        : site abbreviation
        vsn         : node id
        role        : manifest compute name (nxcore / rpi / rpi.lorawan / ...)
        serial_no   : compute serial
        age_min     : minutes since this role last reported (NaN if never /
                      no matching host in the window)
        is_active   : manifest is_active flag (inactive computes still listed,
                      but flagged — they are not expected to report)
        from_cache  : True if the roster came from the cache (manifest was
                      unreachable for this vsn)

    If the manifest is unreachable for a site AND nothing is cached, that
    site is omitted here; callers can fall back to
    _check_node_health_count_based for a manifest-free view.
    """
    if manifest is None:
        manifest, cached_vsns = _load_manifest_computes(sites)
    else:
        cached_vsns = set()

    start, end = last_n_hours(NODE_STATUS_HOURS)
    now = pd.Timestamp.now(tz='UTC')

    rows = []
    for site in sites:
        print(f"  Checking {site.abbr} ({site.vsn})...", end=' ', flush=True)
        computes = manifest.get(site.vsn)
        if not computes:
            print('no manifest (skipped)')
            continue

        from_cache = site.vsn in cached_vsns

        df = sage_data_client.query(
            start=start,
            end=end,
            filter={'name': NODE_LIVENESS_CANARY, 'vsn': site.vsn},
            tail=1,                      # newest sample per series (per host)
        )
        # newest timestamp per meta.host
        host_age = {}
        if not df.empty:
            df = df.copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            latest = df.groupby('meta.host')['timestamp'].max()
            hosts = list(latest.index)
            for h in hosts:
                host_age[h] = (now - latest[h]).total_seconds() / 60.0
        else:
            hosts = []

        for c in sorted(computes, key=lambda c: _role_sort_key(c['name'])):
            host = sage_manifest.find_host_for_serial(hosts, c['serial_no'])
            age = host_age.get(host, np.nan)
            rows.append({
                'abbr':       site.abbr,
                'vsn':        site.vsn,
                'role':       c['name'],
                'serial_no':  c['serial_no'],
                'age_min':    age,
                'is_active':  c['is_active'],
                'from_cache': from_cache,
            })
        print('done')

    return pd.DataFrame(
        rows,
        columns=['abbr', 'vsn', 'role', 'serial_no',
                 'age_min', 'is_active', 'from_cache'],
    )


def _age_to_code(age, warn=ELAPSED_WARN_MIN, fail=ELAPSED_FAIL_MIN):
    """0 gray (inactive handled by caller), 1 red, 2 orange, 3 green."""
    if pd.isna(age):
        return 1                 # never reported in window -> red
    if age <= warn:
        return 3
    if age <= fail:
        return 2
    return 1


def _age_to_text(age):
    if pd.isna(age):
        return '—'
    if age < 90:
        return f'{age:.0f}m'
    if age < 60 * 48:
        return f'{age/60:.0f}h'
    return f'{age/1440:.0f}d'


def plot_node_health(health, warn_min=ELAPSED_WARN_MIN, fail_min=ELAPSED_FAIL_MIN,
                     sites=None):
    """
    Plot compute-host liveness as a role-labeled color grid, reproducing the
    Sage portal's per-node status tooltip (one row per compute role).

    Columns are the union of roles present across the given sites, in portal
    order (nxcore, rpi, rpi.lorawan, nxagent, then any others). Each cell:
      green  : reported within warn_min (default 3m)
      orange : reported within fail_min (default 6m)
      red    : older than fail_min, or never reported in the window
      gray   : role not present at this site, OR present but is_active == False
               (an inactive compute is not expected to report)
    Cell text shows age (e.g. '2m', '30d') or '—'.

    LIVENESS only — green means the chip is reporting, NOT that its sensors are
    healthy (read the sensor grid for that).

    Parameters
    ----------
    health : pd.DataFrame
        Output of check_node_health (long form: one row per site×role).
    warn_min, fail_min : float
        Recency thresholds in minutes (portal defaults 3 / 6).
    sites : list of CROCUSSite, optional
        Accepted for signature parity; not required.
    """
    if health.empty:
        print('No node-health data to plot (manifest unreachable and no cache?).')
        return

    abbrs = list(dict.fromkeys(health['abbr']))           # preserve order
    roles = sorted(health['role'].unique(), key=_role_sort_key)
    n_rows, n_cols = len(abbrs), len(roles)

    display = np.zeros((n_rows, n_cols), dtype=int)        # default gray (0)
    text = [['' for _ in roles] for _ in abbrs]
    any_cache = bool(health['from_cache'].any())

    by_key = {(r.abbr, r.role): r for r in health.itertuples(index=False)}
    for i, abbr in enumerate(abbrs):
        for j, role in enumerate(roles):
            rec = by_key.get((abbr, role))
            if rec is None:
                display[i, j] = 0                          # role absent -> gray
                text[i][j] = ''
            elif not rec.is_active:
                display[i, j] = 0                          # inactive -> gray
                text[i][j] = 'n/a'
            else:
                display[i, j] = _age_to_code(rec.age_min, warn_min, fail_min)
                text[i][j] = _age_to_text(rec.age_min)

    cmap = ListedColormap(['#d3d3d3', '#d73027', '#fc8d59', '#1a9850'])
    fig, ax = plt.subplots(figsize=(n_cols * 1.7 + 1, n_rows * 0.7 + 2))
    ax.imshow(display, cmap=cmap, vmin=0, vmax=3, aspect='auto')

    ax.set_xticks(np.arange(-0.5, n_cols, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows, 1), minor=True)
    ax.grid(which='minor', color='white', linewidth=2)
    ax.tick_params(which='minor', size=0)

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(roles, fontsize=9)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(abbrs, fontsize=10)
    ax.xaxis.tick_top()

    for i in range(n_rows):
        for j in range(n_cols):
            ax.text(j, i, text[i][j], ha='center', va='center', fontsize=9,
                    color='white' if display[i, j] in (1, 3) else 'black')

    legend_elements = [
        Patch(facecolor='#1a9850', label=f'Reporting (≤{warn_min:.0f}m)'),
        Patch(facecolor='#fc8d59', label=f'Lagging (≤{fail_min:.0f}m)'),
        Patch(facecolor='#d73027', label='Down (>fail / none)'),
        Patch(facecolor='#d3d3d3', label='Absent / inactive'),
    ]
    ax.legend(handles=legend_elements, loc='lower right',
              bbox_to_anchor=(1.0, -0.18), ncol=4, fontsize=8)

    now_str = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    cache_note = '  [some rosters from cache]' if any_cache else ''
    ax.set_title(
        f'CROCUS Node Compute-Host Liveness  |  {now_str}{cache_note}\n'
        f'sys.uptime over last 30d — newest per host (NOT sensor health). '
        f'Role-labeled via node manifest.',
        fontsize=10, pad=15)

    fig.tight_layout()
    os.makedirs('figures', exist_ok=True)
    plt.savefig('figures/node_health.png', dpi=150, bbox_inches='tight')
    plt.show()


# ---------------------------------------------------------------------------
# Legacy count-based liveness (manifest-free fallback)
# ---------------------------------------------------------------------------
#
# Retained for the case where the manifest endpoint is unreachable AND nothing
# is cached. This is the older model: it COUNTS rpi hosts and compares to how
# many a site should have (2 if has_lorawan else 1), without naming which rpi
# is down. See check_node_health / plot_node_health above for the role-labeled
# portal-matched version that supersedes this.

# Map a meta.host string to a host TYPE (not role) by suffix.
_HOST_SUFFIX_TYPES = [
    ('ws-nxcore', 'nxcore'),
    ('ws-rpi',    'rpi'),
]


def _host_type(meta_host):
    """Map a full meta.host string to a host type ('nxcore'/'rpi'), or None."""
    if not isinstance(meta_host, str):
        return None
    for suffix, htype in _HOST_SUFFIX_TYPES:
        if meta_host.endswith(suffix):
            return htype
    return None


def _expected_rpi_count(site):
    """How many rpi hosts a site SHOULD have: 2 if it has lorawan, else 1."""
    return 2 if getattr(site, 'has_lorawan', False) else 1


def _check_node_health_count_based(sites, hours=6):
    """Manifest-free liveness: count rpi hosts vs expected. See module notes.

    Returns a DataFrame indexed by site abbr with columns nxcore_age,
    rpi_live, rpi_expected, rpi_age. (Former check_node_health behavior.)
    """
    start, end = last_n_hours(hours)
    now = pd.Timestamp.now(tz='UTC')

    site_abbrs = [s.abbr for s in sites]
    out = pd.DataFrame(
        {'nxcore_age': np.nan, 'rpi_live': 0, 'rpi_expected': 0,
         'rpi_age': np.nan},
        index=site_abbrs,
    )

    for site in sites:
        print(f"  Checking {site.abbr} ({site.vsn})...", end=' ', flush=True)
        out.loc[site.abbr, 'rpi_expected'] = _expected_rpi_count(site)
        df = sage_data_client.query(
            start=start,
            end=end,
            filter={'name': NODE_LIVENESS_CANARY, 'vsn': site.vsn},
        )
        if not df.empty:
            df = df.copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df['htype'] = df['meta.host'].map(_host_type)
            df = df.dropna(subset=['htype'])

            nx = df[df['htype'] == 'nxcore']
            if not nx.empty:
                out.loc[site.abbr, 'nxcore_age'] = (
                    now - nx['timestamp'].max()).total_seconds() / 60.0

            rpi = df[df['htype'] == 'rpi']
            if not rpi.empty:
                out.loc[site.abbr, 'rpi_live'] = rpi['meta.host'].nunique()
                out.loc[site.abbr, 'rpi_age'] = (
                    now - rpi['timestamp'].max()).total_seconds() / 60.0
        print('done')

    return out
