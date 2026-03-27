"""Tests for pytr/check_mappings_pp.py and the check_mappings subcommand."""

import json
from pathlib import Path

from pytr.check_mappings_pp import find_gaps, print_gap_report
from pytr.conv_pp import Converter, Ignore

# ---------------------------------------------------------------------------
# find_gaps
# ---------------------------------------------------------------------------


class TestFindGaps:
    def test_known_type_not_a_gap(self):
        # Pick a known type from Converter.event_types
        known_type = next(iter(Converter.event_types))
        events = [{"eventType": known_type}]
        assert find_gaps(events) == {}

    def test_unknown_type_is_a_gap(self):
        events = [{"eventType": "COMPLETELY_UNKNOWN_XYZ"}]
        gaps = find_gaps(events)
        assert "COMPLETELY_UNKNOWN_XYZ" in gaps
        assert gaps["COMPLETELY_UNKNOWN_XYZ"] == 1

    def test_gap_count_is_correct(self):
        events = [{"eventType": "MYSTERY_EVENT"}] * 5
        gaps = find_gaps(events)
        assert gaps["MYSTERY_EVENT"] == 5

    def test_ignore_type_is_not_a_gap(self):
        # Ignore types ARE in Converter.event_types, so they are not gaps
        ignore_type = next(k for k, v in Converter.event_types.items() if v is Ignore)
        events = [{"eventType": ignore_type}]
        assert find_gaps(events) == {}

    def test_mixed_events(self):
        known_type = next(k for k, v in Converter.event_types.items() if v is not Ignore)
        events = [
            {"eventType": known_type},
            {"eventType": "GAP_TYPE_1"},
            {"eventType": "GAP_TYPE_2"},
            {"eventType": "GAP_TYPE_1"},
        ]
        gaps = find_gaps(events)
        assert known_type not in gaps
        assert gaps["GAP_TYPE_1"] == 2
        assert gaps["GAP_TYPE_2"] == 1

    def test_missing_event_type_key(self):
        events = [{}]  # no 'eventType' key
        gaps = find_gaps(events)
        assert "<missing>" in gaps

    def test_empty_events(self):
        assert find_gaps([]) == {}

    def test_all_converter_types_are_not_gaps(self):
        events = [{"eventType": et} for et in Converter.event_types]
        assert find_gaps(events) == {}


# ---------------------------------------------------------------------------
# print_gap_report
# ---------------------------------------------------------------------------


class TestPrintGapReport:
    def test_no_gaps_prints_ok(self, capsys):
        known_type = next(iter(Converter.event_types))
        print_gap_report([{"eventType": known_type}])
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_gap_prints_warning(self, capsys):
        print_gap_report([{"eventType": "UNKNOWN_TYPE_XYZ"}])
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "UNKNOWN_TYPE_XYZ" in captured.out

    def test_ignored_types_printed(self, capsys):
        ignore_type = next(k for k, v in Converter.event_types.items() if v is Ignore)
        print_gap_report([{"eventType": ignore_type}])
        captured = capsys.readouterr()
        assert ignore_type in captured.out

    def test_empty_events_prints_ok(self, capsys):
        print_gap_report([])
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_registered_absent_section_printed(self, capsys):
        # Pass an empty list — all registered non-Ignore types will be "absent"
        print_gap_report([])
        captured = capsys.readouterr()
        assert "NOT seen" in captured.out or "Registered" in captured.out


# ---------------------------------------------------------------------------
# check_mappings subcommand parser
# ---------------------------------------------------------------------------


class TestCheckMappingsParser:
    def _get_parser(self):
        from pytr.main import get_main_parser

        return get_main_parser()

    def test_subcommand_exists(self):
        parser = self._get_parser()
        args = parser.parse_args(["check_mappings", "events.json"])
        assert args.command == "check_mappings"

    def test_events_file_arg(self):
        parser = self._get_parser()
        args = parser.parse_args(["check_mappings", "events.json"])
        assert args.events_file == Path("events.json")


# ---------------------------------------------------------------------------
# Integration: check_mappings subcommand end-to-end
# ---------------------------------------------------------------------------


class TestCheckMappingsIntegration:
    def test_runs_on_empty_events_file(self, tmp_path, capsys):
        ef = tmp_path / "events.json"
        ef.write_text(json.dumps([]), encoding="utf-8")

        import sys

        from pytr.main import get_main_parser

        old_argv = sys.argv
        sys.argv = ["pytrpp2", "check_mappings", str(ef)]
        try:
            parser = get_main_parser()
            args = parser.parse_args(["check_mappings", str(ef)])
            with open(args.events_file, encoding="utf-8") as fh:
                events = json.load(fh)
            print_gap_report(events)
            captured = capsys.readouterr()
            assert "OK" in captured.out
        finally:
            sys.argv = old_argv

    def test_reports_gap_for_unknown_event(self, tmp_path, capsys):
        events = [{"eventType": "BRAND_NEW_TR_EVENT"}, {"eventType": "BRAND_NEW_TR_EVENT"}]
        ef = tmp_path / "events.json"
        ef.write_text(json.dumps(events), encoding="utf-8")

        from pytr.main import get_main_parser

        args = get_main_parser().parse_args(["check_mappings", str(ef)])
        with open(args.events_file, encoding="utf-8") as fh:
            loaded = json.load(fh)
        print_gap_report(loaded)
        captured = capsys.readouterr()
        assert "BRAND_NEW_TR_EVENT" in captured.out
        assert "WARNING" in captured.out
