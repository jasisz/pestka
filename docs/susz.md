# Susz

Susz (`.susz`, Polish for dried fruit: the export with the water of JSON
pressed out) is Pestka's binary export format. It carries the same records
as a lean4export 3.1.0 ndjson file, in the same order, without text to parse.
`pestka pack FILE.ndjson FILE.susz [0|2]` writes one, of version 2 unless
asked for 0; `pestka FILE.susz [WORKERS]` checks one, recognised by its first
four bytes. `pestka FILE.ndjson [WORKERS]` packs the export into version 2 in
memory, with no file between, and checks that, read by the same reader
(`NdjsonThroughSusz` in `main.av`); a file that cannot be packed, or whose
image the reader rejects, is read by the ndjson reader instead, so a bad
line is reported by its number as it always was.

This page describes version 0 and version 2, which Pestka writes and reads
today, and the rules every version keeps. Version 1, a tree of blocks for
workers to read at once, is a design of its own (branch `reader/susz-v1`),
not part of this page; version 2 does not build on it, and its number only
says that it came after.

## Rules

1. **The file is input, not a witness.** A Susz file holds structure only: no
   hashes, loose bound variable ranges or flags. A checker computes all of
   these itself, exactly as for ndjson. Every id a record names is looked up
   as an ndjson line's would be; a record that names an id not defined before
   it is an error. A damaged file is a different input, checked as it is.
   What a file says to help a reader (where blocks are, what the frontier
   holds, how many records a block has, a declaration's word on names
   placed, the marks) is held to the records it describes, and a file whose
   hints disagree with its records is rejected: every reader verifies every
   hint, so two readers that follow this page cannot disagree on a file.
   The verdict `accepted` is given only once the whole file was read and
   verified.
2. **Declaration order is content.** Declarations keep their order in the
   export. Admission to the environment, the rule that a declaration names
   only constants placed before it, and the decision whether checking may be
   reordered (Pestka's `placed`, see `CheckedByNamespace` in
   `check/decl.av`) are all computed from that order, never from how the file
   is laid out.
3. **Layout is a hint.** Blocks, their order and their sizes (version 1
   onwards) may only change how fast a file is read, never what is checked
   or what is reported.
