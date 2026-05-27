# functions for accessing the Sage Python data API

# Standard library
import datetime as dt

# Third party
import pandas as pd
import sage_data_client
from sage_utils import SAGE_MISSING, RESAMPLE_INTERVAL

import sys
sys.path.append('../rivers')

from ncei_io import (
    search_ncei_stations_bbox,
    nearest_station,
    get_ghcnd_daily_summaries,
)


def query_raingauge(site, start, end=None):
    """
    Query RG-15 optical rain gauge data from the Sage/Waggle API.

    The RG-15 reports only during rain events — dry periods return no data.
    Reporting interval is approximately 30 seconds during active rainfall.

    Parameters
    ----------
    site : CrocusSite
        Site object from crocus_sites.py, e.g. CCICS
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1d'
    end : str, optional
        End datetime. If omitted, defaults to now.

    Returns
    -------
    pd.DataFrame with UTC DatetimeIndex and columns:
        event_acc  — rainfall accumulation during current event (mm)
        total_acc  — cumulative total since last reset (mm)
        rint       — rain rate intensity (mm/hr)
        vsn        — Sage/Waggle node ID
    Returns an empty DataFrame if no rain events occurred in the period.

    Raises
    ------
    ValueError if site has no raingauge.
    """
    if not site.has_raingauge:
        raise ValueError(
            f"{site.full_name} has no rain gauge configured."
        )

    query_kwargs = dict(
        start=start,
        filter={
            'name': (
                'env.raingauge.event_acc|'
                'env.raingauge.total_acc|'
                'env.raingauge.rint'
            ),
            'vsn': site.vsn,
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    if df.empty:
        return pd.DataFrame()

    df_wide = df.pivot_table(
        index='timestamp',
        columns='name',
        values='value',
        aggfunc='mean'
    ).astype(float)
    df_wide = df_wide.replace(SAGE_MISSING, float('nan'))
    df_wide.index = pd.to_datetime(df_wide.index, utc=True)
    df_wide.columns = ['event_acc', 'rint', 'total_acc']
    df_wide['vsn'] = site.vsn

    return df_wide



def query_asos(site, start, end):
    """
    Fetch hourly ASOS data from the Iowa Environmental Mesonet for the
    nearest available airport station to a CROCUS site.

    Tries stations in order of distance, falling back to the next nearest
    if a station returns no data. All available IEM variables are returned.

    Parameters
    ----------
    site : CROCUSSite
        Site object from crocus_sites.py, e.g. NEIU
    start : str
        Start datetime in Sage API format e.g. '2026-03-01T00:00:00Z'
        or bare date '2026-03-01'. As returned by last_n_hours().
    end : str
        End datetime, same format as start.

    Returns
    -------
    pd.DataFrame with UTC DatetimeIndex and columns:
        station                   — ASOS station ID
        tmpc                      — temperature (°C)
        dwpc                      — dewpoint (°C)
        relh                      — relative humidity (%)
        drct                      — wind direction (degrees)
        sknt                      — wind speed (knots)
        gust                      — wind gust (knots)
        mslp                      — mean sea level pressure (hPa)
        alti                      — altimeter setting (inches Hg)
        vsby                      — visibility (miles)
        precip_mm                 — hourly precipitation (mm, converted from p01i)
        wxcodes                   — present weather codes
    Returns an empty DataFrame if no data found at any nearby station.
    """
    import requests
    from io import StringIO

    # All IEM ASOS variable codes to request
    IEM_VARS = [
        'tmpc', 'dwpc', 'relh',
        'drct', 'sknt', 'gust',
        'mslp', 'alti', 'vsby',
        'p01i', 'wxcodes',
    ]

    # Chicago-area ASOS stations
    candidates = {
        'KMDW': (41.7859, -87.7524),   # Midway
        'KORD': (41.9742, -87.9073),   # O'Hare
        'KPWK': (42.1142, -87.9015),   # Palwaukee/Chicago Executive
        'KARR': (41.7719, -88.4754),   # Aurora
    }

    # Sort by distance to site
    sorted_stations = sorted(
        candidates.items(),
        key=lambda x: (x[1][0] - site.lat)**2 + (x[1][1] - site.lon)**2
    )

    def _fetch(station_id):
        t_start = pd.to_datetime(start, utc=True)
        t_end   = pd.to_datetime(end,   utc=True)

        data_str = '&'.join(f'data={v}' for v in IEM_VARS)
        url = (
            "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
            f"?station={station_id}"
            f"&{data_str}"
            f"&year1={t_start.year}&month1={t_start.month}&day1={t_start.day}"
            f"&year2={t_end.year}&month2={t_end.month}&day2={t_end.day}"
            f"&tz=UTC&format=onlycomma&latlon=no&missing=M&trace=T&direct=no"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  Request failed for {station_id}: {e}")
            return pd.DataFrame()

        df = pd.read_csv(StringIO(resp.text), skiprows=5,
                         names=['station', 'valid'] + IEM_VARS)
        if df.empty:
            return pd.DataFrame()

        df['valid'] = pd.to_datetime(df['valid'], utc=True)
        df = df.set_index('valid').sort_index()

        # Numeric conversion — replace missing/trace
        for col in IEM_VARS:
            if col == 'wxcodes':
                continue
            df[col] = pd.to_numeric(
                df[col].replace({'T': 0.0, 'M': float('nan')}),
                errors='coerce'
            )

        # Convert precip inches → mm
        df['precip_mm'] = df['p01i'] * 25.4
        df = df.drop(columns=['p01i'])

        # Convert wind knots → m/s
        df['sknt'] = df['sknt'] * 0.51444
        df = df.rename(columns={'sknt': 'wind_speed'})
        if 'gust' in df.columns:
            df['gust'] = df['gust'] * 0.51444

        return df

    for station_id, coords in sorted_stations:
        print(f"Trying ASOS station: {station_id} "
              f"({coords[0]:.4f}, {coords[1]:.4f})")
        df = _fetch(station_id)
        if not df.empty and df['tmpc'].notna().any():
            print(f"  Using {station_id}")
            return df
        print(f"  No data returned, trying next nearest...")

    print(f"No ASOS data found for any station near {site.abbr}.")
    return pd.DataFrame()

def query_cocorahs(site, start, end, n_stations=3):
    """
    Find the nearest CoCoRaHS stations to a CROCUS site and return
    daily precipitation totals via the Iowa Environmental Mesonet (IEM).

    Station locations are discovered via the GHCND station metadata file
    (fast, cached after first call). Data is fetched from IEM which is
    significantly faster than NCEI for recent dates.

    CoCoRaHS stations report a 24-hour accumulation ending at 7 AM local
    time — not directly comparable to the RG-15 continuous record, but
    useful for event-level validation.

    Parameters
    ----------
    site : CROCUSSite
        Site object from crocus_sites.py, e.g. NEIU
    start : str
        Start datetime in Sage API format e.g. '2026-03-01T00:00:00Z'
        or bare date '2026-03-01'. As returned by last_n_hours().
    end : str
        End datetime, same format as start.
    n_stations : int, optional
        Number of nearest stations to return. Default 3.

    Returns
    -------
    pd.DataFrame with UTC DatetimeIndex and columns:
        precip_mm  — daily precipitation (mm)
        station    — IEM station ID (e.g. 'IL-CK-36')
        name       — station name
        dist_km    — distance from site (km)
    Returns an empty DataFrame if no data found.
    """
    import requests
    from io import StringIO

    def _ghcnd_to_iem(station_id):
        """Convert GHCND ID (US1ILCK0036) → IEM ID (IL-CK-36)."""
        s      = station_id[3:]        # 'ILCK0036'
        state  = s[:2]                 # 'IL'
        county = s[2:4]                # 'CK'
        number = str(int(s[4:]))       # '36' (strips leading zeros)
        return f"{state}-{county}-{number}"

    def _fetch_iem(iem_ids, t_start, t_end):
        stations_str = '&stations='.join(iem_ids)
        url = (
            "https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py"
            f"?network=IL_COCORAHS"
            f"&stations={stations_str}"
            f"&year1={t_start.year}&month1={t_start.month}&day1={t_start.day}"
            f"&year2={t_end.year}&month2={t_end.month}&day2={t_end.day}"
            f"&format=csv&na=blank"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  IEM request failed: {e}")
            return pd.DataFrame()

        df = pd.read_csv(StringIO(resp.text), low_memory=False)
        return df

    # --- Station discovery via GHCND (cached after first call) --------------
    bbox_deg = 1.0
    candidates = search_ncei_stations_bbox(
        north=site.lat + bbox_deg,
        south=site.lat - bbox_deg,
        west=site.lon - bbox_deg,
        east=site.lon + bbox_deg,
    )

    cocorahs = candidates[candidates['STATION'].str.startswith('US1')].copy()
    if cocorahs.empty:
        print(f"No CoCoRaHS stations found within {bbox_deg}° of {site.abbr}.")
        return pd.DataFrame()

    nearby = nearest_station(site.lat, site.lon, cocorahs, n=n_stations)
    print(f"Nearest CoCoRaHS stations to {site.abbr}:")
    print(nearby[['STATION', 'NAME', 'DIST_KM']].to_string(index=False))

    # --- Convert IDs and fetch from IEM -------------------------------------
    t_start = pd.to_datetime(start, utc=True)
    t_end   = pd.to_datetime(end,   utc=True)

    nearby['IEM_ID'] = nearby['STATION'].apply(_ghcnd_to_iem)
    iem_ids = nearby['IEM_ID'].tolist()

    df_all = _fetch_iem(iem_ids, t_start, t_end)

    if df_all.empty:
        print(f"CoCoRaHS stations found but no observations reported in this period.")
        print(f"Stations checked: {', '.join(iem_ids)}")
        return pd.DataFrame()

    # --- Wrangle ------------------------------------------------------------
    df_all['day']       = pd.to_datetime(df_all['day'], utc=True)
    df_all              = df_all.set_index('day').sort_index()
    df_all['precip_mm'] = pd.to_numeric(df_all['precip_in'], errors='coerce') * 25.4

    # Merge in distance and name from nearby lookup
    df_all = df_all.rename(columns={'station': 'station'})
    df_all = df_all.merge(
        nearby[['IEM_ID', 'NAME', 'DIST_KM']].rename(
            columns={'IEM_ID': 'station', 'NAME': 'name', 'DIST_KM': 'dist_km'}
        ),
        on='station', how='left'
    )

    return df_all[['precip_mm', 'station', 'name', 'dist_km']].sort_index()