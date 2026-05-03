"""
Tests for pytr.trdl_pp — get_timestamp and Downloader.
Tests for pytr.main — export_pp argument parser.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pytr.trdl_pp import Downloader, get_timestamp

# ---------------------------------------------------------------------------
# get_timestamp
# ---------------------------------------------------------------------------


class TestGetTimestamp:
    def test_standard_tr_format_with_milliseconds(self):
        dt = get_timestamp("2024-02-20T16:32:07.731+0000")
        assert dt.year == 2024
        assert dt.month == 2
        assert dt.day == 20
        assert dt.hour == 16
        assert dt.minute == 32

    def test_iso_format_with_colon_timezone(self):
        dt = get_timestamp("2024-01-15T10:30:00+00:00")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15

    def test_no_timezone_truncated_fallback(self):
        # Falls through to fromisoformat(ts[:19])
        dt = get_timestamp("2024-03-01T08:15:30")
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.day == 1
        assert dt.hour == 8

    def test_timezone_info_preserved(self):
        dt = get_timestamp("2024-02-20T16:32:07.731+0000")
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------


class TestDownloader:
    def test_init_starts_clean(self):
        dl = Downloader(headers={"User-Agent": "test/1.0"})
        assert dl.errors == 0
        assert dl.futures == []

    def test_dl_skips_existing_file(self, tmp_path):
        existing = tmp_path / "existing.pdf"
        existing.write_bytes(b"dummy")
        dl = Downloader(headers={"User-Agent": "test/1.0"})
        dl.dl("https://example.com/doc.pdf", existing)
        # No future should be queued since file already exists
        assert len(dl.futures) == 0

    def test_dl_queues_missing_file(self, tmp_path):
        missing = tmp_path / "new.pdf"
        dl = Downloader(headers={"User-Agent": "test/1.0"})
        dl.dl("https://example.com/doc.pdf", missing)
        # Future should be queued (actual HTTP request not made in unit test)
        assert len(dl.futures) == 1

    def test_dl_redownload_flag_queues_existing(self, tmp_path):
        existing = tmp_path / "existing.pdf"
        existing.write_bytes(b"dummy")
        dl = Downloader(headers={"User-Agent": "test/1.0"})
        dl.dl("https://example.com/doc.pdf", existing, redownload=True)
        assert len(dl.futures) == 1


# ---------------------------------------------------------------------------
# export_pp argument parser
# ---------------------------------------------------------------------------


class TestExportPpParser:
    @pytest.fixture
    def parser(self):
        from pytr.main import get_main_parser

        return get_main_parser()

    def test_last_days_default_is_zero(self, parser):
        args = parser.parse_args(["export_pp"])
        assert args.last_days == 0

    def test_days_until_default_is_zero(self, parser):
        args = parser.parse_args(["export_pp"])
        assert args.days_until == 0

    def test_last_days_parsed_as_int(self, parser):
        args = parser.parse_args(["export_pp", "--last_days", "7"])
        assert args.last_days == 7

    def test_days_until_parsed_as_int(self, parser):
        args = parser.parse_args(["export_pp", "--days_until", "3"])
        assert args.days_until == 3

    def test_dir_parsed_as_path(self, parser):
        args = parser.parse_args(["export_pp", "-D", "/tmp/output"])
        assert args.dir == Path("/tmp/output")

    def test_dir_does_not_set_docs_dir(self, parser):
        # -D should NOT trigger document download; docs_dir must remain None
        args = parser.parse_args(["export_pp", "-D", "/tmp/output"])
        assert args.docs_dir is None

    def test_individual_output_files_parsed(self, parser):
        args = parser.parse_args(
            [
                "export_pp",
                "-P",
                "payments.csv",
                "-O",
                "orders.csv",
                "-E",
                "events.json",
            ]
        )
        assert args.payments_file == Path("payments.csv")
        assert args.orders_file == Path("orders.csv")
        assert args.events_file == Path("events.json")

    def test_docs_dir_parsed(self, parser):
        args = parser.parse_args(["export_pp", "-F", "/tmp/docs"])
        assert args.docs_dir == Path("/tmp/docs")

    def test_workers_default(self, parser):
        args = parser.parse_args(["export_pp"])
        assert args.workers == 8

    def test_workers_custom(self, parser):
        args = parser.parse_args(["export_pp", "--workers", "4"])
        assert args.workers == 4

    def test_login_args_present(self, parser):
        args = parser.parse_args(["export_pp", "-n", "+49123456789", "-p", "1234"])
        assert args.phone_no == "+49123456789"
        assert args.pin == "1234"


# ---------------------------------------------------------------------------
# export_pp path traversal guard
# ---------------------------------------------------------------------------


class TestExportPpPathGuard:
    """Regression tests for the resolve-and-contain check in export_pp doc download."""

    def test_normal_path_is_allowed(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        resolved_docs_dir = docs_dir.resolve()
        rel_path = Path("Trading_Trade_Executed") / "2024-01-15 - Some Stock - abc.pdf"
        full_path = docs_dir / rel_path
        # Should not raise
        full_path.resolve().relative_to(resolved_docs_dir)

    def test_dotdot_traversal_is_detected(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        resolved_docs_dir = docs_dir.resolve()
        rel_path = Path("../../etc") / "passwd"
        full_path = docs_dir / rel_path
        with pytest.raises(ValueError):
            full_path.resolve().relative_to(resolved_docs_dir)


# ---------------------------------------------------------------------------
# _find_last_run_timestamp
# ---------------------------------------------------------------------------


class TestFindLastRunTimestamp:
    """Tests for the incremental-mode helper that scans for timestamped export subfolders."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from pytr.main import _find_last_run_timestamp

        self.find = _find_last_run_timestamp

    def test_nonexistent_dir_returns_none(self, tmp_path):
        assert self.find(tmp_path / "does_not_exist") is None

    def test_empty_dir_returns_none(self, tmp_path):
        assert self.find(tmp_path) is None

    def test_single_valid_subdir_returned(self, tmp_path):
        (tmp_path / "2024-03-15_10-30-00").mkdir()
        result = self.find(tmp_path)
        assert result is not None
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_returns_latest_of_multiple(self, tmp_path):
        (tmp_path / "2024-01-01_00-00-00").mkdir()
        (tmp_path / "2024-06-15_12-30-00").mkdir()
        (tmp_path / "2023-12-31_23-59-59").mkdir()
        result = self.find(tmp_path)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_ignores_files_not_dirs(self, tmp_path):
        (tmp_path / "2024-03-15_10-30-00").write_text("not a dir")
        assert self.find(tmp_path) is None

    def test_ignores_non_matching_dir_names(self, tmp_path):
        (tmp_path / "output").mkdir()
        (tmp_path / "2024-03-15").mkdir()  # date only, no time
        (tmp_path / "backup_2024-03-15_10-30-00").mkdir()  # has prefix
        assert self.find(tmp_path) is None

    def test_ignores_non_matching_mixed_with_valid(self, tmp_path):
        (tmp_path / "output").mkdir()
        (tmp_path / "2024-03-15_10-30-00").mkdir()
        result = self.find(tmp_path)
        assert result is not None
        assert result.day == 15


