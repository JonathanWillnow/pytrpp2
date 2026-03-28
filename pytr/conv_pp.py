"""
conv_pp.py — Ported from pytrpp's conv.py.

Converts raw TR timeline events into typed Python objects and exports them
to Portfolio Performance-compatible CSV files (payments.csv, orders.csv).
"""

import json
import re
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from pytr.trdl_pp import get_timestamp

RE_ISIN = re.compile(r"^[A-Z]{2}-?[\dA-Z]{9}-?\d$")


class Amount:
    def __init__(self, value: str | Decimal, currency: str, fraction_digits: int | None = None) -> None:
        self.value = Decimal(value)
        if fraction_digits is not None:
            self.value = self.value.quantize(Decimal("1." + "0" * int(fraction_digits)))
        self.currency = currency

    def __format__(self, format_spec: str):
        if format_spec == ",":
            return str(self.value).replace(".", ",")
        elif format_spec == ".":
            return str(self.value)
        else:
            return format(self.value, format_spec)

    def __repr__(self):
        return f"{repr(self.value)} {self.currency}"

    @classmethod
    def zero(cls, currency="EUR"):
        return cls(Decimal("0.00"), currency)

    @classmethod
    def from_text(cls, text: str):
        CURRENCIES = "€$"
        WHITESPACE = "  \t"
        if text == "Gratis":
            return cls.zero()

        # Remove currency
        if text[0] in CURRENCIES:
            currency = text[0]
            text = text[1:]
        elif text[-1] in CURRENCIES:
            currency = text[-1]
            text = text[:-1]

        if text[0] in "+-":
            text = text[1:]

        text = text.strip(WHITESPACE)

        # Adapted from code by savek-cc (https://github.com/MartinScharrer/pytrpp/issues/2):
        if "." in text and "," in text:
            # Remove any dots (the thousand separators)
            text = text.replace(".", "")
            # Replace the comma (decimal separator) with a dot.
            text = text.replace(",", ".")
        # If only a comma exists, assume it is the decimal separator.
        elif "," in text:
            text = text.replace(",", ".")
        # If only a dot exists or no separator exists, assume it's in the correct format.
        currency = {"€": "EUR", "$": "USD"}.get(currency, ascii(currency))
        return Amount(text, currency)


def amount(event: dict) -> "Amount | None":
    """Extract amount from event."""
    try:
        amount_dict = event["amount"]
        return Amount(amount_dict["value"], amount_dict["currency"], amount_dict["fractionDigits"])
    except KeyError:
        return None


# ---------------------------------------------------------------------------
# Helpers for new-style TR data format (post-early-2025)
# ---------------------------------------------------------------------------
# TR changed section detail values from plain strings to dicts:
#   old: {"title": "X", "detail": "value"}
#   new: {"title": "X", "detail": {"text": "value", "type": "text", ...}}
# These helpers read both formats transparently.


def _detail_text(detail) -> str:
    """Return the display text from a section detail, handling both old (str) and new (dict) format."""
    if isinstance(detail, dict):
        return detail.get("text", "")
    return str(detail) if detail is not None else ""


def _get_section_new(event: dict, *section_titles: str) -> dict:
    """Return {title: text} for the first matching section, using _detail_text for both detail formats."""
    try:
        for section in event["details"]["sections"]:
            if section.get("title") in section_titles:
                result = {}
                for item in section.get("data", []):
                    if isinstance(item, dict) and item.get("title"):
                        result[item["title"]] = _detail_text(item.get("detail"))
                return result
    except (KeyError, TypeError):
        pass
    return {}


_RE_TRANSACTION = re.compile(
    r"(\d[\d.,]*)\s*[×x\*]\s*([\d.,]+[\xa0\s]*[€$])",
    re.UNICODE,
)


