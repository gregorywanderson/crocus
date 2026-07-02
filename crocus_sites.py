"""
crocus_sites.py

Site-specific metadata for the CROCUS (Community Research on Climate and
Urban Science) urban field network in Chicago, Illinois.

Each site is defined as a CROCUSSite instance with attributes for the
Sage/Waggle Virtual Sage Node ID (VSN), geographic coordinates, sensor
availability flags, and sensor-specific metadata (sap flow species labels,
MFR sub-site labels).

Update this file as new nodes are added or site descriptions become available.

Usage
-----
    from crocus_sites import NEIU, ALL_SITES

    # Direct access
    print(NEIU.vsn)          # 'W08D'
    print(NEIU.lat)          # 41.9803
    print(NEIU.has_mfr)      # True

    # Iterate over all sites
    for site in ALL_SITES:
        print(f"{site.abbr:<8} {site.vsn}  {site.full_name}")

    # Filter by sensor type
    mfr_sites = [site for site in ALL_SITES if site.has_mfr]
"""

# Standard library
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Site dataclass
# ---------------------------------------------------------------------------

@dataclass
class CROCUSSite:
    """
    Metadata for a single CROCUS field site.

    Attributes
    ----------
    vsn : str
        Sage/Waggle Virtual Sage Node ID, e.g. 'W08D'
    full_name : str
        Full descriptive name of the site.
    abbr : str
        Short site abbreviation, e.g. 'NEIU'
    lat : float
        Latitude in decimal degrees (WGS84).
    lon : float
        Longitude in decimal degrees (WGS84), negative for west.
    has_aqt : bool
        True if site has an AQT air quality sensor. Default True.
    has_wxt : bool
        True if site has a WXT weather transmitter. Default True.
    has_raingauge : bool
        True if site has an RG-15 optical rain gauge. Default True.
    has_bme680 : bool
        True if site has a BME680 temp/humidity/pressure/gas sensor. Default True.
    has_mfr : bool
        True if site has one or more MFR nodes. Default False.
    has_sapflow : bool
        True if site has one or more sap flow meters. Default False.
    sapflow : dict, optional
        Mapping of sap flow serial number to species label,
        e.g. {'SX61NA0C': 'white_oak_1'}. Required if has_sapflow=True.
    mfr : dict, optional
        Mapping of MFR serial number to sub-site info dict:
        e.g. {'MNLA4O107': {'label': 'savannah', 'lat': 41.981, 'lon': -87.717}}
        Required if has_mfr=True.
    deployments : dict, optional
        Mapping of instrument class to (start, end) date strings, e.g.
        {'wxt': ('2023-05-05', None), 'aqt': ('2023-05-05', None)}.
        Dates are ISO 'YYYY-MM-DD'; end=None means still deployed.
        Semantics (used by coverage graphics via `deployed()`):
          - key present with a start date  -> deployed then; data absent
            *before* the start is expected (pre-deployment), not a gap.
          - key present with start=None     -> known deployed, date unknown.
          - key absent                      -> never deployed here; absence
            of data is intentional, not a gap.
        The weather package (wxt/aqt) shares a single install date per site.
        Sap flow and MFR install dates are not yet recorded and are left out
        until known; add them here as they become available.
    """
    vsn:       str
    full_name: str
    abbr:      str
    lat:       float
    lon:       float

    # Standard Waggle node hardware — True by default
    has_aqt:       bool = True
    has_wxt:       bool = True
    has_raingauge: bool = True
    has_bme680:    bool = True

    # Site-specific additions — False by default
    has_mfr:     bool = False
    has_sapflow: bool = False
    has_lorawan: bool = False

    sapflow: Optional[dict] = field(default=None, repr=False)
    mfr:     Optional[dict] = field(default=None, repr=False)
    deployments: Optional[dict] = field(default=None, repr=False)

    def __post_init__(self):
        if self.has_sapflow and self.sapflow is None:
            raise ValueError(
                f"{self.full_name}: has_sapflow=True but no sapflow dict provided"
            )
        if self.has_mfr and self.mfr is None:
            raise ValueError(
                f"{self.full_name}: has_mfr=True but no mfr dict provided"
            )

    def deployed(self, instrument, when):
        """
        Was `instrument` deployed at this site on/at date `when`?

        Parameters
        ----------
        instrument : str
            Instrument class key, e.g. 'wxt', 'aqt', 'mfr', 'sapflow'.
        when : str, datetime, or pandas.Timestamp
            Date to test (anything pandas can parse).

        Returns
        -------
        bool or None
            True  -> instrument was deployed and `when` is on/after its start.
            False -> instrument exists here but `when` is before its start
                     (pre-deployment) OR the instrument was never deployed here.
            None  -> deployment status unknown (no deployments dict, or the
                     instrument's start date is not recorded); caller should
                     not treat missing data as a gap in this case.

        Intended for coverage graphics: use it to grey out / mask periods
        before an instrument was installed, distinguishing "not yet deployed"
        and "never deployed here" from a genuine data gap.
        """
        import pandas as pd
        if not self.deployments:
            return None
        if instrument not in self.deployments:
            return False          # never deployed at this site
        start, end = self.deployments[instrument]
        if start is None:
            return None           # deployed, but install date unknown
        t = pd.to_datetime(when)
        start = pd.to_datetime(start)
        if t < start:
            return False          # before install -> pre-deployment
        if end is not None and t > pd.to_datetime(end):
            return False          # after removal
        return True

    def deployment_start(self, instrument):
        """
        ISO 'YYYY-MM-DD' start date for `instrument` at this site, or None if
        not recorded (no deployments dict, instrument absent, or date unknown).
        Handy as a backfill start bound so queries skip pre-deployment time.
        """
        if not self.deployments:
            return None
        entry = self.deployments.get(instrument)
        if entry is None:
            return None
        start, _end = entry
        return start

