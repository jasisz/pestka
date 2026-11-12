# Susz

Susz (`.susz`, Polish for dried fruit: the export with the water of JSON
pressed out) is the binary form of a lean4export 3.1 export that Pestka reads
and writes. The format is **Susz 1**, specified apart from Pestka, with the
reference Rust crate `susz` (spec: `susz-v-next.md`, to become the crate's
`SPEC.md`). This page lists only what is Pestka's own: its commands and its
implementation limits. The internal versions 0 and 2 are gone; a file of
either is rejected by its signature.

## Commands

- `pestka pack [--no-index] FILE.ndjson FILE.susz [WORKERS]` writes the
  canonical layout (spec section 9): MAIN, PROOFS, INDEX (left out with
  `--no-index`), SOURCE. Its bytes are those of `susz pack`, for both
  settings.
- `pestka FILE.susz [WORKERS]` checks a file, recognised by its first four
  bytes, `SUSZ`. The verdict never depends on INDEX or SOURCE, which a full
  check does not read.
- `pestka FILE.ndjson [WORKERS]` packs the export into Susz 1 in memory,
  without INDEX, and checks that (`NdjsonThroughSusz` in `main.av`); an
  export the packer refuses, or whose image the reader does not accept, is
  read by the ndjson reader, so a bad line is reported by its number.

The packer refuses what a reader would reject: a name declared twice, a
number past 2^64 - 1 where the format holds a u64, more than 2^32 - 1 items
of a kind, and a proof block naming a constant not declared before its
theorem (rule P). `mdata` lines are not written; their ids stand for the
expression they wrap.

## Checking order

Pestka may check declarations out of file order (`CheckedByNamespace` in
`check/decl.av`). It does so only when every constant a declaration's MAIN
expressions name is placed before it (`NamesPlacedWhereRead`), and checks the
declarations up to the one placing the last constant a literal stands for
(`Nat`, `String`, `String.ofList`, `List`, `Char`, `Char.ofNat`) in file order
first (`LiteralPrefix`, spec OWNER-9). Proof blocks obey rule P and declared
names are unique, so a block never names a constant that a checking order
could make visible to it.

## Implementation limits

Each declines the file (spec 7.2), as a function of its bytes alone:

- A proof block of more than 2^24 expressions (Aver's largest vector): the
  theorem declines when it is checked, in the order of declarations, so an
  earlier failure still rejects the file.
- Frontier entries of one kind whose items do not grow: Pestka's packer, as
  every canonical packer, lists items in the order of their records; a file
  that lists an item below the last one of its kind is declined rather than
  checked against every item listed (an item equal to the last one is a
  duplicate and rejected).
- A number in a field Pestka holds as a machine word past its range: ids and
  counts are at most 2^32 - 1 by the format; offsets and lengths below 2^62.

A MAIN record longer than the 1 MB margin of the 16 MB chunks MAIN is read in
is read again from its start with a larger chunk; no record is declined for
its length.

## Error messages

Structural errors name the section (`header`, `trailer`, `directory`, `MAIN`,
`PROOFS`, `PAD`), the absolute offset of the record or field and the record's
number from 1, as the spec's section 8 asks, for example
`MAIN @ 1042: record 17: unknown name index 9`. A proof block's error is its
theorem's: `Foo.bar: PROOFS @ 18342117: record 12: C is not declared before
the theorem`, reported in the order of declarations with every other failure.