def _parse_transaction_text(text: str):
    """Parse a transaction summary like '3 × 328,70 €' or '0.685102 × 160,56 €'.

    Returns (shares: Decimal, price_text: str) or (None, None) if unparseable.

    Distinguishes thousands-separator dots (e.g. '1.000') from decimal-point dots
    (e.g. '0.685102') by checking whether the dot is followed by exactly three digits.
    """
    m = _RE_TRANSACTION.search(text)
    if not m:
        return None, None
    shares_str = m.group(1)
    price_str = m.group(2).strip()

    if re.search(r"\.\d{3}(?!\d)", shares_str) and not re.search(r"\.\d{1,2}$", shares_str):
        # Thousands separators: strip dots, then replace comma decimal separator
        shares_str = shares_str.replace(".", "").replace(",", ".")
    else:
        # Decimal point notation or plain integer: only replace comma → dot
        shares_str = shares_str.replace(",", ".")

    try:
        shares = Decimal(shares_str)
    except InvalidOperation:
        return None, None
    return shares, price_str


class Event:
    pass


class TransactionEvent(Event):
    def get_isin(self, event: dict):
        try:
            sections = event["details"]["sections"]
            for section in sections:
                action = section.get("action")
                if action:
                    if action["type"] == "instrumentDetail":
                        return action["payload"]
        except KeyError:
            pass
        # Otherwise try to extract it from the icon
        try:
            icon = event["icon"].split("/", 3)[1]
            if RE_ISIN.match(icon):
                return icon
        except (TypeError, ValueError):
            pass
        return ""

    def get_transaction(self, event: dict):
        transaction = {}
        try:
            sections = event["details"]["sections"]
            for section in sections:
                if section.get("title") in ("Transaktion", "Geschäft"):
                    for data in section["data"]:
                        title = data["title"]
                        text = data["detail"]["text"]
                        if title == "Aktion":
                            text = Decimal(text)
                        elif title in ("Gebühr", "Steuern"):
                            if text.lower() == "kostenlos":
                                text = Amount.zero()
                            else:
                                text = Amount.from_text(text)
                        elif title in ("Aktienkurs", "Anteilspreis"):
                            title = "Preis"
                            text = Amount.from_text(text)
                        elif title in ("Gesamt", "Tilgung", "Coupon Zahlung"):
                            text = Amount.from_text(text)
                        elif title in ("Anteile", "Aktien"):
                            title = "Anteile"
                            text = Decimal(text.replace(",", "."))
                        elif title == "Dividende pro Aktie":
                            title = "Dividende je Aktie"
                        transaction[title] = text
        except KeyError:
            pass
        return transaction

    def get_section(self, event: dict, *section_titles: str) -> dict | None:
        try:
            sections = event["details"]["sections"]
            for section in sections:
                if section.get("title") in section_titles:
                    return {data["title"]: data["detail"]["text"] for data in section["data"]}
        except KeyError:
            return None
        return None


class Unknown(Event):
    def __init__(self, event: dict):
        self.event = deepcopy(event)

    def __repr__(self):
        return f"Unknown({self.event['eventType']})"


class Ignore(Event):
    def __init__(self, event: dict):
        self.event = deepcopy(event)

    def __repr__(self):
        return f"Ignore({self.event['eventType']})"


