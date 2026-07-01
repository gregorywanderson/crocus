# crocus

Python notebooks and scripts for accessing, processing, and visualizing data from
the [CROCUS](https://crocus-urban.org/) urban climate sensor network — developed for
both research use and undergraduate teaching.

CROCUS instruments (Vaisala WXT536 weather stations, Vaisala AQT530 air-quality
sensors, and others) are deployed across a set of Chicago-area sites and stream data
to the [Sage Continuum / Waggle](https://sagecontinuum.org/) platform — the working
record of the network. A small sample of QA/QC'd, resampled data was also published to
[ESS-DIVE](https://ess-dive.lbl.gov/). This repository provides tools to work with
**both** sources.

---

## Three ways to get data

Pick the path that matches what you need. They are listed easiest-first.

### 1. Recent data, live from Sage Continuum  ·  *start here*

Notebooks that query the Sage Data Client API directly for roughly the **last six
months** of data. No large downloads, no credentials — they run as-is (including in
Colab). This is the recommended on-ramp for students and for quick looks at current
conditions.

- `crocus_data_access.ipynb` — query a site/instrument and plot recent observations.
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/crocus_data_access.ipynb)
- `crocus_network_sensor_coverage.ipynb` — start-of-session health check: which compute
  hosts are alive and which sensors are reporting, before you query data.
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/crocus_network_sensor_coverage.ipynb)

### 2. Historical high-frequency data, resampled from Sage  ·  *power users*

A pipeline that downloads CROCUS's native high-frequency records from Sage and
resamples them to **5-minute NetCDF archives**, with corrected vector-wind
decomposition and per-bin rain increments. This is slower and requires more setup,
and **backfills are still in progress** — coverage is incomplete and varies by site.

- `crocus_store.py` — core download / resample / archive library.
- `build_sage_archive.py` — CLI driver (`--site`, `--instrument`, date range).
- `run_backfill.sh` — shell wrapper that activates the conda env and runs detached.

> Status: NEIU WXT complete (2023-05-05 → 2025-12-15); CCICS AQT/WXT and NU WXT in
> progress. *(verify before publishing)*

### 3. Published sample, from ESS-DIVE  ·  *small reference set*

Notebooks that download CROCUS data published to ESS-DIVE and produce quicklook plots.
This is a **small, sparse sample** of the network's data — QA/QC'd and resampled, but
covering only selected sites and windows where data was published (sites include NU,
NEIU, CSU, UIC). Useful as a reference example rather than a complete record.

- ESS-DIVE downloader — public, tokenless access to CROCUS packages.
- `essdive_wxt_quicklook.ipynb` — quicklook for native ~10-second WXT data.
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/crocus_wxt_quicklook_essdive.ipynb)

A note on these files: some ESS-DIVE archives do **not** carry unit attributes, so the
quicklook notebooks supply units as named constants. The UIC "air quality" package is a
heterogeneous collection of instruments rather than a standard AQT time series, and is
not directly comparable to the other sites' records.

---

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
---

## Cross-validating the record

The ESS-DIVE sample was QA/QC'd and resampled from the same data that streams to Sage
Continuum. Because the tools here access both sources, it is possible to compare the
published sample against the underlying Sage data — checking that values agree within
the documented processing, and noting metadata (units, `standard_name`, provenance)
where it is incomplete. This is an ongoing, secondary aim of the repo, not a finished
result.

---

## Getting started

```bash
# clone
git clone https://github.com/gregorywanderson/crocus.git
cd crocus

# environment  (TODO: provide environment.yml / requirements.txt)
# core dependencies: sage-data-client, xarray, netCDF4, pandas, numpy, matplotlib
```

The Tier-1 notebooks need only a standard scientific-Python stack plus
`sage-data-client` and can be run in Colab. The archive pipeline (Tier 2) additionally
expects a conda environment; see `run_backfill.sh`.

*(TODO: confirm exact dependency list and add an `environment.yml`.)*

---

## Repository layout

```
crocus/
├── crocus_data_access.ipynb        # Tier 1: recent data, live from Sage
├── crocus_network_sensor_coverage.ipynb  # Tier 1: network/sensor health check
├── essdive_wxt_quicklook.ipynb     # Tier 3: ESS-DIVE quicklook  
├── crocus_store.py                 # Tier 2: archive library
├── build_sage_archive.py           # Tier 2: CLI driver              (to be added)
├── run_backfill.sh                 # Tier 2: backfill wrapper        (to be added)
├── crocus_sites.py                 # site registry
└── sage_utils.py                   # Sage query helpers
```

*(Marked items are not yet committed — remove the note as you upload them.)*

---

## Data sources & acknowledgments

- **CROCUS** — Community Research on Climate and Urban Science. <https://crocus-urban.org/>
- **Sage Continuum / Waggle** — real-time sensor data platform. <https://sagecontinuum.org/>
- **ESS-DIVE** — repository hosting a published sample of CROCUS data. <https://ess-dive.lbl.gov/>

*(TODO: add funding/attribution language CROCUS asks collaborators to use, credit for
the published ESS-DIVE sample, and a citation/DOI if you mint one.)*

---

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3), consistent
with the other repositories in this account. See the `LICENSE` file for the full text.
Data accessed through these tools retains its original ESS-DIVE / CROCUS / Sage terms.
