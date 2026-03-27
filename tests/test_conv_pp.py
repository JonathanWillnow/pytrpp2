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
    CardPayment,
    Converter,
    Dividend,
    FixedAccountTransferIncoming,
    Ignore,
    InterestPayout,
    Investment,
    NewStyleCardRefund,
    NewStyleDividend,
    NewStyleOrder,
    NewStyleSaveBack,
    Order,
    Payment,
    PaymentInbound,
    PaymentOutbound,
    Unknown,
    _detail_text,
    _get_section_new,
    _parse_transaction_text,
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


# ---------------------------------------------------------------------------
# _detail_text and _get_section_new helpers
# ---------------------------------------------------------------------------

class TestDetailHelpers:
    def test_detail_text_with_dict(self):
        assert _detail_text({'text': 'hello', 'type': 'text'}) == 'hello'

    def test_detail_text_with_string(self):
        assert _detail_text('hello') == 'hello'

    def test_detail_text_with_none(self):
        assert _detail_text(None) == ''

    def test_detail_text_dict_missing_text_key(self):
        assert _detail_text({'type': 'status'}) == ''

    def test_get_section_new_reads_first_matching_title(self):
        event = {
            'details': {
                'sections': [
                    {
                        'title': 'Übersicht',
                        'data': [
                            {'title': 'Asset', 'detail': {'text': 'NVIDIA', 'type': 'text'}},
                            {'title': 'Gebühr', 'detail': {'text': '1,00 €', 'type': 'text'}},
                        ],
                    }
                ]
            }
        }
        section = _get_section_new(event, 'Übersicht')
        assert section['Asset'] == 'NVIDIA'
        assert section['Gebühr'] == '1,00 €'

    def test_get_section_new_returns_empty_dict_for_missing_section(self):
        event = {'details': {'sections': []}}
        assert _get_section_new(event, 'Übersicht') == {}

    def test_get_section_new_accepts_multiple_title_candidates(self):
        event = {
            'details': {
                'sections': [
                    {
                        'title': 'Geschäft',
                        'data': [{'title': 'Steuern', 'detail': {'text': '1,87 €'}}],
                    }
                ]
            }
        }
        # Should find 'Geschäft' when searching for ('Transaktion', 'Geschäft')
        section = _get_section_new(event, 'Transaktion', 'Geschäft')
        assert section['Steuern'] == '1,87 €'


# ---------------------------------------------------------------------------
# _parse_transaction_text
# ---------------------------------------------------------------------------

class TestParseTransactionText:
    def test_integer_shares(self):
        shares, price = _parse_transaction_text('2 ×  37,30 €')
        assert shares == Decimal('2')

    def test_fractional_shares_comma_decimal(self):
        shares, price = _parse_transaction_text('0,685102 ×  160,56 €')
        assert shares == Decimal('0.685102')

    def test_fractional_shares_dot_decimal(self):
        shares, price = _parse_transaction_text('0.685102 × 160,56 €')
        assert shares == Decimal('0.685102')

    def test_thousands_separator_dot(self):
        shares, price = _parse_transaction_text('1.000 × 5,00 €')
        assert shares == Decimal('1000')

    def test_price_text_returned(self):
        _, price = _parse_transaction_text('3 × 328,70 €')
        assert '328' in price
        assert '€' in price

    def test_empty_string_returns_none(self):
        shares, price = _parse_transaction_text('')
        assert shares is None
        assert price is None

    def test_no_match_returns_none(self):
        shares, price = _parse_transaction_text('Ausgeführt')
        assert shares is None


# ---------------------------------------------------------------------------
# NewStyleOrder — TRADING_TRADE_EXECUTED
# ---------------------------------------------------------------------------

