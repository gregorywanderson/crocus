# CROCUS

Python notebooks and scripts for accessing, processing, and visualizing data from
the [CROCUS](https://crocus-urban.org/) urban climate sensor network — developed for
both research use and undergraduate teaching.

CROCUS instruments (Vaisala WXT536 weather stations, Vaisala AQT530 air-quality
sensors, and others) are deployed across a set of Chicago-area sites and stream data
to the [Sage Continuum / Waggle](https://sagecontinuum.org/) platform — the working
record of the network. A sample of quality-controlled, resampled data was also published
to [ESS-DIVE](https://ess-dive.lbl.gov/). This repository provides tools to work with
**both** sources.

---

## Understanding data tiers

Environmental data is usually described in **processing tiers** — a standard way to
say how far a dataset sits from the original instrument reading. The tier tells you
what has been done to the data, and therefore how much you should trust it and how much
you still need to check yourself. This is worth learning once, because the same idea
applies to almost any scientific dataset you will ever use.

**Tier 1 — raw / minimally processed. The archival source of truth.**
The closest practical form of the original measurement record: raw or minimally decoded
instrument observations, with original timestamps, sensor names, units, metadata, and
flags preserved. Tier 1 is the source of truth *even though* it may contain missing
values, spikes, duplicated records, calibration drift, or irregular sampling. You trust
it because nothing has been altered — but you must handle its messiness yourself.

**Tier 2 — quality-controlled and standardized.**
Data converted into consistent units, placed on a standard time base, checked for
missing values and obvious physical or instrumental errors, and documented with QA/QC
flags. For a weather station, Tier 2 might be 5-minute temperature, humidity, wind,
pressure, and rainfall values derived from higher-frequency raw samples, with counts and
statistical fields retained. Tier 2 is easier to analyze than Tier 1 — but now you are
relying on someone's QA/QC choices, so those choices should be documented.

**Tier 3 — analysis-ready / derived products.**
Built from Tier 2, and often the most useful for science: coverage summaries, spatial
interpolation, gap filling, gridded fields, climatologies, event classifications,
heat-index products, urban heat-island metrics, model–observation comparisons, or
merged multi-instrument datasets. Tier 3 is the most usable but the *furthest* from the
original measurement, so clear provenance matters most here.

The compact version:

> **Tier 1** preserves what the instrument *reported*.
> **Tier 2** preserves what the instrument most likely *measured*, after QA/QC and
> standardization.
> **Tier 3** provides what users can directly *analyze, map, compare, or model*.

The trade-off runs one way across the tiers: **the higher the tier, the easier the data
is to use, but the further it sits from the raw measurement** — so the more its
trustworthiness depends on documented provenance.

### How the tiers map onto CROCUS

- **Tier 1 — Sage/Waggle observations.** Raw records: timestamp, VSN, measurement
  name, value, units, plugin metadata, original tags, at native (high-frequency) rate.
  This is what the live-Sage notebooks query.
- **Tier 2 — site/instrument time-series products.** Standardized variables, standard
  units, regular 5-minute bins with mean / count / std, missing-value handling, and site
  metadata — the `data/sage_resampled/` archives built by this repo.
  *In progress:* the archives currently deliver the standardization and aggregation part
  of Tier 2; explicit QA/QC flags are still being added, so treat them as Tier 2 in form
  with QA/QC flagging pending.
- **Tier 3 — derived science products.** Built from the Tier 2 archives by notebooks in
  this repo: coverage summaries, and (planned) urban temperature gradients, lake-breeze
  diagnostics, rain-event products, and heat-stress metrics. Some exist today; others are
  in development.

Note that a tier is **not** the same as *where you get the data* (the next section).
The same tier can come from more than one place — for example, Tier 1 raw data is
available both live from the Sage API and, less completely, from database backups. Keep
the two ideas separate: **tier = how processed; source = where you get it.**

### Verifying a derived product: a short example

Provenance matters most when a dataset has been processed by someone else and the exact
method is not written down. The CROCUS sample published to ESS-DIVE is a useful case for
practicing this. Its WXT files are on a 10-second time step, aggregated from the native
high-rate stream. Working from the published files alone, you cannot see *how* each
10-second value was produced — so we checked, by comparing against the native Sage data
for a matching window (see `reverse_engineer_essdive.ipynb`).

That comparison confirmed some of the processing and left one part open. The 10-second
temperature matches a block mean of the native samples, and the wind maximum matches a
block maximum, both closely. The published wind *mean* (`wind_mean_10s`) did not match a
straightforward block mean of the native wind in our check, so the exact method behind
it is something we have not yet reproduced. The comparison so far covers a single window
at one site and should be repeated more widely before drawing firm conclusions. The
practical lesson is general: when using a derived product, it is worth verifying the
processing against the source rather than relying on the description alone.

---

## Three ways to get the data

Separate from the tier of a dataset is the practical question of **where you get it**.
Pick the source that matches what you need; they are listed easiest-first.

### 1. Recent data, live from Sage Continuum  ·  *start here*

Notebooks that query the Sage Data Client API directly for roughly the **last six
months** of data (Tier 1, raw). No large downloads, no credentials — they run as-is
(including in Colab). This is the recommended on-ramp for students and for quick looks at
current conditions. These notebooks can be used for older data, but data befor 2026 is very
high frequency leading to slow downloads and large files.

- `sage_data_access.ipynb` — query a site/instrument and plot recent observations.
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/sage_data_access.ipynb)
- `sage_network_sensor_coverage.ipynb` — start-of-session health check: which compute
  hosts are alive and which sensors are reporting, before you query data.
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/sage_network_sensor_coverage.ipynb)

### 2. Historical data, resampled from Sage  ·  *power users*

A pipeline that downloads CROCUS's native high-frequency records from Sage and resamples
them to **5-minute NetCDF archives** (Tier 2), with vector-wind decomposition and per-bin
rain increments. This is slower and requires more setup, and **backfills are still in
progress** — coverage is incomplete and varies by site. Archives are written to
`data/sage_resampled/`.

- `crocus_store.py` — core download / resample / archive library.
- `build_sage_resampled.py` — CLI driver (`--sites`, `--instruments`, date range).
- `run_backfill.sh` — shell wrapper that activates the conda env and runs one build
  detached.
- `backfill_all.sh` — orchestrates builds across many sites at bounded concurrency,
  breadth-first and resumable.
- `resampled_wxt_quicklook.ipynb`, `resampled_aqt_quicklook.ipynb` — quicklook plots of
  the finished 5-minute archives.

> Status: backfills in progress; coverage is partial and varies by site and instrument.
> Verify actual coverage from the archives themselves before relying on any date range.

### 3. Published sample, from ESS-DIVE  ·  *small reference set*

Notebooks that download CROCUS data published to ESS-DIVE and produce quicklook plots.
This is a **sample** of the network's data, covering selected sites and windows (sites
include NU, NEIU, CSU, UIC). The WXT files are on a 10-second step and the AQT files on a
60-second step. As noted in the tier discussion above, aspects of its processing are
still being verified, so it is best treated as a reference set rather than a definitive
record. Downloads and assembled archives are written to `data/essdive/`.

