#!/bin/sh
# Subset checks (--only, docs/susz.md "Checking part of a file") on small
# files: tests/only/deps.ndjson, written by hand, and the wellformed export
# small.ndjson, each packed into Susz with INDEX. Each case gives the exit
# status and the last line it expects, the same on one worker and on four.
#
# deps.ndjson: axioms A : Prop and a : A, then theorems good : A := a,
# badDep : A := A (ill typed), useBad : A := badDep, bad : A := A (ill
# typed), last : A := good and good.twice : A := good. A full check rejects
# it at badDep. useBad is checked: the proof of badDep, before it, is
# admitted unchecked.
#
# INDEX damaged by tests/indexbad.py ends a subset check that relies on the
# damaged entry as index invalid, and leaves a full check's verdict as it
# was.
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
tmp=$(mktemp -d) || exit 1
trap 'rm -rf "$tmp"' EXIT
fail=0
run() {
  # run WANT PATTERN ARGS...: the status WANT and a last line matching
  # PATTERN, on one worker and on four.
  want=$1 pat=$2
  shift 2
  for w in 1 4; do
    "$root/bin/capped" 2000 20 "$bin" "$@" "$w" >"$tmp/out" 2>&1
    got=$?
    last=$(tail -1 "$tmp/out")
    if [ "$got" -ne "$want" ] || ! printf '%s\n' "$last" | grep -Eq "$pat"; then
      echo "FAIL $* [$w]: status $got, expected $want; $last"
      fail=1
      return 1
    fi
  done
  echo "ok   $(printf '%s ' "$@" | sed "s|$tmp/||g; s|$root/||g")-> $last"
}
deps="$tmp/deps.susz"
"$bin" pack "$root/tests/only/deps.ndjson" "$deps" >/dev/null || { echo "FAIL cannot pack deps.ndjson"; exit 1; }
"$bin" pack --no-index "$root/tests/only/deps.ndjson" "$tmp/deps-n.susz" >/dev/null
run 1 '^rejected: badDep: ' "$deps"
run 0 '^checked: good \(subset; 2 earlier declarations admitted unchecked\)$' --only good "$deps"
run 0 '^checked: a \(subset; 1 earlier declarations admitted unchecked\)$' --only a "$deps"
run 1 '^rejected: bad: declaration type mismatch$' --only bad "$deps"
run 1 '^rejected: badDep: declaration type mismatch$' --only badDep "$deps"
run 0 '^checked: useBad \(subset; 4 earlier declarations admitted unchecked\)$' --only useBad "$deps"
run 0 '^checked: last,good \(2 declarations; subset; 5 earlier declarations admitted unchecked\)$' --only last,good "$deps"
run 0 '^checked: good\.\* \(subset; 7 earlier declarations admitted unchecked\)$' --only 'good.*' "$deps"
run 1 '^rejected: bad: declaration type mismatch$' --only useBad,bad "$deps"
run 2 '^declined: not found: nope, A\.x: ' --only nope,A,A.x "$deps"
run 2 '^declined: not found: a\.\*: ' --only 'a.*' "$deps"
run 2 '^declined: .*has no INDEX section.*--no-index' --only good "$tmp/deps-n.susz"
run 2 '^declined: --only checks part of a Susz file' --only good "$root/tests/only/deps.ndjson"
run 2 '^declined: usage: ' --only
damage() {
  # damage MODE NAME: deps.susz with INDEX damaged.
  python3 -I "$root/tests/indexbad.py" "$1" "$deps" "$tmp/bad.susz" $2 || { echo "FAIL indexbad $1"; fail=1; return 1; }
}
damage garbage && run 2 '^index invalid: INDEX @ [0-9]+: ' --only good "$tmp/bad.susz" &&
  run 1 '^rejected: badDep: ' "$tmp/bad.susz"
damage offset && run 2 '^index invalid: INDEX @ [0-9]+: entry [0-9]+: offset ' --only a "$tmp/bad.susz" &&
  run 1 '^rejected: badDep: ' "$tmp/bad.susz"
damage decl useBad && run 2 '^index invalid: INDEX @ [0-9]+: a name INDEX gives declaration [0-9]+ is not declared by it$' --only useBad "$tmp/bad.susz" &&
  run 0 '^checked: good ' --only good "$tmp/bad.susz"
damage kind a && run 2 '^index invalid: INDEX @ [0-9]+: entry 1: kind 1, its record.s is 0$' --only a "$tmp/bad.susz"
# small.ndjson: inductive types, structures and literals before the
# targets, checked as the environment is built.
small="$tmp/small.susz"
"$bin" pack "$root/tests/export/wellformed/small.ndjson" "$small" >/dev/null || { echo "FAIL cannot pack small.ndjson"; exit 1; }
run 0 '^accepted$' "$small"
run 0 '^checked: Small\.instReprPoint \(subset; 305 earlier declarations admitted unchecked\)$' --only Small.instReprPoint "$small"
run 0 '^checked: Nat\.ne_of_beq_eq_false \(subset; 294 earlier ' --only Nat.ne_of_beq_eq_false "$small"
run 0 '^checked: Small\.\* \(20 declarations; subset; 288 earlier ' --only 'Small.*' "$small"
run 0 '^checked: HMod\.mk \(subset; 134 earlier ' --only HMod.mk "$small"
run 0 '^checked: _private\.Init\.Prelude\.0\.Nat\.ne_of_beq_eq_false\.match_1_1 \(subset' --only _private.Init.Prelude.0.Nat.ne_of_beq_eq_false.match_1_1 "$small"
# An ill-typed declaration of tests/export/illtyped, asked for by name, is
# rejected as a full check rejects it.
for f in fin swap; do
  s="$tmp/$f.susz"
  "$bin" pack "$root/tests/export/illtyped/$f.ndjson" "$s" >/dev/null || { echo "FAIL cannot pack $f.ndjson"; fail=1; continue; }
  "$bin" "$s" 1 >"$tmp/full" 2>&1
  name=$(tail -1 "$tmp/full" | sed -nE 's/^rejected: ([^:]+): .*/\1/p')
  [ -n "$name" ] || { echo "FAIL $f: the full check names no declaration"; fail=1; continue; }
  run 1 "^$(tail -1 "$tmp/full" | sed 's/[].[*^$()+?{}|\\]/\\&/g')\$" --only "$name" "$s"
done
exit $fail