class TestNewStyleOrder:
    def _buy_event(self, event_type='TRADING_TRADE_EXECUTED'):
        event = load_fixture('buy_new.json')
        event['eventType'] = event_type
        return event

    def test_dispatched_for_uppercase_event_type(self):
        results = Converter().process([self._buy_event('TRADING_TRADE_EXECUTED')])
        assert len(results) == 1
        assert isinstance(results[0], Investment)

    def test_dispatched_for_lowercase_variant(self):
        # buy_new.json ships with lowercase 'trading_trade_executed'
        results = Converter().process([load_fixture('buy_new.json')])
        assert len(results) == 1
        assert isinstance(results[0], Investment)

    def test_isin_from_header_section(self):
        result = Converter().process([self._buy_event()])[0]
        assert result.isin == 'US67066G1040'

    def test_name_from_asset_row(self):
        result = Converter().process([self._buy_event()])[0]
        assert result.name == 'NVIDIA'

    def test_type_kauf_for_buy_subtitle(self):
        result = Converter().process([self._buy_event()])[0]
        assert result.type == 'Kauf'

    def test_type_verkauf_for_sell_subtitle(self):
        event = self._buy_event()
        event['subtitle'] = 'Verkaufsorder'
        result = Converter().process([event])[0]
        assert result.type == 'Verkauf'

    def test_shares_fractional(self):
        result = Converter().process([self._buy_event()])[0]
        assert result.shares == Decimal('0.685102')

    def test_costs_from_gebuehr_row(self):
        result = Converter().process([self._buy_event()])[0]
        assert result.costs.value == Decimal('1.00')
        assert result.costs.currency == 'EUR'

    def test_value_is_positive(self):
        # buy_new.json has negative amount (-111); NewStyleOrder takes abs()
        result = Converter().process([self._buy_event()])[0]
        assert result.value.value > 0

    def test_saveback_is_einlieferung(self):
        event = {
            'eventType': 'SAVEBACK_AGGREGATE',
            'timestamp': '2025-01-01T00:00:00+0000',
            'icon': 'logos/IE00B3WJKG14/v2',
            'amount': {'value': '-15', 'currency': 'EUR', 'fractionDigits': 2},
            'details': {'sections': []},
        }
        result = Converter().process([event])[0]
        assert result.type == 'Einlieferung'

    def test_saveback_zero_costs(self):
        event = {
            'eventType': 'SAVEBACK_AGGREGATE',
            'timestamp': '2025-01-01T00:00:00+0000',
            'icon': 'logos/IE00B3WJKG14/v2',
            'amount': {'value': '-15', 'currency': 'EUR', 'fractionDigits': 2},
            'details': {'sections': []},
        }
        result = Converter().process([event])[0]
        assert result.costs.value == Decimal('0.00')

    def test_roundup_type_kauf(self):
        event = {
            'eventType': 'SPARE_CHANGE_AGGREGATE',
            'timestamp': '2025-01-01T00:00:00+0000',
            'icon': 'logos/IE00B3WJKG14/v2',
            'amount': {'value': '-10', 'currency': 'EUR', 'fractionDigits': 2},
            'details': {'sections': []},
        }
        result = Converter().process([event])[0]
        assert result.type == 'Kauf'


# ---------------------------------------------------------------------------
# FixedAccountTransferIncoming — shares from Übersicht
# ---------------------------------------------------------------------------

class TestFixedAccountTransferIncoming:
    def _make_event(self, anteile_text=None):
        data = []
        if anteile_text is not None:
            data.append({
                'title': 'Anteile',
                'detail': {'text': anteile_text, 'type': 'text'},
                'style': 'plain',
            })
        return {
            'eventType': 'ACCOUNT_TRANSFER_INCOMING',
            'timestamp': '2025-01-01T00:00:00+0000',
            'icon': 'logos/IE00B4K6B022/v2',   # needed by get_isin icon fallback path
            'amount': {'value': '0', 'currency': 'EUR', 'fractionDigits': 2},
            'details': {
                'sections': [
                    {'title': 'Übersicht', 'data': data, 'type': 'table'}
                ]
            },
        }

    def test_reads_integer_shares_from_ubersicht(self):
        result = Converter().process([self._make_event('5')])[0]
        assert result.shares == Decimal('5')

    def test_reads_decimal_shares_from_ubersicht(self):
        result = Converter().process([self._make_event('5,5')])[0]
        assert result.shares == Decimal('5.5')

    def test_falls_back_to_one_when_no_anteile(self):
        result = Converter().process([self._make_event()])[0]
        assert result.shares == 1  # base class fallback

    def test_dispatches_to_fixed_class(self):
        result = Converter().process([self._make_event('3')])[0]
        assert isinstance(result, FixedAccountTransferIncoming)


# ---------------------------------------------------------------------------
# NewStyleDividend — SSP_CORPORATE_ACTION_CASH
# ---------------------------------------------------------------------------

class TestNewStyleDividend:
    def _make_event(self, include_shares=True, shares_text='10'):
        data = [
            {'title': 'Steuern', 'detail': {'text': '1,50 €', 'type': 'text'}, 'style': 'plain'},
        ]
        if include_shares:
            data.append({'title': 'Anteile', 'detail': {'text': shares_text, 'type': 'text'}, 'style': 'plain'})
        return {
            'eventType': 'SSP_CORPORATE_ACTION_CASH',
            'timestamp': '2025-01-01T00:00:00+0000',
            'title': 'Test Corp',
            'amount': {'value': '10.00', 'currency': 'EUR', 'fractionDigits': 2},
            'details': {
                'sections': [
                    {
                        'type': 'header',
                        'action': {'type': 'instrumentDetail', 'payload': 'US1234567890'},
                    },
                    {'title': 'Geschäft', 'data': data, 'type': 'table'},
                ]
            },
        }

    def test_dispatched_as_payment(self):
        result = Converter().process([self._make_event()])[0]
        assert isinstance(result, Payment)

    def test_isin_from_header(self):
        result = Converter().process([self._make_event()])[0]
        assert result.isin == 'US1234567890'

    def test_taxes_parsed(self):
        result = Converter().process([self._make_event()])[0]
        assert result.taxes.value == Decimal('1.50')

    def test_csv_with_shares_no_none_literal(self):
        result = Converter().process([self._make_event(include_shares=True)])[0]
        assert 'None' not in result.csv()

    def test_csv_without_shares_no_none_literal(self):
        # Regression: old Dividend.csv() called str(None) → 'None'
        result = Converter().process([self._make_event(include_shares=False)])[0]
        assert 'None' not in result.csv()


