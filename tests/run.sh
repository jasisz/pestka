#!/bin/sh
# Runs the compiled checker on every export under tests/export and compares the exit
# status with the one its directory expects:
#   wellformed/   0 (accepted)
#   malformed/    1 (rejected while reading)
#   illtyped/     1 (rejected by the checker: made from tests/export/PestkaBad.lean
#                    by mkbad.py, each a declaration the checker must not accept)
#   unsupported/  2 (declined: format version)
# and every export tests/soundness.py kept under tests/soundness-findings, each
# invalid, against 1 (rejected).
# Every file runs twice: as given, and with --reorder-always, which checks out
# of file order wherever the reader allows it, as mathlib is; these files are
# too small to pass the limits' unit that turns it on otherwise. The status
# must be the same.
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
# PESTKA_ARGS adds arguments before the file, for example --low-memory.
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
exit $fail
