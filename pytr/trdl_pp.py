"""
trdl_pp.py — Ported from pytrpp's trdl.py.

Contains:
- get_timestamp: parse TR ISO timestamp strings to datetime
- Downloader: simple parallel file downloader
"""

from concurrent.futures import Future, as_completed
from datetime import datetime
from pathlib import Path

from requests import session
from requests_futures.sessions import FuturesSession  # type: ignore[import-untyped]


def get_timestamp(ts: str) -> datetime:
    """Convert string timestamp to datetime object."""
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            return datetime.fromisoformat(ts[:19])


class Downloader:
    """Download multiple files asynchronously"""

    def __init__(self, headers: dict[str, str | bytes], max_workers=8):
        self.futures: list[Future] = []
        self.errors: int = 0
        requests_session = session()
        requests_session.headers = headers
        self.session = FuturesSession(max_workers=max_workers, session=requests_session)

    def dl(self, url: str, filepath: Path | str, redownload: bool = False):
        filepath = Path(filepath)
        if not filepath.exists() or redownload:
            future = self.session.get(url)
            future.filepath = filepath
            self.futures.append(future)

    def wait(self):
        for future in as_completed(self.futures):
            filepath: Path = future.filepath

            try:
                result = future.result()
            except Exception:
                self.errors += 1
            else:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_bytes(result.content)