# ---------------------------------------------------------------------------
# Teros54 depth column rename mapping (shared across all MFR sites)
# ---------------------------------------------------------------------------

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
# Site definitions
# ---------------------------------------------------------------------------

ATMOS = CROCUSSite(
    vsn       = 'W0A4',
    full_name = 'Argonne Testbed for Multiscale Observational Science',
    abbr      = 'ATMOS',
    lat       = 41.701597727,
    lon       = -87.995233141,
    has_lorawan = False,
    deployments = {
        'wxt': ('2024-06-27', None),
        'aqt': ('2024-06-27', None),
    },
)

BIG = CROCUSSite(
    vsn       = 'W0A0',
    full_name = 'Blacks in Green (West Woodlawn)',
    abbr      = 'BIG',
    lat       = 41.777014004,
    lon       = -87.609733534,
    has_lorawan = True,
    has_mfr     = True,
    has_sapflow = True,
    sapflow   = {
        'SX61NA0U': 'tree_1',   # species TBD
        'SX61NA09': 'tree_2',   # species TBD
        'SX61NA0I': 'tree_3',   # species TBD
    },
    mfr       = {
        'MNLA4O10A': {'label': 'champlain', 'lat': 41.778703, 'lon': -87.609806},
        'MNLA4O10B': {'label': 'delta',     'lat': 41.777239, 'lon': -87.608681},
        'MNLA4O10C': {'label': 'langley',   'lat': 41.778769, 'lon': -87.608217},
    },
    deployments = {
        'wxt': ('2024-11-22', None),
        'aqt': ('2024-11-22', None),
    },
)

CCICS = CROCUSSite(
    vsn       = 'W08B',
    full_name = 'Carruthers Center for Inner City Studies — Bronzeville (NEIU satellite)',
    abbr      = 'CCICS',
    lat       = 41.822951506,
    lon       = -87.609693291,
    deployments = {
        'wxt': ('2024-08-27', None),
        'aqt': ('2024-08-27', None),
    },
)

CSU = CROCUSSite(
    vsn       = 'W08E',
    full_name = 'Chicago State University',
    abbr      = 'CSU',
    lat       = 41.719837344,
    lon       = -87.612858510,
    has_lorawan = True,
    has_mfr     = True,
    has_sapflow = True,
    sapflow   = {
        'SX61NA0D': 'cottonwood_1',
        'SX61NA0W': 'cottonwood_2',
        'SX61NA0E': 'cottonwood_3',
        'SX61NA0P': 'american_elm_1',
        'SX61NA0H': 'american_elm_2',
        'SX61NA08': 'maple_1',
        'SX61NA0T': 'maple_2',
        'SX61NA0A': 'maple_3',
    },
    mfr       = {
        'MNLA4O102': {'label': 'non_prairie', 'lat': 41.719631, 'lon': -87.612884},
        'MNLA4O103': {'label': 'prairie',     'lat': 41.719892, 'lon': -87.613022},
    },
    deployments = {
        'wxt': ('2023-07-18', None),
        'aqt': ('2023-07-18', None),
    },
)

DOWN = CROCUSSite(
    vsn       = 'W09D',
    full_name = 'Downers Grove',
    abbr      = 'DOWN',
    lat       = 41.782, #TBD
    lon       = -88.030, #TBD
    deployments = {
        'wxt': ('2025-02-25', None),
        'aqt': ('2025-02-25', None),
    },
)

HUM = CROCUSSite(
    vsn       = 'W0A1',
    full_name = 'Humboldt Park',
    abbr      = 'HUM',
    lat       = 41.905496,  
    lon       = -87.703488, 
    has_lorawan = True,
    has_mfr     = True,
    mfr       = {
        'MNLA4O10F': {'label': 'site_1', 'lat': 41.9000, 'lon': -87.7200},
        'MNLA4O10G': {'label': 'site_2', 'lat': 41.9000, 'lon': -87.7200},
    },
    deployments = {
        'wxt': ('2025-02-20', None),
        'aqt': ('2025-02-20', None),
    },
)

