[← Pestka](../README.md)

# Benchmarks

These are the measurements recorded in README revision `e1b1d11`.
They predate subsequent optimizations; they are a historical snapshot, not a
measurement of the current HEAD.

## Native

On the small Lean Kernel Arena tests (all but `perf/` and the large corpora)
Pestka answers 179 of 179 correctly.

The Arena's large tests and its `perf/` tests, exported as the Arena exports
them and checked on an Apple M2 Pro: on one worker, as the Arena runs Pestka,
and on eight, the default. The instructions retired on one worker are what
the Arena ranks checkers by.
The build is `bin/build-pgo` with `-C target-cpu=native`, guided by the
profile of a check of all of `Init` (see [building with PGO](usage.md#commands)); `init` is the one test
below that profile was made from.

| Test | Verdict | Instructions, 1 worker | Time, 1 worker | Peak, 1 worker | Time, 8 workers | Peak, 8 workers |
|---|---|---|---|---|---|---|
| `init` (58,170 declarations) | accepted | 58.3 G | 7.3 s | 0.7 GB | 3.8 s | 1.0 GB |
| `std` (98,086) | accepted | 102.9 G | 13 s | 1.1 GB | 5.8 s | 1.6 GB |
| `reachability` | accepted | 23.6 G | 2.2 s | 0.4 GB | 1.7 s | 0.4 GB |
| `con-leche` | accepted | 96.3 G | 11 s | 1.1 GB | 5.7 s | 1.5 GB |
| `cedar` | accepted | 143.5 G | 19 s | 1.3 GB | 7.7 s | 1.8 GB |
| `cslib` | accepted | 543.0 G | 81 s | 3.7 GB | 30 s | 4.9 GB |
| `mathlib` (702,040) | accepted | 1.89 T | 313 s | 6.5 GB | 119 s | 8.6 GB |
| `perf/`, 30 tests (in brackets `magma-list-deep-n36`) | as expected | 42.0 G (7.0 G) | 3.6 s (0.5 s) | 0.9 GB | 3.5 s (0.5 s) | 0.9 GB |

### As WebAssembly

The same source compiled by Aver's own wasm-gc backend (not through Rust or
LLVM) and run on V8 under Node 26 by `bin/run-wasm`, the Lean Kernel Arena's
`pestka-wasm` entry: every term, map and closure is an object of the engine's
garbage collector, and the module is about 0.4 MB. It gives the same verdict
as the compiled build on every test here and on the small Arena tests. One
thread, with the module `bin/build-wasm` makes: Binaryen's `wasm-opt` takes
about 6% of the instructions off the one Aver emits.

| Test | Verdict | Instructions | Time | Peak |
|---|---|---|---|---|
| `init` | accepted | 245.7 G | 17 s | 2.5 GB |
| `std` | accepted | 413.8 G | 29 s | 4.8 GB |
| `reachability` | accepted | 81.6 G | 4.7 s | 1.7 GB |
| `con-leche` | accepted | 390.9 G | 26 s | 4.2 GB |
| `cedar` | accepted | 580.2 G | 41 s | 5.0 GB |
| `cslib` | accepted | 2.19 T | 159 s | 11.0 GB |
| `mathlib` | accepted | 9.04 T | 708 s | 13.0 GB |
| `perf/`, 30 tests (in brackets `magma-list-deep-n36`) | as expected | 224 G (22.6 G) | 14 s (1.3 s) | 2.1 GB |