- `build_essdive_archive.ipynb` — public, tokenless download of CROCUS ESS-DIVE packages,
  assembled into per-site/instrument NetCDF archives.
- `essdive_wxt_quicklook.ipynb` — quicklook for the ESS-DIVE WXT data.
  [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gregorywanderson/crocus/blob/main/essdive_wxt_quicklook.ipynb)

A note on these files: some ESS-DIVE archives do not carry unit attributes, so the
quicklook notebooks supply units as named constants. The UIC "air quality" package is a
heterogeneous collection of instruments rather than a standard AQT time series, and is
not directly comparable to the other sites' records.

---

## Notebook & file naming

The repository follows a small, consistent naming convention:

- **Builder notebooks/scripts are named `build_<from>_<to>`** — a transformation named by
  its source and its product. `<to>` is specific when a transformation is applied (e.g.
  `build_sage_resampled` — from Sage, resampled) and generic when data is preserved as
  published (e.g. `build_essdive_archive` — from ESS-DIVE, archived as-is).
- **Consumer notebooks** (quicklooks, audits) are named by the **product they read**,
  since they perform no transformation: `resampled_*_quicklook` reads the Sage-derived
  resampled archive; `essdive_*_quicklook` reads the ESS-DIVE archive.
- **Live-Sage notebooks** carry the `sage_` prefix because they query the Sage API
  directly (`sage_data_access`, `sage_network_sensor_coverage`).
