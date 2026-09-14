# pytrpp2: Trade Republic data exporter with Portfolio Performance support

[![CI](https://github.com/JonathanWillnow/pytrpp2/actions/workflows/ci.yml/badge.svg)](https://github.com/JonathanWillnow/pytrpp2/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pytrpp2)](https://pypi.org/project/pytrpp2/)
[![Python](https://img.shields.io/pypi/pyversions/pytrpp2)](https://pypi.org/project/pytrpp2/)
[![License](https://img.shields.io/github/license/JonathanWillnow/pytrpp2)](LICENSE)

This is a tool for the private API of the Trade Republic online brokerage.
This package and its authors are not affiliated with Trade Republic Bank GmbH.


## Credits and lineage

pytrpp2 builds on the work of two projects:

- [`pytr`](https://github.com/pytr-org/pytr) — the actively maintained Trade Republic API client that pytrpp2 forks. All core functionality (timeline download, document download, transaction export, price alarms, etc.) comes from pytr.
- [`pytrpp`](https://github.com/MartinScharrer/pytrpp) by Martin Scharrer — an earlier extension of pytr that pioneered Portfolio Performance CSV export for Trade Republic data. pytrpp appears to be inactive, so pytrpp2 picks up that work: the PP-specific conversion logic (`export_pp`, `check_mappings`) is ported and extended from pytrpp.


## What pytrpp2 adds compared to pytr

pytrpp2 is a fork of [`pytr`](https://github.com/pytr-org/pytr) and includes all of its original functionality. On top of that, pytrpp2 adds three subcommands specifically for [Portfolio Performance](https://www.portfolio-performance.info/) users:

| Added subcommand | What it does |
|---|---|
| `export_pp` | Downloads your full TR timeline and converts it to Portfolio Performance-compatible CSV files (`payments.csv`, `orders.csv`). Event parsing is done by upstream pytr's parser, which is tested against real TR payloads, so TR API fixes arrive with every upstream merge. Optionally downloads PDF documents. |
| `check_mappings` | Reads an events JSON and reports every event that would be missing from the CSVs (not recognised or failed to parse) — useful after a Trade Republic API update to spot data loss before it reaches Portfolio Performance. |

The CSV format produced by `export_pp` matches exactly what Portfolio Performance expects:
- `payments.csv` → *Account Transactions* (deposits, withdrawals, card payments, dividends, interest, taxes, tax refunds)
- `orders.csv` → *Portfolio Transactions* (buys and sells incl. savings plans and round-ups, saveback and bonus shares, securities transfers, corporate actions)


## Installation

Requires Python 3.10 or newer.

```sh
pip install pytrpp2
```


## export_pp — Portfolio Performance export

Downloads your Trade Republic timeline and converts it to files ready to import into Portfolio Performance.

### Quick start

```sh
# Export CSVs and event log into a directory:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output

# Also download PDF documents into a timestamped subfolder:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output -F /path/to/docs

# Incremental — only export events not exported by an earlier run:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output --incremental
```

Each run with `-D` creates a timestamped subfolder (`YYYY-MM-DD_HH-MM-SS`) inside the given directory. Pass `--incremental` to export only what earlier runs have not exported yet:

- Only **completed** runs count (folder contains `events.json` and a CSV). A run that failed, e.g. at login, does not move the start point forward.
- Events are re-fetched from **7 days before** the most recent completed run. Trade Republic publishes some events after their timestamp, and this overlap also absorbs the UTC/local-time difference in the timeline filter.
- Events whose id already appears in an earlier run's `events.json` are skipped, so the overlap never creates duplicate transactions.

If no completed run is found, all events are fetched.

If phone number or PIN is omitted, pytrpp2 will prompt for them or read them from `~/.pytr/credentials` (first line: phone number, second line: PIN).

### Full argument reference

```
usage: pytrpp2 export_pp [-h] [-n PHONE_NO] [-p PIN] [--applogin]
                          [--waf-token WAF_TOKEN] [--store_credentials]
                          [-D DIR] [-E EVENTS_FILE] [-P PAYMENTS_FILE]
                          [-O ORDERS_FILE] [-F DOCS_DIR] [--workers WORKERS]
                          [--last_days DAYS] [--days_until DAYS]

Authentication:
  -n, --phone_no PHONE_NO       TradeRepublic phone number (international format)
  -p, --pin PIN                 TradeRepublic PIN
  --applogin                    Use app login instead of web login
  --waf-token WAF_TOKEN         Manually provide an aws-waf-token cookie value
  --store_credentials           Store credentials for next run

Output (use -D to set all at once, or specify individually):
  -D, --dir DIR                 Main output directory. Sets default paths for
                                events.json, payments.csv, and orders.csv.
                                Does NOT trigger PDF download — use -F for that.
  -E, --events-file FILE        Write raw event data to this JSON file
  -P, --payments-file FILE      Write payments (dividends, interest, etc.) to this CSV
  -O, --orders-file FILE        Write orders (buy/sell) to this CSV
  -F, --docs-dir DIR            Download PDF documents into this directory.
                                A timestamped subfolder (YYYY-MM-DD_HH-MM-SS) is
                                created automatically on each run.

Download options:
  --workers N                   Number of parallel download workers (default: 8)

Date range (both default to 0 = include everything):
  --last_days DAYS              Include only the last N days of data
  --days_until DAYS             Exclude the most recent N days (offset the end date)
  --incremental                 Only export events not exported by an earlier run
                                (requires -D). Re-fetches from 7 days before the last
                                completed run and skips already exported event ids.
```

### Output files

| File | Contents | Portfolio Performance import |
|---|---|---|
| `payments.csv` | Deposits, withdrawals, card payments, dividends, interest, taxes, tax refunds | *Account Transactions* |
| `orders.csv` | Buys / sells, savings plans, round-ups, saveback, bonus shares, securities transfers, corporate actions | *Portfolio Transactions* |
| `events.json` | Full raw event data from TR timeline | — (audit / debugging) |
| `DOCS_DIR/YYYY-MM-DD_HH-MM-SS/` | PDF documents (contract notes, tax statements) | — |

`events.json` is written before the conversion starts, so the raw data is kept even if something goes wrong later.

How special cases are booked in `orders.csv`:

| Trade Republic event | Portfolio Performance rows |
|---|---|
| Saveback, Aktien-Bonus, private markets 1 % bonus | *Einlieferung* of the shares at their value |
| Securities transfer in / out | *Einlieferung* / *Auslieferung*, value 0 |
| Share booking by a corporate action (e.g. spin-off shares credited, cancelled, re-credited) | one *Einlieferung* / *Auslieferung* per booking, value 0 |
| Split, bonus shares | *Einlieferung* of the added shares, value 0 |
| Spin-off | *Einlieferung* of the new security, value 0 |
| Swap / merger / reverse split | *Auslieferung* of the old and *Einlieferung* of the new security; a cash payment turns the new side into a *Kauf* (or the old side into a *Verkauf* for proceeds) |

Cash events without any amount (e.g. a Vorabpauschale fully covered by the tax allowance, a 0,00 € dividend) produce no row and are counted as ignored.

Portfolio Performance cannot import splits or spin-offs as such; if you prefer to record them with PP's own corporate action dialogs, skip those rows during import.

After conversion, `export_pp` prints an event audit and the gap check (see `check_mappings` below).


## check_mappings — Gap detector

Runs the same conversion as `export_pp` on an events JSON and reports every event that would be missing from `payments.csv` and `orders.csv` — typically caused by Trade Republic renaming or introducing event types after a platform update.

```sh
pytrpp2 check_mappings /path/to/events.json
```

Output:
- Event audit: events, converted (with order / payment row counts), ignored, unknown, errors
- **WARNING** with date, title, subtitle and id of every event that was not recognised or failed to convert — check these in the TR app and book them manually if needed
- Rows converted with parser warnings (e.g. share count could not be parsed) — verify these in PP
- Intentionally ignored types (account events, notifications, cancelled orders — expected)

`export_pp` runs this check automatically after every conversion, so you only need to call it manually to re-check an older events JSON.


## Authentication

Authentication works the same as in pytr. See [pytr's README](https://github.com/pytr-org/pytr#authentication) for details on web login, app login, and the credentials file.


## Development

See [pytr's README](https://github.com/pytr-org/pytr#development) for general setup, linting, and formatting instructions — the toolchain is identical (`uv`, `ruff`, `mypy`).

Clone and install this fork:

```sh
git clone https://github.com/JonathanWillnow/pytrpp2.git
cd pytrpp2
uv sync --group dev
uv run pytest
```

A pre-commit hook runs the full test suite automatically before every commit.


## Bugs and contributing

For bugs or feature requests in the PP-specific functionality (`export_pp`, `check_mappings`), open an issue in this repository. For issues with core Trade Republic API behaviour, do not forget to report them [upstream in pytr](https://github.com/pytr-org/pytr/issues).


## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
