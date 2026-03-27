"""Tests for pytr/classify_pp.py and the build_classification subcommand parser."""

import json
from pathlib import Path

from pytr.classify_pp import (
    DEFAULT_CONFIG_PATH,
    SECURITY_EVENT_TYPES,
    _extract_isin,
    build,
    collect_isins,
    load_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_new_event(event_type: str, isin: str, title: str = "Test Security") -> dict:
    """Minimal new-style TR event with ISIN in header section."""
    return {
        "eventType": event_type,
        "title": title,
        "icon": f"logos/{isin}/v2",
        "details": {
            "sections": [
                {
                    "type": "header",
                    "action": {
                        "type": "instrumentDetail",
                        "payload": isin,
                    },
                }
            ]
        },
    }


def _make_old_event(event_type: str, isin: str, title: str = "Old Security") -> dict:
    """Minimal old-style TR event with ISIN in icon path."""
    return {
        "eventType": event_type,
        "title": title,
        "icon": f"logos/{isin}/v2",
        "details": {"sections": []},
    }


# ---------------------------------------------------------------------------
# _extract_isin
# ---------------------------------------------------------------------------


class TestExtractIsin:
    def test_new_style_header_section(self):
        event = _make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983")
        assert _extract_isin(event) == "IE00B4L5Y983"

    def test_old_style_icon_fallback(self):
        event = _make_old_event("ORDER_EXECUTED", "IE00B3WJKG14")
        assert _extract_isin(event) == "IE00B3WJKG14"

    def test_prefers_header_over_icon(self):
        # header has one ISIN, icon has another — header wins
        event = _make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983")
        event["icon"] = "logos/IE00B3WJKG14/v2"
        assert _extract_isin(event) == "IE00B4L5Y983"

    def test_no_isin_returns_empty(self):
        event = {"eventType": "TRADING_TRADE_EXECUTED", "title": "X", "details": {"sections": []}}
        assert _extract_isin(event) == ""

    def test_invalid_icon_returns_empty(self):
        event = {"eventType": "ORDER_EXECUTED", "icon": "logos/not-an-isin/v2", "details": {"sections": []}}
        assert _extract_isin(event) == ""

    def test_missing_details_key(self):
        event = {"eventType": "ORDER_EXECUTED", "icon": "logos/IE00B4L5Y983/v2"}
        assert _extract_isin(event) == "IE00B4L5Y983"

    def test_empty_event(self):
        assert _extract_isin({}) == ""


# ---------------------------------------------------------------------------
# collect_isins
# ---------------------------------------------------------------------------


class TestCollectIsins:
    def test_single_new_style_event(self):
        events = [_make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "iShares Core MSCI World")]
        result = collect_isins(events)
        assert result == {"IE00B4L5Y983": "iShares Core MSCI World"}

    def test_single_old_style_event(self):
        events = [_make_old_event("ORDER_EXECUTED", "IE00B3WJKG14", "iShares Core MSCI EM")]
        result = collect_isins(events)
        assert result == {"IE00B3WJKG14": "iShares Core MSCI EM"}

    def test_non_security_event_is_skipped(self):
        events = [{"eventType": "ACCOUNT_STATEMENT", "title": "Statement", "icon": "logos/IE00B4L5Y983/v2"}]
        result = collect_isins(events)
        assert result == {}

    def test_duplicate_isin_uses_first_title(self):
        events = [
            _make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "First Title"),
            _make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "Second Title"),
        ]
        result = collect_isins(events)
        assert result == {"IE00B4L5Y983": "First Title"}

    def test_multiple_isins(self):
        events = [
            _make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "World ETF"),
            _make_old_event("ORDER_EXECUTED", "IE00B3WJKG14", "EM ETF"),
        ]
        result = collect_isins(events)
        assert set(result.keys()) == {"IE00B4L5Y983", "IE00B3WJKG14"}

    def test_all_security_event_types_are_accepted(self):
        # Each event type in SECURITY_EVENT_TYPES should be collected
        isin = "IE00B4L5Y983"
        for et in SECURITY_EVENT_TYPES:
            events = [_make_new_event(et, isin, "Title")]
            result = collect_isins(events)
            assert isin in result, f"Event type {et!r} was not collected"

    def test_savings_plan_event(self):
        events = [_make_new_event("TRADING_SAVINGSPLAN_EXECUTED", "IE00B4L5Y983", "Savings ETF")]
        result = collect_isins(events)
        assert result == {"IE00B4L5Y983": "Savings ETF"}

    def test_empty_events_list(self):
        assert collect_isins([]) == {}


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_config(tmp_path / "nonexistent.json")
        assert result == {}

    def test_valid_config(self, tmp_path):
        config = {"classifications": {"IE00B4L5Y983": "RISKY", "DE0001030542": "CASH"}}
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(json.dumps(config), encoding="utf-8")
        result = load_config(cfg_file)
        assert result == {"IE00B4L5Y983": "RISKY", "DE0001030542": "CASH"}

    def test_unknown_key_defaults_to_risky(self, tmp_path, capsys):
        config = {"classifications": {"IE00B4L5Y983": "UNKNOWN_CAT"}}
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(json.dumps(config), encoding="utf-8")
        result = load_config(cfg_file)
        assert result == {"IE00B4L5Y983": "RISKY"}
        captured = capsys.readouterr()
        assert "RISKY" in captured.out

    def test_empty_classifications(self, tmp_path):
        config = {"classifications": {}}
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(json.dumps(config), encoding="utf-8")
        assert load_config(cfg_file) == {}

    def test_default_config_path_constant(self):
        assert DEFAULT_CONFIG_PATH == Path.home() / ".pytr" / "classifications_config.json"

    def test_none_falls_back_to_default_path(self, monkeypatch, tmp_path):
        # Monkeypatch DEFAULT_CONFIG_PATH to a temp path that doesn't exist
        import pytr.classify_pp as cp

        monkeypatch.setattr(cp, "DEFAULT_CONFIG_PATH", tmp_path / "no_config.json")
        result = cp.load_config(None)
        assert result == {}


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