# ---------------------------------------------------------------------------
# CardPayment and NewStyleCardRefund
# ---------------------------------------------------------------------------

class TestCardPayment:
    def _make_card_event(self, event_type, amount_value):
        return {
            'eventType': event_type,
            'timestamp': '2025-01-01T00:00:00+0000',
            'amount': {'value': str(amount_value), 'currency': 'EUR', 'fractionDigits': 2},
        }

    def test_card_transaction_value_is_positive(self):
        event = self._make_card_event('CARD_TRANSACTION', -50)
        result = Converter().process([event])[0]
        assert result.value.value > 0

    def test_card_aft_value_is_positive(self):
        event = self._make_card_event('CARD_AFT', -30)
        result = Converter().process([event])[0]
        assert result.value.value > 0

    def test_card_payment_type_is_entnahme(self):
        event = self._make_card_event('CARD_TRANSACTION', -50)
        result = Converter().process([event])[0]
        assert result.type == 'Entnahme'

    def test_card_refund_value_is_positive(self):
        event = self._make_card_event('CARD_REFUND', -20)
        result = Converter().process([event])[0]
        assert result.value.value > 0

    def test_card_refund_type_is_einlage(self):
        event = self._make_card_event('CARD_REFUND', 20)
        result = Converter().process([event])[0]
        assert result.type == 'Einlage'

    def test_card_verification_ignored(self):
        event = self._make_card_event('CARD_VERIFICATION', 0)
        results = Converter().process([event])
        assert results == []


# ---------------------------------------------------------------------------
# New event type dispatch — bank transfers and new Ignores
# ---------------------------------------------------------------------------

class TestNewEventTypeMappings:
    def _simple(self, event_type, amount_value=0):
        return {
            'eventType': event_type,
            'timestamp': '2025-01-01T00:00:00+0000',
            'amount': {'value': str(amount_value), 'currency': 'EUR', 'fractionDigits': 2},
        }

    def test_bank_transaction_incoming_dispatches_to_payment_inbound(self):
        result = Converter().process([self._simple('BANK_TRANSACTION_INCOMING', 100)])[0]
        assert isinstance(result, PaymentInbound)

    def test_bank_transaction_outgoing_dispatches_to_payment_outbound(self):
        result = Converter().process([self._simple('BANK_TRANSACTION_OUTGOING', 50)])[0]
        assert isinstance(result, PaymentOutbound)

    def test_bank_transaction_outgoing_direct_debit_dispatches(self):
        result = Converter().process([self._simple('BANK_TRANSACTION_OUTGOING_DIRECT_DEBIT', 50)])[0]
        assert isinstance(result, PaymentOutbound)

    def test_bank_transaction_outgoing_scheduled_is_ignored(self):
        assert Converter().process([self._simple('BANK_TRANSACTION_OUTGOING_SCHEDULED')]) == []

    def test_trading_order_cancelled_is_ignored(self):
        assert Converter().process([self._simple('TRADING_ORDER_CANCELLED')]) == []

    def test_trading_savingsplan_execution_failed_is_ignored(self):
        assert Converter().process([self._simple('TRADING_SAVINGSPLAN_EXECUTION_FAILED')]) == []

    def test_order_rejected_is_ignored(self):
        assert Converter().process([self._simple('ORDER_REJECTED')]) == []

    def test_ssp_corporate_action_activity_is_ignored(self):
        assert Converter().process([self._simple('SSP_CORPORATE_ACTION_ACTIVITY')]) == []

    def test_ssp_corporate_action_no_cash_is_ignored(self):
        assert Converter().process([self._simple('SSP_CORPORATE_ACTION_NO_CASH')]) == []

    def test_documents_changed_is_ignored(self):
        assert Converter().process([self._simple('DOCUMENTS_CHANGED')]) == []

    def test_sharebooking_is_ignored(self):
        assert Converter().process([self._simple('SHAREBOOKING')]) == []

    def test_general_meeting_is_ignored(self):
        assert Converter().process([self._simple('GENERAL_MEETING')]) == []

    def test_tax_year_end_report_created_is_ignored(self):
        assert Converter().process([self._simple('TAX_YEAR_END_REPORT_CREATED')]) == []
