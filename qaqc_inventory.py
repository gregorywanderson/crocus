"""
qaqc_inventory.py — descriptive QA/QC scan of a CROCUS archive.

Produces a per-channel inventory of anomalous bins and groups them into dated
episodes, so anomalies can be cross-referenced against known events (fireworks,
wildfire smoke, dust storms / haboobs) before deciding what is an instrument
fault versus a real environmental signal the sensor correctly captured.

Classification per channel uses physically-motivated bounds:
  - IMPOSSIBLE : below a hard floor or above a hard ceiling that no real value
                 can take (e.g. CO of -8 ppm). Almost certainly instrument fault.
  - EXTREME    : within the physical range but far above typical — a CANDIDATE
                 real event (smoke, dust, fireworks). Kept and dated, NOT
                 assumed bad.
  - BASELINE-SUSPECT : just below zero (e.g. small negative CO). This is a
                 SYMPTOM, not a verdict. It can be benign noise scatter around
                 zero on a healthy electrochemical cell, OR evidence the
                 sensor's zero has drifted and it needs recalibration/service.
                 The archive CANNOT distinguish these or "correct" them on its
                 own: a real baseline correction requires reference-instrument
                 data, zero-air calibrations, or the sensor calibration/
                 maintenance log. So these bins are flagged for adjudication
                 WITH that context, not pre-labeled recoverable.

The scan is descriptive only: it changes nothing in the archive. A companion
boolean mask of IMPOSSIBLE (hard-fault) bins is offered separately (see
build_flag_mask); baseline-suspect and extreme-but-physical are deliberately
NOT masked, as those are policy decisions requiring outside context.
"""
import numpy as np
import pandas as pd


# Per-channel bounds. (hard_lo, soft_lo, typ_hi, hard_hi). Units follow the
# archive: gases in ppb except CO in ppm; PM in ug m-3. These are STARTING
# POINTS for discussion with colleagues, not settled thresholds.
BOUNDS = {
    'co':   dict(hard_lo=0.0,  soft_lo=-0.5, typ_hi=10.0,  hard_hi=50.0,   units='ppm'),
    'no':   dict(hard_lo=0.0,  soft_lo=-5.0, typ_hi=200.0, hard_hi=2000.0, units='ppb'),
    'no2':  dict(hard_lo=0.0,  soft_lo=-5.0, typ_hi=150.0, hard_hi=2000.0, units='ppb'),
    'o3':   dict(hard_lo=0.0,  soft_lo=-5.0, typ_hi=120.0, hard_hi=1000.0, units='ppb'),
    'pm1':  dict(hard_lo=0.0,  soft_lo=-1.0, typ_hi=50.0,  hard_hi=2000.0, units='ug m-3'),
    'pm25': dict(hard_lo=0.0,  soft_lo=-1.0, typ_hi=75.0,  hard_hi=2000.0, units='ug m-3'),
    'pm10': dict(hard_lo=0.0,  soft_lo=-1.0, typ_hi=150.0, hard_hi=5000.0, units='ug m-3'),
}

# Known events to annotate episodes against (extend freely). Dates are local.
KNOWN_EVENTS = [
    ('2025-05-16', 'Chicago-area haboob / major dust storm'),
    # July 4 fireworks recur annually; flagged programmatically below.
]


def _episodes(times, max_gap_bins=12):
    """Group a DatetimeIndex of flagged bins into contiguous episodes.

    Bins separated by <= max_gap_bins (default 12 = 1 hour at 5-min) are the
    same episode. Returns list of (start, end, n_bins).
    """
    if len(times) == 0:
        return []
    t = pd.DatetimeIndex(sorted(times))
    # gap in number of 5-min steps between consecutive flagged bins.
    # Use asi8 (ns since epoch) rather than .view('int64'); asi8 is tz-safe
    # and stable across pandas versions.
    steps = np.diff(t.asi8) / (5 * 60 * 1e9)
    breaks = np.where(steps > max_gap_bins)[0]
    groups = np.split(np.arange(len(t)), breaks + 1)
    out = []
    for g in groups:
        seg = t[g]
        out.append((seg[0], seg[-1], len(seg)))
    return out


def _annotate(start, end):
    """Tag an episode with any known event it overlaps (incl. July 4).

    Episode timestamps may arrive tz-naive or tz-aware depending on how the
    archive's time index round-tripped through NetCDF, so normalize both the
    episode bounds and the event timestamps to UTC-aware before comparing.
    """
    def _aware(ts):
        ts = pd.Timestamp(ts)
        return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')

    start = _aware(start)
    end = _aware(end)
    day = pd.Timedelta('1D')

    tags = []
    for d, label in KNOWN_EVENTS:
        ev = _aware(d)
        if start - day <= ev <= end + day:
            tags.append(label)
    # annual July 4 fireworks window (Jul 4 evening .. Jul 5 early)
    for yr in range(start.year, end.year + 1):
        j4 = _aware(f'{yr}-07-04')
        if start - day <= j4 <= end + day:
            tags.append('July 4 fireworks (candidate)')
    return tags


