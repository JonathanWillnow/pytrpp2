"""
Tests for pytr.conv_pp — Portfolio Performance CSV export.

conv_pp delegates event parsing to upstream pytr (pytr.event / pytr.transactions) and maps
the resulting transactions onto PP's orders.csv / payments.csv. The central test runs every
real TR fixture in tests/events through export_pp's conversion and checks the rows against
upstream's hand-verified expectations in test_events.py, translated into PP CSV terms.
"""

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
from test_events import test_data as UPSTREAM_CASES

from pytr.conv_pp import ORDERS_HEADER, PAYMENT_TYPES, PAYMENTS_HEADER, Converter
from pytr.event import get_event_logger

EVENTS_DIR = Path(__file__).parent / "events"


def load_event(name: str) -> dict:
    return json.loads((EVENTS_DIR / name).read_text(encoding="utf-8"))


def money(value) -> Decimal:
    return abs(Decimal(str(value or 0))).quantize(Decimal("0.01"))


def shares(value):
    return None if value is None else abs(Decimal(str(value))).normalize()


# ---------------------------------------------------------------------------
# Specification: upstream transactions -> PP rows
# ---------------------------------------------------------------------------


def expected_pp_rows(transactions: list[dict]) -> list[tuple]:
    """Translate upstream's expected transactions into (kind, type, value, isin, shares, fees, taxes)."""

    def row(kind, typ, t, value=None, isin=None, n=None):
        return (
            kind,
            typ,
            money(t.get("Wert") if value is None else value),
            (t.get("ISIN") if isin is None else isin) or "",
            shares(t.get("Stück") if n is None else n),
            money(t.get("Gebühren")) if kind == "order" else Decimal("0.00"),
            money(t.get("Steuern")),
        )

    types = [t["Typ"] for t in transactions]
    if types == ["Kauf", "Einlage"] and money(transactions[0]["Wert"]) == money(transactions[1]["Wert"]):
        return [row("order", "Einlieferung", transactions[0])]

    rows = []
    for t in transactions:
        typ = t["Typ"]
        if typ in ("Kauf", "Verkauf"):
            rows.append(row("order", typ, t))
        elif typ in ("Umbuchung (Eingang)", "Split", "Spinoff"):
            rows.append(row("order", "Einlieferung", t, value=0))
        elif typ == "Umbuchung (Ausgang)":
            rows.append(row("order", "Auslieferung", t, value=0))
        elif typ == "Swap":
            cash = Decimal(str(t.get("Wert") or 0))
            rows.append(row("order", "Verkauf" if cash > 0 else "Auslieferung", t, value=cash if cash > 0 else 0))
            rows.append(
                row(
                    "order",
                    "Kauf" if cash < 0 else "Einlieferung",
                    t,
                    value=cash if cash < 0 else 0,
                    isin=t.get("ISIN2"),
                    n=t.get("Stück2"),
                )
            )
        elif typ in PAYMENT_TYPES:
            # Payments without any amount (e.g. a 0,00 dividend) have nothing to book.
            if money(t.get("Wert")) or money(t.get("Steuern")) or money(t.get("Gebühren")):
                rows.append(row("payment", typ, t))
        else:
            raise AssertionError(f"test spec has no PP mapping for {typ!r}")
    return rows


def actual_pp_rows(rows) -> list[tuple]:
    return [
        (r.kind, r.type, r.value, r.isin, r.shares, r.fees if r.kind == "order" else Decimal("0.00"), r.taxes)
        for r in rows
    ]


@pytest.mark.parametrize("case", UPSTREAM_CASES, ids=[c["filename"] for c in UPSTREAM_CASES])
def test_upstream_fixture_converts_to_expected_pp_rows(case):
    rows, report = Converter().process([load_event(case["filename"])])

    assert report.errors == []
    assert report.unknown == []

    if case.get("event_type") is None:
        assert rows == []
        assert sum(report.ignored.values()) == 1
        return

    expected = expected_pp_rows(case.get("transactions", []))
    assert actual_pp_rows(rows) == expected
    assert report.converted == (1 if expected else 0)


def test_every_fixture_file_is_covered_by_upstream_cases():
    covered = {c["filename"] for c in UPSTREAM_CASES}
    on_disk = {p.name for p in EVENTS_DIR.glob("*.json")}
    assert on_disk - covered == set()


