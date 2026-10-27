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
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
fail=0
for dir in export/wellformed:0 export/malformed:1 export/illtyped:1 export/unsupported:2 soundness-findings:1; do
  name=${dir%%:*}
  want=${dir##*:}
  for f in "$root"/tests/"$name"/*.ndjson; do
    "$root/bin/capped" 2000 20 "$bin" "$f" >/dev/null 2>&1
    got=$?
    if [ "$got" -eq "$want" ]; then
      echo "ok   ${name#export/}/$(basename "$f")"
    else
      echo "FAIL ${name#export/}/$(basename "$f"): status $got, expected $want"
      fail=1
    fi
  done
done
exit $fail