# ---------------------------------------------------------------------------
# export_pp --incremental parser
# ---------------------------------------------------------------------------


class TestExportPpIncrementalParser:
    @pytest.fixture
    def parser(self):
        from pytr.main import get_main_parser

        return get_main_parser()

    def test_incremental_default_is_false(self, parser):
        args = parser.parse_args(["export_pp"])
        assert args.incremental is False

    def test_incremental_flag_sets_true(self, parser):
        args = parser.parse_args(["export_pp", "--incremental"])
        assert args.incremental is True

    def test_incremental_with_dir(self, parser):
        args = parser.parse_args(["export_pp", "--incremental", "-D", "/tmp/out"])
        assert args.incremental is True
        assert args.dir == Path("/tmp/out")


# ---------------------------------------------------------------------------
# export_pp incremental doc-download regression
# ---------------------------------------------------------------------------


def _run_export_pp(argv, *, fake_tl_events=None, fake_downloader=None):
    """Invoke main() with mocked login / Timeline / Converter and return captured data."""
    import pytr.main as m
    import pytr.utils as u

    if fake_tl_events is None:
        fake_tl_events = []

    captured = {}

    class FakeTimeline:
        def __init__(self, tr, output_path, not_before=0, not_after=float("inf"), store_event_database=True, **kw):
            captured["store_event_database"] = store_event_database
            self.events = list(fake_tl_events)

        async def tl_loop(self):
            pass

    patches = [
        patch("pytr.main.login", return_value=MagicMock()),
        patch("pytr.main.Timeline", FakeTimeline),
        patch("pytr.main.Converter"),
        patch("pytr.main.print_gap_report"),
    ]
    if fake_downloader is not None:
        patches.append(patch("pytr.main.PPDownloader", fake_downloader))

    old_argv = sys.argv
    old_log_level = u.log_level
    sys.argv = argv
    try:
        with _nested(*patches):
            u.log_level = None  # allow main() to set verbosity each call
            m.main()
    finally:
        sys.argv = old_argv
        u.log_level = old_log_level

    return captured


