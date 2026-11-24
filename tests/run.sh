#!/bin/sh
# Runs the compiled checker on every export under tests/export and compares the exit
# status with the one its directory expects:
#   wellformed/   0 (accepted)
#   malformed/    1 (rejected while reading)
#   illtyped/     1 (rejected by the checker: made from tests/export/PestkaBad.lean
#                    by mkbad.py, each a declaration the checker must not accept;
#                    walls_*Bad from tests/export/Walls.lean, origin_sumBad
#                    from tests/export/Origin.lean, nat_* from
#                    tests/export/NatSize.lean: a result past 128 MiB is
#                    refused before it is computed, as the reference does)
# The walls_*Good exports (tests/export/Walls.lean) hold only when definitional
# equality is tried in the right order: the wrong one computes 2^23 steps and
# runs past the 20 s cap. nat_shiftGood (NatSize.lean) shifts by 2^24 + 1
# bits, one past what Bits.shiftLeft took before Aver 0.36.1.
# origin_sumGood (tests/export/Origin.lean) holds only when a side of lazy
# delta that comes to the form the other side began at meets it: otherwise a
# loop of 300000 rounds runs past the 20 s cap.
# renov_* (wellformed/ and illtyped/) are tests of the kernel renovation's
# flags (lean4#16595), taken from the Arena's renovation tests
# (lean-kernel-arena, renovation/Renovation.lean), exported as format 3.2;
# renov_flags_* are made from them by hand: flags in a 3.1 export (read and
# used), and in malformed/ a 3.2 export whose type lacks its flags, a type
# with only some of them, and a 3.1 export mixing flagged blocks with others.
#   unsupported/  2 (declined: format version)
# and every export tests/soundness.py kept under tests/soundness-findings, each
# invalid, against 1 (rejected).
# Every file runs twice: as given, and with --reorder-always, which checks out
# of file order wherever the reader allows it, as mathlib is; these files are
# too small to pass the limits' unit that turns it on otherwise. The status
# must be the same.
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
# PESTKA_ARGS adds arguments before the file, for example --high-memory.
fail=0
for mode in "" --reorder-always; do
  tag=${mode:+" [$mode]"}
  for dir in export/wellformed:0 export/malformed:1 export/illtyped:1 export/unsupported:2 soundness-findings:1; do
    name=${dir%%:*}
    want=${dir##*:}
    for f in "$root"/tests/"$name"/*.ndjson; do
      "$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS $mode "$f" >/dev/null 2>&1
      got=$?
      if [ "$got" -eq "$want" ]; then
        echo "ok   ${name#export/}/$(basename "$f")$tag"
      else
        echo "FAIL ${name#export/}/$(basename "$f")$tag: status $got, expected $want"
        fail=1
      fi
    done
  done
done
# A theorem over 16382 binders, its innermost variable one past the 16383 a
# node's stored loose range saturates at: generated, as the export is 2.4 MB.
deep=$(mktemp) || exit 1
python3 "$root/tests/gen_deep_binder_export.py" 16382 "$deep"
"$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS "$deep" >/dev/null 2>&1
got=$?
rm -f "$deep"
if [ "$got" -eq 0 ]; then
  echo "ok   generated/deep-binder-16382"
else
  echo "FAIL generated/deep-binder-16382: status $got, expected 0"
  fail=1
fi
# Two lists of 200000 cells, equal only cell by cell, each tail one
# comparison deeper (DeepArgumentsResumed): equal, and with the last cell
# changed, unequal; before, a stack overflow. Generated, as each is 17 MB.
for kind in good bad; do
  python3 "$root/tests/gen_deep_list_export.py" 200000 "$deep" $([ $kind = bad ] && echo bad)
  "$root/bin/capped" 2000 20 "$bin" $PESTKA_ARGS "$deep" >/dev/null 2>&1
  got=$?
  want=0; [ $kind = bad ] && want=1
  if [ "$got" -eq "$want" ]; then
    echo "ok   generated/deep-list-200000-$kind"
  else
    echo "FAIL generated/deep-list-200000-$kind: status $got, expected $want"
    fail=1
  fi
done
rm -f "$deep"
exit $fail