IBP = CROCUSSite(
    vsn       = 'W07C', 
    full_name = 'Indian Boundary Prairies (TNC/NEIU)',
    abbr      = 'IBP',
    lat       = 41.608158146,  
    lon       = -87.7046499, 
    has_aqt       = False,  # no standard weather package here — node + MFR only
    has_wxt       = False,
    has_raingauge = False,
    has_bme680    = False,
    has_lorawan = True,
    has_mfr     = True,
    mfr       = {
        'MNLA4O10D': {'label': 'site_1', 'lat': 41.608168, 'lon': -87.7046499},
    },
    deployments = {
        # No WXT/AQT ever deployed here (no 'wxt'/'aqt' keys).
        # Packman (NU) node + MFR only; install dates not yet recorded.
        'node': (None, None),
        'mfr':  (None, None),
    },
)

NEIU = CROCUSSite(
    vsn       = 'W08D',
    full_name = 'Northeastern Illinois University',
    abbr      = 'NEIU',
    lat       = 41.980532992,
    lon       = -87.716623746,
    has_lorawan = True,
    has_raingauge = False,  # RPi currently inactive
    has_mfr     = True,
    has_sapflow = True,
    sapflow   = {
        'SX61NA0C': 'white_oak_1',
        'SX61NA0X': 'white_oak_2',
        'SX61NA0V': 'american_elm_1',
        'SX61NA01': 'sugar_maple_1',
        'SX61NA0J': 'sugar_maple_2',
        'SX61NA0N': 'sugar_maple_3',
    },
    mfr       = {
        # MNLA4O107 is North (lawn) and MNLA4O108 is South (savanna), but VWC
        # saturation data confirms the savanna (clay soil) is the southern
        'MNLA4O107': {'label': 'lawn', 'lat': 41.981459, 'lon': -87.717300},
        'MNLA4O108': {'label': 'savannah', 'lat': 41.977505, 'lon': -87.716479},
    },
    deployments = {
        'wxt': ('2023-05-05', None),
        'aqt': ('2023-05-05', None),
    },
)

NU = CROCUSSite(
    vsn       = 'W099',
    full_name = 'Northwestern University',
    abbr      = 'NU',
    lat       = 42.051407767,
    lon       = -87.677659396,
    has_lorawan = True,
    has_mfr     = True,
    has_sapflow = True,
    sapflow   = {
        'SX61NA0Y': 'maple_1',
        'SX61NA0F': 'maple_2',
        'SX61NA07': 'oak_1',
        'SX61NA0G': 'oak_2',
        'SX61NA0L': 'maple_3',
        'SX61N501': 'maple_4',
    },
    mfr       = {
        'MNLA4O104': {'label': 'grove', 'lat': 42.052580, 'lon': -87.676820},
    },
    deployments = {
        'wxt': ('2023-12-06', None),
        'aqt': ('2023-12-06', None),
    },
)

SHEDD = CROCUSSite(
    vsn       = 'W09E',
    full_name = 'Shedd Aquarium',
    abbr      = 'SHEDD',
    lat       = 41.868043147,
    lon       = -87.613391117,
    deployments = {
        'wxt': ('2025-02-28', None),
        'aqt': ('2025-02-28', None),
    },
)

UIC = CROCUSSite(
    vsn       = 'W096',
    full_name = 'University of Illinois Chicago',
    abbr      = 'UIC',
    lat       = 41.868532807,
    lon       = -87.645894840,
    has_lorawan = True,
    has_mfr     = True,
    has_sapflow = True,
    sapflow   = {
        'SX61NA0B': 'american_elm_1',
        'SX61NA0R': 'honey_locust_1',
        'SX61NA0M': 'honey_locust_2',
        'SX61NA0S': 'maple_1',
        'SX61NA0K': 'maple_2',
        'SX61NA05': 'honey_locust_3',
        'SX61NA0O': 'american_elm_2',
    },
    mfr       = {
        'MNLA4O105': {'label': 'greenhouse',    'lat': 41.869385, 'lon': -87.645848},
        'MNLA4O106': {'label': 'parking_lot_5', 'lat': 41.868385, 'lon': -87.649106},
    },
    deployments = {
        'wxt': ('2024-06-26', None),
        'aqt': ('2024-06-26', None),
    },
)

VLPK = CROCUSSite(
    vsn       = 'W095',
    full_name = 'Villa Park',
    abbr      = 'VLPK',
    lat       = 41.8848846,
    lon       = -87.978717,
    deployments = {
        'wxt': ('2025-03-14', None),
        'aqt': ('2025-03-14', None),
    },
)


# ---------------------------------------------------------------------------
# All sites — for iteration and filtering
# ---------------------------------------------------------------------------

ALL_SITES = [ATMOS, BIG, CCICS, CSU, DOWN, HUM, IBP, NEIU, NU, SHEDD, UIC, VLPK]
