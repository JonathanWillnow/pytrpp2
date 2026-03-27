# pytrpp2: Trade Republic data exporter with Portfolio Performance support

This is a tool for the private API of the Trade Republic online brokerage.
This package and its authors are not affiliated with Trade Republic Bank GmbH.

---

## What pytrpp2 adds compared to pytr

pytrpp2 is a fork of [`pytr`](https://github.com/pytr-org/pytr) and includes all of its original functionality. On top of that, pytrpp2 adds three subcommands specifically for [Portfolio Performance](https://www.portfolio-performance.info/) users:

| Added subcommand | What it does |
|---|---|
| `export_pp` | Downloads your full TR timeline and converts it to Portfolio Performance-compatible CSV files (`payments.csv`, `orders.csv`). Handles all TR event types including the post-2025 API format. Optionally downloads PDF documents. |
| `build_classification` | Reads the raw events JSON from `export_pp` and generates a `classification.json` taxonomy (Asset Allocation: RISKY / CASH) ready to import into Portfolio Performance under *Wertpapiere → Klassifizierungen*. |
| `check_mappings` | Reads an events JSON and reports any TR event types that have no converter handler — useful after a Trade Republic API update to spot silent data loss before it happens. |

The CSV format produced by `export_pp` matches exactly what Portfolio Performance expects:
- `payments.csv` → *Account Transactions* (dividends, interest, coupons, bond repayments, transfers)
- `orders.csv` → *Portfolio Transactions* (buy / sell / savings plan orders)

---

## Installation

Install from this repository:

```sh
pip install git+https://github.com/your-org/pytrpp2.git
```

Or clone and install in editable mode for development:

```sh
git clone https://github.com/your-org/pytrpp2.git
cd pytrpp2
pip install -e .
```

---

## Commands

The CLI entry point is `pytrpp2`. Run `pytrpp2 --help` or `pytrpp2 <command> --help` for details.

```
Commands:
  login                 Check credentials and log in (performs device reset if needed)
  portfolio             Show current portfolio
  details               Get details for an ISIN
  dl_docs               Download all PDF documents from the timeline
  export_transactions   Export timeline transactions to CSV
  get_price_alarms      Get current price alarms
  set_price_alarms      Set new price alarms
  export_pp             Export TR timeline to Portfolio Performance CSV format  ← added by pytrpp2
  build_classification  Build a Portfolio Performance classification taxonomy   ← added by pytrpp2
  check_mappings        Check for unmapped TR event types in an events JSON     ← added by pytrpp2
  completion            Print shell tab completion

Global options:
  -h, --help                            show this help message and exit
  -V, --version                         Print version information and quit
  -v, --verbosity {warning,info,debug}  Set verbosity level (default: info)
```

---

## export_pp — Portfolio Performance export

Downloads your Trade Republic timeline and converts it to files ready to import into Portfolio Performance.

### Quick start

```sh
# Export CSVs and event log into a directory:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output

# Also download PDF documents into a timestamped subfolder:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output -F /path/to/docs

# Incremental — only the last 30 days:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output --last_days 30
```

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
```

### Output files

| File | Contents | Portfolio Performance import |
|---|---|---|
| `payments.csv` | Dividends, interest, coupons, bond repayments, transfers | *Account Transactions* |
| `orders.csv` | Buy / sell / savings plan orders | *Portfolio Transactions* |
| `events.json` | Full raw event data from TR timeline | — (audit / debugging) |
| `DOCS_DIR/YYYY-MM-DD_HH-MM-SS/` | PDF documents (contract notes, tax statements) | — |

After conversion, `export_pp` automatically runs a mapping gap check (see `check_mappings` below) and prints event counts.

---

## build_classification — Asset Allocation taxonomy

Reads the events JSON from `export_pp` and generates a `classification.json` for Portfolio Performance's *Klassifizierungen* feature. It collects every security ISIN from your transaction history and assigns each one to a category based on an optional config file.

```sh
# Minimal — all ISINs default to RISKY:
pytrpp2 build_classification /path/to/events.json classification.json

# With explicit config:
pytrpp2 build_classification /path/to/events.json classification.json --config /path/to/classifications_config.json
```

Import the result in Portfolio Performance under:
> **Wertpapiere → Klassifizierungen → [taxonomy] → ⋮ → Importieren**

### Config file format

Copy `pytr/classifications_config.example.json` to `~/.pytr/classifications_config.json` and edit it:

```json
{
  "classifications": {
    "IE00B4L5Y983": "RISKY",
    "IE00B3WJKG14": "CASH",
    "DE0001030542": "CASH"
  }
}
```

Valid keys: `RISKY` (Risikobehafteter Portfolioteil) and `CASH` (Risikoarmer Anteil). ISINs not listed default to `RISKY`. After each run, any unconfigured ISINs are printed to the console.

If `--config` is not provided, pytrpp2 looks for `~/.pytr/classifications_config.json` automatically.

---

## check_mappings — Gap detector

Checks an events JSON for TR event types that have no handler in the converter. These would be silently dropped from `payments.csv` and `orders.csv` — typically caused by Trade Republic renaming or introducing event types after a platform update.

```sh
pytrpp2 check_mappings /path/to/events.json
```

Output:
- **WARNING** + table of unmapped types with counts (if any gaps exist)
- Intentionally ignored types (account events, notifications — expected)
- Registered handlers not seen in this export (old TR names / unused handlers)

`export_pp` runs this check automatically after every conversion, so you only need to call it manually to re-check an older events JSON.

---

## Authentication

### Web login (default)

Web login simulates a browser session using [app.traderepublic.com](https://app.traderepublic.com/). After entering your phone number and PIN, you will receive a four-digit code in the TradeRepublic app or via SMS. You may need to re-enter a code periodically when the session cookie expires.

### App login

App login uses the same method as the mobile app. Pass `--applogin` to use it. On first use, a device reset is performed — a private key is generated and saved locally. **This will log you out of your mobile device.**

```sh
pytrpp2 login --applogin
```

### AWS WAF token

Since early 2026 Trade Republic requires an `aws-waf-token` cookie on all auth endpoints. pytrpp2 handles this automatically during web login. If automatic detection fails, you can paste a token copied from your browser session:

```sh
pytrpp2 export_pp --waf-token <token> ...
```

### Credentials file

If you omit `-n` and `-p`, pytrpp2 reads from `~/.pytr/credentials`:

```
+49123456789
1234
```

Pass `--store_credentials` to save credentials automatically after a successful login.

---

## Development

### Setup

```sh
git clone https://github.com/your-org/pytrpp2.git
cd pytrpp2
pip install -e ".[dev]"
```

### Run tests

```sh
pytest tests/
```

### Linting and formatting

```sh
ruff format
ruff check --fix-only
mypy .
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
