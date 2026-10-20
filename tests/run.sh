#!/bin/sh
# Runs bin/pestka on every export under tests/export and compares the exit
# status with the one its directory expects:
#   wellformed/   0 (accepted)
#   malformed/    1 (rejected while reading)
#   unsupported/  2 (declined: format version)
root=$(cd "$(dirname "$0")/.." && pwd)
fail=0
for dir in wellformed:0 malformed:1 unsupported:2; do
  name=${dir%%:*}
  want=${dir##*:}
  for f in "$root"/tests/export/"$name"/*.ndjson; do
    "$root/bin/capped" 2000 20 "$root/bin/pestka" "$f" >/dev/null 2>&1
    got=$?
    if [ "$got" -eq "$want" ]; then
      echo "ok   $name/$(basename "$f")"
    else
      echo "FAIL $name/$(basename "$f"): status $got, expected $want"
      fail=1
    fi
  done
done
exit $fail
