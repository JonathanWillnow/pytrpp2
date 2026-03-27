"""
check_mappings_pp.py — TR event-type gap detector for Portfolio Performance export.

Compares the event types seen in a raw events JSON against the event types
registered in conv_pp.Converter.event_types.  Any type that appears in the data
but is NOT in the mapping is a gap: those transactions are silently dropped from
orders.csv / payments.csv.

Can be used:
  - As a standalone subcommand: ``pytrpp2 check_mappings events.json``
  - Inline after export_pp conversion via ``print_gap_report(events)``
"""

from __future__ import annotations

from pytr.conv_pp import Converter, Ignore


def _known_types() -> set[str]:
    return set(Converter.event_types.keys())


def _ignore_types() -> set[str]:
    return {k for k, v in Converter.event_types.items() if v is Ignore}


def find_gaps(events: list[dict]) -> dict[str, int]:
    """Return {event_type: count} for types that appear in events but have no handler.

    A 'gap' means the event type is not in Converter.event_types at all — these
    events are silently dropped by the converter.
    """
    known = _known_types()
    seen: dict[str, int] = {}
    for event in events:
        et = event.get("eventType") or "<missing>"
        seen[et] = seen.get(et, 0) + 1
    return {et: count for et, count in seen.items() if et not in known}


def print_gap_report(events: list[dict]) -> None:
    """Print a full gap analysis to stdout.

    Prints three sections:
    - GAP: types in data with no handler (silently dropped)
    - Intentionally ignored types (Ignore handler, expected)
    - Registered non-Ignore types not seen in this data
    """
    known = _known_types()
    ignore = _ignore_types()

    seen: dict[str, int] = {}
    for event in events:
        et = event.get("eventType") or "<missing>"
        seen[et] = seen.get(et, 0) + 1

    gaps = {et: count for et, count in seen.items() if et not in known}
    ignored_in_data = {et: count for et, count in seen.items() if et in ignore}
    registered_absent = (known - ignore) - set(seen.keys())

    if gaps:
        print()
        print("=" * 70)
        print("WARNING: unmapped event types found — transactions may be missing.")
        print("  These event types appear in your TR data but have no handler in")
        print("  Converter.event_types and were silently dropped from the CSVs.")
        print("  Add them to conv_pp.py to fix the gap.")
        print()
        print(f"  {'Event type':<45}  {'Count':>6}")
        print(f"  {'-' * 45}  {'-' * 6}")
        for et, count in sorted(gaps.items(), key=lambda x: -x[1]):
            print(f"  {et:<45}  {count:>6}")
        print("=" * 70)
    else:
        print("  Mapping gap check: OK — all event types are covered.")

    if ignored_in_data:
        print()
        print("  Intentionally ignored (no financial data expected):")
        for et, count in sorted(ignored_in_data.items(), key=lambda x: -x[1]):
            print(f"    {et:<45}  {count:>6}x")

    if registered_absent:
        print()
        print("  Registered handlers NOT seen in this export:")
        print("    (bond/transfer types you may not have had, or old TR names)")
        for et in sorted(registered_absent):
            print(f"    {et}")
