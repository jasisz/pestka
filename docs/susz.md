# Susz in Pestka

Pestka reads [Susz 1](https://github.com/jasisz/susz). The format, its rules
and the reference `susz` tool live in that repository. This page only covers
what is specific to Pestka.

## Commands

```sh
main FILE.susz [WORKERS]                                # check a Susz file
main --only NAME[,NAME...] FILE.susz [WORKERS]          # check some declarations of it
main FILE.ndjson [WORKERS]                              # convert in memory, then check
main pack [--no-index] FILE.ndjson FILE.susz [WORKERS]  # write a Susz file
```

Pestka tells the two inputs apart by the first four bytes of the file.

For ndjson input, Pestka converts the export in memory with its own
converter, written in Aver, and checks the result. If the converter refuses
the file, or the result is not accepted by the reader, Pestka falls back to
reading the ndjson line by line, so a broken line is reported by its number.

`pack` writes exactly the bytes `susz pack` writes, with or without the index.
We test that on every export we have. It is a second implementation of the
spec, and a benchmark for Aver. For real use, `susz pack` is faster.

A full check never reads the index or the source section.

## Checking part of a file

`--only` checks the named declarations of a Susz file instead of the whole
file. It needs the INDEX section, which `susz pack` and `main pack` write
unless given `--no-index`; a file without it is declined with a message that
says so. An ndjson file is declined too: pack it first.

```sh
main --only Nat.add_comm mathlib.susz                # one declaration
main --only Nat.add_comm,List.map_id mathlib.susz    # several
main --only 'Finset.*' mathlib.susz                  # every name under Finset
```

A name is written with dots, as Lean prints it; a component of digits only
is a numeric component. `Foo.*` asks for every name under `Foo`, not `Foo`
itself. A constructor or recursor name asks for its inductive block.

Pestka finds each name in INDEX, then reads MAIN from its start up to the
record of the last declaration asked for, and stops there. Records only
point back, so everything a declaration needs comes before it, but MAIN has
no offsets for its other records and must be decoded up to that point. Of
PROOFS it reads only the blocks of the theorems up to there. The proof
blocks of other theorems are never decoded, unless checking a target
unfolds one of those theorems.

What a subset check trusts. A declaration is checked against the
environment of everything before it in the file, as in a full check. That
environment is built the same way, with one difference:

- Inductive blocks and the quotient package before the last target are
  derived and compared with the file, as in a full check, because reduction
  relies on the recursor and quotient rules they add.
- Names must be new and universe parameters distinct, as always.
- Every other declaration before the last target, an axiom, definition,
  theorem or opaque constant that was not asked for, is admitted as the
  file states it. Its type and value are not checked, and a theorem's proof
  is not looked at.
- Unsafe and partial declarations are skipped, as in a full check. A target
  that is unsafe or partial is declined.

So a subset verdict holds only if the declarations admitted unchecked are
well typed. An ill-typed definition the target unfolds could make it pass,
or make a reduction run forever. A full check is the only way to vouch
for the whole file.

Pestka prints what it checked, and never `accepted`:

| Last line | Status | Meaning |
|---|---|---|
| `checked: NAME (subset; N earlier declarations admitted unchecked)` | 0 | the targets check, given the declarations before them as stated |
| `rejected: WHY` | 1 | a target fails, or the file is malformed in the part read, or an inductive block before the target fails |
| `declined: WHY` | 2 | a name is not found, the file has no INDEX, or Pestka cannot judge |
| `index invalid: WHY` | 2 | INDEX disagrees with the records; this says nothing about the file |

A rejection names the declaration that failed. It is a verdict on the file
as well: a full check would reject it too. A `checked` result says nothing
about the declarations after the last target, nor about the proofs and
values admitted unchecked. For example, a theorem that uses a lemma whose
proof is wrong is `checked`, since the lemma's proof is not looked at.

The INDEX is trusted for nothing. Pestka decodes the whole section and
checks its sizes, the front coding of the name table, that the keys are in
strictly increasing order, and that every declaration index is in range.
While reading MAIN it checks, for each declaration asked for, that its
record sits at the offset INDEX gives, has the kind INDEX gives, has the
proof block INDEX gives, and declares the name that led to it. Any
disagreement ends the check as `index invalid`. A name INDEX does not hold
is `not found`. Pestka cannot tell an INDEX that leaves a name out from a
file without that name, short of reading all of MAIN.

## Checking order

Pestka may check declarations out of file order, grouped by namespace, which
makes its caches work better. Before it does, it checks in file order every
declaration up to the one that declares the last of the constants that
literals depend on (`Nat`, `String`, `String.ofList`, `List`, `Char`,
`Char.ofNat`). The format guarantees the rest is safe: a proof block can only
name constants declared before its theorem, and declared names are unique.

## Limits

Pestka declines a file, rather than rejecting it, when it hits one of its own
limits:

- A proof block with more than 2^24 expressions. The theorem is declined when
  it is checked, so an earlier real error in the file still wins. A count
  above 2^32 - 1 is not a limit but a format error: the file is rejected at
  the theorem's record in MAIN, as the spec says.
- Frontier entries of one kind that are not listed in increasing order.
  Canonical packers always list them in order.
- A number above 2^62 in an offset or length. Ids and counts are already at
  most 2^32 - 1 by the format.

## Error messages

Errors say where they are: the section, the byte offset and the record number,
for example `MAIN @ 1042: record 17: unknown name index 9`. An error inside a
proof block is reported as its theorem's failure, in declaration order:
`Foo.bar: PROOFS @ 18342117: record 12: C is not declared before the theorem`.
