[← Pestka](../README.md)

# Benchmarks

Measured on revision `88fb511`, compiled by Aver at commit `d55294ab0`.

## Native

On the small Lean Kernel Arena tests (all but `perf/` and the large corpora)
Pestka answers 179 of 179 correctly.

The Arena's large tests and its `perf/` tests, exported as the Arena exports
them and checked on an Apple M2 Pro: on one worker, as the Arena runs Pestka,
and on four, the default. The instructions retired on one worker are what
the Arena ranks checkers by.
The build is `bin/build-pgo` with `-C target-cpu=native`, guided by the
profile of a check of all of `Init` (see [building with PGO](usage.md#commands)); `init` is the one test
below that profile was made from.

| Test | Verdict | Instructions, 1 worker | Time, 1 worker | Peak, 1 worker | Time, 4 workers | Peak, 4 workers |
|---|---|---|---|---|---|---|
| `init` (58,170 declarations) | accepted | 47.5 G | 6.6 s | 0.9 GB | 3.6 s | 1.4 GB |
| `std` (101,286) | accepted | 81.8 G | 12 s | 1.3 GB | 5.7 s | 2.0 GB |
| `reachability` | accepted | 20.8 G | 2.0 s | 0.3 GB | 1.4 s | 0.4 GB |
| `con-leche` | accepted | 77.6 G | 10 s | 1.3 GB | 5.3 s | 1.8 GB |
| `cedar` | accepted | 115.2 G | 18 s | 1.5 GB | 8.2 s | 2.1 GB |
| `cslib` | accepted | 375.0 G | 56 s | 3.6 GB | 29 s | 4.8 GB |
| `mathlib` (702,040) | accepted | 1.19 T | 187 s | 6.6 GB | 71 s | 9.4 GB |
| `perf/`, 30 tests (in brackets `magma-list-deep-n36`) | as expected | 45.5 G (6.7 G) | 4.0 s (0.46 s) | 0.9 GB | 4.0 s (0.47 s) | 0.9 GB |

### As WebAssembly

The same source compiled by Aver's own wasm-gc backend (not through Rust or
LLVM) and run on V8 under Node 26 by `bin/run-wasm`, the Lean Kernel Arena's
`pestka-wasm` entry, which runs it with `--low-memory`: every term, map and closure is an object of the engine's
garbage collector, and the module is about 0.4 MB. It gives the same verdict
as the compiled build on every test here and on the small Arena tests. One
thread, with the module `bin/build-wasm` makes: Binaryen's `wasm-opt` takes
about 6% of the instructions off the one Aver emits.

| Test | Verdict | Instructions | Time | Peak |
|---|---|---|---|---|
| `init` | accepted | 247.4 G | 18 s | 2.3 GB |
| `std` | accepted | 428.5 G | 31 s | 3.3 GB |
| `reachability` | accepted | 68.0 G | 4.1 s | 1.3 GB |
| `con-leche` | accepted | 402.0 G | 28 s | 3.3 GB |
| `cedar` | accepted | 600.7 G | 43 s | 4.3 GB |
| `cslib` | accepted | 1.90 T | 135 s | 9.3 GB |
| `mathlib` | accepted | 7.09 T | 524 s | 11.9 GB |
| `perf/`, 30 tests (in brackets `magma-list-deep-n36`) | as expected | 197 G (11.0 G) | 15 s (0.77 s) | 1.9 GB |
