# functions for accessing the Sage Python data API

# Standard library
import datetime as dt

# Third party
import pandas as pd
import sage_data_client

# local
from crocus_sites import TEROS_DEPTHS

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
    >>> df = query_aqt(NEIU, start, end)
    """
    now   = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours)
    return start.strftime('%Y-%m-%dT%H:%M:%SZ'), now.strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def query_aqt(site, start, end=None, resample=RESAMPLE_INTERVAL):
    """
    Query Vaisala AQT530 air quality transmitter data from the Sage/Waggle API.
    Returns PM1, PM2.5, PM10, CO, NO, NO2, O3, temperature, humidity and
    pressure resampled to a consistent 5-minute resolution.
    NB: Some nodes have PM sensors that have stopped functioning — check
    site status before interpreting PM data.

    Parameters
    ----------
    site: CROCUSSite
         Site object from crocus_sites.py, e.g. NEIU
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
    
    vsn = site.vsn
    
    if not site.has_aqt:
        raise ValueError(
            f"{site.full_name} has no AQT configured."
        )
    
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
    
    if df.empty:
        print(f"No AQT data returned for {vsn}.")
        return pd.DataFrame()

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


def query_wxt(site, start, end=None, resample=RESAMPLE_INTERVAL):
    """
    Query Vaisala WXT536 weather transmitter data from the Sage/Waggle API.
    Returns temperature, humidity, pressure, rain accumulation, wind direction
    and wind speed resampled to a consistent 5-minute resolution.
    NB: Historical WXT data (pre-2026) was sampled at >1Hz — resampling
    is essential for historical queries.

    Parameters
    ----------
    site : CROCUSSite
         Site object from crocus_sites.py, e.g. NEIU
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
    
    vsn = site.vsn

    if not site.has_wxt:
        raise ValueError(
            f"{site.full_name} has no WXT configured."
        )

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
    
    if df.empty:
        print(f"No WXT data returned for {vsn}.")
        return pd.DataFrame()

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

def query_sapflow(site, start, end=None):
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
    site : CrocusSite
        Site object from crocus_sites.py, e.g. NEIU
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
    ValueError if site has no sap flow data.
    """
    if not site.has_sapflow:
        raise ValueError(
            f"{site.full_name} has no sap flow sensors configured."
        )

    query_kwargs = dict(
        start=start,
        filter={
            'name': 'uncorrected_inner|uncorrected_outer|battery_voltage',
            'vsn':  site.vsn,
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    if df.empty:
        return {}

    result = {}

    for serial, info in site.sapflow.items():
        subset = df[df['meta.serial_number_tag'] == serial].copy()
        if subset.empty:
            continue

        df_wide = subset.pivot_table(
            index='timestamp',
            columns='name',
            values='value',
            aggfunc='mean'
        ).astype(float)
        df_wide = df_wide.replace(SAGE_MISSING, float('nan'))
        df_wide.index = pd.to_datetime(df_wide.index, utc=True)
        df_wide = df_wide.rename(columns={
            'uncorrected_inner': 'inner',
            'uncorrected_outer': 'outer',
        })
        df_wide['vsn']    = site.vsn
        df_wide['serial'] = serial

        result[info] = df_wide 

    return result


def query_mfr(site, start, end=None):
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
    returned as a separate DataFrame keyed by sub-site label.

    Note: QC flags are available in the published CSV/NetCDF dataset but
    are not applied here. Treat returned values as raw observations.

    Note: Timestamps are UTC. The published dataset description references
    local Chicago time (CDT/CST).

    Parameters
    ----------
    site : CrocusSite
        Site object from crocus_sites.py, e.g. NEIU
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1h'
    end : str, optional
        End datetime. If omitted, defaults to now.

    Returns
    -------
    dict of pd.DataFrame, keyed by sub-site label (e.g. 'savannah', 'lawn').
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
    ValueError if site has no MFR data.
    """
    if not site.has_mfr:
        raise ValueError(
            f"{site.full_name} has no MFR nodes configured."
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
            'vsn': site.vsn,
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    if df.empty:
        return {}

    result = {}

    for serial, info in site.mfr.items():
        subset = df[df['meta.serial_number_tag'] == serial].copy()
        if subset.empty:
            continue

        df_wide = subset.pivot_table(
            index='timestamp',
            columns='name',
            values='value',
            aggfunc='mean'
        ).astype(float)
        df_wide = df_wide.replace(SAGE_MISSING, float('nan'))
        df_wide.index = pd.to_datetime(df_wide.index, utc=True)
        df_wide = df_wide.rename(columns={
            'air_temperature':         'air_temp',
            'barometric_pressure':     'pressure',
            'relative_humidity':       'humidity',
            'vapour_pressure_deficit': 'vpd',
            'in_shortwave':            'in_shortwave',
            'out_shortwave':           'out_shortwave',
            'in_longwave':             'in_longwave',
            'out_longwave':            'out_longwave',
            'heat_flux':               'heat_flux',
            'battery_voltage':         'battery_voltage',
            'solar_voltage':           'solar_voltage',
            **TEROS_DEPTHS,
        })
        df_wide['vsn']    = site.vsn
        df_wide['serial'] = serial

        result[info['label']] = df_wide
        
    return result

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


def query_bme680(site, start, end=None, resample=RESAMPLE_INTERVAL):
    """
    Query BME680 environmental sensor data from the Sage/Waggle API.

    The BME680 is mounted in a radiation shield external to the node enclosure — providing
    ambient temperature, humidity, pressure measurements, and a broadband gas resistance
    (a proxy for VOC/combustion load, not calibrated to specific compounds).

    Parameters
    ----------
    site : CROCUSSite
        Site object from crocus_sites.py, e.g. NEIU
    start : str
        Start datetime, absolute e.g. '2023-06-01' or relative e.g. '-1h'
    end : str, optional
        End datetime. If omitted, defaults to now.
    resample : str, optional
        Pandas offset string for output resolution, e.g. '1min', '5min', '1h'.
        Default is RESAMPLE_INTERVAL.

    Returns
    -------
    pd.DataFrame resampled to `resample` interval with UTC DatetimeIndex
    and columns:
        temp, humidity, pressure, gas_resistance, vsn, sensor
    Returns an empty DataFrame if no data is found.

    Raises
    ------
    ValueError if site has no BME680 configured.
    """
    if not site.has_bme680:
        raise ValueError(
            f"{site.full_name} has no BME680 configured."
        )

    query_kwargs = dict(
        start=start,
        filter={
            'name': (
                'env.temperature|env.relative_humidity|'
                'env.pressure|env.gas_resistance'
            ),
            'vsn':    site.vsn,
            'sensor': 'bme680',
        }
    )
    if end is not None:
        query_kwargs['end'] = end

    df = sage_data_client.query(**query_kwargs)

    if df.empty:
        print(f"No BME680 data returned for {site.vsn}.")
        return pd.DataFrame()

    df_wide = df.pivot_table(
        index='timestamp',
        columns='name',
        values='value',
        aggfunc='mean'
    ).astype(float)
    df_wide = df_wide.replace(SAGE_MISSING, float('nan'))
    df_wide.index = pd.to_datetime(df_wide.index, utc=True)
    
    df_wide = df_wide.rename(columns={
        'env.gas_resistance':    'gas_resistance',
        'env.relative_humidity': 'humidity',
        'env.pressure':          'pressure',
        'env.temperature':       'temp',
    })

    df_wide = df_wide.resample(resample).mean(numeric_only=True)

    df_wide['vsn']    = df['meta.vsn'].iloc[0]
    df_wide['sensor'] = df['meta.sensor'].iloc[0]

    return df_wide