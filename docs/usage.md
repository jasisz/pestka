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
`AVER_FLAGS` on to `aver compile`. `AVER_FLAGS=--single-thread` builds
Pestka for one thread: the workers then run one after another, and Aver
counts references with plain instructions instead of atomic ones (needs an
Aver with `--single-thread`). That is the build for one worker, as the Arena
runs it; the default build keeps its workers on threads of their own.
`bin/build-pgo` builds once with instrumentation, checks TRAIN with it on
one worker, and builds again with the profile that run left; `FLAGS` adds
rustc flags to both builds (the Arena gives `-C target-cpu=native`). It needs
`llvm-profdata`, from rustup's `llvm-tools` component. A profile of a check
of `init-prelude` alone cuts 12–15% of the instructions on the recorded benchmarks,
those far from it included; one of all of `Init` cuts another 1–1.5% on the
tests it was not made from (`std`, `con-leche`, `cedar`, `mathlib`).

Pestka builds the environment in file order, checking inductive types and
the quotient package as it meets them, and then checks the types and
values of the other declarations on WORKERS threads at once (eight by
default), each against the environment at its own place in the file. The
verdict is the first failure in file order, as in a strictly sequential
check. Reading shares out the same way: the lines are parsed on the workers
in rounds and go into the tables in file order, each round while the next
one is parsed.

When each worker has more declarations than its caches hold (`mathlib` on
one worker), the deferred declarations are checked grouped by the first
component of their names, so that declarations about the same things meet
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
one worker unless said. These measurements were recorded before the later
namespace-ordering and cache-limit changes:

| Test | Default | `--low-memory` |
|---|---|---|
| `mathlib` | 1726 G, 7.6 GB, 295 s | 1871 G (+8.4%), 4.7 GB, 294 s |
| `mathlib`, 8 workers | 13.0 GB | 5.4 GB, 99 s |
| `init` | 51.4 G, 0.98 GB | 56.6 G (+10%), 0.51 GB |
| `etale` | 21.4 G, 0.84 GB | 22.2 G (+3.8%), 0.46 GB |

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
