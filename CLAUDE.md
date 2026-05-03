# pytrpp2

Fork of [`pytr`](https://github.com/pytr-org/pytr) with added Portfolio Performance export functionality, packaged as `pytrpp2` on PyPI.

- **Python package name:** `pytr` (internal module, inherited from upstream)
- **CLI entry point:** `pytrpp2`
- **PyPI name:** `pytrpp2`

---

## Upstream sync policy

pytrpp2 is an **independent fork**. All PP-specific functionality lives exclusively in `*_pp.py` files. This separation means upstream changes can be pulled cleanly without touching pytrpp2-specific code.

**When merging from `upstream/master` (pytr-org/pytr):**

- **Take upstream changes as-is** for core pytr files: `api.py`, `alarms.py`, `details.py`, `dl.py`, `event.py`, `portfolio.py`, `timeline.py`, `parsing.py`, and any other non-`_pp` module.
- **Always keep pytrpp2 versions** of: `pyproject.toml` (name, version, description, scripts, URLs), `.github/workflows/`, `CLAUDE.md`, `README.md`. These are pytrpp2-owned and must never be overwritten by upstream.
- **`main.py` is a hybrid**: take upstream structural changes, but always preserve the `export_pp` and `check_mappings` subcommands added by this fork.
- **`*_pp.py` files** are never present in upstream — no merge conflict possible, no action needed.

---

## Module layout

| File | Origin | Purpose |
|---|---|---|
| `pytr/api.py`, `timeline.py`, `dl.py`, etc. | upstream pytr | Core TR API — do not modify unless necessary |
| `pytr/conv_pp.py` | ported from pytrpp | TR event → Portfolio Performance CSV conversion |
| `pytr/trdl_pp.py` | ported from pytrpp | `get_timestamp`, `Downloader` |
| `pytr/check_mappings_pp.py` | new | Audit events for unmapped TR event types |
| `pytr/main.py` | upstream + additions | Added `export_pp`, `check_mappings` subcommands |

PP-specific additions use the `_pp` filename suffix.

---

## MANDATORY: Testing

Every new feature and every bug fix requires a test in `tests/`.

| Change type | Test file |
|---|---|
| PP conversion (new event type, parsing) | `test_conv_pp.py` |
| `export_pp` CLI argument or behaviour | `test_trdl_pp.py` |
| `Downloader`, `get_timestamp`, utilities | `test_trdl_pp.py` |
| Mapping gap checker | `test_check_mappings_pp.py` |
| Upstream module change | `test_<module>.py` |
| Bug fix | regression test that would have caught the bug |

Run the suite from this directory:

```sh
.venv/Scripts/python.exe -m pytest tests/ -v
# or
uv run pytest
```

A pre-commit hook runs the full suite automatically before every commit.

---

## Release

1. Bump `version` in `pyproject.toml`
2. Commit and push to `main`
3. `git tag vX.Y.Z && git push origin vX.Y.Z`

CI runs tests across Python 3.10–3.13, then publishes to PyPI and creates a GitHub Release automatically. See `dev_readme.md` for the full release checklist and PyPI Trusted Publisher setup.
