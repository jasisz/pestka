#!/bin/sh
# Packs every export the tests use into Susz (docs/susz.md) and checks that
# Pestka says the same about the Susz file as about the ndjson file: the same
# output, line for line, on one worker and on four, as given and with
# --reorder-always. A file pestka pack refuses (a malformed export the packer
# already finds bad) is listed and skipped. Also checks that packing is
# deterministic, and an export with two bad declarations.
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
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
  echo "FAIL $(basename "$nd") [$w $mode]: ndjson status $a, susz status $b"
  diff "$tmp/a" "$tmp/b" | head -4
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
  for w in 1 4; do
    for mode in "" --reorder-always; do
      same "$f" "$s" "$w" "$mode" || fail=1
    done
  done
  echo "ok   $(basename "$f")"
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
exit $fail
