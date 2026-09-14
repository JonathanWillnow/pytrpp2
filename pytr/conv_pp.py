"""
conv_pp.py — Portfolio Performance CSV export for Trade Republic events.

Classification and parsing of TR events is delegated to upstream pytr
(pytr.event.Event and pytr.transactions.TransactionExporter). Upstream tests that code
against real TR payloads and keeps it current with TR API changes, so pytrpp2 gets those
fixes with every upstream merge. This module only maps upstream's transactions onto the
two Portfolio Performance CSV imports:

- orders.csv   — portfolio transactions: Kauf, Verkauf, Einlieferung, Auslieferung
- payments.csv — account transactions: Einlage, Entnahme, Dividende, Zinsen, Steuern, ...

Every event ends up in exactly one bucket of the ConversionReport — converted, ignored
(known non-financial), unknown (upstream could not classify it) or error (parsing failed) —
so no event is dropped silently.
"""

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable

from pytr.event import Event, get_event_logger
from pytr.transactions import TransactionExporter

ORDERS_HEADER = [
    "Wert",
    "Buchungswährung",
    "Datum",
    "Uhrzeit",
    "Typ",
    "Notiz",
    "Gebühren",
    "Steuern",
    "ISIN",
    "Wertpapiername",
    "Stück",
]
PAYMENTS_HEADER = [
    "Wert",
    "Buchungswährung",
    "Datum",
    "Uhrzeit",
    "Typ",
    "Notiz",
    "Steuern",
    "ISIN",
    "Wertpapiername",
    "Stück",
]

# German labels produced by TransactionExporter(lang="de") for account transactions.
PAYMENT_TYPES = {
    "Einlage",
    "Entnahme",
    "Dividende",
    "Zinsen",
    "Zinsbelastung",
    "Steuern",
    "Steuerrückerstattung",
    "Gebühren",
    "Gebührenerstattung",
}

_UNKNOWN_EVENT_LOG_PREFIX = "Ignoring unknown event"


@dataclass
class PPRow:
    """One line in orders.csv (kind='order') or payments.csv (kind='payment')."""

    kind: str
    type: str
    value: Decimal
    currency: str
    dt: datetime
    note: str
    isin: str = ""
    name: str = ""
    shares: Decimal | None = None
    fees: Decimal = Decimal("0.00")
    taxes: Decimal = Decimal("0.00")
    warning: str = ""  # reported in ConversionReport.warnings

    def csv_fields(self) -> list[str]:
        dt = self.dt.astimezone()
        fields = [_fmt(self.value), self.currency, f"{dt:%d.%m.%Y}", f"{dt:%H:%M:%S}", self.type, self.note]
        if self.kind == "order":
            fields.append(_fmt(self.fees))
        fields += [_fmt(self.taxes), self.isin, self.name, _fmt(self.shares)]
        return fields


@dataclass
class Issue:
    """An event that was not (fully) converted."""

    key: str  # eventType, or "<missing>: <subtitle>" for events without eventType
    event: str  # human-readable identification: date, title, subtitle, id
    detail: str = ""


@dataclass
class ConversionReport:
    total: int = 0
    converted: int = 0
    orders: int = 0
    payments: int = 0
    ignored: dict[str, int] = field(default_factory=dict)
    unknown: list[Issue] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def gaps(self) -> list[Issue]:
        """Events that may carry financial data but are missing from the CSVs."""
        return self.unknown + self.errors


def event_key(event: dict) -> str:
    """Group key for an event in reports: its eventType, or its subtitle/title if eventType is missing."""
    et = event.get("eventType")
    if et:
        return str(et)
    label = event.get("subtitle") or event.get("title")
    return f"<missing>: {label}" if label else "<missing>"


def describe_event(event: dict) -> str:
    date = str(event.get("timestamp") or "")[:10]
    return f"{date} {event.get('title') or ''} -- {event.get('subtitle') or ''} (id {event.get('id')})"


