# Pestka

*Pestka* is Polish for the stone of a fruit, its kernel, and, said of a task,
for a piece of cake.

Pestka is a type checker for Lean 4. It reads an environment exported by
[`lean4export`](https://github.com/leanprover/lean4export) (NDJSON, format
3.1.0) and checks every declaration with its own implementation of Lean's type
theory: universe levels, definitional equality, inductive types (mutual and
nested, with their recursors derived and compared with the export),
quotients, and the Nat and String literal extensions. It answers accepted or
rejected, and admits nothing unchecked.

It is written in [Aver](https://github.com/jasisz/aver), a statically typed
language designed for AI to write and humans to review, which compiles to Rust
and has its own claims checked by Lean's kernel. Pestka is a Lean kernel
written in Aver, by an AI agent under human guidance.

## Status

On the small Lean Kernel Arena tests (all but `perf/` and the large corpora)
Pestka answers 171 of 171 correctly.

The Arena's large tests and its `perf/` tests, exported as the Arena exports
them and checked on an Apple M2 Pro: on one worker, as the Arena runs Pestka,
and on eight, the default. The instructions retired on one worker are what
the Arena ranks checkers by.

| Test | Verdict | Instructions, 1 worker | Time, 1 worker | Peak, 1 worker | Time, 8 workers | Peak, 8 workers |
|---|---|---|---|---|---|---|
| `init` (58,170 declarations) | accepted | 208.5 G | 20 s | 0.8 GB | 6.9 s | 1.4 GB |
| `std` (98,086) | accepted | 369.4 G | 37 s | 1.2 GB | 11 s | 2.5 GB |
| `reachability` | accepted | 103.0 G | 9.0 s | 0.4 GB | 7.3 s | 0.4 GB |
| `con-leche` | accepted | 366.0 G | 40 s | 1.0 GB | 17 s | 1.9 GB |
| `cedar` | accepted | 495.2 G | 51 s | 1.5 GB | 16 s | 2.6 GB |
| `navier-stokes-euler` | accepted | 2.22 T | 217 s | 3.8 GB | 90 s | 8.2 GB |
| `cslib` | accepted | 2.35 T | 269 s | 3.9 GB | 67 s | 6.6 GB |
| `mathlib` (702,040) | accepted | 8.67 T | 991 s | 8.7 GB | 229 s | 12.1 GB |
| `perf/`, 28 tests (in brackets `magma-list-deep-n36`) | as expected | 434 G (299 G) | 38 s (26 s) | 1.0 GB | 38 s (26 s) | 1.0 GB |

## What it does differently

The checker follows the reference kernel's algorithm. What is its own:

- **It is written in Aver**, a pure functional language compiled to Rust:
  the checker's state is a value passed from function to function. A state
  could be kept and gone back to, but the checker never does: it hands its
  state on, so the compiled code finds each cache with a single owner and
  updates it in place. Caches kept as persistent tries, copying a path on
  every write so that an old version nobody held stayed intact, cost 17%
  more instructions on `Init`.
- **Declarations are checked in parallel with a sequential verdict.** The
  environment is built in file order; the other declarations are then
  checked on several workers, each against the environment at its own place
  in the file, and the verdict is the first failure in file order.
- **Free variables are named by what they are.** A variable is its type and
  value, and how many variables of that same type and value are open where
  its binder is opened. Two binders open at once with the same type and value
  get different counts, and Lean only needs variables that meet to be told
  apart; two binders that get the same variable are never open at once, and
  they have the same type and value, so whatever holds of a term with one
  holds of it with the other. The checker no longer makes a fresh variable
  for every opening, nor another for every place in a telescope: a binder
  opened again gets its variable again, and so does a type or an instance
  that is the third binder of one theorem and the seventh of the next, so
  what was found about the terms under it, instance diamonds included, is
  found again. On slices of `mathlib` naming variables by their place in the
  telescope and the next point cut 18–20% of the instructions; naming them
  by their kind instead cut 4–5% more.
- **What a worker finds is kept across declarations.** Each worker meets its
  declarations in file order, so every constant a result rests on is still
  there in the next one. It carries its variables and their context, and the
  results of inference, checking, reduction and comparison, about closed
  terms and, with variables named as above, open ones too; checking a term
  with a universe parameter is kept for the same parameters, and the last
  four lists of parameters keep theirs.
  A constant's type and a definition's value at universe levels depend only
  on the levels as written, and are kept as well. Every cache has a limit and
  is emptied past it.
- **Failures are kept too.** Within a declaration, pairs found
  definitionally different are remembered as well as pairs found equal: its
  free variables each have one type and value, so the answer for a pair does
  not change while it is checked. In `std`, one proof compared the same pairs
  hundreds of times and took 211 s without this, 3 s with it.
- **Weak head normalization runs a lazy machine**: arguments wait as terms
  with their environment and are built only when needed, each at most once;
  definitions unfold and recursor rules fire inside it.
- **Deep binders are not copied.** Opening a binder substitutes its variable
  into the body, as the reference does; past 128 open binders, bodies are
  inferred under their variables as they are instead, so deep nesting does
  not copy each body once per binder above it.
- **Laws** state the properties the optimizations rely on and are checked
  with the code; see below.

## Next

A second core lives in `next/`: values as terms with their environment and
free variables as de Bruijn levels, so that entering a binder copies
nothing. It answers as the first does, and `both` checks every deferred
declaration with each and rejects at the first where their answers differ,
but in Aver it is slower than the first core, which is the one used.

## Laws

Besides examples, some `verify` blocks state laws: an equation checked on
every combination of the values its `given` lines list, and the claim
`aver proof` tries to prove for all of them.

- `natOp law natSpec` (`check/lits.av`): the fourteen Nat operations the
  checker computes on literals agree with Lean's own definitions of them
  (`Nat.sub` by `pred`, `Nat.div` and `Nat.mod` by their equations,
  `Nat.bitwise` for `land`, `lor` and `xor`, and so on).
- `pack law roundTrip` and `pack law rangeNeverShrinks` (`core/exprs.av`):
  the metadata packed into every node reads back as it was, and the loose
  bound variable range read back is never below the true one, so a
  substitution never skips a term it has to change. `aver proof` proves the
  second for all inputs.
- `apply law applySpec` (`core/subst.av`): substitution, with its skipping
  by metadata and its memo for shared subterms, gives what plain recursion
  gives; `abstractFVars law undoneByInstantiateRev` puts abstracted
  variables back.
- `localGet` laws (`check/state.av`): the local context, a persistent trie,
  holds what was put, keeps every other variable and finds each declared
  one.

```bash
aver verify . --module-root .                                  # examples and laws
aver proof check/lits.av --module-root . --backend aver --check-json
```

## Requirements

- **Aver at the commit in [`.aver-version`](.aver-version).** The version
  string (`0.31.0-dev`) does not move between upstream commits, so the project
  pins a SHA rather than a number.
- **Lean** through elan, and `lean4export` built for the same Lean, only to
  produce input files. Pestka itself never runs Lean. The numbers here come
  from exports made as the Lean Kernel Arena makes them: `lean4export`
  `master` built with Lean 4.34.1, or with the Lean a test project pins.
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
.build/target/release/main FILE.ndjson [WORKERS [old|next|both]]
tests/run.sh               # every export under tests/export against its expected status
tests/arena.sh DIR         # the small Lean Kernel Arena tests, each under bin/capped
```

`bin/build` uses the `aver` on `PATH`, or the one `AVER` names. The third
argument picks the core: `old` (the default), `next` (the second core, in
`next/`, being built), or `both`, which checks every deferred declaration
with each and rejects at the first where their answers differ.

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
`declined: <why>`. `main` returns the matching exit status, the one the Lean
Kernel Arena and `lake comparator` read:

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
  without `String` and `Repr`), `malformed/` and `unsupported/` written by hand,
  and `illtyped/`: declarations the checker must reject, made by
  `tests/export/mkbad.py` from the correct ones of `tests/export/PestkaBad.lean`
  (`wellformed/levelled_*`), aimed at the naming of free variables.
- `check/` — the type checker: `Check.State` (environment, local context,
  caches), `Check.Tc` (inference, weak head normal form, definitional
  equality), `Check.Decl` (adding declarations), `Check.Induct`,
  `Check.Recursor`, `Check.Nested`, `Check.IndAdd` (inductive blocks),
  `Check.Quot`, `Check.Lits` (Nat and String literals).
- `bin/` — `build`, and `capped` (kills a run above a memory or time cap;
  macOS does not enforce `ulimit -v`).
- `proto/` — scouting prototypes used for early measurements. Not part of the
  checker.