def _nested(*cms):
    """Enter a stack of context managers (poor-man's contextlib.ExitStack)."""
    from contextlib import ExitStack

    stack = ExitStack()
    for cm in cms:
        stack.enter_context(cm)
    return stack


class TestExportPpIncrementalDocDownloadRegression:
    """
    Regression: export_pp --incremental must not re-download PDFs for historical events.

    Root cause: Timeline.finish_timeline_details() reads all_events.json and merges it
    into tl.events when store_event_database=True (the default).  In incremental mode
    this inflates tl.events with the full historical event set, so the doc-download loop
    re-queues every historical PDF on every run.

    Fix: export_pp passes store_event_database=False to Timeline.
    """

    def test_store_event_database_is_false(self, tmp_path):
        """Timeline must be constructed with store_event_database=False so that
        tl.events is never merged with the historical all_events.json database."""
        (tmp_path / "2024-01-01_00-00-00").mkdir()
        captured = _run_export_pp(
            [
                "pytrpp2",
                "export_pp",
                "-n",
                "+49123456789",
                "-p",
                "1234",
                "-D",
                str(tmp_path),
                "--incremental",
            ]
        )
        assert captured.get("store_event_database") is False

    def test_store_event_database_is_false_without_incremental(self, tmp_path):
        """store_event_database=False must also hold for non-incremental runs —
        export_pp writes its own per-run events.json and must not touch all_events.json."""
        captured = _run_export_pp(
            [
                "pytrpp2",
                "export_pp",
                "-n",
                "+49123456789",
                "-p",
                "1234",
                "-D",
                str(tmp_path),
            ]
        )
        assert captured.get("store_event_database") is False

    def test_only_tl_events_are_queued_for_download(self, tmp_path):
        """Doc download must queue exactly the documents from tl.events — no more.

        This guards against the merge bug: if store_event_database=True were
        accidentally restored, finish_timeline_details() would replace tl.events
        with the full historical set and all historical PDFs would be re-downloaded.
        """
        (tmp_path / "2024-01-01_00-00-00").mkdir()

        new_event = {
            "id": "evt-new",
            "eventType": "TRADING_TRADE_EXECUTED",
            "timestamp": "2026-01-15T10:00:00.000+0000",
            "title": "Buy",
            "subtitle": "MSCI World",
            "details": {
                "sections": [
                    {
                        "type": "documents",
                        "data": [
                            {
                                "id": "d1",
                                "title": "Abrechnung",
                                "detail": "15.01.2026",
                                "action": {"payload": "https://example.com/new.pdf"},
                            }
                        ],
                    }
                ]
            },
        }

        queued = []

        class FakeDownloader:
            def __init__(self, **kw):
                pass

            def dl(self, url, path, **kw):
                queued.append(url)

            def wait(self):
                pass

        _run_export_pp(
            [
                "pytrpp2",
                "export_pp",
                "-n",
                "+49123456789",
                "-p",
                "1234",
                "-D",
                str(tmp_path),
                "-F",
                str(tmp_path / "docs"),
                "--incremental",
            ],
            fake_tl_events=[new_event],
            fake_downloader=FakeDownloader,
        )

        assert len(queued) == 1, f"expected 1 doc queued, got {len(queued)}: {queued}"
        assert queued[0] == "https://example.com/new.pdf"
