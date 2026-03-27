# pytrpp2: Download TradeRepublic data and export to Portfolio Performance

This is a tool for the private API of the Trade Republic online brokerage.
This package and its authors are not affiliated with Trade Republic Bank GmbH.

It can export orders and transactions into files ready to import into [Portfolio Performance](https://www.portfolio-performance.info/) —
*an open source tool to calculate the overall performance of an investment portfolio across all accounts using True-Time Weighted Return or Internal Rate of Return.*
The authors of this package are not affiliated with Portfolio Performance.

This package is based on [`pytr`](https://github.com/pytr-org/pytr) originally by marzzzello, extended with Portfolio Performance export functionality.

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

## Usage

The command is `pytrpp2`. Run `pytrpp2 --help` to see all available subcommands.

```
usage: pytrpp2 [-h] [-V] [-v {warning,info,debug}]
               {help,login,portfolio,details,dl_docs,export_transactions,
                get_price_alarms,set_price_alarms,export_pp,completion} ...

Commands:
  help                  Print this help message
  login                 Check credentials and log in (performs device reset if needed)
  portfolio             Show current portfolio
  details               Get details for an ISIN
  dl_docs               Download all PDF documents from the timeline
  export_transactions   Export timeline transactions to CSV
  get_price_alarms      Get current price alarms
  set_price_alarms      Set new price alarms
  export_pp             Export TR timeline to Portfolio Performance CSV format
  completion            Print shell tab completion

Global options:
  -h, --help                            show this help message and exit
  -V, --version                         Print version information and quit
  -v, --verbosity {warning,info,debug}  Set verbosity level (default: info)
```

---

## export_pp — Portfolio Performance Export

The `export_pp` subcommand downloads your full Trade Republic timeline and converts it into files that Portfolio Performance can import.

### Recommended usage

```sh
# Export CSVs and event log into a directory (no PDF download):
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output

# Also download PDF documents into a timestamped subfolder:
pytrpp2 export_pp -n +49123456789 -p 1234 -D /path/to/output -F /path/to/docs

# Limit to the last 30 days:
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

options:
  -h, --help                    show this help message and exit

Authentication:
  -n, --phone_no PHONE_NO       TradeRepublic phone number (international format, e.g. +49123456789)
  -p, --pin PIN                 TradeRepublic PIN
  --applogin                    Use app login instead of web login
  --waf-token WAF_TOKEN         Manually provide an aws-waf-token cookie value (copy from browser session)
  --store_credentials           Store credentials (phone number, PIN, cookies) for next run

Output (use -D to set all at once, or specify individually):
  -D, --dir DIR                 Main output directory. Automatically sets paths for
                                events.json, payments.csv, and orders.csv.
                                Does NOT trigger PDF download — use -F for that.
  -E, --events-file FILE        Write raw event data to this JSON file
  -P, --payments-file FILE      Write payments (dividends, interest, etc.) to this CSV file
  -O, --orders-file FILE        Write orders (buy/sell) to this CSV file
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

| File | Contents | Portfolio Performance import type |
|---|---|---|
| `payments.csv` | Dividends, interest payouts, coupon payments, bond repayments | Account transactions |
| `orders.csv` | Buy and sell orders | Security orders |
| `events.json` | Full raw event data from TR timeline | — (audit / debugging) |
| `DOCS_DIR/YYYY-MM-DD_HH-MM-SS/` | PDF documents (contract notes, tax statements, etc.) | — |

---

## Authentication

### Web login (default)

Web login simulates a browser session using [app.traderepublic.com](https://app.traderepublic.com/). After entering your phone number and PIN, you will receive a four-digit code in the TradeRepublic app or via SMS. You will need to re-enter a code periodically when the session cookie expires.

### App login

App login uses the same method as the mobile app. Pass `--applogin` to use it. On first use, a device reset is performed — a private key is generated and saved locally. **This will log you out of your mobile device.**

```sh
pytrpp2 login --applogin
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