def inventory(ds, channels=None, verbose=True):
    """Scan channels and print a dated inventory. Returns a summary dict."""
    if channels is None:
        channels = [c for c in BOUNDS if c in ds.data_vars]

    summary = {}
    for ch in channels:
        b = BOUNDS[ch]
        mean = ds[ch].sel(statistic='mean').to_series()
        std = ds[ch].sel(statistic='std').to_series()
        cnt = ds[ch].sel(statistic='count').to_series()

        impossible = mean[(mean < b['hard_lo']) | (mean > b['hard_hi'])]
        extreme = mean[(mean >= b['typ_hi']) & (mean <= b['hard_hi'])]
        # Sub-zero but not far below: a SYMPTOM (baseline-suspect), not a verdict.
        # Could be benign zero-scatter or a drifted zero needing recalibration;
        # the archive cannot tell which, so it is reported, not "corrected".
        baseline_suspect = mean[(mean < b['hard_lo']) & (mean >= b['soft_lo'])]
        impossible_hard = mean[(mean > b['hard_hi'])
                               | (mean < b['soft_lo'])]

        summary[ch] = dict(
            n_total=len(mean),
            n_impossible=len(impossible),
            n_impossible_hard=len(impossible_hard),
            n_baseline_suspect=len(baseline_suspect),
            n_extreme=len(extreme),
        )

        if not verbose:
            continue
        print(f"\n=== {ch}  [{b['units']}] "
              f"(typ<= {b['typ_hi']}, hard {b['hard_lo']}..{b['hard_hi']}) ===")
        print(f"  bins: {len(mean)}  "
              f"hard-fault: {len(impossible_hard)}  "
              f"baseline-suspect (sub-zero, needs calibration context): "
              f"{len(baseline_suspect)}  "
              f"extreme-but-physical: {len(extreme)}")

        # Hard-fault episodes (instrument errors) — dated
        if len(impossible_hard):
            print("  HARD-FAULT episodes (likely instrument error):")
            for s, e, n in _episodes(impossible_hard.index):
                seg = mean[(mean.index >= s) & (mean.index <= e)]
                segstd = std[(std.index >= s) & (std.index <= e)]
                sig = ("stuck" if segstd.median() < 1e-3
                       else "noisy" if segstd.median() > 1 else "mixed")
                print(f"    {s:%Y-%m-%d %H:%M} .. {e:%Y-%m-%d %H:%M}  "
                      f"({n} bins, range {seg.min():.2f}..{seg.max():.2f}, {sig})")

        # Baseline-suspect episodes — dated. Reporting WHEN the sensor sat
        # sub-zero is the evidence to line up against the calibration log; the
        # scan asserts nothing about whether these are recoverable.
        if len(baseline_suspect):
            print("  BASELINE-SUSPECT episodes (sub-zero; adjudicate w/ calibration data):")
            for s, e, n in _episodes(baseline_suspect.index):
                seg = mean[(mean.index >= s) & (mean.index <= e)]
                print(f"    {s:%Y-%m-%d %H:%M} .. {e:%Y-%m-%d %H:%M}  "
                      f"({n} bins, range {seg.min():.2f}..{seg.max():.2f})")

        # Extreme-but-physical episodes — dated and annotated (candidate events)
        if len(extreme):
            print("  EXTREME-but-physical episodes (CANDIDATE real events):")
            for s, e, n in _episodes(extreme.index):
                seg = mean[(mean.index >= s) & (mean.index <= e)]
                tags = _annotate(s, e)
                tagstr = ("  <-- " + "; ".join(tags)) if tags else ""
                print(f"    {s:%Y-%m-%d %H:%M} .. {e:%Y-%m-%d %H:%M}  "
                      f"({n} bins, peak {seg.max():.1f}){tagstr}")

    return summary


def build_flag_mask(ds, channels=None):
    """Return an xarray Dataset of boolean masks marking HARD-FAULT bins per
    channel (True = flagged invalid). Descriptive companion to the archive;
    does NOT modify it. Mild/recoverable and extreme-but-physical are NOT
    flagged here — those are policy decisions left to discussion.
    """
    import xarray as xr
    if channels is None:
        channels = [c for c in BOUNDS if c in ds.data_vars]
    masks = {}
    for ch in channels:
        b = BOUNDS[ch]
        mean = ds[ch].sel(statistic='mean').reset_coords('statistic', drop=True)
        flag = (mean > b['hard_hi']) | (mean < b['soft_lo'])
        masks[ch + '_badflag'] = flag
    return xr.Dataset(masks)
