[← Pestka](../README.md)

# Build and run

Run Pestka commands from the repository root unless a step explicitly changes directory.

## Requirements

- **Aver at the version in [`.aver-version`](../.aver-version)**, a release
  on crates.io.
- **Lean** through elan, and `lean4export` built for the same Lean, only to
  produce input files. Pestka itself never runs Lean. The [recorded benchmark numbers](benchmarks.md) come
  from exports made as the Lean Kernel Arena makes them: `lean4export`
  `master` built with Lean 4.34.1, or with the Lean a test project pins.
- A Rust toolchain, for the compiled build, with the `llvm-tools` component
  for `bin/build-pgo`.
- For the WebAssembly build, Node (24 or later) and Binaryen's `wasm-opt`.

### Installing the pinned Aver

```bash
cargo install aver-lang --version "$(cat .aver-version)" --locked --features wasm
```

`--features wasm` adds `--target wasm-gc` and `aver run --wasm-gc`. Add
`wasip2` to the feature list for `--target wasip2` and `aver run --wasip2`.

### Producing input

```bash
git clone https://github.com/leanprover/lean4export
cd lean4export && echo leanprover/lean4:v4.34.1 > lean-toolchain && lake build
.lake/build/bin/lean4export Init > init.ndjson          # all of Init, ~348 MB
.lake/build/bin/lean4export MyModule -- MyModule.foo     # one constant and its dependencies
```

### Susz

An export can be packed once into Susz, Pestka's binary form of it
([format](susz.md)), and checked from that as often as needed:

```bash
.build/target/release/main pack mathlib.ndjson mathlib.susz   # 5.90 GB to 661 MB, about a minute
.build/target/release/main mathlib.susz [WORKERS]
```

Pestka recognises a Susz file by its first bytes. It reads it into the same
tables as the ndjson file and checks it the same way, with the same verdict;
only a malformed record is named by its number rather than its line. The
packer refuses what the reader would reject while reading. On mathlib,
reading takes 95 G instructions and 11 s on one thread instead of 184 G and
24 s (16 s and 247 G reading the ndjson file on four), and the whole check on
four workers 71 s and 1156 G instead of 79 s and 1320 G.

## Commands

```bash
aver check . --module-root .                 # types, effects, lint
aver verify . --module-root .                # run the verify blocks
aver run main.av --module-root . -- FILE.ndjson
```

Compiled to Rust, which is the build meant for large inputs:

```bash
bin/build                  # aver compile + cargo build --release into .build/
bin/build-pgo TRAIN.ndjson # the same, guided by a profile of checking TRAIN
.build/target/release/main [--low-memory] FILE.ndjson [WORKERS]
tests/run.sh               # fixtures in file order and with --reorder-always
tests/arena.sh DIR         # small Arena tests, in both orders, under bin/capped
python3 tests/soundness.py corpus DIR --exclude '*/perf/*' --max-bytes 4000000
                                             # compare Pestka with other kernels
python3 tests/soundness.py mutate FILE # guaranteed-invalid mutations; no kernel may accept
```

`tests/soundness.py` accepts repeated `--kernel 'NAME=COMMAND {file}'`
arguments, so Pestka can be compared with any checker that uses the Arena exit
codes. Add `--require-verdict NAME` for commands such as `aver run`: an exit
without an `accepted`, `rejected:` or `declined:` line is then a runner error,
not a kernel verdict. Reports retain bounded command output for diagnostics,
with no path of the machine they ran on: a program is named by its path in
the repository or by its name, an input by its path from the directory
holding the one given, the home directory as `~`.
In `mutate` mode it first requires every selected kernel to accept the seed,
then injects loose bound variables and duplicate universe parameters. An
invalid export accepted by any kernel is kept under `tests/soundness-findings/`.

`bin/build` uses the `aver` on `PATH`, or the one `AVER` names, and passes
`AVER_FLAGS` on to `aver compile`. The workers run on threads of their
own; the same build serves one worker and many.
`bin/build-pgo` builds once with instrumentation, checks TRAIN with it on
one worker, and builds again with the profile that run left; `FLAGS` adds
rustc flags to both builds (the Arena gives `-C target-cpu=native`). It needs
`llvm-profdata`, from rustup's `llvm-tools` component. A profile of a check
of `init-prelude` alone cuts 12–15% of the instructions on the recorded benchmarks,
those far from it included; one of all of `Init` cuts another 1–1.5% on the
tests it was not made from (`std`, `con-leche`, `cedar`, `mathlib`).

Pestka builds the environment in file order, checking inductive types and
the quotient package as it meets them, and then checks the types and
values of the other declarations on WORKERS threads at once (four by
default), each against the environment at its own place in the file. The
verdict is the first failure in file order, as in a strictly sequential
check. Reading shares out the same way: the lines are parsed on the workers
in rounds, each worker a range of the chunk being read where the split put
it, and go into the tables in file order, each round while the next one is
parsed (decision `RangesInPlace` in `export/reader.av`).