class TestBuild:
    def _write_events(self, tmp_path, events):
        ef = tmp_path / "events.json"
        ef.write_text(json.dumps(events), encoding="utf-8")
        return ef

    def test_build_creates_output_file(self, tmp_path):
        events = [_make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "World ETF")]
        ef = self._write_events(tmp_path, events)
        out = tmp_path / "classification.json"
        build(ef, out)
        assert out.exists()

    def test_build_output_has_expected_structure(self, tmp_path):
        events = [_make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "World ETF")]
        ef = self._write_events(tmp_path, events)
        out = tmp_path / "classification.json"
        build(ef, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["name"] == "Asset Allocation"
        assert "categories" in data
        assert "instruments" in data

    def test_build_instrument_defaults_to_risky(self, tmp_path):
        events = [_make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "World ETF")]
        ef = self._write_events(tmp_path, events)
        out = tmp_path / "classification.json"
        build(ef, out, config_path=tmp_path / "no_config.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        inst = data["instruments"][0]
        assert inst["identifiers"]["isin"] == "IE00B4L5Y983"
        assert inst["categories"][0]["path"] == ["Risikobehafteter Portfolioteil"]
        assert inst["categories"][0]["weight"] == 100.0

    def test_build_instrument_uses_config_for_cash(self, tmp_path):
        events = [_make_new_event("TRADING_TRADE_EXECUTED", "DE0001030542", "Bond ETF")]
        ef = self._write_events(tmp_path, events)
        config = {"classifications": {"DE0001030542": "CASH"}}
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        out = tmp_path / "classification.json"
        build(ef, out, config_path=cfg)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["instruments"][0]["categories"][0]["path"] == ["Risikoarmer Anteil"]

    def test_build_instrument_name(self, tmp_path):
        events = [_make_new_event("ORDER_EXECUTED", "IE00B4L5Y983", "My ETF")]
        ef = self._write_events(tmp_path, events)
        out = tmp_path / "classification.json"
        build(ef, out, config_path=tmp_path / "no_config.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["instruments"][0]["identifiers"]["name"] == "My ETF"

    def test_build_instruments_sorted_by_isin(self, tmp_path):
        events = [
            _make_new_event("TRADING_TRADE_EXECUTED", "ZZ0000000001", "Z-ETF"),
            _make_new_event("TRADING_TRADE_EXECUTED", "AA0000000001", "A-ETF"),
        ]
        ef = self._write_events(tmp_path, events)
        out = tmp_path / "classification.json"
        build(ef, out, config_path=tmp_path / "no_config.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        isins = [i["identifiers"]["isin"] for i in data["instruments"]]
        assert isins == sorted(isins)

    def test_build_empty_events_produces_empty_instruments(self, tmp_path):
        ef = self._write_events(tmp_path, [])
        out = tmp_path / "classification.json"
        build(ef, out, config_path=tmp_path / "no_config.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["instruments"] == []

    def test_build_creates_parent_dirs(self, tmp_path):
        events = [_make_new_event("TRADING_TRADE_EXECUTED", "IE00B4L5Y983", "ETF")]
        ef = self._write_events(tmp_path, events)
        out = tmp_path / "subdir" / "deep" / "classification.json"
        build(ef, out, config_path=tmp_path / "no_config.json")
        assert out.exists()


# ---------------------------------------------------------------------------
# build_classification subcommand parser
# ---------------------------------------------------------------------------


class TestBuildClassificationParser:
    def _get_parser(self):
        from pytr.main import get_main_parser

        return get_main_parser()

    def test_subcommand_exists(self):
        parser = self._get_parser()
        args = parser.parse_args(["build_classification", "events.json", "out.json"])
        assert args.command == "build_classification"

    def test_events_file_arg(self):
        parser = self._get_parser()
        args = parser.parse_args(["build_classification", "events.json", "out.json"])
        assert args.events_file == Path("events.json")

    def test_output_file_arg(self):
        parser = self._get_parser()
        args = parser.parse_args(["build_classification", "events.json", "out.json"])
        assert args.output_file == Path("out.json")

    def test_config_defaults_to_none(self):
        parser = self._get_parser()
        args = parser.parse_args(["build_classification", "events.json", "out.json"])
        assert args.config_path is None

    def test_config_arg(self):
        parser = self._get_parser()
        args = parser.parse_args(["build_classification", "events.json", "out.json", "--config", "my_cfg.json"])
        assert args.config_path == Path("my_cfg.json")
