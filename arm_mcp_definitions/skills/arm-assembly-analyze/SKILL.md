---
name: arm-assembly-analyze
description: Estimate assembly throughput and CPU resource pressure with llvm-mca from the command line. Use for static analysis of hot loops and architecture-specific assembly during Arm optimization.
---

# Analyze assembly with LLVM MCA

Run commands through the agent's shell. This replaces the former `mca` MCP tool.
Use textual assembly, not an object file or executable. Generate assembly from
source with the project's compiler and target flags (for example, Clang `-S`),
or extract a suitable instruction region from disassembly. Preprocess `.S` files
before analysis. Retain instruction syntax and target architecture.

This skill runs in the user's environment; LLVM is not installed in the Arm MCP
server image. Use an installed `llvm-mca` (sometimes version-suffixed). If it is
absent, ask before installing LLVM with the user's platform package manager,
then resolve the installed binary (for example `llvm-mca-18` or a package-manager
LLVM `bin` directory). Do not modify the server container.

```sh
command -v llvm-mca || command -v llvm-mca-18
llvm-mca --mtriple=aarch64 --mcpu=help
llvm-mca --mtriple=aarch64 --mcpu=neoverse-n1 \
  --iterations=100 --bottleneck-analysis --resource-pressure loop.s
```

Choose the CPU matching the requested deployment; `neoverse-n1` is only an
example. Use `--mtriple=x86_64` with an appropriate supported CPU for x86 input.
An AArch64 model can run on an x86 host when compiled into LLVM; the analysis
target is distinct from the host/container architecture. List supported CPUs
for the installed LLVM version rather than inventing a scheduling model. If
the requested target or instruction is unsupported, report the limitation.

Isolate a representative hot loop, optionally with `LLVM-MCA-BEGIN` and
`LLVM-MCA-END` assembly comment markers. Record LLVM version, target triple,
CPU, options, input region, instructions, cycles, IPC, block throughput, and
resource pressure. Compare equivalent work with the same settings when
evaluating changes. Estimates omit real cache misses, branch behavior, OS
effects, and workload inputs; do not present cycles or IPC as measured runtime
or claim a speedup without a benchmark. Use `knowledge_base_search` for Arm
intrinsics and CPU guidance when needed.
