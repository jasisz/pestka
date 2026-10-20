# Pestka

A type checker for Lean 4 proofs, written in [Aver](https://github.com/jasisz/aver).

Pestka reads a Lean environment exported by
[`lean4export`](https://github.com/leanprover/lean4export) (NDJSON, format
3.1.0) and checks every declaration with its own implementation of Lean's type
theory: universe levels, definitional equality, inductive types and their
recursors, quotients, and the Nat and String literal extensions. It answers
accepted or rejected.

Status: Pestka type checks definitions, theorems, inductive types (mutual
and nested, with their recursors derived and compared with the export) and the
quotient package. On the small Lean Kernel Arena tests (all but `perf/` and the
large corpora) it answers 171 of 171 correctly. It checks all of `Init` from
Lean 4.32.0 (57,277 declarations, none admitted unchecked) in about 21 s and
1.9 GB with eight workers on an Apple M2 Pro, and in about 80 s on one.

Of the Arena's `perf/` tests, all pass within 3 GB and 60 s but one:
`magma-list-deep-n36` takes about 73 s (the Arena allows 390 s). `app-lam`,
built so that copying binder bodies adds up quadratically, takes 0.85 s and
1.4 GB on the same machine.

## How it checks

The checker follows the reference kernel's algorithm, with these choices of
its own:

- Facts about closed terms (types, definitional equalities and
  inequalities) are kept across declarations by each worker, which meets its
  declarations in file order, so a fact found once holds in every later one.
- Weak head normalization runs a machine whose arguments wait as terms with
  their environment and are built only when needed, each at most once;
  definitions unfold and recursor rules fire inside it.
- Opening a binder substitutes its variable into the body, as the reference
  does; past 128 open binders, bodies are inferred under their variables as
  they are instead, so deep nesting does not copy each body once per binder
  above it.

## Requirements

- **Aver at the commit in [`.aver-version`](.aver-version).** The version
  string (`0.31.0-dev`) does not move between upstream commits, so the project
  pins a SHA rather than a number.
- **Lean 4.35.0** through elan, and `lean4export` at tag `v4.35.0`, only to
  produce input files. Pestka itself never runs Lean.
- A Rust toolchain, for the compiled build.

### Installing the pinned Aver

```bash
git clone https://github.com/jasisz/aver aver
git -C aver checkout "$(cat .aver-version)"
cargo install --path aver aver-lang --locked --features wasm
```

`--features wasm` adds `--target wasm-gc` and `aver run --wasm-gc`. Add
`wasip2` to the feature list for `--target wasip2` and `aver run --wasip2`.

### Producing input

```bash
git clone https://github.com/leanprover/lean4export
cd lean4export && git checkout v4.35.0 && lake build
.lake/build/bin/lean4export Init > init.ndjson          # all of Init, ~346 MB
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
bin/pestka FILE.ndjson [WORKERS]   # runs .build/target/release/main, maps the verdict to the exit status
tests/run.sh               # every export under tests/export against its expected status
tests/arena.sh DIR         # the small Lean Kernel Arena tests, each under bin/capped
```

`bin/build` uses the `aver` on `PATH`, or the one `AVER` names.

Pestka builds the environment in file order, checking inductive types and
the quotient package as it meets them, and then checks the types and
values of the other declarations on WORKERS threads at once (eight by
default), each against the environment at its own place in the file. The
verdict is the first failure in file order, as in a strictly sequential
check. Reading shares out the same way: the lines are parsed on the workers
in rounds and go into the tables in file order, each round while the next
one is parsed.

Reading all of `Init` (346 MB, 6.1 million expressions) takes about 9 s
compiled on one thread and about 4 s on eight. The VM is far slower on
large files; use it for `verify` and small inputs.

Compiled to WebAssembly:

```bash
aver compile main.av --module-root . --target wasm-gc -o out/
aver compile main.av --module-root . --target wasip2 -o out/
aver run main.av --module-root . --wasm-gc -- FILE.ndjson
```

Under wasip2, `Disk` reaches only preopened directories; `aver run --wasip2`
preopens the current directory, so pass a relative path.

## Exit codes

The last line printed is the verdict: `accepted`, `rejected: <why>` or
`declined: <why>`. `bin/pestka` turns it into the exit status the Lean Kernel
Arena and `lake comparator` read, and reports any other ending, such as a
crash, as 3:

| Code | Meaning |
|---|---|
| 0 | every declaration accepted |
| 1 | a declaration rejected |
| 2 | input uses something Pestka does not support yet (declined) |

## Layout

- `main.av` — command line and verdict.
- `json/` — one NDJSON line to a JSON tree (`Json.Line`, `Json.Escapes`) and
  field access (`Json.Access`).
- `core/` — the type theory's data: `Core.Names`, `Core.Levels`, `Core.Exprs`
  (with hash and loose bound variable range in every node), `Core.Decls`,
  `Core.Hash`. Not `kernel/`: Aver reserves `Kernel.*`.
- `export/` — reading a lean4export file: `Export.Stream` (whole file,
  header first), `Export.Reader` (lines parsed in rounds on the workers,
  each round added in order while the next is parsed), `Export.Items`
  (names, levels, expressions),
  `Export.Declarations`, `Export.Tables`.
- `tests/export/` — small exports: `wellformed/` from `tests/export/Small.lean`
  (`small.ndjson` is the whole module, `small_core.ndjson` the constants
  without `String` and `Repr`), `malformed/` and `unsupported/` written by hand.
- `check/` — the type checker: `Check.State` (environment, local context,
  caches), `Check.Tc` (inference, weak head normal form, definitional
  equality), `Check.Decl` (adding declarations), `Check.Induct`,
  `Check.Recursor`, `Check.Nested`, `Check.IndAdd` (inductive blocks),
  `Check.Quot`, `Check.Lits` (Nat and String literals).
- `bin/` — `build`, the `pestka` wrapper, and `capped` (kills a run above a
  memory or time cap; macOS does not enforce `ulimit -v`).
- `proto/` — scouting prototypes used for early measurements. Not part of the
  checker.
