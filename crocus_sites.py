"""
crocus_sites.py

Site-specific metadata for the CROCUS (Community Research on Climate and
Urban Science) urban field network in Chicago, Illinois.

Each site is defined as a CROCUSSite instance with attributes for the
Sage/Waggle node ID, geographic coordinates, sensor availability, and
sensor-specific metadata (sap flow species labels, MFR sub-site labels).

Update this file as new nodes are added or site descriptions become available.

Usage
-----
    from crocus_sites import NEIU, CROCUS_SITES

    # Direct access
    print(NEIU.vsn)          # 'W08D'
    print(NEIU.lat)          # 41.9803

    # Iterate over all sites with a specific sensor
    wxt_sites = [name for name, site in CROCUS_SITES.items() if site.has_wxt]

    # Look up by abbreviation
    site = CROCUS_SITES['NEIU']
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
    lat : float
        Latitude in decimal degrees (WGS84).
    lon : float
        Longitude in decimal degrees (WGS84), negative for west.
    has_aqt : bool
        True if site has an AQT air quality sensor.
    has_wxt : bool
        True if site has a WXT weather transmitter.
    has_mfr : bool
        True if site has one or more MFR nodes.
    has_sapflow : bool
        True if site has one or more sap flow meters.
    sapflow : dict, optional
        Mapping of sap flow serial number to species label,
        e.g. {'SX61NA0C': 'white_oak_1'}. Required if has_sapflow=True.
    mfr : dict, optional
        Mapping of MFR serial number to sub-site label,
        e.g. {'MNLA4O107': 'savannah'}. Required if has_mfr=True.
    """
    vsn:       str
    full_name: str
    lat:       float
    lon:       float

    has_aqt:     bool = False
    has_wxt:     bool = False
    has_mfr:     bool = False
    has_sapflow: bool = False

    sapflow: Optional[dict] = field(default=None, repr=False)
    mfr:     Optional[dict] = field(default=None, repr=False)

    def __post_init__(self):
        if self.has_sapflow and self.sapflow is None:
            raise ValueError(
                f"{self.full_name}: has_sapflow=True but no sapflow dict provided"
            )
        if self.has_mfr and self.mfr is None:
            raise ValueError(
                f"{self.full_name}: has_mfr=True but no mfr dict provided"
            )


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
    lat       = 41.7000,   # TBD — approximate
    lon       = -87.9800,  # TBD — approximate
    has_aqt   = True,
    has_wxt   = True,
)

BIG = CROCUSSite(
    vsn       = 'W0A0',
    full_name = 'Blacks in Green (West Woodlawn)',
    lat       = 41.7766,   # TBD
    lon       = -87.6298,  # TBD
    has_aqt   = True,
    has_wxt   = True,
    has_mfr   = True,
    has_sapflow = True,
    sapflow   = {
        'SX61NA0U': 'tree_1',   # species TBD
        'SX61NA09': 'tree_2',   # species TBD
        'SX61NA0I': 'tree_3',   # species TBD
    },
    mfr       = {
        'MNLA4O10A': 'site_1',  # sub-site TBD
        'MNLA4O10B': 'site_2',  # sub-site TBD
        'MNLA4O10C': 'site_3',  # sub-site TBD
    },
)

CCICS = CROCUSSite(
    vsn       = 'W08B',
    full_name = 'Carruthers Center for Inner City Studies — Bronzeville (NEIU satellite)',
    lat       = 41.8318,   # TBD
    lon       = -87.6180,  # TBD
    has_aqt   = True,
    has_wxt   = True,
)

CSU = CROCUSSite(
    vsn       = 'W08E',
    full_name = 'Chicago State University',
    lat       = 41.7232,   # TBD
    lon       = -87.6050,  # TBD
    has_aqt   = True,
    has_wxt   = True,
    has_mfr   = True,
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
        'MNLA4O102': 'non_prairie',
        'MNLA4O103': 'prairie',
    },
)

HUM = CROCUSSite(
    vsn       = 'W0A1',
    full_name = 'Humboldt Park',
    lat       = 41.9000,   # TBD
    lon       = -87.7200,  # TBD
    has_aqt   = True,
    has_wxt   = True,
)

NEIU = CROCUSSite(
    vsn       = 'W08D',
    full_name = 'Northeastern Illinois University',
    lat       = 41.9803,
    lon       = -87.7170,
    has_aqt   = True,
    has_wxt   = True,
    has_mfr   = True,
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
        'MNLA4O107': 'savannah',  # Swamp White Oak Savannah (south)
        'MNLA4O108': 'lawn',      # Lawn near Administrative building
    },
)

NU = CROCUSSite(
    vsn       = 'W099',
    full_name = 'Northwestern University',
    lat       = 42.0565,   # TBD
    lon       = -87.6753,  # TBD
    has_aqt   = True,
    has_wxt   = True,
    has_mfr   = True,
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
        'MNLA4O104': 'site_1',   # sub-site TBD
    },
)

SHEDD = CROCUSSite(
    vsn       = 'W09E',
    full_name = 'Shedd Aquarium',
    lat       = 41.8676,   # TBD
    lon       = -87.6139,  # TBD
    has_aqt   = True,
    has_wxt   = True,
)

UIC = CROCUSSite(
    vsn       = 'W096',
    full_name = 'University of Illinois Chicago',
    lat       = 41.8708,   # TBD
    lon       = -87.6505,  # TBD
    has_aqt   = True,
    has_wxt   = True,
    has_mfr   = True,
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
        'MNLA4O105': 'site_1',   # sub-site TBD
        'MNLA4O106': 'site_2',   # sub-site TBD
    },
)


# ---------------------------------------------------------------------------
# Master site dictionary — for programmatic access and iteration
# ---------------------------------------------------------------------------

CROCUS_SITES = {
    'ATMOS': ATMOS,
    'BIG':   BIG,
    'CCICS': CCICS,
    'CSU':   CSU,
    'HUM':   HUM,
    'NEIU':  NEIU,
    'NU':    NU,
    'SHEDD': SHEDD,
    'UIC':   UIC,
}

# Reverse lookup: VSN → site abbreviation
VSN_TO_SITE = {site.vsn: name for name, site in CROCUS_SITES.items()}