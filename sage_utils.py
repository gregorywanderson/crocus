# functions for accessing the Sage Python data API

# Standard library
import datetime as dt

# Third party
import pandas as pd
import sage_data_client

# Note: The Sage API uses SAGE_MISSING as a fill value for missing measurements.
# All query functions replace this with NaN before returning.

SAGE_MISSING = -9999.9  # Sage API fill value for missing data

# Default resampling interval for query functions.
# 5-minute is chosen to match the current WXT and AQT plugin output resolution
# and to provide consistent output across all years:
#   - WXT historical (pre-2026): >1Hz → downsampled to 5min
#   - AQT historical (pre-2026): 1-minute → downsampled to 5min
#   - WXT current (post-2026):   5-minute → no change
#   - AQT current (post-2026):   5-minute → no change

RESAMPLE_INTERVAL = '5min'


CROCUS_NODES = { 
    'ATMOS': 'W0A4',  # Argonne Testbed for Multiscale Observational Science
    'BIG':   'W0A0',  # Blacks in Green (West Woodlawn)
    'CCICS': 'W08B',  # Carruthers Center for Inner City Studies - Bronzeville (NEIU satellite)
    'CSU':   'W08E',  # Chicago State University
    'HUM':   'W0A1',  # Humboldt Park 
    'NEIU':  'W08D',  # Northeastern Illinois University
    'NU':    'W099',  # Northwestern University
    'SHEDD': 'W09E',  # Shedd Aquarium
    'UIC':   'W096',  # University of Illinois Chicago
}

# ---------------------------------------------------------------------------
# Site-specific metadata
# ---------------------------------------------------------------------------

# Sap flow serial number to meaningful label mapping per node.
# Each sap flow meter uses a thermal dissipation probe with two sensors
# at different depths within the tree (inner and outer xylem).
# Update species labels here as new nodes are characterized.

SAPFLOW_LABELS = {
    'W08D': {
        'SX61NA0C': 'white_oak_1',
        'SX61NA0X': 'white_oak_2',
        'SX61NA0V': 'american_elm_1',
        'SX61NA01': 'sugar_maple_1',
        'SX61NA0J': 'sugar_maple_2',
        'SX61NA0N': 'sugar_maple_3',
    },
    'W08E': {
        'SX61NA0D': 'cottonwood_1',
        'SX61NA0W': 'cottonwood_2',
        'SX61NA0E': 'cottonwood_3',
        'SX61NA0P': 'american_elm_1',
        'SX61NA0H': 'american_elm_2',
        'SX61NA08': 'maple_1',
        'SX61NA0T': 'maple_2',
        'SX61NA0A': 'maple_3',
    },
    'W099': {
        'SX61NA0Y': 'maple_1',
        'SX61NA0F': 'maple_2',
        'SX61NA07': 'oak_1',
        'SX61NA0G': 'oak_2',
        'SX61NA0L': 'maple_3',
        'SX61N501': 'maple_4',
    },
    'W096': {
        'SX61NA0B': 'american_elm_1',
        'SX61NA0R': 'honey_locust_1',
        'SX61NA0M': 'honey_locust_2',
        'SX61NA0S': 'maple_1',
        'SX61NA0K': 'maple_2',
        'SX61NA05': 'honey_locust_3',
        'SX61NA0O': 'american_elm_2',
    },
    'W0A0': {
        'SX61NA0U': 'tree_1',   # species TBD
        'SX61NA09': 'tree_2',   # species TBD
        'SX61NA0I': 'tree_3',   # species TBD
    },
}