def test_all_fixtures_in_one_run_have_no_gaps():
    events = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(EVENTS_DIR.glob("*.json"))]
    _, report = Converter().process(events)
    assert report.gaps == []
    assert report.total == len(events)
    assert report.converted + sum(report.ignored.values()) == len(events)


# ---------------------------------------------------------------------------
# Regressions from the audit
# ---------------------------------------------------------------------------


class TestEventsWithoutEventType:
    """TR delivers some events without an eventType key; the old converter crashed on them."""

    @pytest.mark.parametrize("name", ["buy_new_no_eventType.json", "buy_new2.json", "buy_no_eventType.json"])
    def test_buy_without_event_type_is_exported(self, name):
        event = load_event(name)
        assert "eventType" not in event
        rows, report = Converter().process([event])
        assert report.gaps == []
        assert [(r.kind, r.type) for r in rows] == [("order", "Kauf")]

    def test_buy_values(self):
        (row,), _ = Converter().process([load_event("buy_new_no_eventType.json")])
        assert row.isin == "US67066G1040"
        assert row.shares == Decimal("0.685102")
        assert row.value == Decimal("111.00")
        assert row.fees == Decimal("1.00")

    def test_does_not_abort_other_events(self):
        events = [load_event("buy_no_eventType.json"), load_event("bardividende.json")]
        rows, report = Converter().process(events)
        assert report.converted == 2
        assert {r.kind for r in rows} == {"order", "payment"}


class TestValuesPreviouslyWrong:
    def test_sell_taxes_are_exported(self):
        (row,), _ = Converter().process([load_event("limit-sell-order.json")])
        assert (row.type, row.taxes, row.shares) == ("Verkauf", Decimal("17.36"), Decimal("11"))

    def test_dividend_taxes_and_shares(self):
        (row,), _ = Converter().process([load_event("bardividende.json")])
        assert (row.type, row.value, row.taxes, row.shares) == (
            "Dividende",
            Decimal("2.24"),
            Decimal("0.78"),
            Decimal("10.640298"),
        )

    def test_negative_corporate_action_cash_is_taxes(self):
        (row,), _ = Converter().process([load_event("vorabpauschale_negative.json")])
        assert row.type == "Steuern"

    def test_legacy_migrated_trade_is_exported(self):
        (row,), report = Converter().process([load_event("legacy_verkauforder_neu_abgerechnet.json")])
        assert report.gaps == []
        assert (row.type, row.shares) == ("Verkauf", Decimal("27"))

    def test_trade_invoice_type_is_kauf_not_order_kind(self):
        (row,), _ = Converter().process([load_event("trade_invoice.json")])
        assert row.type == "Kauf"

    def test_saveback_is_single_delivery(self):
        rows, _ = Converter().process([load_event("saveback.json")])
        assert [(r.kind, r.type, r.value) for r in rows] == [("order", "Einlieferung", Decimal("15.00"))]

    def test_split_adds_shares(self):
        (row,), _ = Converter().process([load_event("aktiensplit.json")])
        assert (row.type, row.value, row.shares) == ("Einlieferung", Decimal("0.00"), Decimal("49"))

    def test_swap_with_cash_is_delivery_out_and_buy(self):
        rows, _ = Converter().process([load_event("zwischenpapiere.json")])
        assert [(r.type, r.isin, r.shares, r.value) for r in rows] == [
            ("Auslieferung", "DK0064307839", Decimal("119"), Decimal("0.00")),
            ("Kauf", "DK0064307755", Decimal("17"), Decimal("151.59")),
        ]


def test_payment_fee_is_kept_visible():
    """payments.csv has no fee column; a deposit fee must not vanish silently."""
    (row,), report = Converter().process([load_event("payment_inbound_credit_card.json")])
    assert (row.type, row.value) == ("Einlage", Decimal("1000.00"))
    assert "Gebühren 7,00 EUR" in row.note
    assert [w.detail for w in report.warnings] == [
        "fee of 7,00 EUR is not booked in payments.csv; verify the cash balance"
    ]


# ---------------------------------------------------------------------------
# Robustness: nothing is dropped silently, nothing aborts the export
# ---------------------------------------------------------------------------


