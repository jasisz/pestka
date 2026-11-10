# Susz

Susz (`.susz`, Polish for dried fruit: the export with the water of JSON
pressed out) is Pestka's binary export format. It carries the same records
as a lean4export 3.1.0 ndjson file, in the same order, without text to parse.
`pestka pack FILE.ndjson FILE.susz` writes one; `pestka FILE.susz [WORKERS]`
checks one, recognised by its first four bytes.

This page describes version 0, which Pestka writes and reads today, and the
rules later versions keep.

## Rules

1. **The file is input, not a witness.** A Susz file holds structure only: no
   hashes, loose bound variable ranges or flags. A checker computes all of
   these itself, exactly as for ndjson. Every id a record names is looked up
   as an ndjson line's would be; a record that names an id not defined before
   it is an error. A damaged file is a different input, checked as it is.
2. **Declaration order is content.** Declarations keep their order in the
   export. Admission to the environment, the rule that a declaration names
   only constants placed before it, and the decision whether checking may be
   reordered (Pestka's `placed`, see `CheckedByNamespace` in
   `check/decl.av`) are all computed from that order, never from how the file
   is laid out.
3. **Layout is a hint.** Blocks, their order and their sizes (version 1
   onwards) may only change how fast a file is read, never what is checked
   or what is reported.
4. **Errors are deterministic.** A structural error is reported for the
   first bad record in file order, named by its number within its block
   (`record N: ...`), whatever the number of workers. Errors found while
   checking are the same as for the ndjson file the Susz file was packed
   from, since the reader builds the same tables through the same functions.
5. **Packing is deterministic.** The same ndjson file gives the same bytes.
6. **Unknown version, rejected.** A reader rejects a version it does not
   know.

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

### File

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

## Later versions

Version 1 is planned to split the file for workers, keeping rules 1 to 4:

- a table of declaration headers (name, parameters, type, kind) in the
  export's order, which is what admission and the `placed` check read;
- one shared block with the names, levels and the expressions that several
  declarations use (about 30 M expressions on mathlib), read first;
- blocks of declaration bodies (values and proofs) grouped the way Pestka
  checks them (`CheckedByNamespace`), each naming only itself and the shared
  block, so that workers can read their blocks at once; on mathlib 66.9 M of
  the 74.8 M expressions only proofs reach belong to a single theorem.

Blocks would start at 4 KB boundaries for a future memory-mapped reader, and
the block directory would let a checker read one declaration with only the
blocks it needs. A hash of the source ndjson file and a checksum may be
added to the header, as information only.
