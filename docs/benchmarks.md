[← Pestka](../README.md)

# Benchmarks

Measured on the revision that last changed this file, compiled by Aver
0.34.1, on an Apple M2 Pro. One run each. Other work ran on the machine at
the same time (load average about 3 to 4), so the times may be a little
high; instruction counts move far less.

## What a user runs

A large export is checked in two steps, as the Lean Kernel Arena does it
(`bin/arena-run`):

```sh
susz pack --no-index FILE.ndjson FILE.susz   # the Rust packer, github.com/jasisz/susz
main FILE.susz [WORKERS]                     # Pestka on the Susz file
```

The tables give the two steps apart. The total is their sum. The steps do
not run at the same time, so the peak is Pestka's: the packer's peak is
lower on every test (1.7 GB on `mathlib`).

The packer is `susz` 6808070, built with `-C target-cpu=native`. Its numbers
are taken with the ndjson file already in the page cache. Read cold from the
disk, packing `mathlib` took 29–32 s and 47 G instead of 5.0 s and 35.6 G.

## Native

On the small Lean Kernel Arena tests (all but `perf/` and the large corpora)
Pestka answers 183 of 183 correctly.

The Arena's large tests and its `perf/` tests, exported as the Arena exports
them, packed, then checked on four workers (the default) and on one. Four
workers take more instructions than one, mostly from the caches each worker
fills on its own (see [workers](usage.md#workers)). The Lean Kernel Arena
counts instructions retired over all threads. The build is `bin/build-pgo`
with `-C target-cpu=native`, guided by the profile of a check of all of
`Init` packed into Susz (see [building with PGO](usage.md#commands)); `init`
is the one test below that profile was made from.

| Test | Verdict | Packing | Time, 4 workers | Peak, 4 workers | Instructions, 4 workers | Time, 1 worker | Peak, 1 worker | Instructions, 1 worker |
|---|---|---|---|---|---|---|---|---|
| `init` (58,170 declarations) | accepted | 0.3 s, 2.2 G | 3.5 s | 1.0 GB | 49.0 G | 6.1 s | 0.86 GB | 42.1 G |
| `std` (101,286) | accepted | 0.5 s, 3.7 G | 5.1 s | 1.4 GB | 82.6 G | 10 s | 1.2 GB | 72.6 G |
| `reachability` | accepted | 0.02 s, 0.2 G | 1.2 s | 0.45 GB | 21.1 G | 1.8 s | 0.35 GB | 20.7 G |
| `con-leche` | accepted | 0.4 s, 3.1 G | 4.5 s | 1.3 GB | 75.4 G | 8.6 s | 1.2 GB | 68.4 G |
| `cedar` | accepted | 0.7 s, 5.4 G | 7.5 s | 1.5 GB | 111.6 G | 15 s | 1.4 GB | 100.1 G |
| `cslib` | accepted | 2.1 s, 14.6 G | 24 s | 3.4 GB | 345.9 G | 51 s | 3.2 GB | 332.1 G |
| `mathlib` (702,040) | accepted | 5.0 s, 35.6 G | 66 s | 6.2 GB | 1.11 T | 173 s | 5.5 GB | 1.07 T |
| `perf/`, 29 tests (in brackets `magma-list-deep-n36`) | as expected | 0.01 s, 0.8 G | 3.3 s (0.46 s) | 1.0 GB | 38.3 G (6.7 G) | 3.2 s (0.47 s) | 1.0 GB | 37.4 G (6.6 G) |

So `mathlib` takes about 71 s and 1149 G from the ndjson file to the
verdict on four workers. The `perf/` row adds up the 29 tests, run one at a
time, and its peak is the largest of them.

### Susz

Pestka also accepts the ndjson file itself: it converts the export into
Susz in memory with its own converter, written in Aver, and checks the
result (see [Susz in Pestka](susz.md)). That is slower than the two steps
above:

| `mathlib` | Time, 4 workers | Peak, 4 workers | Instructions, 4 workers | Time, 1 worker | Peak, 1 worker | Instructions, 1 worker |
|---|---|---|---|---|---|---|
| `susz pack`, then Pestka on the Susz file | 71 s | 6.2 GB | 1149 G | 178 s | 5.5 GB | 1109 G |
| Pestka on the ndjson file | 126 s | 6.2 GB | 1516 G | 218 s | 5.5 GB | 1449 G |

Packed sizes, without INDEX:

| Test | ndjson | Susz |
|---|---|---|
| `init` | 348 MB | 34 MB |
| `std` | 597 MB | 61 MB |
| `reachability` | 19 MB | 1.9 MB |
| `con-leche` | 551 MB | 54 MB |
| `cedar` | 872 MB | 90 MB |
| `cslib` | 2.42 GB | 250 MB |
| `mathlib` | 6.18 GB | 637 MB |

### Checking part of a file

`--only NAME` on `mathlib.susz` packed with INDEX (623 MB, of which INDEX
is 15.6 MB), against a full check of the same file. Plain `bin/build`, not
PGO, four workers, one run each, on AC power with the machine otherwise
quiet. "Read" is how many of the 702,040 declarations Pestka decodes MAIN
up to.

| Target | Read | Time | Peak | Instructions |
|---|---|---|---|---|
| `Int.neg_ediv` (early) | 14,276 (2%) | 0.28 s | 0.13 GB | 3.2 G |
| `CategoryTheory.FintypeCat.Action.isConnected_of_transitive` (middle) | 351,044 (50%) | 6.3 s | 2.1 GB | 49.5 G |
| `HenselianLocalRing.TFAE` (late) | 698,733 (99.5%) | 10.2 s | 3.5 GB | 72.8 G |
| whole file (`accepted`) | 702,040 | 74 s | 6.3 GB | 1336 G |

A late target still costs reading nearly all of MAIN and building the
environment before it, inductive blocks derived; what it saves is checking
the types and values of every other declaration, and decoding their
proofs: 95% of the instructions of a full check. On one worker the late target takes the same 10.2 s and 72.8 G,
since only one declaration is left to check.

### As WebAssembly

The same source compiled by Aver's own wasm-gc backend (not through Rust or
LLVM) and run on V8 under Node 26 as `bin/run-wasm` runs it, with
`--low-memory`, the Lean Kernel Arena's `pestka-wasm` entry
(`bin/arena-run --wasm`): every term, map and closure is an object of the
engine's garbage collector, and the module is about 0.6 MB. It gives the
same verdict as the compiled build on every test here and on the small
Arena tests. One thread, with the module `bin/build-wasm` makes: Binaryen's
`wasm-opt` takes about 6% of the instructions off the one Aver emits.

The file is packed by the same Rust `susz` first, so packing costs what the
native table says. The numbers below are Pestka's alone, on the Susz file.

| Test | Verdict | Instructions | Time | Peak |
|---|---|---|---|---|
| `init` | accepted | 196.5 G | 15 s | 2.4 GB |
| `std` | accepted | 340.6 G | 26 s | 3.6 GB |
| `reachability` | accepted | 64.8 G | 3.8 s | 1.4 GB |
| `con-leche` | accepted | 311.8 G | 22 s | 3.0 GB |
| `cedar` | accepted | 463.9 G | 36 s | 4.1 GB |
| `cslib` | accepted | 1.52 T | 111 s | 9.1 GB |
| `mathlib` | accepted | 5.78 T | 403 s | 11.3 GB |
| `perf/`, 29 tests (in brackets `magma-list-deep-n36`) | as expected | 156.7 G (11.4 G) | 9.5 s (0.66 s) | 2.1 GB |
