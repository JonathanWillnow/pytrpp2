"""
Tests for pytr.conv_pp — Portfolio Performance conversion layer.

Covers:
- Amount: construction, from_text parsing, formatting
- Converter.process: event type dispatch, Ignore filtering, Unknown handling
- Converter.convert: CSV output format and content
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pytr.conv_pp import (
    Amount,
    Converter,
    Dividend,
    Ignore,
    InterestPayout,
    Investment,
    Order,
    Payment,
    Unknown,
)

TESTS_DIR = Path(__file__).parent


def load_fixture(name: str) -> dict:
    return json.loads((TESTS_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------

class TestAmount:
    def test_basic_creation(self):
        a = Amount("10.50", "EUR")
        assert a.value == Decimal("10.50")
        assert a.currency == "EUR"

    def test_fraction_digits_quantizes(self):
        a = Amount("10.5", "EUR", fraction_digits=2)
        assert a.value == Decimal("10.50")

    def test_zero_default_currency(self):
        a = Amount.zero()
        assert a.value == Decimal("0.00")
        assert a.currency == "EUR"

    def test_zero_custom_currency(self):
        a = Amount.zero("USD")
        assert a.currency == "USD"

    def test_from_text_euro_prefix(self):
        a = Amount.from_text("€10,50")
        assert a.value == Decimal("10.50")
        assert a.currency == "EUR"

    def test_from_text_euro_suffix_with_space(self):
        a = Amount.from_text("17,77 €")
        assert a.value == Decimal("17.77")
        assert a.currency == "EUR"

    def test_from_text_gratis(self):
        a = Amount.from_text("Gratis")
        assert a.value == Decimal("0.00")
        assert a.currency == "EUR"

    def test_from_text_thousands_and_decimal_separator(self):
        a = Amount.from_text("3.002,80 €")
        assert a.value == Decimal("3002.80")

    def test_from_text_strips_sign(self):
        a = Amount.from_text("-1,00 €")
        assert a.value == Decimal("1.00")

    def test_format_comma_decimal(self):
        a = Amount("10.50", "EUR")
        assert f"{a:,}" == "10,50"

    def test_format_dot_decimal(self):
        a = Amount("10.50", "EUR")
        assert f"{a:.}" == "10.50"

    def test_repr(self):
        a = Amount("10.50", "EUR")
        assert "EUR" in repr(a)


# ---------------------------------------------------------------------------
# Converter.process — event dispatch and filtering
# ---------------------------------------------------------------------------

class TestConverterProcess:
    def test_buy_order_returns_investment(self):
        event = load_fixture("buy.json")
        results = Converter().process([event])
        assert len(results) == 1
        assert isinstance(results[0], Investment)

    def test_buy_order_isin(self):
        event = load_fixture("buy.json")
        result = Converter().process([event])[0]
        assert result.isin == "IE00B4K6B022"

    def test_buy_order_shares(self):
        event = load_fixture("buy.json")
        result = Converter().process([event])[0]
        assert result.shares == Decimal("60")

    def test_buy_order_type_is_kauf(self):
        event = load_fixture("buy.json")
        result = Converter().process([event])[0]
        assert result.type == "Kauf"

    def test_buy_order_costs(self):
        event = load_fixture("buy.json")
        result = Converter().process([event])[0]
        assert result.costs.value == Decimal("1.00")
        assert result.costs.currency == "EUR"

    def test_buy_order_no_taxes(self):
        event = load_fixture("buy.json")
        result = Converter().process([event])[0]
        assert result.taxes.value == Decimal("0.00")

    def test_buy_order_name(self):
        event = load_fixture("buy.json")
        result = Converter().process([event])[0]
        assert result.name == "Euro Stoxx 50 EUR (Dist)"

    def test_dividend_returns_payment(self):
        event = load_fixture("bardividende.json")
        results = Converter().process([event])
        assert len(results) == 1
        assert isinstance(results[0], Payment)

    def test_dividend_isin_from_icon(self):
        # bardividende.json has no instrumentDetail action; ISIN falls back to icon
        event = load_fixture("bardividende.json")
        result = Converter().process([event])[0]
        assert result.isin == "US20030N1019"

    def test_dividend_name(self):
        event = load_fixture("bardividende.json")
        result = Converter().process([event])[0]
        assert result.name == "Comcast (A)"

    def test_dividend_shares(self):
        event = load_fixture("bardividende.json")
        result = Converter().process([event])[0]
        assert result.shares == Decimal("10.640298")

    def test_interest_payout_has_taxes(self):
        event = load_fixture("zinsen.json")
        result = Converter().process([event])[0]
        assert isinstance(result, InterestPayout)
        assert result.taxes.value == Decimal("1.87")

    def test_ignored_event_type_excluded_from_output(self):
        event = {
            "eventType": "ORDER_CANCELED",
            "timestamp": "2024-01-01T00:00:00+0000",
            "amount": {"value": "0", "currency": "EUR", "fractionDigits": 2},
        }
        results = Converter().process([event])
        assert results == []

    def test_unknown_event_type_produces_unknown_object(self):
        event = {
            "eventType": "SOME_FUTURE_UNKNOWN_EVENT",
            "timestamp": "2024-01-01T00:00:00+0000",
            "amount": {"value": "0", "currency": "EUR", "fractionDigits": 2},
        }
        results = Converter().process([event])
        assert len(results) == 1
        assert isinstance(results[0], Unknown)

    def test_mixed_events_correct_counts(self):
        buy = load_fixture("buy.json")
        dividend = load_fixture("bardividende.json")
        ignored = {"eventType": "ORDER_CANCELED", "timestamp": "2024-01-01T00:00:00+0000",
                   "amount": {"value": "0", "currency": "EUR", "fractionDigits": 2}}
        results = Converter().process([buy, dividend, ignored])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Converter.convert — CSV output
# ---------------------------------------------------------------------------

class TestConverterConvert:
    def test_orders_csv_created(self, tmp_path):
        event = load_fixture("buy.json")
        orders_file = tmp_path / "orders.csv"
        Converter().convert([event], None, orders_file)
        assert orders_file.exists()

    def test_orders_csv_header(self, tmp_path):
        event = load_fixture("buy.json")
        orders_file = tmp_path / "orders.csv"
        Converter().convert([event], None, orders_file)
        first_line = orders_file.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == "Wert;Buchungswährung;Datum;Uhrzeit;Typ;Notiz;Gebühren;Steuern;ISIN;Wertpapiername;Stück"

    def test_orders_csv_one_data_row(self, tmp_path):
        event = load_fixture("buy.json")
        orders_file = tmp_path / "orders.csv"
        Converter().convert([event], None, orders_file)
        lines = orders_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2  # header + 1 row

    def test_orders_csv_contains_isin(self, tmp_path):
        event = load_fixture("buy.json")
        orders_file = tmp_path / "orders.csv"
        Converter().convert([event], None, orders_file)
        content = orders_file.read_text(encoding="utf-8")
        assert "IE00B4K6B022" in content

    def test_payments_csv_created(self, tmp_path):
        event = load_fixture("bardividende.json")
        payments_file = tmp_path / "payments.csv"
        Converter().convert([event], payments_file, None)
        assert payments_file.exists()

    def test_payments_csv_header(self, tmp_path):
        event = load_fixture("bardividende.json")
        payments_file = tmp_path / "payments.csv"
        Converter().convert([event], payments_file, None)
        first_line = payments_file.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == "Wert;Buchungswährung;Datum;Uhrzeit;Typ;Notiz;Steuern;ISIN;Wertpapiername;Stück"

    def test_payments_csv_one_data_row(self, tmp_path):
        event = load_fixture("bardividende.json")
        payments_file = tmp_path / "payments.csv"
        Converter().convert([event], payments_file, None)
        lines = payments_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2  # header + 1 row

    def test_payments_csv_contains_isin(self, tmp_path):
        event = load_fixture("bardividende.json")
        payments_file = tmp_path / "payments.csv"
        Converter().convert([event], payments_file, None)
        content = payments_file.read_text(encoding="utf-8")
        assert "US20030N1019" in content

    def test_investment_not_written_to_payments(self, tmp_path):
        event = load_fixture("buy.json")
        payments_file = tmp_path / "payments.csv"
        Converter().convert([event], payments_file, None)
        lines = payments_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1  # header only, no data rows

    def test_payment_not_written_to_orders(self, tmp_path):
        event = load_fixture("bardividende.json")
        orders_file = tmp_path / "orders.csv"
        Converter().convert([event], None, orders_file)
        lines = orders_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1  # header only, no data rows
