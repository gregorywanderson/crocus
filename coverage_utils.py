# functions for assessing CROCUS data coverage

# Standard library
import datetime as dt

# Third party
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sage_data_client
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from sage_utils import SAGE_MISSING, last_n_hours
import crocus_sites

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


def check_network_status(sites, hours=6, rg15_hours=24):
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