class Investment(TransactionEvent):
    note: str
    type: str

    TYPES = {
        "Round up": "Kauf",
        "Sparplan": "Kauf",
        "Saveback": "Einlieferung",
        "Wertpapiertransfer": "Einlieferung",
        "Kauf": "Kauf",
        "Verkauf": "Verkauf",
    }

    def __init__(self, event: dict):
        self.dt: datetime = get_timestamp(event["timestamp"])
        self.value: Amount | None = amount(event)  # type: ignore[assignment]
        if event.get("title", "").startswith("Anleihe"):
            self.note = "Anleihe"
        self.isin: str = self.get_isin(event)
        transaction = self.get_transaction(event)
        self.price = transaction.get("Preis")
        self.taxes = transaction.get("Steuern", Amount.zero())
        self.costs = transaction.get("Gebühr", Amount.zero())
        if self.value is None:
            self.value = transaction.get("Gesamt", Amount.zero())
        overview = self.get_section(event, "Übersicht") or {}
        for t in ("Asset", "Anteil"):
            self.name = overview.get(t)
            if self.name is not None:
                break
        try:
            self.type
        except AttributeError:
            ty: str | None = None
            for t in ("Ordertyp", "Orderart", "Auftragsart"):
                ty = overview.get(t)
                if ty is not None:
                    break
            self.type = self.TYPES.get(ty, ty) if ty is not None else "Kauf"
        self.shares = transaction.get("Anteile")
        if self.shares is None:
            self.shares = 1

    @staticmethod
    def csv_header(sep=";"):
        return f"Wert{sep}Buchungswährung{sep}Datum{sep}Uhrzeit{sep}Typ{sep}Notiz{sep}Gebühren{sep}Steuern{sep}ISIN{sep}Wertpapiername{sep}Stück\n"

    def csv(self, sep=";", decimal=","):
        dt = self.dt.astimezone()
        return (
            f"{self.value:{decimal}}{sep}{self.value.currency}{sep}{dt:%d.%m.%Y}{sep}"
            f"{dt:%H:%M:%S}{sep}{self.type}{sep}{self.note}{sep}{self.costs:{decimal}}{sep}{self.taxes:{decimal}}{sep}"
            f"{self.isin}{sep}{self.name}{sep}{str(self.shares).replace('.', ',')}\n"
        )


class Payment(Event):
    note: str
    type: str

    def __init__(self, event: dict):
        self.dt: datetime = get_timestamp(event["timestamp"])
        self.value: Amount | None = amount(event)  # type: ignore[assignment]

    def csv(self, sep=";", decimal=","):
        dt = self.dt.astimezone()
        try:
            taxes = f"{self.taxes:{decimal}}"
        except AttributeError:
            taxes = ""
        return f"{str(self.value.value).replace('.', ',')}{sep}{self.value.currency}{sep}{dt:%d.%m.%Y}{sep}{dt:%H:%M:%S}{sep}{self.type}{sep}{self.note}{sep}{taxes}{sep}{sep}{sep}\n"

    @staticmethod
    def csv_header(sep=";"):
        return f"Wert{sep}Buchungswährung{sep}Datum{sep}Uhrzeit{sep}Typ{sep}Notiz{sep}Steuern{sep}ISIN{sep}Wertpapiername{sep}Stück\n"


class RoundUp(Investment):
    """benefits_spare_change_execution"""

    note = "Round-up"


class AccountTransferIncoming(Investment):
    note = "Eingehender Wertpapierübertrag"
    type = "Einlieferung"

    def __init__(self, event: dict):
        super().__init__(event)
        if self.value is None:
            self.value = Amount.zero()


def securities_transfer_outgoing(event):
    try:
        return SecuritiesTransferOutgoing(event)
    except Exception:
        return Ignore(event)


class SecuritiesTransferOutgoing(Investment):
    note = "Ausgehender Wertpapierübertrag"
    type = "Auslieferung"

    def __init__(self, event: dict):
        self.dt: datetime = get_timestamp(event["timestamp"])
        self.isin: str = self.get_isin(event)
        overview = self.get_section(event, "Übersicht", "Overview") or {}
        for t in ("Asset", "Anteil"):
            self.name = overview.get(t)
            if self.name is not None:
                break
        self.shares = overview.get("Aktien")
        if self.shares is None:
            self.shares = 1
        self.costs = Amount.zero()
        self.taxes = Amount.zero()
        self.value = Amount.zero()


class SavingsPlanExec(Investment):
    note = "Sparplan"


class SaveBack(Investment):
    note = "SaveBack"


class Order(Investment):
    note = "Wertpapierorder"


class StockPerkRefunded(AccountTransferIncoming):
    note = "Gratisaktie"

    def __init__(self, event: dict):
        super().__init__(event)
        self.type = "Einlieferung"


