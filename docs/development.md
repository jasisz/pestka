[← Pestka](../README.md)

# Developing Pestka

Run commands from the repository root.

```bash
aver check . --module-root .
aver verify . --module-root .
bin/build
tests/run.sh
```

The fixture suite covers accepted exports, malformed input, ill-typed declarations,
unsupported formats and saved soundness findings. For differential testing and
mutation testing, see [the command reference](usage.md#commands).

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
- Universe levels (`core/univ.av`), against `levelValue`, what a level
  denotes for an assignment of its parameters: `isGeq law sound` (a
  level accepted as at least another is so for every assignment),
  `isEquiv law sound`, `normalize`, `mkMax` and `mkImax law keepsValue`,
  and `instantiate law sameAsSubstitutedValues`. `aver proof` proves the
  helpers below them for all inputs (`toOffset`, `mkSucc`, `mkSuccN`,
  `biggerExplicit law keepsValue`, `isNotZero law atLeastOne`,
  `normalizesToZero law alwaysZero`, `isExplicit law valueIsDepth`, values
  never negative); the rest it does not yet, as they turn on `==` between
  levels or recurse through normal forms.

```bash
aver verify . --module-root .                                  # examples and laws
aver proof check/lits.av --module-root . --backend aver --check-json
```

## Source map

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