When each worker has more declarations than its caches hold (`mathlib` on
one worker), the deferred declarations are checked grouped by the first
two components of their namespaces, a declaration going with those named
under it (`Foo.bar` with `Foo.bar.eq_1`), so that declarations about the same things meet
the facts they share before those are let go (decision `CheckedByNamespace`
in `check/decl.av`). That is sound only when every declaration names
constants placed before it, which the reader makes sure of as it reads
(`NamesPlacedWhereRead` in `export/tables.av`); otherwise the file order
stays. `--reorder-always` is a tool for tests: it groups on any file the
reader allows it on, however small, so that `tests/run.sh` and
`tests/arena.sh` check every file in both orders.

The VM is far slower on large files; use it for `verify` and small inputs.

### Low-memory mode

`--low-memory` trades instructions for memory: the caches a worker carries
across declarations stop at smaller limits, and the facts about closed
terms, kept for the whole run otherwise, are emptied past a limit too. The
limits were chosen by what a cost model of the caches says each GB kept
returns, then swept on `mathlib` until the peak reached what reading
alone takes (decision `LowMemoryMode` in `check/state.av`). PGO build,
one worker unless said:

| Test | Default | `--low-memory` |
|---|---|---|
| `mathlib` | 1187 G, 6.6 GB, 187 s | 1243 G (+4.7%), 4.9 GB, 220 s |
| `mathlib`, 4 workers | 7.1 GB, 73–74 s | 5.0 GB, 71 s |
| `init` | 47.4 G, 0.90 GB | 51.7 G (+9.1%), 0.52 GB |
| `etale` | 17.5 G, 0.78 GB | 18.4 G (+4.9%), 0.43 GB |

What the mode cannot shrink is the environment. Pestka holds every
expression of the export until the process ends; on `mathlib` reading
alone peaks at 4.7 GB, of which the 105 M expression nodes are 3.4 GB, the
index table that reading needs 0.8 GB and the names 0.3 GB. Three quarters
of the nodes are the values of theorems, which nothing reads once the
theorem is checked, except that Lean's kernel, and so Pestka, unfolds a
theorem where it reduces a proof: `Init` unfolds `Acc.inv` under
`WellFounded.fixF_eq`, `etale` `Iff.mpr` and `Localization.mk_eq_mk_iff`
under `Localization.rec`. A mode that let theorem values go once checked
was tried and declined both files. Going below the environment would take
reading and checking a chunk at a time, with a first pass over the file to
learn where each expression is used last, or a denser representation of
stored terms.

`tests/run.sh` and `tests/arena.sh` take `PESTKA_ARGS`, so
`PESTKA_ARGS=--low-memory sh tests/run.sh` runs them in this mode.

### Workers

Workers take more instructions than one worker on the same file: reading in
rounds parses each line into a value of its own before the tables take it,
and each worker keeps caches of its own and learns again facts that another
worker has already found. The workers share caches only an eighth larger
than one worker's, so the peak stays close to one worker's (decision
`FrugalWorkers` in `check/decl.av`). `mathlib`, PGO build:

| Workers | Time | Peak | Instructions |
|---|---|---|---|
| 1 | 180 s | 6.6 GB | 1185 G |
| 4 | 73–74 s | 7.1 GB | 1283 G (+8%) |

Of that 8%, reading in rounds takes about 4.5% (55 G) and saves about
10 s. The rest comes mostly from the smaller caches each worker keeps. Four
workers each given a whole worker's caches would need about twice the
memory.

### WebAssembly

Compiled to WebAssembly:

```bash
bin/build-wasm                               # wasm-gc, optimized by wasm-opt, into .build-wasm/
bin/run-wasm FILE.ndjson
aver compile main.av --module-root . --target wasip2 -o out/
aver run main.av --module-root . --wasm-gc -- FILE.ndjson
```

`bin/run-wasm` runs the module under Node through Aver's host for wasm-gc
programs ([`wasm-host/`](../wasm-host), copied from `tools/wasm-work` of the
Aver release, which the crate leaves out),
with a heap of up to 14 GB and young-generation semi-spaces of 256 MB. It
passes on Pestka's exit status only when the verdict line agrees with it and
exits with 3 otherwise, so a crash of V8 or of the host never reads as a
verdict. `aver run --wasm-gc` uses Wasmtime instead, whose collector is far
slower on Pestka (17 times the instructions of V8 on `etale`) and whose heap
stops at 4 GiB.

Under wasip2, `Disk` reaches only preopened directories; `aver run --wasip2`
preopens the current directory, so pass a relative path.

## Exit codes

The last line printed is the verdict: `accepted`, `rejected: <why>` or
`declined: <why>`. `main` returns the matching exit status, the one the Lean
Kernel Arena and `lake comparator` read:

| Code | Meaning |
|---|---|
| 0 | every declaration accepted |
| 1 | a declaration rejected |
| 2 | input uses something Pestka does not support yet (declined) |
| 3 | `bin/run-wasm` only: the host or V8 failed, no verdict |