class CardTransaction(Payment):
    type = "Entnahme"
    note = "Kartenzahlung"

    def __init__(self, event: dict):
        super().__init__(event)
        self.note += f": {event['title']}"


class PaymentInbound(Payment):
    type = "Einlage"
    note = "Eingehende Überweisung"


class PaymentInboundSepaDirectDebit(PaymentInbound):
    note = "Eingehende Lastschrift"


class PaymentOutbound(Payment):
    type = "Entnahme"
    note = "Ausgehende Überweisung"


def SspCorporateActionInvoiceCash(event: dict) -> Event:
    if event["subtitle"] == "Vorabpauschale":
        return Vorabpauschale(event)
    else:
        return Dividend(event)


class Vorabpauschale(Payment, TransactionEvent):
    note = "Vorabpauschale"
    type = "Steuern"

    def __init__(self, event: dict):
        super().__init__(event)
        self.isin: str = self.get_isin(event)
        transaction = self.get_transaction(event)
        self.taxes = transaction.get("Steuern", Amount.zero())
        self.name = event["title"]

    def csv(self, sep=";"):
        s = super().csv(sep).rstrip(f"\n{sep}")
        return f'{s}{sep}{self.isin}{sep}"{self.name}"{sep}\n'


class Dividend(Payment, TransactionEvent):
    """Dividend payout"""

    type = "Dividende"
    note = "Dividende"

    def __init__(self, event: dict):
        super().__init__(event)
        self.isin: str = self.get_isin(event)
        transaction = self.get_transaction(event)
        self.shares = transaction.get("Anteile")
        self.dividend_per_share = transaction.get("Dividende je Aktie")
        self.taxes = transaction.get("Steuern", Amount.zero())
        self.name = event["title"]

    def csv(self, sep=";"):
        s = super().csv(sep).rstrip(f"\n{sep}")
        return f'{s}{sep}{self.isin}{sep}"{self.name}"{sep}{str(self.shares).replace(".", ",")}\n'


class CouponPayment(Payment, TransactionEvent):
    type = "Dividende"
    note = "Coupon Zahlung"

    def __init__(self, event: dict):
        super().__init__(event)
        self.isin: str = self.get_isin(event)
        transaction = self.get_transaction(event)
        self.shares = 1
        self.value = transaction["Coupon Zahlung"]
        self.taxes = transaction.get("Steuern", Amount.zero())
        self.name = f"{event['title']}: Coupon {transaction['Coupon']}"

    def csv(self, sep=";"):
        s = super().csv(sep).rstrip(f"\n{sep}")
        return f'{s}{sep}{self.taxes}{sep}{self.isin}{sep}"{self.name}"{sep}{self.shares}\n'


class InterestPayout(Payment, TransactionEvent):
    type = "Zinsen"
    note = "Zinsen"

    def __init__(self, event: dict):
        super().__init__(event)
        transaction = self.get_transaction(event)
        self.taxes = transaction.get("Steuern", Amount.zero())


class TaxRefund(Payment):
    type = "Steuerrückerstattung"
    note = "Steuerrückerstattung"


class CardRefund(CardTransaction):
    type = "Einlage"
    note = "Kartenrückzahlung"


class CardOriginalCreditTransaction(CardTransaction):
    type = "Einlage"
    note = "Kartenrückzahlung"


class CardWithdrawal(CardTransaction):
    type = "Entnahme"
    note = "Geldautomat"

    def __init__(self, event: dict):
        super().__init__(event)
        self.note += f" {event['subtitle']}"


class CardOrderBilled(Payment):
    type = "Gebühren"
    note = "Kartengebühr"


class BondRepayment(Investment):
    note = "Anleihe"

    def __init__(self, event: dict):
        super().__init__(event)
        self.type = "Verkauf"


# ---------------------------------------------------------------------------
# New-style event handlers (post-early-2025 TR data format)
# ---------------------------------------------------------------------------


