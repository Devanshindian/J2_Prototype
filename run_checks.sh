#!/bin/sh
# Both suites at once: j2_flow_test.py --fast and --fast --browser, each in its own throwaway copy of the repo (files linked, runs/ linked run by run),
# so the runs the tests make never meet. Logs are unbuffered, so progress shows while they run.
# Usage: ./run_checks.sh ['glob of run folders to leave out', e.g. 'j2-20261103-*' for live runs still being written]
set -u
here=$(cd "$(dirname "$0")" && pwd); skip=${1:-}
mirror(){ d=$(mktemp -d "${TMPDIR:-/tmp}/j2-checks-XXXXXX"); mkdir "$d/runs"
  for f in "$here"/* "$here"/.env "$here"/.venv; do [ -e "$f" ] && [ "$(basename "$f")" != runs ] && ln -s "$f" "$d/"; done
  for r in "$here"/runs/*; do case "$(basename "$r")" in $skip) ;; *) ln -s "$r" "$d/runs/";; esac; done; echo "$d"; }
a=$(mirror); b=$(mirror)
echo "fast:    $a/fast.log"; echo "browser: $b/browser.log"
( cd "$a" && .venv/bin/python -u j2_flow_test.py --fast > fast.log 2>&1; echo $? > fast.exit ) &
( cd "$b" && .venv/bin/python -u j2_flow_test.py --fast --browser > browser.log 2>&1; echo $? > browser.exit ) &
wait
for x in "$a/fast" "$b/browser"; do echo "$(basename "$x"): exit $(cat "$x.exit"), $(grep -c ' ok$' "$x.log") ok"; grep -A6 Traceback "$x.log" | tail -7; done
[ "$(cat "$a/fast.exit")" = 0 ] && [ "$(cat "$b/browser.exit")" = 0 ]
