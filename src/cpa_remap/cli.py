from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from . import engine, parsers


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _load_timing_report(filename: str, report_format: str):
    if report_format == "opensta":
        return parsers.parse_rpt(filename)
    if report_format == "tempus":
        return parsers.parse_rpt_new(filename)

    sample = Path(filename).read_text(errors="ignore")[:8192]
    if re.search(r"Path\s+\d+:\s+VIOLATED", sample):
        return parsers.parse_rpt_new(filename)
    return parsers.parse_rpt(filename)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpa-remap",
        description="Run critical-path-based physically aware remapping on a post-layout netlist.",
    )
    parser.add_argument("--top-module", required=True, help="Top module name in the input netlist.")
    parser.add_argument("--netlist", required=True, help="Post-layout Verilog netlist.")
    parser.add_argument("--def-file", required=True, help="DEF file containing placed instance locations.")
    parser.add_argument("--timing-report", required=True, help="Register-to-register violated timing report.")
    parser.add_argument("--lib", dest="libs", action="append", required=True, help="Liberty file. Repeat for multiple libraries.")
    parser.add_argument("--design-name", default=None, help="Name used for the output subdirectory. Defaults to --top-module.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for generated cones, reports, and rewritten netlist.")
    parser.add_argument("--abc-bin", default=os.environ.get("CPA_REMAP_ABC", "abc"), help="ABC executable path.")
    parser.add_argument("--sta-bin", default=os.environ.get("CPA_REMAP_STA", "sta"), help="OpenSTA executable path.")
    parser.add_argument("--paths-per-group", type=_positive_int, default=1_000_000_000, help="Critical paths processed together per batch.")
    parser.add_argument("--distance-threshold", type=int, default=40, help="Cell-distance threshold in microns for cone construction.")
    parser.add_argument("--relax", type=int, default=0, help="Allowed timing degradation percentage for non-critical subpaths.")
    parser.add_argument("--report-format", choices=("auto", "opensta", "tempus"), default="auto", help="Timing report parser to use.")
    parser.add_argument("--count-new-gates", action="store_true", help="Count new gate usage in accepted remapped cones.")
    parser.add_argument("--rewrite-debug-num", type=int, default=-1, help="Limit rewritten cones for debugging; -1 rewrites all.")
    parser.add_argument("--dry-run", action="store_true", help="Parse inputs and print a summary without launching ABC/OpenSTA.")
    return parser


def run(args: argparse.Namespace) -> int:
    design_name = args.design_name or args.top_module

    cell_to_cell = parsers.parse_lib(args.libs)
    path_id_to_path = _load_timing_report(args.timing_report, args.report_format)
    inst_to_location = parsers.parse_def(args.def_file)
    inst_to_node, module_to_module = parsers.parse_verilog(
        args.top_module,
        args.netlist,
        inst_to_location,
        cell_to_cell,
    )

    if args.dry_run:
        print(f"design: {design_name}")
        print(f"libraries: {len(args.libs)}")
        print(f"cells: {len(cell_to_cell)}")
        print(f"violated paths: {len(path_id_to_path)}")
        print(f"placed instances: {len(inst_to_location)}")
        print(f"parsed instances: {len(inst_to_node)}")
        print(f"modules: {len(module_to_module)}")
        return 0

    cone_id_to_cone = engine.main_remap(
        design_name,
        args.paths_per_group,
        args.distance_threshold,
        path_id_to_path,
        inst_to_node,
        cell_to_cell,
        args.libs,
        args.count_new_gates,
        args.relax,
        output_dir=args.output_dir,
        abc_executable=args.abc_bin,
        sta_executable=args.sta_bin,
    )
    engine.main_rewrite(
        module_to_module,
        cone_id_to_cone,
        inst_to_node,
        args.def_file,
        design_name,
        debug_num=args.rewrite_debug_num,
        output_dir=args.output_dir,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
