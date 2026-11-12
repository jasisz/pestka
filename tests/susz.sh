#!/bin/sh
# Packs every export the tests use into Susz 1 (docs/susz.md), with INDEX and
# without (--no-index), and checks that Pestka says the same about each Susz
# file as about the ndjson file: the same output, line for line, on one
# worker and on four, as given, with --reorder-always and with
# --show-placed. The last prints the reader's decision whether checking may
# leave file order, which must be the same for every format. A file pestka
# pack refuses (a malformed export the packer already finds bad) is listed
# and skipped. Also checks that packing is deterministic; that the file with
# INDEX and the one without differ only by INDEX and its directory entry
# (their outputs the same); that Pestka's packer and the Rust crate susz,
# written apart, give the same bytes for both, when SUSZ_BIN names the
# crate's binary; an export with two bad declarations; and files damaged by
# tests/suszbad.py: each rejected (or declined) with the message the damage
# calls for, the same on one worker and on four.
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
susz="${SUSZ_BIN:-}"
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
  # A malformed record is placed by its line in ndjson and by its offset and
  # record number in Susz (spec section 8); the rest must be the same.
  sed -E 's/^rejected: (line [0-9]+|MAIN @ [0-9]+: record [0-9]+): /rejected: /' "$tmp/a" >"$tmp/a2"
  sed -E 's/^rejected: (line [0-9]+|MAIN @ [0-9]+: record [0-9]+): /rejected: /' "$tmp/b" >"$tmp/b2"
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
  "$bin" pack --no-index "$f" "$s.n" >/dev/null 2>&1
  if [ -n "$susz" ]; then
    "$susz" pack "$f" "$s.z" >/dev/null 2>&1
    "$susz" pack "$f" "$s.zn" --no-index >/dev/null 2>&1
    if ! cmp -s "$s" "$s.z" || ! cmp -s "$s.n" "$s.zn"; then
      echo "FAIL $(basename "$f"): pestka pack and susz pack differ"
      fail=1
    fi
  fi
  for w in 1 4; do
    for mode in "" --reorder-always --show-placed; do
      same "$f" "$s" "$w" "$mode" || fail=1
      same "$f" "$s.n" "$w" "$mode" || fail=1
    done
  done
  workersAlike "$s" "" || fail=1
  workersAlike "$s" --reorder-always || fail=1
  echo "ok   $(basename "$f")"
}
unchanged() {
  # unchanged NDJSON MODE: the damaged file gives the same output as the
  # file as packed, on one worker and on four.
  s="$tmp/d.susz"
  "$bin" pack "$1" "$s" >/dev/null 2>&1 || return 0
  python3 -I "$root/tests/suszbad.py" "$2" "$s" "$s.bad"
  case $? in 3) echo "skip $(basename "$1") $2"; return 0 ;; 0) ;; *) echo "FAIL suszbad $2"; return 1 ;; esac
  for w in 1 4; do
    "$root/bin/capped" 2000 20 "$bin" "$s" $w >"$tmp/u1" 2>&1
    "$root/bin/capped" 2000 20 "$bin" "$s.bad" $w >"$tmp/u2" 2>&1
    if ! cmp -s "$tmp/u1" "$tmp/u2"; then
      echo "FAIL $(basename "$1") $2: the verdict changed"
      diff "$tmp/u1" "$tmp/u2" | head -4
      return 1
    fi
  done
  echo "ok   $(basename "$1") $2: $(tail -1 "$tmp/u2")"
}
declinedBy() {
  # declinedBy NDJSON MODE PATTERN: as damaged, but declined.
  s="$tmp/d.susz"
  "$bin" pack "$1" "$s" >/dev/null 2>&1 || return 0
  python3 -I "$root/tests/suszbad.py" "$2" "$s" "$s.bad"
  case $? in 3) echo "skip $(basename "$1") $2"; return 0 ;; 0) ;; *) echo "FAIL suszbad $2"; return 1 ;; esac
  workersAlike "$s.bad" "" || return 1
  if [ "$a" -ne 2 ] || ! tail -1 "$tmp/w1" | grep -Eq "^declined: .*$3"; then
    echo "FAIL $(basename "$1") $2: status $a, expected a decline matching '$3'"
    tail -1 "$tmp/w1"
    return 1
  fi
  echo "ok   $(basename "$1") $2: $(tail -1 "$tmp/w1")"
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
# Damaged files: a proof block's damage is its declaration's error, in the
# order of declarations; the rest rejects before checking.
small="$root/tests/export/wellformed/small.ndjson"
damaged "$small" tag "[^:]+: PROOFS @ [0-9]+: record 1: unknown record tag 99$" || fail=1
cp "$tmp/w1" "$tmp/first"
damaged "$small" twotags "[^:]+: PROOFS @ [0-9]+: record 1: unknown record tag 99$" || fail=1
if ! cmp -s "$tmp/first" "$tmp/w1"; then
  echo "FAIL twotags: the first damaged block in declaration order is not the one reported"
  fail=1
