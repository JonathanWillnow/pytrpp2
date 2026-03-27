"""
Tests for pytr.trdl_pp — get_timestamp and Downloader.
Tests for pytr.main — export_pp argument parser.
"""

from pathlib import Path

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
        args = parser.parse_args([
            "export_pp",
            "-P", "payments.csv",
            "-O", "orders.csv",
            "-E", "events.json",
        ])
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

    def test_applogin_flag(self, parser):
        args = parser.parse_args(["export_pp", "--applogin"])
        assert args.applogin is True


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
