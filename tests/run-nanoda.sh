#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: run-nanoda.sh NANODA_BIN FILE.ndjson" >&2
    exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$1" "$script_dir/nanoda.json" < "$2"
