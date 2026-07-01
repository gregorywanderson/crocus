#!/usr/bin/env python3
"""
build_sage_resampled.py

Command-line driver for backfilling the historic CROCUS 5-minute archive.

This wraps crocus_store.build_site so a long, resumable backfill can be run
unattended from a terminal instead of a notebook kernel. It is the recommended
way to build large archives: a terminal process survives where a notebook
kernel may crash on memory pressure, it logs to a file so you can check on a
multi-hour run after the fact, and the underlying build is resumable — if the
process dies or you Ctrl-C it, just run the same command again and it picks up
from the last completed chunk.

Examples
--------
    # One site, one instrument, an explicit window:
    python build_sage_resampled.py --sites NEIU --instruments wxt \
        --start 2024-06-01 --end 2024-09-01

    # Both of "my" sites, both instruments, auto-resolved start (probes for
    # first data), runs to now:
    python build_sage_resampled.py --sites NEIU,CCICS --instruments wxt,aqt

    # Smaller chunks for a very dense node, custom log:
    python build_sage_resampled.py --sites NEIU --instruments wxt \
        --chunk-days 1 --log neiu_wxt.log

Resuming
--------
Just re-run the exact same command. Completed chunks are checkpointed under
{outdir}/_chunks/{abbr}_{instrument}/ and skipped on the next run. Keep
--chunk-days the same across runs of the same build, or the chunk boundaries
shift and prior checkpoints will not be reused.

Notes
-----
A site is skipped for an instrument it does not have (e.g. NEIU has no active
rain gauge, but that does not affect WXT/AQT). Sites and instruments that
produce no data in the window are reported and the run continues to the next.
"""

# Standard library
import argparse
import logging
import sys
import time

# Local
import crocus_store as cs
from crocus_sites import ALL_SITES


# Name -> CROCUSSite lookup, keyed by uppercase abbreviation.
SITES_BY_ABBR = {s.abbr.upper(): s for s in ALL_SITES}

VALID_INSTRUMENTS = ('wxt', 'aqt')


def _setup_logging(log_path):
    """Log to stdout always, and to a file as well if log_path is given."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_path:
        handlers.append(logging.FileHandler(log_path))
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
    )


def _parse_csv_arg(value, name):
    """Parse a comma-separated CLI argument into a clean list of tokens."""
    items = [v.strip() for v in value.split(',') if v.strip()]
    if not items:
        raise argparse.ArgumentTypeError(f"--{name} cannot be empty")
    return items


def _resolve_sites(tokens):
    """Map abbreviation tokens to CROCUSSite objects, erroring on unknowns."""
    resolved = []
    unknown = []
    for tok in tokens:
        site = SITES_BY_ABBR.get(tok.upper())
        if site is None:
            unknown.append(tok)
        else:
            resolved.append(site)
    if unknown:
        valid = ', '.join(sorted(SITES_BY_ABBR))
        raise SystemExit(
            f"Unknown site(s): {', '.join(unknown)}\nValid sites: {valid}"
        )
    return resolved


def _validate_instruments(tokens):
    """Lower-case and validate instrument tokens."""
    out = []
    for tok in tokens:
        t = tok.lower()
        if t not in VALID_INSTRUMENTS:
            raise SystemExit(
                f"Unknown instrument: {tok}. "
                f"Valid: {', '.join(VALID_INSTRUMENTS)}"
            )
        out.append(t)
    return out


def build_one(site, instrument, args):
    """Run a single site/instrument build, logging outcome and timing.

    Returns True on a written archive, False if skipped or no data, and lets
    unexpected exceptions propagate so a real failure is loud (the build is
    resumable, so re-running continues from the last good chunk).
    """
    logging.info("=== %s / %s : starting ===", site.abbr, instrument)
    t0 = time.time()
    path = cs.build_site(
        site, instrument,
        outdir=args.outdir,
        start=args.start,
        end=args.end,
        chunk_days=args.chunk_days,
        verbose=True,
    )
    dt = time.time() - t0
    if path:
        logging.info("=== %s / %s : wrote %s in %.0fs ===",
                     site.abbr, instrument, path, dt)
        return True
    logging.info("=== %s / %s : nothing written (skipped / no data) in %.0fs ===",
                 site.abbr, instrument, dt)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Resumable backfill driver for the CROCUS 5-minute archive.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--sites', required=True,
        help="Comma-separated site abbreviations, e.g. NEIU,CCICS",
    )
    parser.add_argument(
        '--instruments', default='wxt',
        help="Comma-separated instruments to build (wxt,aqt). Default: wxt",
    )
    parser.add_argument(
        '--start', default=None,
        help="Backfill start (e.g. 2024-06-01). Default: probe for first data.",
    )
    parser.add_argument(
        '--end', default=None,
        help="Backfill end (e.g. 2024-09-01). Default: now (UTC).",
    )
    parser.add_argument(
        '--chunk-days', type=int, default=3, dest='chunk_days',
        help="Fetch chunk width in days. Default: 3. Keep constant across "
             "resumed runs of the same build.",
    )
    parser.add_argument(
        '--outdir', default=cs.DEFAULT_OUTDIR,
        help="Output directory for the archive and checkpoints. Default: %(default)s",
    )
    parser.add_argument(
        '--log', default=None,
        help="Optional log file path (in addition to console output).",
    )
    args = parser.parse_args(argv)

    _setup_logging(args.log)

    site_tokens = _parse_csv_arg(args.sites, 'sites')
    instr_tokens = _parse_csv_arg(args.instruments, 'instruments')
    sites = _resolve_sites(site_tokens)
    instruments = _validate_instruments(instr_tokens)

    logging.info(
        "Backfill plan: sites=%s instruments=%s start=%s end=%s "
        "chunk_days=%d outdir=%s",
        [s.abbr for s in sites], instruments,
        args.start or 'auto', args.end or 'now',
        args.chunk_days, args.outdir,
    )

    run_t0 = time.time()
    written = 0
    total = 0
    # Each (site, instrument) is independent and individually resumable, so a
    # failure in one does not lose the archives already written for others.
    for site in sites:
        for instrument in instruments:
            total += 1
            if build_one(site, instrument, args):
                written += 1

    logging.info(
        "All done: %d/%d builds produced an archive in %.0fs total.",
        written, total, time.time() - run_t0,
    )


if __name__ == '__main__':
    main()