class TestRobustness:
    @pytest.mark.parametrize(
        "bad_event",
        [
            {},
            {"id": "x"},
            {"id": "x", "timestamp": "not a date", "title": "t", "subtitle": "s"},
            {"id": "x", "timestamp": "2026-08-01T10:00:00.000+0000", "title": "t", "subtitle": "s", "details": None},
        ],
    )
    def test_malformed_event_is_reported_not_raised(self, bad_event):
        rows, report = Converter().process([bad_event, load_event("buy.json")])
        assert len(report.errors) == 1
        assert report.converted == 1
        assert len(rows) == 1

    def test_unknown_event_type_is_reported(self):
        event = {
            "id": "abc",
            "timestamp": "2026-08-01T10:00:00.000+0000",
            "title": "Something new",
            "subtitle": "Brand new",
            "eventType": "BRAND_NEW_TR_EVENT",
        }
        rows, report = Converter().process([event])
        assert rows == []
        assert [i.key for i in report.unknown] == ["BRAND_NEW_TR_EVENT"]
        assert "Something new" in report.unknown[0].event

    def test_known_non_financial_event_is_ignored_not_unknown(self):
        _, report = Converter().process([load_event("address_changed.json")])
        assert report.gaps == []
        assert report.ignored == {"ADDRESS_CHANGED": 1}

    def test_unmapped_pp_type_is_an_error(self, monkeypatch):
        converter = Converter()
        monkeypatch.setattr(
            converter._exporter,
            "from_event",
            lambda event: iter([{"Typ": "Zauberei", "Wert": 1, "Notiz": "", "ISIN": None, "Stück": None}]),
        )
        rows, report = converter.process([load_event("buy.json")])
        assert rows == []
        assert "Zauberei" in report.errors[0].detail

    def test_parser_warnings_are_reported(self):
        event = load_event("buy.json")
        event["details"]["sections"] = [s for s in event["details"]["sections"] if s.get("title") != "Transaktion"]
        _, report = Converter().process([event])
        assert any("shares" in w.detail for w in report.warnings)

    def test_log_handler_is_removed(self, monkeypatch):
        handlers_before = list(get_event_logger().handlers)
        converter = Converter()

        def boom(raw, event):
            raise KeyboardInterrupt

        monkeypatch.setattr(converter, "rows_for_event", boom)
        with pytest.raises(KeyboardInterrupt):
            converter.process([load_event("buy.json")])
        assert get_event_logger().handlers == handlers_before

    def test_rows_sorted_by_date(self):
        newer, older = load_event("buy_new.json"), load_event("buy.json")
        rows, _ = Converter().process([newer, older])
        assert [r.dt for r in rows] == sorted(r.dt for r in rows)


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