4. **Errors are deterministic.** A structural error of the header, the main
   block, the frontier or the trailer rejects the file before any
   declaration is checked; it is reported for the first bad record in file
   order, named by its number within its block (`record N: ...`). A
   structural error of a proof block (version 2) is an error of that block's
   declaration: it is reported, as `NAME: proof record N: ...` (N counting
   the block's records from 1, its count not being one) or `NAME: proof
   block: ...` for the block as a whole, in the order of declarations with
   every other failure, the earliest declaration's first. Within one
   declaration its building failures (its name already taken, its universe
   parameters named twice) come first, then its block's error, then any
   failure of checking it. So the verdict is the same on any number of
   workers, and the same for a reader that decodes every block while
   reading as for one that decodes each when its declaration is checked.
   Errors found while checking are the same as for the ndjson file the Susz
   file was packed from, since the reader builds the same tables through the
   same functions.
5. **Packing is deterministic.** The same ndjson file gives the same bytes.
6. **Unknown version, rejected.** A reader rejects a version it does not
   know; Pestka reads versions 0 and 2.

## Encoding

All fixed-width integers are little-endian. A *varint* is an unsigned
integer in little-endian base 128: seven bits per byte, low bits first, the
high bit set on every byte but the last; at most 10 bytes. A *string* is a
varint byte length followed by that many bytes of UTF-8. A *list* is a varint
count followed by that many varints. A *bool* is one byte, 0 or 1.

Ids are implicit and dense, as in the ndjson files lean4export writes: names
are numbered from 1 (0 is the anonymous name), levels from 1 (0 is the zero
level), expressions from 0, declarations from 0, each in record order. A name
or level is named by its id. An expression is named by **how far back** it
is: `d` means the expression whose id is the next expression id minus `d`;
`d` is at least 1, so only earlier expressions can be named (`d = 0`
names nothing and is an unknown expression).

### File (version 0)

```
header   "SUSZ" | version: u8 = 0 | 3 bytes = 0 | meta: string
block 0  records ...
trailer  counts | blocks | trailer length: u32 | "ZSUS"
```

- `meta` is the text of the `meta` object of the ndjson header line,
  `{"meta":<meta>}`; its `format.version` is checked as the header line's is.
- The trailer ends the file. Its last eight bytes are its own length (all of
  it, these eight bytes included) and the closing signature, so a reader
  finds it from the end of the file.
- `counts`: four u32, the next name, level, expression and declaration id
  after the last record (names and levels count the implicit 0).
- `blocks`: a u32 count, then for each block its byte offset and length (two
  u64) and the first name, level, expression and declaration id it defines
  (four u32). Version 0 has exactly one block, starting at 1, 1, 0, 0, and
  the reader checks the counts against what it read.

### Records

A record is a tag byte and its fields.

| Tag | Record | Fields |
| --- | --- | --- |
| 1 | name `str` | prefix name, string |
| 2 | name `num` | prefix name, number varint |
| 3 | level `succ` | level |
| 4 | level `max` | level, level |
| 5 | level `imax` | level, level |
| 6 | level `param` | name |
| 7 | `bvar` | index varint |
| 8 | `sort` | level |
| 9 | `const` | name, list of levels |
| 10 | `app` | function back, argument back |
| 11 | `lam` | binder byte, name, type back, body back |
| 12 | `forallE` | binder byte, name, type back, body back |
| 13 | `letE` | name, type back, value back, body back |
| 14 | `natVal` | string of decimal digits (any size) |
| 15 | `strVal` | string |
| 16 | `proj` | structure name, field index varint, structure back |
| 17 | `mdata` | wrapped expression back (the metadata itself is not kept) |
| 18 | declaration | kind byte, then its fields |

Binder byte: 0 default, 1 implicit, 2 strict implicit, 3 instance implicit.
`letE`'s `nondep` is not kept: it only matters to elaboration.

A declaration's *head* is its name, its list of universe parameter names and
its type back. Kinds:

| Kind | Declaration | Fields after the kind |
| --- | --- | --- |
| 0 | axiom | head, unsafe bool |
| 1 | definition | head, value back, hints, safety byte, list of names (`all`) |
| 2 | theorem | head, value back, list of names (`all`) |
| 3 | opaque | head, value back, unsafe bool, list of names (`all`) |
| 4 | quotient | head, kind byte: 0 type, 1 ctor, 2 lift, 3 ind |
| 5 | inductive block | types, constructors, recursors, each a varint count and the parts |

Hints: byte 0 opaque, 1 abbrev, 2 regular followed by the height varint.
Safety: 0 safe, 1 unsafe, 2 partial.

In an inductive block a type is: head, unsafe bool, numParams, numIndices,
list `all`, list `ctors`, numNested, isRec bool, isReflexive bool. A
constructor: head, unsafe bool, inductive type's name, cidx, numParams,
numFields. A recursor: head, unsafe bool, list `all`, numParams, numIndices,
numMotives, numMinors, rules (a varint count of: constructor name, nfields,
right-hand side back), k bool. Numbers are varints.

## Version 2: proofs in blocks of their own

On mathlib 66.9 M of the 104.9 M expressions belong to a single theorem's
proof: no declaration reaches them but through that theorem's value. Version
2 keeps each such proof in a block of its own, which a reader may leave as
bytes until the theorem is checked, and decode then into a term that lives
only while it is checked (`Core.Lazy`).

```
header   "SUSZ" | version: u8 = 2 | 3 bytes = 0 | meta: string
main     records ...
proofs   blocks ...
trailer  counts | main offset, length: u64 | proofs offset, length: u64 | trailer length: u32 = 56 | "ZSUS"
```

- `counts`: four u32, the next name, level, expression and declaration id
  after the main block; the expressions are the main block's.
- The proof section starts where the main block ends and ends where the
  trailer starts.

### Main block

Records 1 to 18 as in version 0, with ids numbered as there over the main
block alone, and:

| Tag | Record | Fields |
| --- | --- | --- |
| 18, kind 6 | theorem with a proof block | head, block length varint, placed bool, list of names (`all`) |
| 19 | frontier entry | kind byte: 0 name, 1 level, 2 expression; how far back varint |

A frontier entry names the name, level or expression `d` back from the next
of its kind (`d` at least 1; for names and levels the implicit 0 counts, so
`d` = 1 before any name record names the anonymous name). The entries of
each kind are numbered from 0 in record order: they are the frontier, all a
proof block may name outside itself.

A kind-6 theorem's block is the next block of the proof section: the first
kind-6 declaration's block starts the section, and each block starts where
the one before ended. The blocks must fill the section exactly; a file whose
lengths disagree with the section is rejected. Only theorems have blocks,
and Pestka skips no theorem, so every block of an accepted file was decoded.

### Proof blocks

A block is a count varint, the number of expression records it holds (at
least 1, and at most half its length, since an expression record takes at
least two bytes), then records until that many expression records are read;
the block must end there. The last expression record is the theorem's
value. Records:

- Expression records 7 to 17 as in version 0, but an expression reference
  `r` from the block's expression `k` (counted from 0) names the block's own
  expression `k - r` when `1 <= r <= k`, and otherwise frontier expression
  `r - k - 1`. A name is a frontier name index, a level a frontier level
  index. Only frontier entries listed before the block's declaration record
  may be named, so a proof holds only expressions read before its theorem.
- `19 | mark: varint`: the expression records after it stood before
  declaration `mark` in the export. A block's mark starts at 0, never goes
  down, and is never past the block's own declaration.

### Placed

Pestka checks out of file order only when every declaration names
constants placed before it alone (`NamesPlacedWhereRead`,
`CheckedByNamespace`): the ndjson reader holds the constants each
expression line names (a constant's own, a projection's structure, `Nat`
for a number, and `String`, `String.ofList`, `List`, `Char`, `Char.ofNat`
for a string) against the next declaration line, which must have them
placed before it, or place them itself as an inductive block Pestka does
not skip. Version 2 decides it the same way for every file:

- the main block's records as in ndjson;
- each proof block's records against their marks: a name a record names
  must be placed before declaration `mark`, or by it as such an inductive
  block (`PlaceCodes` in `core/lazy.av`, `FrontierAndPlaces` in
  `export/susz.av`);
- the placed bool of a kind-6 declaration says whether its block's records
  all pass. The reader takes it into the decision while reading; decoding
  the block holds it to the records, and a block whose bool disagrees is an
  error of its declaration.

A file `pestka pack` writes keeps every expression's mark from the export,
so the decision is that of the ndjson file it was packed from;
`pestka --show-placed` prints it. If a block's bool is wrong, the decision
may differ, but that declaration fails, and every declaration before it
names only constants placed before it, so the earliest failure, the one
reported, is the same in any order of checking.

### Limits

A reader rejects rather than allocates from the file: a block's count is
held to its length before any room is made for it; lists and strings are
read only as far as the bytes go; the proof section and every block lie
within the file. A record of the main block longer than 1 MB that crosses
a 16 MB chunk is declined, as in version 0, and so is a literal longer than
1 MB in a proof block, or a block of more than 2^24 expressions (Aver's
largest vector).

### Packing

`pestka pack` writes version 0 and rewrites it (`Export.Split`): every
expression only one theorem's value reaches goes to that theorem's block,
in export order, after a mark record wherever its mark changes; the rest
stays in the main block, renumbered densely, each frontier entry right
after its item (the anonymous name's and level zero's first). An
expression no declaration reaches stays in the main block.
`proto/lazypack` writes the same bytes from a version-0 file, apart from
Pestka, as a check of both.

## Later versions

A table of declaration headers read first, and the main block split for
workers to read at once (as in version 1), would let several readers share
the main block's work. Blocks could start at 4 KB boundaries for a future
memory-mapped reader. A hash of the source ndjson file and a checksum may be
added to the header, as information only.
