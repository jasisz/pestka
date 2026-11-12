# Susz in Pestka

Pestka reads [Susz 1](https://github.com/jasisz/susz). The format, its rules
and the reference `susz` tool live in that repository. This page only covers
what is specific to Pestka.

## Commands

```sh
main FILE.susz [WORKERS]                                # check a Susz file
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