fi
damaged "$small" lastblock "PROOFS @ [0-9]+: record 1: unknown record tag 99$" || fail=1
damaged "$small" tag17 "PROOFS @ [0-9]+: record 1: unknown record tag 17$" || fail=1
damaged "$small" tag19 "PROOFS @ [0-9]+: record 1: unknown record tag 19$" || fail=1
damaged "$small" count "PROOFS @ [0-9]+: record [0-9]+: the block ends inside it$" || fail=1
damaged "$small" fewer "PROOFS @ [0-9]+: record [0-9]+: 1 bytes after the last record$|bytes after the last record$" || fail=1
damaged "$small" hugecount "MAIN @ [0-9]+: record [0-9]+: a proof block of [0-9]+ bytes cannot hold [0-9]+ expressions$" || fail=1
damaged "$small" ref "PROOFS @ [0-9]+: record [0-9]+: unknown expression reference 1073741824$" || fail=1
damaged "$small" late "PROOFS @ [0-9]+: record [0-9]+: unknown expression reference [0-9]+$" || fail=1
damaged "$small" rulep "PROOFS @ [0-9]+: record [0-9]+: .* is not declared before the theorem$" || fail=1
damaged "$small" nonminimal "PROOFS @ [0-9]+: record [0-9]+: a varint is not minimal or not below 2\^64$" || fail=1
damaged "$small" natzero "PROOFS @ [0-9]+: record [0-9]+: a Nat literal ends in a zero byte$" || fail=1
damaged "$small" dupname "MAIN @ [0-9]+: record [0-9]+: .* is declared twice$" || fail=1
damaged "$small" dupfront "MAIN @ [0-9]+: record [0-9]+: frontier (name|level|expression) [0-9]+ is listed twice$" || fail=1
damaged "$small" length "MAIN @ [0-9]+: record [0-9]+: a proof block of [0-9]+ bytes runs past PROOFS" || fail=1
damaged "$small" short "PROOFS @ [0-9]+: the proof blocks fill [0-9]+ of [0-9]+ bytes$" || fail=1
damaged "$small" frontier "MAIN @ [0-9]+: record [0-9]+: a frontier entry names nothing$" || fail=1
damaged "$small" counts "trailer @ [0-9]+: the counts" || fail=1
damaged "$small" magic "header @ 0: not a Susz 1 file$" || fail=1
damaged "$small" pad "PAD @ [0-9]+: a byte is not zero$" || fail=1
declinedBy "$small" major "header @ 8: Susz major version 2 is not known$" || fail=1
declinedBy "$small" must "the file needs a section Pestka does not know$" || fail=1
# Damage a full check never sees: the verdict is that of the file as packed.
unchanged "$small" index || fail=1
unchanged "$small" extra || fail=1
exit $fail
