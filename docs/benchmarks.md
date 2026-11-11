[← Pestka](../README.md)

# Benchmarks

Measured on the revision that last changed this file, compiled by Aver
0.33.1.

## Native

On the small Lean Kernel Arena tests (all but `perf/` and the large corpora)
Pestka answers 179 of 179 correctly.

The Arena's large tests and its `perf/` tests, exported as the Arena exports
them and checked on an Apple M2 Pro with the default build: on four workers,
the default, and on one. Four workers parse the file in rounds, each a
range of the chunk being read where it lies, and share caches an eighth
larger than one worker's, so their peak stays close to one
worker's; they take more instructions than one worker, from parsing each line
into a value of its own and from caches each worker fills on its own (see
[workers](usage.md#workers)). The Lean Kernel Arena counts instructions
retired over all threads.
The build is `bin/build-pgo` with `-C target-cpu=native`, guided by the
profile of a check of all of `Init` (see [building with PGO](usage.md#commands)); `init` is the one test
below that profile was made from.

| Test | Verdict | Time, 4 workers | Peak, 4 workers | Instructions, 4 workers | Time, 1 worker | Peak, 1 worker | Instructions, 1 worker |
|---|---|---|---|---|---|---|---|
| `init` (58,170 declarations) | accepted | 3.2 s | 1.0 GB | 56.6 G | 6.6 s | 0.9 GB | 47.5 G |
| `std` (101,286) | accepted | 5.4 s | 1.5 GB | 96.3 G | 11 s | 1.3 GB | 81.7 G |
| `reachability` | accepted | 1.2 s | 0.4 GB | 21.1 G | 1.8 s | 0.3 GB | 20.7 G |
| `con-leche` | accepted | 4.6 s | 1.3 GB | 87.9 G | 9.2 s | 1.3 GB | 77.3 G |
| `cedar` | accepted | 7.6 s | 1.5 GB | 131.9 G | 17 s | 1.5 GB | 115.1 G |
| `cslib` | accepted | 25 s | 3.7 GB | 408.6 G | 54–56 s | 3.6 GB | 373.5 G |
| `mathlib` (702,040) | accepted | 73–74 s | 7.1 GB | 1.28 T | 180 s | 6.6 GB | 1.19 T |
| `perf/`, 30 tests (in brackets `magma-list-deep-n36`) | as expected | 3.9 s (0.47 s) | 0.9 GB | 46.7 G (6.7 G) | 4.3 s (0.49 s) | 0.9 GB | 45.5 G (6.7 G) |

### Susz

`mathlib` packed into [Susz](susz.md) by `pestka pack` (5.90 GB of ndjson to
661 MB, in about a minute) and checked from that, with the same build as the
table above and the same verdict and output. `bin/build-pgo` also packs the
export it is given into Susz and checks that, so both readers are in the
profile: that took 6 G off reading Susz and left ndjson where it was.

| | From ndjson | From Susz |
|---|---|---|
| Reading, to the `constants` line, one thread | 23.8 s, 184.1 G | 11.0 s, 95.3 G |
| Reading, four workers | 14.6 s, 239.4 G | 10.8 s, 95.3 G (read on one thread) |
| Whole check, four workers | 76.7 s, 7.6 GB, 1313.7 G | 70.6 s, 7.6 GB, 1155.9 G |
| Whole check, one worker | 184 s, 7.0 GB, 1196.9 G | 179 s, 7.1 GB, 1108.0 G |

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
