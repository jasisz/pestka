#!/bin/sh
# Runs the compiled checker over the small Lean Kernel Arena test files and tallies the
# answers. DIR is the unpacked lean-arena-tests.tar.gz, with good/ and bad/
# subdirectories. Every file runs under bin/capped: MB megabytes of resident
# memory (default 2000) and SECONDS seconds (default 20). The perf/ tests and
# the large corpora are skipped: a perf test once peaked at 11 GB.
#
#   tests/arena.sh DIR [MB] [SECONDS]
#
# Prints one line per file not answered correctly, then the totals. A good
# file must be accepted (0) and a bad one rejected (1); a decline (2) is
# counted apart, as the Arena does.
dir=${1:?usage: tests/arena.sh DIR [MB] [SECONDS]}
mb=${2:-2000}
secs=${3:-20}
root=$(cd "$(dirname "$0")/.." && pwd)
bin="${PESTKA_BIN:-$root/.build/target/release/main}"
ok=0; declined=0; wrong=0; crashed=0
for kind in good bad; do
  [ "$kind" = good ] && want=0 || want=1
  for f in $(find "$dir/$kind" -name '*.ndjson' -not -path '*/perf/*' -size -4000k | sort); do
    "$root/bin/capped" "$mb" "$secs" "$bin" "$f" >/dev/null 2>&1
    got=$?
    name=${f#"$dir"/}
    if [ "$got" -eq "$want" ]; then
      ok=$((ok + 1))
    elif [ "$got" -eq 2 ]; then
      declined=$((declined + 1)); echo "DECLINED $name"
    elif [ "$got" -eq 0 ] || [ "$got" -eq 1 ]; then
      wrong=$((wrong + 1)); echo "WRONG    $name: status $got"
    else
      crashed=$((crashed + 1)); echo "CRASH    $name: status $got"
    fi
  done
done
echo "correct $ok, declined $declined, wrong $wrong, crashed or capped $crashed"
