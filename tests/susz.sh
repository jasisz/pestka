#!/bin/sh
# Packs every export the tests use into Susz (docs/susz.md), of version 2
# (pestka pack's default) and of version 0, and checks that Pestka says the
# same about each Susz file as about the ndjson file: the same output, line
# for line, on one worker and on four, as given, with --reorder-always and
# with --show-placed. The last prints the reader's decision whether checking
# may leave file order, which must be the same for every format:
# tests/export/wellformed/placedMarks.ndjson has a proof whose expression
# stood before an earlier declaration than its theorem, and
# tests/export/illtyped/placedWaits.ndjson an expression no declaration uses
# naming a constant placed later. A file pestka pack refuses (a malformed
# export the packer already finds bad) is listed and skipped. Also checks
# that packing is deterministic; that Pestka's packer and proto/lazypack,
# written apart, give the same bytes, when lazypack is built (LAZYPACK names
# it, or proto/lazypack/target/release/lazypack); an export with two bad
# declarations; and files of version 2 damaged by tests/suszbad.py: each
# rejected, with the message the damage calls for, the same on one worker
# and on four.
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
lazypack="${LAZYPACK:-$root/proto/lazypack/target/release/lazypack}"
tmp=$(mktemp -d) || exit 1
trap 'rm -rf "$tmp"' EXIT
fail=0
same() {
  # same NDJSON SUSZ WORKERS [MODE]: one check of both files.
  nd=$1 sz=$2 w=$3 mode=$4
  "$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS $mode "$nd" "$w" >"$tmp/a" 2>&1
  a=$?
  "$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS $mode "$sz" "$w" >"$tmp/b" 2>&1
  b=$?
  if [ "$a" -eq "$b" ] && cmp -s "$tmp/a" "$tmp/b"; then
    return 0
  fi
  # A malformed record is placed by its line in ndjson and by its record
  # number in Susz (docs/susz.md, rule 4); the rest must be the same.
  sed -E 's/^rejected: (line|record) [0-9]+: /rejected: /' "$tmp/a" >"$tmp/a2"
  sed -E 's/^rejected: (line|record) [0-9]+: /rejected: /' "$tmp/b" >"$tmp/b2"
  if [ "$a" -eq "$b" ] && cmp -s "$tmp/a2" "$tmp/b2"; then
    return 0
  fi
  echo "FAIL $(basename "$nd") [$(basename "$sz") $w $mode]: ndjson status $a, susz status $b"
  diff "$tmp/a" "$tmp/b" | head -4
  return 1
}
workersAlike() {
  # workersAlike SUSZ [MODE]: the same output on one worker and on four.
  "$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS $2 "$1" 1 >"$tmp/w1" 2>&1
  a=$?
  "$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS $2 "$1" 4 >"$tmp/w4" 2>&1
  b=$?
  if [ "$a" -eq "$b" ] && cmp -s "$tmp/w1" "$tmp/w4"; then
    return 0
  fi
  echo "FAIL $(basename "$1") [$2]: one worker and four differ"
  diff "$tmp/w1" "$tmp/w4" | head -4
  return 1
}
check() {
  f=$1
  s="$tmp/$(basename "$f" .ndjson).susz"
  if ! "$bin" pack "$f" "$s" >"$tmp/pack" 2>&1; then
    echo "skip $(basename "$f"): $(cat "$tmp/pack")"
    return 0
  fi
  "$bin" pack "$f" "$s.again" >/dev/null 2>&1
  if ! cmp -s "$s" "$s.again"; then
    echo "FAIL $(basename "$f"): packing twice gave different bytes"
    fail=1
  fi
  "$bin" pack "$f" "$s.0" 0 >/dev/null 2>&1
  if [ -x "$lazypack" ]; then
    "$lazypack" "$s.0" "$s.lp" 2>/dev/null
    if ! cmp -s "$s" "$s.lp"; then
      echo "FAIL $(basename "$f"): pestka pack and lazypack differ"
      fail=1
    fi
  fi
  for w in 1 4; do
    for mode in "" --reorder-always --show-placed; do
      same "$f" "$s" "$w" "$mode" || fail=1
      same "$f" "$s.0" "$w" "$mode" || fail=1
    done
  done
  workersAlike "$s" "" || fail=1
  workersAlike "$s" --reorder-always || fail=1
  echo "ok   $(basename "$f")"
}
damaged() {
  # damaged NDJSON MODE PATTERN: the file packed, damaged by MODE and
  # rejected with a message matching PATTERN, the same on one worker and on
  # four.
  s="$tmp/d.susz"
  "$bin" pack "$1" "$s" >/dev/null 2>&1 || return 0
  python3 -I "$root/tests/suszbad.py" "$2" "$s" "$s.bad"
  case $? in 3) echo "skip $(basename "$1") $2"; return 0 ;; 0) ;; *) echo "FAIL suszbad $2"; return 1 ;; esac
  workersAlike "$s.bad" "" || return 1
  if [ "$a" -ne 1 ] || ! tail -1 "$tmp/w1" | grep -Eq "^rejected: .*$3"; then
    echo "FAIL $(basename "$1") $2: status $a, expected a rejection matching '$3'"
    tail -1 "$tmp/w1"
    return 1
  fi
  echo "ok   $(basename "$1") $2: $(tail -1 "$tmp/w1")"
}
for f in "$root"/tests/export/*/*.ndjson "$root"/tests/soundness-findings/*.ndjson; do
  check "$f"
done
# Two bad declarations, one after the other: the verdict names the same one
# from either file, on one worker and on four.
two="$tmp/two.ndjson"
python3 -I "$root/tests/export/mkbad.py" "$root/tests/export/wellformed/levelled_fin.ndjson" "$tmp/one.ndjson" PestkaBad.finGood "" 0 >/dev/null &&
  python3 -I "$root/tests/export/mkbad.py" "$tmp/one.ndjson" "$two" PestkaBad.fin "" 0 >/dev/null &&
  check "$two" && grep -h "rejected" "$tmp/a"
# Damaged files of version 2: a proof block's damage is its declaration's
# error, in the order of declarations; the rest rejects before checking.
small="$root/tests/export/wellformed/small.ndjson"
marks="$root/tests/export/wellformed/placedMarks.ndjson"
damaged "$small" tag "[^:]+: proof record [0-9]+: unknown record tag 99$" || fail=1
cp "$tmp/w1" "$tmp/first"
damaged "$small" twotags "[^:]+: proof record [0-9]+: unknown record tag 99$" || fail=1
if ! cmp -s "$tmp/first" "$tmp/w1"; then
  echo "FAIL twotags: the first damaged block in declaration order is not the one reported"
  fail=1
fi
damaged "$small" lastblock "proof record [0-9]+: unknown record tag 99$" || fail=1
damaged "$small" count "proof record [0-9]+: the block ends inside it$" || fail=1
damaged "$small" fewer "proof block: [0-9]+ bytes after the last record$" || fail=1
damaged "$small" hugecount "proof block: a count of 1099511627776 expressions in [0-9]+ bytes$" || fail=1
damaged "$small" ref "proof record [0-9]+: unknown expression reference 1073741824$" || fail=1
damaged "$small" late "proof record [0-9]+: unknown expression reference [0-9]+$" || fail=1
damaged "$small" mark "proof record 1: mark [0-9]+ is below the mark before it" || fail=1
damaged "$small" markdown "proof record [0-9]+: .* is not placed before declaration 0, but the declaration says every name is$" || fail=1
damaged "$small" placed "proof block: the declaration says a name is named before it is placed, but none is$" || fail=1
damaged "$marks" placed "T: proof record 2: C is not placed before declaration 1, but the declaration says every name is$" || fail=1
damaged "$small" length "the proof blocks take [0-9]+ bytes, the proof section [0-9]+$" || fail=1
damaged "$small" section "the proof section does not lie between the main block and the trailer$" || fail=1
damaged "$small" frontier "record [0-9]+: a frontier entry names nothing$" || fail=1
damaged "$small" version "Susz version 3 is not known$" || fail=1
exit $fail
