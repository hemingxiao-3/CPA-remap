from __future__ import annotations

import argparse
import re
from pathlib import Path


def extract_r2r_timing(input_report: Path, output_report: Path) -> tuple[float, float, int]:
    lines = input_report.read_text().splitlines(keepends=True)
    collecting_startpoint = False
    collecting_endpoint = False
    current_path: list[str] = []
    extracted_paths: list[list[str]] = []
    wns = 0.0
    tns = 0.0

    for line in lines:
        if line.startswith("Startpoint") and "edge-triggered flip-flop clocked by" in line:
            collecting_startpoint = True
            collecting_endpoint = False
            current_path = [line]
            continue

        if line.startswith("Endpoint") and "edge-triggered flip-flop clocked by" in line:
            collecting_endpoint = True
            current_path.append(line)
            continue

        if "VIOLATED" in line:
            if collecting_startpoint and collecting_endpoint:
                current_path.append(line)
                extracted_paths.append(current_path)
                slack_match = re.search(r"(-?\d+\.\d+)", line)
                if slack_match:
                    slack = float(slack_match.group(1))
                    wns = min(wns, slack)
                    tns += slack
            collecting_startpoint = False
            collecting_endpoint = False
            current_path = []
            continue

        if collecting_startpoint and collecting_endpoint:
            current_path.append(line)

    with output_report.open("w") as handle:
        for path in extracted_paths:
            handle.writelines(path)
            handle.write("\n\n\n")

    return wns, tns, len(extracted_paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract violated register-to-register timing paths from an OpenSTA report.")
    parser.add_argument("input_report", type=Path)
    parser.add_argument("output_report", type=Path)
    args = parser.parse_args()

    wns, tns, path_count = extract_r2r_timing(args.input_report, args.output_report)
    print(f"wns: {wns}")
    print(f"tns: {tns}")
    print(f"path_count: {path_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
