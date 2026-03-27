# pytrpp2

Fork of [`pytr`](https://github.com/pytr-org/pytr) with added Portfolio Performance export functionality, packaged as `pytrpp2` on PyPI.

- **Python package name:** `pytr` (internal module, inherited from upstream)
- **CLI entry point:** `pytrpp2`
- **PyPI name:** `pytrpp2`

---

## Module layout

| File | Origin | Purpose |
|---|---|---|
| `pytr/api.py`, `timeline.py`, `dl.py`, etc. | upstream pytr | Core TR API — do not modify unless necessary |
| `pytr/conv_pp.py` | ported from pytrpp | TR event → Portfolio Performance CSV conversion |
| `pytr/trdl_pp.py` | ported from pytrpp | `get_timestamp`, `Downloader` |
| `pytr/classify_pp.py` | new | Build PP classification taxonomy from events |
| `pytr/check_mappings_pp.py` | new | Audit events for unmapped TR event types |
| `pytr/main.py` | upstream + additions | Added `export_pp`, `build_classification`, `check_mappings` subcommands |

PP-specific additions use the `_pp` filename suffix.

---

## MANDATORY: Testing

Every new feature and every bug fix requires a test in `tests/`.

| Change type | Test file |
|---|---|
| PP conversion (new event type, parsing) | `test_conv_pp.py` |
| `export_pp` CLI argument or behaviour | `test_trdl_pp.py` |
| `Downloader`, `get_timestamp`, utilities | `test_trdl_pp.py` |
| Classification builder | `test_classify_pp.py` |
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
