"""
check_mappings_pp.py — find TR events that export_pp cannot convert.

Runs the same conversion as export_pp and reports every event that did not end up in
orders.csv / payments.csv although it may carry financial data:

- unknown: upstream pytr could not classify the event
- error:   classification or parsing raised an exception

Known non-financial events (address changes, cancelled orders, ...) are listed separately
and are not gaps.

Can be used:
  - As a standalone subcommand: ``pytrpp2 check_mappings events.json``
  - Inline after export_pp conversion via ``print_gap_report(events, report)``
"""

from __future__ import annotations

from pytr.conv_pp import ConversionReport, Converter, Issue


def _count_by_key(issues: list[Issue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.key] = counts.get(issue.key, 0) + 1
    return counts


def find_gaps(events: list[dict]) -> dict[str, int]:
    """Return {event_key: count} for events that are missing from the CSVs (unknown or failed)."""
    _, report = Converter().process(events)
    return _count_by_key(report.gaps)


def print_gap_report(events: list[dict], report: ConversionReport | None = None) -> None:
    """Print the conversion audit and every gap to stdout.

    Pass the report returned by Converter.convert() to avoid converting the events twice.
    """
    if report is None:
        _, report = Converter().process(events)

    print()
    print("  Event audit:")
    print(f"    Events                    : {report.total}")
    print(
        f"    Converted                 : {report.converted}  ({report.orders} order rows, {report.payments} payment rows)"
    )
    print(f"    Ignored (non-financial)   : {sum(report.ignored.values())}")
    print(f"    Unknown                   : {len(report.unknown)}")
    print(f"    Errors                    : {len(report.errors)}")

    if report.gaps:
        print()
        print("=" * 70)
        print("WARNING: events missing from the CSVs — transactions may be missing in PP.")
        print("  Check these in the TR app and book them manually if needed; please also")
        print("  report them so the parser can be extended.")
        for label, issues in (("Unknown event", report.unknown), ("Failed to convert", report.errors)):
            for issue in issues:
                print(f"  {label}: [{issue.key}] {issue.event}" + (f"\n      {issue.detail}" if issue.detail else ""))
        print("=" * 70)
    else:
        print("  Mapping gap check: OK — every event was converted or is known to be non-financial.")

    if report.warnings:
        print()
        print("  Converted with parser warnings (verify these rows):")
        for issue in report.warnings:
            print(f"    [{issue.key}] {issue.event}: {issue.detail}")

    if report.ignored:
        print()
        print("  Intentionally ignored (no financial data expected):")
        for key, count in sorted(report.ignored.items(), key=lambda x: -x[1]):
            print(f"    {key:<45}  {count:>6}x")