class NewStyleOrder(Investment):
    """Handler for TRADING_TRADE_EXECUTED — new TR name and new data layout.

    Shares and price are encoded as a single 'Transaktion' text in 'Übersicht'
    (e.g. '3 × 328,70 €') rather than separate rows in a 'Transaktion' section.
    """

    note = "Wertpapierorder"

    def __init__(self, event: dict):
        self.dt = get_timestamp(event["timestamp"])
        self.isin = self.get_isin(event)
        overview = _get_section_new(event, "Übersicht")
        self.name = overview.get("Asset") or event.get("title", "")
        subtitle = event.get("subtitle", "").lower()
        if "sell" in subtitle or "verkauf" in subtitle or "verk" in subtitle:
            self.type = "Verkauf"
        else:
            self.type = "Kauf"
        fee_text = overview.get("Gebühr", "")
        try:
            self.costs = (
                Amount.from_text(fee_text)
                if fee_text and fee_text.lower() not in ("", "kostenlos", "gratis")
                else Amount.zero()
            )
        except Exception:
            self.costs = Amount.zero()
        self.taxes = Amount.zero()
        self.value = amount(event)  # type: ignore[assignment]
        if self.value is not None:
            self.value = Amount(abs(self.value.value), self.value.currency)
        transaction_text = overview.get("Transaktion", "")
        shares, price_text = _parse_transaction_text(transaction_text)
        self.shares = shares if shares is not None else Decimal("1")
        try:
            self.price = Amount.from_text(price_text) if price_text else None
        except Exception:
            self.price = None
        if self.value is None:
            self.value = Amount.zero()


class NewStyleSavingsPlan(NewStyleOrder):
    """Handler for TRADING_SAVINGSPLAN_EXECUTED."""

    note = "Sparplan"

    def __init__(self, event: dict):
        super().__init__(event)
        self.type = "Kauf"


class NewStyleRoundUp(NewStyleOrder):
    """Handler for SPARE_CHANGE_AGGREGATE (TR round-up feature)."""

    note = "Round-up"

    def __init__(self, event: dict):
        super().__init__(event)
        self.type = "Kauf"


class NewStyleSaveBack(NewStyleOrder):
    """Handler for SAVEBACK_AGGREGATE (TR 1% cashback reinvestment).

    Classified as Einlieferung (free delivery) with zero costs.
    Fix 11: value is kept from the event (not zeroed) so PP can compute the correct Kurs.
    """

    note = "TR 1% Saveback"

    def __init__(self, event: dict):
        super().__init__(event)
        self.type = "Einlieferung"
        self.costs = Amount.zero()


class CardPayment(Payment):
    """Handler for CARD_TRANSACTION and CARD_AFT (card purchases and debit settlements).

    TR sends negative amounts for outgoing card charges; PP expects positive Entnahme values.
    """

    type = "Entnahme"
    note = "Konsum"

    def __init__(self, event: dict):
        super().__init__(event)
        if self.value is not None:
            self.value = Amount(abs(self.value.value), self.value.currency)


class NewStyleCardRefund(Payment):
    """Handler for CARD_REFUND (money returned after a card transaction).

    Named NewStyleCardRefund to avoid collision with the existing CardRefund class
    which handles the old-format 'card_refund' event type.
    """

    type = "Einlage"
    note = "Konsum"

    def __init__(self, event: dict):
        super().__init__(event)
        if self.value is not None:
            self.value = Amount(abs(self.value.value), self.value.currency)


