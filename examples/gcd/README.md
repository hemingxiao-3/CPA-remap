# gcd Example

This directory contains a small post-layout input set for exercising CPA-remap:

- `gcd_nangate45-tcl.v`: post-layout Verilog netlist
- `gcd_nangate45-tcl.def`: placed DEF with instance locations
- `r2r_timing.rpt`: violated register-to-register OpenSTA timing paths

The corresponding Nangate45 liberty file is not included. Pass your local copy with `--lib` when running the tool.
