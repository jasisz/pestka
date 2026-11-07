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
.build/target/release/main FILE.ndjson [WORKERS]
tests/run.sh               # every export under tests/export against its expected status
tests/arena.sh DIR         # the small Lean Kernel Arena tests, each under bin/capped
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

`bin/build` uses the `aver` on `PATH`, or the one `AVER` names.
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

The VM is far slower on large files; use it for `verify` and small inputs.

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