- **Project-level libraries** keep the `crocus_` prefix because they are scoped to the
  CROCUS project rather than to any one data source (`crocus_store.py`, `crocus_sites.py`).

Data lives under `data/`, organized by provenance: `data/sage_resampled/` and
`data/essdive/`.

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

The ESS-DIVE sample was resampled from the same data that streams to Sage Continuum.
Because the tools here access both sources, it is possible to compare the published
sample against the underlying Sage data — checking where values agree within the
processing and noting metadata (units, `standard_name`, provenance) that is incomplete.
This is an ongoing, secondary aim of the repo, not a finished result.

---

## Getting started

```bash
# clone
git clone https://github.com/gregorywanderson/crocus.git
cd crocus

# environment  (TODO: provide environment.yml / requirements.txt)
# core dependencies: sage-data-client, xarray, netCDF4, pandas, numpy, matplotlib
```

The live-Sage notebooks (source 1) need only a standard scientific-Python stack plus
`sage-data-client` and can be run in Colab. The archive pipeline (source 2) additionally
expects a conda environment; see `run_backfill.sh`.

*(TODO: confirm exact dependency list and add an `environment.yml`.)*

---

## Repository layout

```
crocus/
├── sage_data_access.ipynb              # Tier 1: recent data, live from Sage
├── sage_network_sensor_coverage.ipynb  # Tier 1: network/sensor health check
├── crocus_store.py                     # Tier 2: archive library
├── build_sage_resampled.py             # Tier 2: CLI driver (from Sage -> resampled)
├── run_backfill.sh                     # Tier 2: single-build backfill wrapper
├── backfill_all.sh                     # Tier 2: multi-site backfill orchestrator
├── resampled_wxt_quicklook.ipynb       # quicklook of resampled WXT archive
├── resampled_aqt_quicklook.ipynb       # quicklook of resampled AQT archive
├── build_essdive_archive.ipynb         # download + assemble ESS-DIVE packages
├── essdive_wxt_quicklook.ipynb         # ESS-DIVE WXT quicklook
├── reverse_engineer_essdive.ipynb      # provenance check of the ESS-DIVE processing
├── crocus_sites.py                     # site registry (project-level)
└── sage_utils.py                       # Sage query helpers
```

Data directories (`data/sage_resampled/`, `data/essdive/`) are created as archives are
built and are not tracked in the repository.

---

## Data sources & acknowledgments

- **CROCUS** — Community Research on Climate and Urban Science. <https://crocus-urban.org/>
- **Sage Continuum / Waggle** — real-time sensor data platform. <https://sagecontinuum.org/>
- **ESS-DIVE** — repository hosting a published sample of CROCUS data. <https://ess-dive.lbl.gov/>

*(TODO: add funding/attribution language CROCUS asks collaborators to use, credit for the
published ESS-DIVE sample, and a citation/DOI if one is minted.)*

---

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3), consistent
with the other repositories in this account. See the `LICENSE` file for the full text.
Data accessed through these tools retains its original ESS-DIVE / CROCUS / Sage terms.