def read_csv(path: Path) -> list[list[str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


class TestCsvOutput:
    def test_headers(self, tmp_path):
        Converter().convert([], tmp_path / "payments.csv", tmp_path / "orders.csv")
        assert read_csv(tmp_path / "orders.csv") == [ORDERS_HEADER]
        assert read_csv(tmp_path / "payments.csv") == [PAYMENTS_HEADER]

    def test_order_row(self, tmp_path):
        Converter().convert([load_event("buy_new_no_eventType.json")], None, tmp_path / "orders.csv")
        (_, row) = read_csv(tmp_path / "orders.csv")
        record = dict(zip(ORDERS_HEADER, row))
        assert record["Wert"] == "111,00"
        assert record["Buchungswährung"] == "EUR"
        assert record["Typ"] == "Kauf"
        assert record["Gebühren"] == "1,00"
        assert record["ISIN"] == "US67066G1040"
        assert record["Stück"] == "0,685102"
        assert record["Datum"].count(".") == 2 and record["Uhrzeit"].count(":") == 2

    def test_payment_row(self, tmp_path):
        Converter().convert([load_event("bardividende.json")], tmp_path / "payments.csv", None)
        (_, row) = read_csv(tmp_path / "payments.csv")
        record = dict(zip(PAYMENTS_HEADER, row))
        assert (record["Wert"], record["Typ"], record["Steuern"], record["Stück"]) == (
            "2,24",
            "Dividende",
            "0,78",
            "10,640298",
        )

    def test_date_is_local_time(self, tmp_path):
        event = load_event("buy.json")
        Converter().convert([event], None, tmp_path / "orders.csv")
        (_, row) = read_csv(tmp_path / "orders.csv")
        from datetime import datetime

        local = datetime.fromisoformat(event["timestamp"][:-2] + ":" + event["timestamp"][-2:]).astimezone()
        assert (row[2], row[3]) == (f"{local:%d.%m.%Y}", f"{local:%H:%M:%S}")

    def test_delimiter_in_name_is_quoted(self, tmp_path):
        event = load_event("buy.json")
        event["title"] = "Foo; Bar"
        Converter().convert([event], None, tmp_path / "orders.csv")
        (_, row) = read_csv(tmp_path / "orders.csv")
        assert len(row) == len(ORDERS_HEADER)
        assert row[ORDERS_HEADER.index("Wertpapiername")] == "Foo; Bar"

    def test_orders_and_payments_are_split(self, tmp_path):
        events = [load_event("buy.json"), load_event("bardividende.json"), load_event("deposit.json")]
        report = Converter().convert(events, tmp_path / "payments.csv", tmp_path / "orders.csv")
        assert len(read_csv(tmp_path / "orders.csv")) - 1 == report.orders == 1
        assert len(read_csv(tmp_path / "payments.csv")) - 1 == report.payments == 2


# ---------------------------------------------------------------------------
# pytrpp2 rules — events upstream mishandles, found in a real export (anonymised)
# ---------------------------------------------------------------------------

PP_EVENTS_DIR = Path(__file__).parent / "pp_events"


def load_pp_event(name: str) -> dict:
    return json.loads((PP_EVENTS_DIR / name).read_text(encoding="utf-8"))


class TestPytrpp2Rules:
    def test_securities_transfer_in_books_shares(self):
        """Regression: upstream booked "Du hast 3 Aktien erhalten" as a 0 € cash deposit."""
        rows, report = Converter().process([load_pp_event("account_transfer_incoming.json")])
        assert report.gaps == []
        assert [(r.kind, r.type, r.value, r.isin, r.shares) for r in rows] == [
            ("order", "Einlieferung", Decimal("0.00"), "DE0005493365", Decimal("3"))
        ]

    def test_securities_transfer_out_books_shares(self):
        event = load_pp_event("account_transfer_incoming.json")
        event["eventType"] = "ACCOUNT_TRANSFER_OUTGOING"
        (row,), _ = Converter().process([event])
        assert (row.type, row.shares) == ("Auslieferung", Decimal("3"))

    def test_cash_account_transfer_stays_with_upstream(self):
        event = load_pp_event("account_transfer_incoming.json")
        event["amount"] = {"currency": "EUR", "value": 100.0, "fractionDigits": 2}
        rows, _ = Converter().process([event])
        assert [(r.kind, r.type, r.value) for r in rows] == [("payment", "Einlage", Decimal("100.00"))]

    def test_spinoff_share_bookings_net_to_holding(self):
        """Regression: Veralto spin-off (+1, cancelled -1, re-booked +1) was ignored entirely,
        so the later sale of 1 share had no holding in PP."""
        events = [
            load_pp_event("sharebooking.json"),
            load_pp_event("sharebooking_canceled.json"),
            load_pp_event("sharebooking2.json"),
        ]
        rows, report = Converter().process(events)
        assert report.gaps == []
        assert [(r.type, r.isin, r.shares) for r in rows] == [
            ("Einlieferung", "US92338C1036", Decimal("1")),
            ("Auslieferung", "US92338C1036", Decimal("1")),
            ("Einlieferung", "US92338C1036", Decimal("1")),
        ]

    def test_sharebooking_without_share_count_is_an_error(self):
        event = load_pp_event("sharebooking.json")
        for section in event["details"]["sections"]:
            if section.get("title") == "Transaktion":
                section["data"] = []
        rows, report = Converter().process([event])
        assert rows == []
        assert "share booking without share count" in report.errors[0].detail

    def test_exemption_order_created_is_ignored(self):
        rows, report = Converter().process([load_pp_event("exemption_order_created.json")])
        assert (rows, report.gaps, report.ignored) == ([], [], {"EXEMPTION_ORDER_CREATED": 1})

    def test_zero_vorabpauschale_books_nothing(self):
        """Regression: a Vorabpauschale covered by the allowance produced a 'Steuern 0,00' row."""
        rows, report = Converter().process([load_pp_event("vorabpauschale_zero.json")])
        assert rows == []
        assert report.gaps == []
        assert sum(report.ignored.values()) == 1

    def test_no_gaps_in_pp_fixtures(self):
        events = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PP_EVENTS_DIR.glob("*.json"))]
        _, report = Converter().process(events)
        assert report.gaps == []
