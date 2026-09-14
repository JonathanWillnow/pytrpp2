"""Tests for pytr/check_mappings_pp.py and the check_mappings subcommand."""

import json
from pathlib import Path

import pytest

from pytr.check_mappings_pp import find_gaps, print_gap_report
from pytr.conv_pp import Converter

EVENTS_DIR = Path(__file__).parent / "events"


def load_event(name: str) -> dict:
    return json.loads((EVENTS_DIR / name).read_text(encoding="utf-8"))


def unknown_event(event_type="BRAND_NEW_TR_EVENT", **overrides) -> dict:
    event = {
        "id": "id-1",
        "timestamp": "2026-08-01T10:00:00.000+0000",
        "title": "Hypoport",
        "subtitle": "Etwas Neues",
        "eventType": event_type,
    }
    event.update(overrides)
    return event


# ---------------------------------------------------------------------------
# find_gaps
# ---------------------------------------------------------------------------


class TestFindGaps:
    def test_converted_event_is_not_a_gap(self):
        assert find_gaps([load_event("buy.json")]) == {}

    def test_ignored_event_is_not_a_gap(self):
        assert find_gaps([load_event("address_changed.json")]) == {}

    def test_unknown_type_is_a_gap(self):
        assert find_gaps([unknown_event(), unknown_event(id="id-2")]) == {"BRAND_NEW_TR_EVENT": 2}

    def test_unknown_event_without_event_type_is_keyed_by_subtitle(self):
        event = unknown_event()
        del event["eventType"]
        assert find_gaps([event]) == {"<missing>: Etwas Neues": 1}

    def test_classifiable_event_without_event_type_is_not_a_gap(self):
        assert find_gaps([load_event("buy_new_no_eventType.json")]) == {}

    def test_malformed_event_is_a_gap(self):
        assert find_gaps([{}]) == {"<missing>": 1}

    def test_empty_events(self):
        assert find_gaps([]) == {}

    def test_no_gaps_in_any_fixture(self):
        events = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(EVENTS_DIR.glob("*.json"))]
        assert find_gaps(events) == {}


# ---------------------------------------------------------------------------
# print_gap_report
# ---------------------------------------------------------------------------


class TestPrintGapReport:
    def test_no_gaps_prints_ok(self, capsys):
        print_gap_report([load_event("buy.json")])
        out = capsys.readouterr().out
        assert "OK" in out
        assert "WARNING" not in out

    def test_gap_prints_warning_with_event_details(self, capsys):
        print_gap_report([unknown_event()])
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "BRAND_NEW_TR_EVENT" in out
        assert "2026-08-01 Hypoport -- Etwas Neues" in out

    def test_error_prints_exception(self, capsys):
        print_gap_report([{"id": "broken"}])
        out = capsys.readouterr().out
        assert "Failed to convert" in out
        assert "KeyError" in out

    def test_audit_counts(self, capsys):
        events = [
            load_event("buy.json"),
            load_event("bardividende.json"),
            load_event("address_changed.json"),
            unknown_event(),
        ]
        print_gap_report(events)
        out = capsys.readouterr().out
        assert "Events                    : 4" in out
        assert "Converted                 : 2  (1 order rows, 1 payment rows)" in out
        assert "Ignored (non-financial)   : 1" in out
        assert "Unknown                   : 1" in out

    def test_ignored_types_printed(self, capsys):
        print_gap_report([load_event("address_changed.json")])
        assert "ADDRESS_CHANGED" in capsys.readouterr().out

    def test_empty_events_prints_ok(self, capsys):
        print_gap_report([])
        assert "OK" in capsys.readouterr().out

    def test_uses_given_report_without_reconverting(self, capsys, monkeypatch):
        events = [unknown_event()]
        _, report = Converter().process(events)

        def fail(*a, **kw):
            raise AssertionError("events converted twice")

        monkeypatch.setattr(Converter, "process", fail)
        print_gap_report(events, report)
        assert "BRAND_NEW_TR_EVENT" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# check_mappings subcommand
# ---------------------------------------------------------------------------


class TestCheckMappingsCommand:
    @pytest.fixture
    def run(self, monkeypatch):
        import sys

        import pytr.main as m
        import pytr.utils as u

        def _run(events_file):
            monkeypatch.setattr(sys, "argv", ["pytrpp2", "check_mappings", str(events_file)])
            monkeypatch.setattr(u, "log_level", None)
            m.main()

        return _run

    def test_subcommand_parses_events_file(self):
        from pytr.main import get_main_parser

        args = get_main_parser().parse_args(["check_mappings", "events.json"])
        assert args.command == "check_mappings"
        assert args.events_file == Path("events.json")

    def test_reports_ok_for_converted_events(self, tmp_path, capsys, run):
        ef = tmp_path / "events.json"
        ef.write_text(json.dumps([load_event("buy_new_no_eventType.json")]), encoding="utf-8")
        run(ef)
        assert "OK" in capsys.readouterr().out

    def test_reports_gap_for_unknown_event(self, tmp_path, capsys, run):
        ef = tmp_path / "events.json"
        ef.write_text(json.dumps([unknown_event(), unknown_event(id="id-2")]), encoding="utf-8")
        run(ef)
        out = capsys.readouterr().out
        assert "BRAND_NEW_TR_EVENT" in out
        assert "WARNING" in out
