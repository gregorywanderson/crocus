# CROCUS Data Access

Python notebooks and utilities for accessing sensor data from the
[CROCUS](https://crocus-urban.org) (Community Research on Climate and Urban Science)
network of Waggle/Sage nodes deployed across Chicago, Illinois.

## Contents

- **`crocus_data_access.ipynb`** — Main notebook demonstrating how to query,
  wrangle, and visualize data from CROCUS sensors including the Vaisala WXT536
  weather transmitter, Vaisala AQT530 air quality transmitter, Hydreon RG-15
  rain gauge, SFM1x sap flow meters, and ICT International MFR soil nodes.

[![Open crocus_data_access.ipynb in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/crocus_data_access.ipynb)

- **`sage_utils.py`** — Query functions that wrap the Sage Data Client and
  return clean wide-format DataFrames suitable for analysis and plotting.

- **`crocus_sites.py`** — Site metadata for all CROCUS field locations including
  coordinates, sensor availability, and instrument serial number mappings.

### CROCUS Network and Sensor Coverage Dashboard

[![Open crocus\_network\_sensor\_coverage.ipynb in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/crocus_network_sensor_coverage.ipynb)

`crocus_network_sensor_coverage.ipynb` provides a quick operational view of the CROCUS network. It checks whether node compute hosts are currently reporting and whether the expected sensors at each site are returning recent data. The notebook is intended as a status and coverage dashboard rather than a detailed scientific analysis notebook.

The notebook uses the helper module `coverage_utils.py`, which contains functions for querying recent CROCUS data coverage and plotting the results. It includes tools to:

* check whether individual sensors are reporting at a site,
* summarize current sensor reporting status across the full CROCUS network,
* plot a color-coded sensor coverage grid,
* check compute-host liveness using `sys.uptime`,
* join compute-host liveness information to the Sage node manifest so host roles such as `nxcore`, `rpi`, `rpi.lorawan`, and `nxagent` can be labeled,
* plot a separate node liveness grid showing which compute hosts are reporting.

The sensor coverage grid and node liveness grid answer related but different questions. A node can be alive and reporting system metrics even when one or more attached sensors are not reporting. For that reason, the notebook treats compute-host liveness and sensor coverage as separate layers of network status.


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
| DOWN  | Downers Grove                                |
| HUM   | Humboldt Park                                |
| IBP   | Indian Boundary Prairies (TNC)               |
| NEIU  | Northeastern Illinois University             |
| NU    | Northwestern University                      |
| SHEDD | Shedd Aquarium                               |
| UIC   | University of Illinois Chicago               |
| VLPK  | Villa Park |

## Further Reading

- [Sage Data Client](https://github.com/sagecontinuum/sage-data-client)
- [Sage Portal](https://portal.sagecontinuum.org/nodes)
- [CROCUS Instrument Cookbooks](https://crocus-urban.github.io/instrument-cookbooks/)
- [CROCUS Data on ESS-DIVE](https://data.ess-dive.lbl.gov/portals/crocus/Data)

