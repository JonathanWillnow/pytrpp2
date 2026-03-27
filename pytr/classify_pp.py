"""
classify_pp.py — Portfolio Performance Klassifizierung taxonomy builder.

Reads events.json (raw TR timeline dump produced by export_pp), collects every
ISIN that appears in a security transaction, maps each to a category using an
optional config file, and writes classification.json ready to import into
Portfolio Performance:

  Wertpapiere > Klassifizierungen > [taxonomy] > ⋮ > Importieren

Category keys
-------------
  RISKY  — Risikobehafteter Portfolioteil (stocks, ETFs, bonds — default)
  CASH   — Risikoarmer Anteil (cash-like instruments)

Every ISIN not listed in the config defaults to RISKY.  Copy
pytr/classifications_config.example.json to ~/.pytr/classifications_config.json
and add entries to override individual ISINs.
"""

import json
import re
from pathlib import Path

_RE_ISIN = re.compile(r"^[A-Z]{2}-?[\dA-Z]{9}-?\d$")

DEFAULT_CONFIG_PATH = Path.home() / ".pytr" / "classifications_config.json"

TAXONOMY = {
    "name": "Asset Allocation",
    "categories": [
        {
            "name": "Risikobehafteter Portfolioteil",
            "key": "RISKY",
            "color": "#e8432d",
            "children": [],
        },
        {
            "name": "Risikoarmer Anteil",
            "key": "CASH",
            "color": "#4caf50",
            "children": [],
        },
    ],
}

# Event types that carry an ISIN (security transactions, both old and new TR names)
SECURITY_EVENT_TYPES = {
    # New TR names (post-2025)
    "TRADING_TRADE_EXECUTED",
    "trading_trade_executed",
    "TRADING_SAVINGSPLAN_EXECUTED",
    "SPARE_CHANGE_AGGREGATE",
    "SAVEBACK_AGGREGATE",
    "ACCOUNT_TRANSFER_INCOMING",
    "ACCOUNT_TRANSFER_OUTGOING",
    "SECURITIES_TRANSFER_OUTGOING",
    "ssp_securities_transfer_outgoing",
    "REPAYMENT",
    "COUPON_PAYMENT",
    "SSP_CORPORATE_ACTION_CASH",
    # Old TR names (historical data, pre-2025)
    "ORDER_EXECUTED",
    "TRADE_INVOICE",
    "SAVINGS_PLAN_EXECUTED",
    "SAVINGS_PLAN_INVOICE_CREATED",
    "ssp_corporate_action_invoice_cash",
    "benefits_spare_change_execution",
    "benefits_saveback_execution",
}

_VALID_KEYS = {"RISKY", "CASH"}


def _extract_isin(event: dict) -> str:
    """Extract ISIN from a TR event, handling both new-style and old-style formats.

    New-style: ISIN is in the header section's action.payload.
    Old-style:  ISIN is encoded in the icon path (e.g. "logos/IE00B4K6B022/v2").
    """
    # New-style: header section action payload
    try:
        for section in event.get("details", {}).get("sections", []):
            if section.get("type") == "header":
                action = section.get("action", {})
                if action.get("type") == "instrumentDetail":
                    isin = action.get("payload", "")
                    if isin:
                        return isin
    except (KeyError, TypeError):
        pass
    # Old-style: icon path fallback
    try:
        icon = event.get("icon", "").split("/")[1]
        if _RE_ISIN.match(icon):
            return icon
    except (IndexError, AttributeError):
        pass
    return ""


def collect_isins(events: list[dict]) -> dict[str, str]:
    """Return {isin: security_name} for every security event in the list.

    Only event types that represent actual security transactions are included.
    The first-seen title for each ISIN is used as the security name.
    """
    isins: dict[str, str] = {}
    for event in events:
        if event.get("eventType") not in SECURITY_EVENT_TYPES:
            continue
        isin = _extract_isin(event)
        if not isin:
            continue
        if isin not in isins:
            isins[isin] = event.get("title", "")
    return isins


def load_config(config_path: Path | None = None) -> dict[str, str]:
    """Return {isin: category_key} from a classifications_config.json file.

    Args:
        config_path: Explicit path to the config file.  If None, falls back to
                     ~/.pytr/classifications_config.json.  Returns an empty dict
                     if the file does not exist (all ISINs default to RISKY).
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as fh:
        data = json.load(fh)
    raw = data.get("classifications", {})
    result = {}
    for isin, key in raw.items():
        if key not in _VALID_KEYS:
            print(f"  classifications_config: unknown key '{key}' for {isin} — defaulting to RISKY")
            key = "RISKY"
        result[isin] = key
    return result


def build(events_file: Path, output_file: Path, config_path: Path | None = None) -> None:
    """Build classification.json from events.json and an optional config.

    Args:
        events_file:  Path to the raw events JSON produced by export_pp.
        output_file:  Where to write the classification JSON.
        config_path:  Optional ISIN override config.  Falls back to
                      ~/.pytr/classifications_config.json when None.
    """
    with open(events_file, encoding="utf-8") as fh:
        events = json.load(fh)

    known_isins = collect_isins(events)
    config = load_config(config_path)

    key_to_name = {cat["key"]: cat["name"] for cat in TAXONOMY["categories"]}

    instruments = []
    for isin, name in sorted(known_isins.items()):
        key = config.get(isin, "RISKY")
        instruments.append(
            {
                "identifiers": {"name": name, "isin": isin},
                "categories": [{"path": [key_to_name[key]], "weight": 100.0}],
            }
        )

    taxonomy = {**TAXONOMY, "instruments": instruments}
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump(taxonomy, fh, indent=2, ensure_ascii=False)

    print(f"  Wrote {len(instruments)} securities to {output_file.name}")

    new_isins = {isin: name for isin, name in known_isins.items() if isin not in config}
    if new_isins:
        print()
        print("INFO: the following ISINs were not in the config and defaulted to RISKY.")
        print("  To override, add them to your classifications_config.json.")
        print()
        print(f"  {'ISIN':<14}  Name")
        print(f"  {'-' * 14}  {'-' * 40}")
        for isin, name in sorted(new_isins.items()):
            print(f"  {isin:<14}  {name}")