# MFR node serial number to meaningful label mapping per node.
# Update site labels here as sub-site descriptions become available.
MFR_LABELS = {
    'W08D': {
        'MNLA4O107': 'savannah',  # Swamp White Oak Savannah (south)
        'MNLA4O108': 'lawn',      # Lawn near Administrative building
    },
    'W08E': {
        'MNLA4O102': 'non_prairie',
        'MNLA4O103': 'prairie',
    },
    'W099': {
        'MNLA4O104': 'site_1',    # sub-site TBD
    },
    'W096': {
        'MNLA4O105': 'site_1',    # sub-site TBD
        'MNLA4O106': 'site_2',    # sub-site TBD
    },
    'W0A0': {
        'MNLA4O10A': 'site_1',    # sub-site TBD
        'MNLA4O10B': 'site_2',    # sub-site TBD
        'MNLA4O10C': 'site_3',    # sub-site TBD
    },
}

# Teros54 depth column rename mapping
TEROS_DEPTHS = {
    'temp_d1': 'temp_15cm',
    'temp_d2': 'temp_30cm',
    'temp_d3': 'temp_45cm',
    'temp_d4': 'temp_60cm',
    'vwc_d1':  'vwc_15cm',
    'vwc_d2':  'vwc_30cm',
    'vwc_d3':  'vwc_45cm',
    'vwc_d4':  'vwc_60cm',
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def last_n_hours(hours=1):
    """
    Return a (start, end) tuple for the last N hours in Sage API format.

    Parameters
    ----------
    hours : int or float, optional
        Number of hours to look back. Default is 1.

    Returns
    -------
    tuple of str : (start, end) formatted as '%Y-%m-%dT%H:%M:%SZ'

    Examples
    --------
    >>> start, end = last_n_hours(6)
    >>> df = query_aqt('W08D', start, end)
    """
    now   = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours)
    return start.strftime('%Y-%m-%dT%H:%M:%SZ'), now.strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def query_aqt(vsn, start, end=None, resample=RESAMPLE_INTERVAL):
    """
    Query AQT air quality data from the Sage/Waggle API for a single node.

    Parameters
    ----------
    vsn : str
        Node ID, e.g. 'W08D'
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1h'
    end : str, optional
        End datetime. If omitted, defaults to now.
    resample : str, optional
        Pandas offset string for output resolution, e.g. '1min', '5min', '1h'.
        Default is RESAMPLE_INTERVAL. Should be >= native data resolution.    

    Returns
    -------
    pd.DataFrame resampled to `resample` interval with UTC DatetimeIndex
    and columns:
        humidity, pressure, temp, co, no, no2, o3, pm1, pm10, pm25, vsn, sensor
    """
    exclude = {'aqt.house.datetime', 'aqt.house.uptime'}

    query_kwargs = dict(
        start=start,
        filter={
            'name': 'aqt.*',
            'vsn': vsn,
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    df_wide = df[~df['name'].isin(exclude)].pivot_table(
        index='timestamp',
        columns='name',
        values='value',
        aggfunc='mean'
    ).astype(float)
    # Replace Sage missing value flag with NaN
    df_wide = df_wide.replace(SAGE_MISSING, float('nan'))

    df_wide.index = pd.to_datetime(df_wide.index, utc=True)
    df_wide.columns = [
        'humidity', 'pressure', 'temp',
        'co', 'no', 'no2', 'o3',
        'pm1', 'pm10', 'pm25'
    ]

    # Resample to consistent output resolution — see RESAMPLE_INTERVAL
    df_wide = df_wide.resample(resample).mean(numeric_only=True)

    df_wide['vsn']    = df['meta.vsn'].iloc[0]
    df_wide['sensor'] = df['meta.sensor'].iloc[0]

    return df_wide


def query_wxt(vsn, start, end=None, resample=RESAMPLE_INTERVAL):
    """
    Query WXT weather data from the Sage/Waggle API for a single node.
    NB: Historical WXT data (pre-2025 approx.) was sampled at >1Hz,
    resulting in ~1M rows per day. Current data is averaged to 5-minute
    intervals server-side. The 5-minute resample in query_wxt() handles
    both cases correctly.

    Parameters
    ----------
    vsn : str
        Node ID, e.g. 'W08D'
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1h'
    end : str, optional
        End datetime. If omitted, defaults to now.
    resample : str, optional
        Pandas offset string for output resolution, e.g. '1min', '5min', '1h'.
        Default is RESAMPLE_INTERVAL. Should be >= native data resolution.    

    Returns
    -------
     pd.DataFrame resampled to `resample` interval with UTC DatetimeIndex
     and columns:
        humidity, pressure, temp, rain, wind_dir, wind_speed, vsn, sensor
    """

    query_kwargs = dict(
        start=start,
        filter={
            'name': 'wxt.env.humidity|wxt.env.pressure|wxt.env.temp|'
            'wxt.rain.accumulation|wxt.wind.direction|wxt.wind.speed',
            'vsn': vsn,
            }
        )          
  
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    df_wide = df.pivot_table(
        index='timestamp',
        columns='name',
        values='value',
        aggfunc='mean'
    ).astype(float)
    # Replace Sage missing value flag with NaN
    df_wide = df_wide.replace(SAGE_MISSING, float('nan'))

    df_wide.index = pd.to_datetime(df_wide.index, utc=True)
    df_wide.columns = [
        'humidity', 'pressure', 'temp',
        'rain', 'wind_dir', 'wind_speed'
        ]
   
    # Resample to consistent output resolution — see RESAMPLE_INTERVAL
    df_wide = df_wide.resample(resample).mean(numeric_only=True)   

    df_wide['vsn']    = df['meta.vsn'].iloc[0]
    df_wide['sensor'] = df['meta.sensor'].iloc[0]

    return df_wide


def query_sapflow(vsn, start, end=None):
    """
    Query sap flow sensor data from the Sage/Waggle API for a single node.

    Each sap flow meter uses a thermal dissipation probe with two sensors
    at different depths within the tree (inner and outer xylem). The
    'inner' and 'outer' columns are uncorrected temperature differences
    in cm/hr — a correction step is required to convert these to
    calibrated sap flow rates.

    Sensors connect to the waggle node via LoRaWAN. Multiple sap flow
    meters are connected to a single node; each is returned as a
    separate DataFrame keyed by species label.

    Parameters
    ----------
    vsn : str
        Node ID, e.g. 'W08D'
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1h'
    end : str, optional
        End datetime. If omitted, defaults to now.

    Returns
    -------
    dict of pd.DataFrame, keyed by species label (e.g. 'white_oak_1').
    Each DataFrame has a UTC DatetimeIndex and columns:
        inner, outer, battery_voltage, vsn, serial
    Returns an empty dict if no data is found.

    Raises
    ------
    ValueError if vsn is not in SAPFLOW_LABELS.
    """
    if vsn not in SAPFLOW_LABELS:
        raise ValueError(
            f"No sap flow label mapping for node '{vsn}'. "
            f"Known nodes: {list(SAPFLOW_LABELS.keys())}"
        )

    query_kwargs = dict(
        start=start,
        filter={
            'name': 'uncorrected_inner|uncorrected_outer|battery_voltage',
            'vsn': vsn,
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    if df.empty:
        return {}

    labels = SAPFLOW_LABELS[vsn]
    result = {}

    for serial, label in labels.items():
        subset = df[df['meta.serial_number_tag'] == serial].copy()
        if subset.empty:
            continue

        df_wide = subset.pivot_table(
            index='timestamp',
            columns='name',
            values='value',
            aggfunc='mean'
        ).astype(float)
        # Replace Sage missing value flag with NaN
        df_wide = df_wide.replace(SAGE_MISSING, float('nan'))

        df_wide.index = pd.to_datetime(df_wide.index, utc=True)
        df_wide = df_wide.rename(columns={
            'uncorrected_inner': 'inner',
            'uncorrected_outer': 'outer',
        })
        df_wide['vsn']    = vsn
        df_wide['serial'] = serial

        result[label] = df_wide

    return result


def query_mfr(vsn, start, end=None):
    """
    Query Multi-Function Research (MFR) node data from the Sage/Waggle API.

    MFR nodes are LoRaWAN-enabled and report atmospheric, soil, and
    hydrological variables. Each node supports:
      - ATH-VPD: 2m air temperature (°C), barometric pressure (Pa),
                 relative humidity (%), vapour pressure deficit (kPa)
      - SN500: incoming/outgoing shortwave and longwave radiation (W/m²)
      - HFP01-05: soil heat flux at 10cm depth (W/m²)
      - Teros54: soil temperature (°C) and volumetric water content (%)
                 at 15, 30, 45, and 60 cm depth
      - MFR Node: battery voltage (V) and solar voltage (V)

    Multiple MFR nodes may be connected to a single waggle node; each is
    returned as a separate DataFrame keyed by site label.

    Note: QC flags are available in the published CSV/NetCDF dataset but
    are not applied here. Treat returned values as raw observations.

    Note: Timestamps are UTC. The published dataset description references
    local Chicago time (CDT/CST).

    Parameters
    ----------
    vsn : str
        Node ID, e.g. 'W08D'
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1h'
    end : str, optional
        End datetime. If omitted, defaults to now.

    Returns
    -------
    dict of pd.DataFrame, keyed by site label (e.g. 'savannah', 'lawn').
    Each DataFrame has a UTC DatetimeIndex and columns:
        air_temp, pressure, humidity, vpd,
        in_shortwave, out_shortwave, in_longwave, out_longwave,
        heat_flux,
        temp_15cm, temp_30cm, temp_45cm, temp_60cm,
        vwc_15cm, vwc_30cm, vwc_45cm, vwc_60cm,
        battery_voltage, solar_voltage,
        vsn, serial
    Returns an empty dict if no data is found.

    Raises
    ------
    ValueError if vsn is not in MFR_LABELS.
    """
    if vsn not in MFR_LABELS:
        raise ValueError(
            f"No MFR label mapping for node '{vsn}'. "
            f"Known nodes: {list(MFR_LABELS.keys())}"
        )

    query_kwargs = dict(
        start=start,
        filter={
            'name': (
                'air_temperature|barometric_pressure|relative_humidity|'
                'vapour_pressure_deficit|'
                'in_shortwave|out_shortwave|in_longwave|out_longwave|'
                'heat_flux|'
                'temp_d1|temp_d2|temp_d3|temp_d4|'
                'vwc_d1|vwc_d2|vwc_d3|vwc_d4|'
                'battery_voltage|solar_voltage'
            ),
            'vsn': vsn,
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    if df.empty:
        return {}

    labels = MFR_LABELS[vsn]
    result = {}

    for serial, label in labels.items():
        subset = df[df['meta.serial_number_tag'] == serial].copy()
        if subset.empty:
            continue

        df_wide = subset.pivot_table(
            index='timestamp',
            columns='name',
            values='value',
            aggfunc='mean'
        ).astype(float)
        # Replace Sage missing value flag with NaN
        df_wide = df_wide.replace(SAGE_MISSING, float('nan'))

        df_wide.index = pd.to_datetime(df_wide.index, utc=True)
        df_wide = df_wide.rename(columns={
            'air_temperature':       'air_temp',
            'barometric_pressure':   'pressure',
            'relative_humidity':     'humidity',
            'vapour_pressure_deficit': 'vpd',
            'in_shortwave':          'in_shortwave',
            'out_shortwave':         'out_shortwave',
            'in_longwave':           'in_longwave',
            'out_longwave':          'out_longwave',
            'heat_flux':             'heat_flux',
            'battery_voltage':       'battery_voltage',
            'solar_voltage':         'solar_voltage',
            **TEROS_DEPTHS,
        })
        df_wide['vsn']    = vsn
        df_wide['serial'] = serial

        result[label] = df_wide

    return result
