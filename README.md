# CROCUS Data Access

Python notebooks and utilities for accessing sensor data from the
[CROCUS](https://crocus-urban.org) (Community Research on Climate and Urban Science)
network of Waggle/Sage nodes deployed across Chicago, Illinois.

## Contents

- **`crocus_data_access.ipynb`** — Main notebook demonstrating how to query,
  wrangle, and visualize data from CROCUS sensors including the Vaisala WXT536
  weather transmitter, Vaisala AQT530 air quality transmitter, Hydreon RG-15
  rain gauge, SFM1x sap flow meters, and ICT International MFR soil nodes.

- **`sage_utils.py`** — Query functions that wrap the Sage Data Client and
  return clean wide-format DataFrames suitable for analysis and plotting.

- **`crocus_sites.py`** — Site metadata for all CROCUS field locations including
  coordinates, sensor availability, and instrument serial number mappings.

[![Open crocus_data_access.ipynb in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/crocus_data_access.ipynb)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Set `SITE` to any available site object and run the notebook top to bottom:

```python
from crocus_sites import NEIU, CSU, NU   # import any site
SITE = NEIU                               # set the active site
```

## CROCUS Network

| Site  | Location                                      |
|-------|-----------------------------------------------|
| ATMOS | Argonne Testbed for Multiscale Observational Science |
| BIG   | Blacks in Green, West Woodlawn               |
| CCICS | Carruthers Center for Inner City Studies, Bronzeville |
| CSU   | Chicago State University                     |
| HUM   | Humboldt Park                                |
| NEIU  | Northeastern Illinois University             |
| NU    | Northwestern University                      |
| SHEDD | Shedd Aquarium                               |
| UIC   | University of Illinois Chicago               |

## Further Reading

- [Sage Data Client](https://github.com/sagecontinuum/sage-data-client)
- [Sage Portal](https://portal.sagecontinuum.org/nodes)
- [CROCUS Instrument Cookbooks](https://crocus-urban.github.io/instrument-cookbooks/)
- [CROCUS Data on ESS-DIVE](https://data.ess-dive.lbl.gov/portals/crocus/Data)

