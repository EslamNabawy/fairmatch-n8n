from pathlib import Path

from parity import render_report, run_suite


def main() -> int:
    results = run_suite()
    report = render_report(results)
    report_path = Path(__file__).resolve().parent / "PARITY_REPORT.txt"
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    print(f"Saved report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
