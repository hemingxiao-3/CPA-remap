# CPA-remap Paper Summary

CPA-remap targets timing optimization after layout by using physical information that is already available from the implemented design. It avoids relying on pre-layout delay prediction by directly extracting critical paths, cell locations, and netlist topology from post-layout artifacts.

The framework has four main stages:

1. Extract violated critical paths from timing reports.
2. Merge and partition critical-path subgraphs into initial logic cones.
3. Grow each cone using location-aware proximity constraints.
4. Remap cones with ABC and OpenSTA timing constraints, then accept only cones that improve timing without exceeding the configured degradation allowance.

The original research evaluated CPA-remap on OpenCores benchmarks in Nangate45 and an industrial sub-20nm design. The public repository keeps the implementation and a small example input; large experiment outputs remain local and ignored by git.