def _fmt(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f").replace(".", ",")


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return abs(Decimal(str(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _shares(value) -> Decimal | None:
    if value is None:
        return None
    return abs(Decimal(str(value))).normalize()


# ---------------------------------------------------------------------------
# pytrpp2 rules for events upstream pytr does not handle (yet)
# ---------------------------------------------------------------------------
# Found in real exports. A rule returns the PP rows for an event ([] = nothing to book) and
# overrides upstream's classification, or None to leave the event to upstream. Propose these
# upstream; once upstream handles an event correctly, remove its rule here.

_RE_ISIN_IN_ICON = re.compile(r"(?:^|/)([A-Z]{2}[A-Z0-9]{9}\d)(?:/|$)")


def _isin(raw: dict, event: Event) -> str:
    if event.isin:
        return event.isin
    m = _RE_ISIN_IN_ICON.search(str(raw.get("icon") or ""))
    return m.group(1) if m else ""


def _section_items(raw: dict, *titles: str) -> dict[str, str]:
    items: dict[str, str] = {}
    for section in (raw.get("details") or {}).get("sections") or []:
        if section.get("title") in titles and isinstance(section.get("data"), list):
            for item in section["data"]:
                if isinstance(item, dict) and item.get("title"):
                    detail = item.get("detail")
                    items[item["title"]] = detail.get("text", "") if isinstance(detail, dict) else str(detail or "")
    return items


def _share_count(text: str) -> Decimal:
    shares = _shares(Event._parse_float_from_text_value(text, pref_locale="en"))
    if not shares:
        raise ValueError(f"cannot parse share count {text!r}")
    return shares


def _delivery(typ: str, raw: dict, event: Event, shares: Decimal) -> PPRow:
    title = event.title or ""
    return PPRow(
        kind="order",
        type=typ,
        value=Decimal("0.00"),
        currency="EUR",
        dt=event.date,
        note=f"{raw.get('subtitle')} - {title}" if raw.get("subtitle") else title,
        isin=_isin(raw, event),
        name=title,
        shares=shares,
    )


def _securities_account_transfer(raw: dict, event: Event) -> list[PPRow] | None:
    """ACCOUNT_TRANSFER_INCOMING/OUTGOING of shares, e.g. "Du hast 3 Aktien erhalten".

    Upstream maps ACCOUNT_TRANSFER_INCOMING to a cash deposit, which books 0 € and loses the
    shares. Transfers that carry an amount are cash and stay with upstream.
    """
    overview = _section_items(raw, "Übersicht", "Overview")
    count = overview.get("Anteile") or overview.get("Aktien") or overview.get("Shares")
    if not count or (raw.get("amount") or {}).get("value"):
        return None
    typ = "Einlieferung" if str(raw.get("eventType")).upper().endswith("INCOMING") else "Auslieferung"
    return [_delivery(typ, raw, event, _share_count(count))]


def _sharebooking(raw: dict, event: Event) -> list[PPRow]:
    """SHAREBOOKING / SHAREBOOKING_CANCELED: shares booked in or out by a corporate action.

    TR books and cancels these separately (Veralto spin-off 2023: +1, -1, +1), so every event
    is one delivery. Upstream ignores both, which makes later sales exceed the holdings.
    """
    txn = _section_items(raw, "Transaktion", "Transaction")
    booked_in = txn.get("Gutgeschriebene Anteile") or txn.get("Eingebuchte Anteile")
    booked_out = txn.get("Ausgebuchte Anteile")
    if booked_in:
        return [_delivery("Einlieferung", raw, event, _share_count(booked_in))]
    if booked_out:
        return [_delivery("Auslieferung", raw, event, _share_count(booked_out))]
    raise ValueError("share booking without share count")


def _nothing_to_book(raw: dict, event: Event) -> list[PPRow]:
    return []


FORK_RULES: dict[str, Callable[[dict, Event], list[PPRow] | None]] = {
    "ACCOUNT_TRANSFER_INCOMING": _securities_account_transfer,
    "ACCOUNT_TRANSFER_OUTGOING": _securities_account_transfer,
    "SHAREBOOKING": _sharebooking,
    "SHAREBOOKING_CANCELED": _sharebooking,
    "EXEMPTION_ORDER_CREATED": _nothing_to_book,  # Freistellungsauftrag created
}


class _WarningCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage().split("\n", 1)[0])


class Converter:
    def __init__(self):
        self._exporter = TransactionExporter(lang="de")

    def rows_for_event(self, raw: dict, event: Event) -> list[PPRow]:
        """Map upstream's transactions for one event onto PP rows.

        Raises ValueError for transaction types that have no PP CSV equivalent.
        """
        txns = list(self._exporter.from_event(event))
        currency = (raw.get("amount") or {}).get("currency") or "EUR"
        title = event.title or ""

        def order(typ, t, value=None, isin=None, shares=None, name=None):
            return PPRow(
                kind="order",
                type=typ,
                value=_money(t["Wert"] if value is None else value),
                currency=currency,
                dt=event.date,
                note=t["Notiz"] or title,
                isin=(t["ISIN"] if isin is None else isin) or "",
                name=name or title,
                shares=_shares(t["Stück"] if shares is None else shares),
                fees=_money(t["Gebühren"]),
                taxes=_money(t["Steuern"]),
            )

        # Saveback, Aktien-Bonus and the private markets 1 % bonus arrive as a buy plus a
        # matching deposit. PP models that as a single delivery of the shares.
        if (
            len(txns) == 2
            and [t["Typ"] for t in txns] == ["Kauf", "Einlage"]
            and _money(txns[0]["Wert"]) == _money(txns[1]["Wert"])
        ):
            return [order("Einlieferung", txns[0])]

        rows: list[PPRow] = []
        for t in txns:
            typ = t["Typ"]
            if typ in ("Kauf", "Verkauf"):
                name = title if not t["ISIN"] or t["ISIN"] == event.isin else (event.note or t["Notiz"])
                rows.append(order(typ, t, name=name))
            elif typ == "Umbuchung (Eingang)":
                rows.append(order("Einlieferung", t, value=0))
            elif typ == "Umbuchung (Ausgang)":
                rows.append(order("Auslieferung", t, value=0))
            elif typ == "Split":
                # Stück holds the shares added by the split / bonus shares.
                rows.append(order("Einlieferung", t, value=0))
            elif typ == "Spinoff":
                # ISIN is the new security, ISIN2 the parent it was spun off from.
                rows.append(order("Einlieferung", t, value=0, name=event.note or title))
            elif typ == "Swap":
                # ISIN/Stück are removed and ISIN2/Stück2 added. A cash component is booked as
                # the purchase price of the new shares (negative) or sale proceeds of the old (positive).
                cash = Decimal(str(t["Wert"] or 0))
                rows.append(order("Verkauf" if cash > 0 else "Auslieferung", t, value=cash if cash > 0 else 0))
                rows.append(
                    order(
                        "Kauf" if cash < 0 else "Einlieferung",
                        t,
                        value=cash if cash < 0 else 0,
                        isin=t["ISIN2"],
                        shares=t["Stück2"],
                        name=event.note or title,
                    )
                )
            elif typ in PAYMENT_TYPES and not (_money(t["Wert"]) or _money(t["Steuern"]) or _money(t["Gebühren"])):
                continue  # nothing to book, e.g. a Vorabpauschale covered by the tax allowance
            elif typ in PAYMENT_TYPES:
                note, warning = t["Notiz"] or title, ""
                fees = _money(t["Gebühren"])
                if fees:
                    # payments.csv has no fee column and TR does not say whether the fee is part of
                    # the amount, so keep it visible instead of guessing a booking.
                    note = f"{note} (Gebühren {_fmt(fees)} {currency})"
                    warning = f"fee of {_fmt(fees)} {currency} is not booked in payments.csv; verify the cash balance"
                rows.append(
                    PPRow(
                        kind="payment",
                        type=typ,
                        value=_money(t["Wert"]),
                        currency=currency,
                        dt=event.date,
                        note=note,
                        isin=t["ISIN"] or "",
                        name=title if t["ISIN"] else "",
                        shares=_shares(t["Stück"]),
                        taxes=_money(t["Steuern"]),
                        warning=warning,
                    )
                )
            else:
                raise ValueError(f"no Portfolio Performance mapping for transaction type {typ!r}")
        return rows

    def process(self, events: list[dict]) -> tuple[list[PPRow], ConversionReport]:
        report = ConversionReport(total=len(events))
        rows: list[PPRow] = []
        capture = _WarningCapture()
        event_logger = get_event_logger()
        event_logger.addHandler(capture)
        try:
            for raw in events:
                capture.messages.clear()
                key, desc = event_key(raw), describe_event(raw)
                # A single malformed event must never abort the whole export.
                try:
                    event = Event.from_dict(raw)
                    rule = FORK_RULES.get(str(raw.get("eventType") or "").upper())
                    rule_rows = rule(raw, event) if rule is not None else None
                    if rule_rows is not None:
                        event_rows = rule_rows
                        capture.messages.clear()  # the rule overrides upstream's verdict
                    elif event.event_type is not None:
                        event_rows = self.rows_for_event(raw, event)
                    else:
                        event_rows = []
                except Exception as e:
                    report.errors.append(Issue(key, desc, f"{type(e).__name__}: {e}"))
                    continue

                if event_rows:
                    report.converted += 1
                    rows.extend(event_rows)
                    report.warnings.extend(Issue(key, desc, r.warning) for r in event_rows if r.warning)
                elif any(m.startswith(_UNKNOWN_EVENT_LOG_PREFIX) for m in capture.messages):
                    report.unknown.append(Issue(key, desc))
                else:
                    report.ignored[key] = report.ignored.get(key, 0) + 1
                for m in capture.messages:
                    if not m.startswith(_UNKNOWN_EVENT_LOG_PREFIX):
                        report.warnings.append(Issue(key, desc, m))
        finally:
            event_logger.removeHandler(capture)

        rows.sort(key=lambda r: r.dt)
        report.orders = sum(1 for r in rows if r.kind == "order")
        report.payments = sum(1 for r in rows if r.kind == "payment")
        return rows, report

    def convert(
        self, events: list[dict], payments_file: None | str | Path, orders_file: None | str | Path
    ) -> ConversionReport:
        rows, report = self.process(events)
        for path, kind, header in ((payments_file, "payment", PAYMENTS_HEADER), (orders_file, "order", ORDERS_HEADER)):
            if not path:
                continue
            with open(path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh, delimiter=";", lineterminator="\n")
                writer.writerow(header)
                writer.writerows(r.csv_fields() for r in rows if r.kind == kind)
        return report