class NewStyleDividend(Payment, TransactionEvent):
    """Handler for SSP_CORPORATE_ACTION_CASH (new name for dividend events).

    Uses _get_section_new so it handles both old-style string and new-style dict
    detail values. Handles None shares safely in csv() output.
    """

    type = "Dividende"
    note = "Dividende"

    def __init__(self, event: dict):
        super().__init__(event)
        self.isin = self.get_isin(event)
        self.name = event.get("title", "")
        section = _get_section_new(event, "Geschäft", "Transaktion")
        shares_str = section.get("Aktien", section.get("Anteile", ""))
        try:
            self.shares = Decimal(shares_str.replace(",", ".")) if shares_str else None
        except InvalidOperation:
            self.shares = None
        taxes_text = section.get("Steuern", "")
        try:
            self.taxes = Amount.from_text(taxes_text) if taxes_text else Amount.zero()
        except Exception:
            self.taxes = Amount.zero()

    def csv(self, sep=";"):
        s = Payment.csv(self, sep).rstrip(f"\n{sep}")
        shares_str = str(self.shares).replace(".", ",") if self.shares is not None else ""
        return f'{s}{sep}{self.isin}{sep}"{self.name}"{sep}{shares_str}\n'


class NewStyleCouponPayment(Payment, TransactionEvent):
    """Handler for COUPON_PAYMENT with new data format.

    Replaces CouponPayment which crashes on new-format section data.
    Uses _get_section_new for robust section reading.
    """

    type = "Dividende"
    note = "Coupon Zahlung"

    def __init__(self, event: dict):
        super().__init__(event)
        self.isin = self.get_isin(event)
        self.name = event.get("title", "")
        section = _get_section_new(event, "Transaktion", "Geschäft", "Übersicht")
        taxes_text = section.get("Steuern", "")
        try:
            self.taxes = Amount.from_text(taxes_text) if taxes_text else Amount.zero()
        except Exception:
            self.taxes = Amount.zero()
        self.shares = Decimal("1")

    def csv(self, sep=";"):
        s = Payment.csv(self, sep).rstrip(f"\n{sep}")
        shares_str = str(self.shares).replace(".", ",") if self.shares is not None else ""
        return f'{s}{sep}{self.isin}{sep}"{self.name}"{sep}{shares_str}\n'


class NewStyleBondRepayment(NewStyleOrder):
    """Handler for REPAYMENT (bond maturity) with new data format.

    Replaces BondRepayment which uses the old-style section parser.
    """

    note = "Anleihe"

    def __init__(self, event: dict):
        super().__init__(event)
        self.type = "Verkauf"
        self.note = "Anleihe"


class NewStyleSecuritiesTransferOutgoing(Investment):
    """Handler for ACCOUNT_TRANSFER_OUTGOING and SECURITIES_TRANSFER_OUTGOING.

    Reads share count from Übersicht → Anteile or Aktien using _get_section_new.
    Value is zero (transfers have no cash consideration).
    """

    note = "Ausgehender Wertpapierübertrag"
    type = "Auslieferung"

    def __init__(self, event: dict):
        self.dt = get_timestamp(event["timestamp"])
        self.isin = self.get_isin(event)
        self.name = event.get("title", "")
        overview = _get_section_new(event, "Übersicht")
        anteile = overview.get("Anteile") or overview.get("Aktien")
        if anteile:
            try:
                self.shares = Decimal(anteile.replace(",", ".").strip())
            except InvalidOperation:
                self.shares = Decimal("1")
        else:
            self.shares = Decimal("1")
        self.costs = Amount.zero()
        self.taxes = Amount.zero()
        self.value = Amount.zero()
        self.price = None


class FixedAccountTransferIncoming(AccountTransferIncoming):
    """Fix for ACCOUNT_TRANSFER_INCOMING: reads actual share count from Übersicht → Anteile.

    The base class falls back to shares=1 because transfer events have no
    'Transaktion'/'Geschäft' section. This subclass overrides shares with the
    correct value from the 'Übersicht' section after calling super().__init__().
    """

    def __init__(self, event: dict):
        super().__init__(event)
        overview = _get_section_new(event, "Übersicht")
        anteile = overview.get("Anteile")
        if anteile:
            try:
                self.shares = Decimal(anteile.replace(",", ".").strip())
            except InvalidOperation:
                pass


