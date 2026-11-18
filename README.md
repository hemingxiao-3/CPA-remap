# CPA-remap

CPA-remap is a critical-path-based physically aware remapping framework for post-layout timing optimization. It extracts violated critical paths and placed-cell locations, builds proximity-aware logic cones, remaps each cone with timing constraints, and rewrites accepted cones back into the netlist.

This repository contains the open-source tool code and a small `gcd` post-layout example. Large historical experiment data is intentionally kept out of git under `_archive/legacy/`.

## Repository Layout

```text
src/cpa_remap/        Core Python package
scripts/              Utility scripts
examples/gcd/         Small post-layout example input
docs/                 Notes and paper summary
```

## Requirements

- Python 3.10+
- ABC executable available as `abc` or passed with `--abc-bin`
- OpenSTA executable available as `sta` or passed with `--sta-bin`
- A Liberty file for the target standard-cell library, passed with `--lib`

The example netlist uses Nangate45 cell names. The Nangate45 liberty file is not bundled because its file header describes separate license restrictions; provide your own local copy when running the example.

## Install

```bash
python -m pip install -e .
```

## Smoke Test The Example Inputs

`--dry-run` parses the Liberty, timing report, DEF, and netlist without invoking ABC or OpenSTA:

```bash
cpa-remap \
  --top-module gcd \
  --netlist examples/gcd/gcd_nangate45-tcl.v \
  --def-file examples/gcd/gcd_nangate45-tcl.def \
  --timing-report examples/gcd/r2r_timing.rpt \
  --lib /path/to/Nangate45_typ.lib \
  --report-format opensta \
  --dry-run
```

## Run CPA-remap

```bash
cpa-remap \
  --top-module gcd \
  --netlist examples/gcd/gcd_nangate45-tcl.v \
  --def-file examples/gcd/gcd_nangate45-tcl.def \
  --timing-report examples/gcd/r2r_timing.rpt \
  --lib /path/to/Nangate45_typ.lib \
  --report-format opensta \
  --design-name gcd_demo \
  --output-dir outputs \
  --distance-threshold 40 \
  --paths-per-group 1000000000 \
  --relax 0
```

Generated cones, timing comparisons, reports, and rewritten netlists are written under `outputs/<design-name>/`.

## Citation

If you use CPA-remap in academic work, please cite the accepted paper:

> Mingxiao He, Pengcheng Huang, Zhenyu Zhao, and Peiyun Bian. "CPA-remap: Critical-path-based Physically Aware Remapping Framework for Timing Optimization." ICCD 2025.
