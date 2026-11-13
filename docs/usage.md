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

Convert the export to [Susz](https://github.com/jasisz/susz) once and check
the Susz file. That is the fast way:

```bash
cargo install susz
susz pack --no-index mathlib.ndjson mathlib.susz   # 6.2 GB to 637 MB, about 5 s
.build/target/release/main mathlib.susz [WORKERS]
```

Pestka also accepts the ndjson file directly and converts it in memory with
its own converter, which is slower. `main pack` writes a Susz file with that
converter; the bytes are the same as from `susz pack`. More in
[Susz in Pestka](susz.md), numbers in [the benchmarks](benchmarks.md#susz).

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
.build/target/release/main [--low-memory] FILE.susz [WORKERS]   # or FILE.ndjson
.build/target/release/main --only NAME[,NAME...] FILE.susz [WORKERS]
                           # check only some declarations, by the file's INDEX
tests/run.sh               # fixtures in file order and with --reorder-always
tests/only.sh              # --only on small files, with damaged INDEX sections
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
one worker, then TRAIN packed into Susz (unless it is Susz already), and builds again with the profile that run left; `FLAGS` adds
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
check. A Susz file is read on one thread. A theorem's proof stays as
bytes until its declaration is checked, and the worker checking it decodes
it then. An ndjson file is first packed into Susz in memory, with its
lines parsed on the workers.

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
returns, then swept on `mathlib` (decision `LowMemoryMode` in
`check/state.av`). Susz files, PGO build, one worker unless said:

| Test | Default | `--low-memory` |
|---|---|---|
| `mathlib` | 1074 G, 5.5 GB, 175 s | 1117 G (+4.0%), 3.9 GB, 171 s |
| `mathlib`, 4 workers | 1114 G, 6.2 GB, 66 s | 1174 G (+5.4%), 3.9 GB, 67 s |
| `init` | 42.2 G, 0.86 GB | 45.6 G (+8.0%), 0.45 GB |
| `etale` | 17.0 G, 0.82 GB | 17.0 G (+0.0%), 0.44 GB |

What the mode cannot shrink is what reading builds. Pestka keeps the
tables it reads from MAIN until the process ends, and keeps the PROOFS
section as bytes. On `mathlib` that is 38 M expressions and 4.2 M names,
plus 317 MB of proofs, and when reading ends the process holds about
3.2 GB. The 67 M expressions of the theorems' proofs are not built while
reading. A proof is decoded when its theorem is checked, and no table
keeps the term after that. The low-memory peak of 3.9 GB is the 3.2 GB of reading plus
what checking holds at once. Going lower would take a denser form of the
stored terms, or reading MAIN a part at a time.

`tests/run.sh` and `tests/arena.sh` take `PESTKA_ARGS`, so
`PESTKA_ARGS=--low-memory sh tests/run.sh` runs them in this mode.

### Workers

On a Susz file the workers only check: the file is read on one thread
whatever their number, so the extra instructions of more workers come
from checking: each worker keeps caches of its own and finds again facts
that another worker has already found. The workers share caches only an
eighth larger than one worker's, so the peak stays close to one worker's
(decision `FrugalWorkers` in `check/decl.av`). `mathlib.susz`, PGO build:

| Workers | Time | Peak | Instructions |
|---|---|---|---|
| 1 | 175 s | 5.5 GB | 1074 G |
| 4 | 66 s | 6.2 GB | 1114 G (+3.7%) |

An ndjson file is first packed into Susz in memory. That packer parses
the lines on the workers in rounds and packs them in file order (decision
`ParsedInRounds` in `export/pack.av`), so there more workers also cost
parsing work.

### Checking part of a file

`--only NAME[,NAME...]` checks the named declarations of a Susz file, found
by its INDEX section, instead of the whole file; `Foo.*` names everything
under `Foo`. The declarations before the last target are admitted to the
environment, with inductive blocks and quotients still checked and the
others taken as stated. The result is `checked: ...`, never `accepted`.
[Susz in Pestka](susz.md#checking-part-of-a-file) says exactly what such a
result trusts, and [the benchmarks](benchmarks.md#checking-part-of-a-file)
what it saves.

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
`declined: <why>`. With `--only` it is `checked: <names> (subset; ...)`
instead of `accepted`, or `index invalid: <why>`. `main` returns the matching exit status, the one the Lean
Kernel Arena and `lake comparator` read:

| Code | Meaning |
|---|---|
| 0 | every declaration accepted |
| 1 | a declaration rejected |
| 2 | input uses something Pestka does not support yet (declined) |
| 2 | `--only` only: the file's INDEX disagrees with its records (`index invalid: <why>`), no verdict |
| 3 | `bin/run-wasm` only: the host or V8 failed, no verdict |