class Converter:
    event_types: dict[str, Callable[[dict], Any]] = {
        # --- Old-name orders (historical data, pre-2025) ---
        "ORDER_EXECUTED": Order,
        "TRADE_INVOICE": Order,
        "SAVINGS_PLAN_EXECUTED": SavingsPlanExec,
        "SAVINGS_PLAN_INVOICE_CREATED": SavingsPlanExec,
        "trading_savingsplan_executed": SavingsPlanExec,
        "ACCOUNT_TRANSFER_INCOMING": FixedAccountTransferIncoming,  # fixed: reads shares from Übersicht
        "SECURITIES_TRANSFER_OUTGOING": NewStyleSecuritiesTransferOutgoing,  # updated: new-format parser
        "ssp_securities_transfer_outgoing": NewStyleSecuritiesTransferOutgoing,
        "ORDER_EXPIRED": Ignore,
        "ORDER_CANCELED": Ignore,
        "YEAR_END_TAX_REPORT": Ignore,
        "PRE_DETERMINED_TAX_BASE_EARNING": Ignore,
        "REFERENCE_ACCOUNT_CHANGED": Ignore,
        "EX_POST_COST_REPORT": Ignore,
        "card_successful_verification": Ignore,
        # --- New-name orders (post-2025 TR renames) ---
        "TRADING_TRADE_EXECUTED": NewStyleOrder,
        "trading_trade_executed": NewStyleOrder,  # lowercase variant seen in some TR responses
        "TRADING_SAVINGSPLAN_EXECUTED": NewStyleSavingsPlan,
        "SPARE_CHANGE_AGGREGATE": NewStyleRoundUp,
        "SAVEBACK_AGGREGATE": NewStyleSaveBack,
        "ACCOUNT_TRANSFER_OUTGOING": NewStyleSecuritiesTransferOutgoing,
        "TRADING_ORDER_CANCELLED": Ignore,
        "TRADING_SAVINGSPLAN_EXECUTION_FAILED": Ignore,
        "ORDER_REJECTED": Ignore,
        # --- Old-name payments (historical data, pre-2025) ---
        "PAYMENT_INBOUND": PaymentInbound,
        "INCOMING_TRANSFER": PaymentInbound,
        "PAYMENT_INBOUND_SEPA_DIRECT_DEBIT": PaymentInboundSepaDirectDebit,
        "PAYMENT_OUTBOUND": PaymentOutbound,
        "OUTGOING_TRANSFER": PaymentOutbound,
        "INCOMING_TRANSFER_DELEGATION": PaymentInbound,
        "OUTGOING_TRANSFER_DELEGATION": PaymentOutbound,
        "CREDIT": Dividend,
        "ssp_corporate_action_invoice_cash": SspCorporateActionInvoiceCash,
        "ssp_corporate_action_invoice_shares": Ignore,  # Vorabpauschale without payment
        "INTEREST_PAYOUT_CREATED": InterestPayout,
        "INTEREST_PAYOUT": InterestPayout,
        "card_successful_oct": CardOriginalCreditTransaction,
        "card_order_billed": CardOrderBilled,
        "card_refund": CardRefund,
        "card_successful_atm_withdrawal": CardWithdrawal,
        "STOCK_PERK_REFUNDED": StockPerkRefunded,
        "REPAYMENT": NewStyleBondRepayment,  # updated: new-format parser
        "COUPON_PAYMENT": NewStyleCouponPayment,  # updated: new-format parser
        # Old-name card
        "card_successful_transaction": CardTransaction,
        "card_failed_transaction": Ignore,
        "card_failed_atm_withdrawal": Ignore,
        "card_failed_verification": Ignore,
        # Old-name card-related orders
        "benefits_spare_change_execution": RoundUp,
        "benefits_saveback_execution": SaveBack,
        # --- New-name payments (post-2025 TR renames) ---
        "BANK_TRANSACTION_INCOMING": PaymentInbound,
        "BANK_TRANSACTION_OUTGOING": PaymentOutbound,
        "BANK_TRANSACTION_OUTGOING_SCHEDULED": Ignore,
        "BANK_TRANSACTION_OUTGOING_DIRECT_DEBIT": PaymentOutbound,
        "SSP_CORPORATE_ACTION_CASH": NewStyleDividend,
        "SSP_CORPORATE_ACTION_ACTIVITY": Ignore,
        "SSP_CORPORATE_ACTION_NO_CASH": Ignore,
        "SSP_CORPORATE_ACTION_INFORMATIVE": Ignore,
        # New-name card
        "CARD_TRANSACTION": CardPayment,
        "CARD_AFT": CardPayment,  # final settlement of a card charge
        "CARD_VERIFICATION": Ignore,  # pre-auth check, no money movement
        "CARD_REFUND": NewStyleCardRefund,
        # --- Account / admin ---
        "PUK_CREATED": Ignore,
        "CUSTOMER_CREATED": Ignore,
        "SECURITIES_ACCOUNT_CREATED": Ignore,
        "DOCUMENTS_CREATED": Ignore,
        "DOCUMENTS_ACCEPTED": Ignore,
        "DOCUMENTS_CHANGED": Ignore,
        "DEVICE_RESET": Ignore,
        "PIN_RESET": Ignore,
        "EMAIL_VALIDATED": Ignore,
        "INPAYMENTS_SEPA_MANDATE_CREATED": Ignore,
        "QUARTERLY_REPORT": Ignore,
        "GESH_CORPORATE_ACTION": Ignore,
        "GENERAL_MEETING": Ignore,
        "SHAREBOOKING": Ignore,
        "SHAREBOOKING_CANCELED": Ignore,
        "CRYPTO_TNC_UPDATE_2025": Ignore,
        "new_tr_iban": Ignore,
        "ssp_corporate_action_informative_notification": Ignore,
        "VERIFICATION_TRANSFER_ACCEPTED": Ignore,
        "MOBILE_CHANGED": Ignore,
        "STOCK_PERK_EXPIRED": Ignore,
        "AML_SOURCE_OF_WEALTH_RESPONSE_EXECUTED": Ignore,
        "MOBILE_RESET": Ignore,
        # --- Taxes ---
        "EXEMPTION_ORDER_CHANGED": Ignore,
        "EXEMPTION_ORDER_CHANGE_REQUESTED": Ignore,
        "TAX_REFUND": TaxRefund,
        "ssp_tax_correction_invoice": TaxRefund,
        "TAX_YEAR_END_REPORT": Ignore,
        "TAX_YEAR_END_REPORT_CREATED": Ignore,
        # --- Reports / other ---
        "EX_POST_COST_REPORT_CREATED": Ignore,
        "timeline_legacy_migrated_events": Ignore,
    }

    def convert(self, events: dict, payments_file: None | str | Path, orders_file: None | str | Path):
        processed = self.process(events)

        if payments_file:
            with open(payments_file, "w", encoding="utf-8") as fh:
                fh.write(Payment.csv_header())
                for p in processed:
                    if isinstance(p, Payment):
                        fh.write(p.csv())

        if orders_file:
            with open(orders_file, "w", encoding="utf-8") as fh:
                fh.write(Investment.csv_header())
                for p in processed:
                    if isinstance(p, Investment):
                        fh.write(p.csv())

    def process(self, events: dict):
        data = []
        for event in events:
            func = self.event_types.get(event["eventType"], Unknown)
            try:
                ev = func(event)
                if isinstance(ev, Unknown):
                    print(f"Unknown event type {event['eventType']}")
                if not isinstance(ev, Ignore):
                    data.append(ev)
            except (AttributeError, IndexError, KeyError, TypeError):
                print(f"Error while processing event type {event['eventType']}")
        return data


def main():
    import sys

    filename = sys.argv[1]
    with open(filename, "rt", encoding="utf-8") as fh:
        events = json.load(fh)
    basedir = Path(filename).parent
    Converter().convert(events, basedir / "payments.csv", basedir / "orders.csv")


if __name__ == "__main__":
    main()
