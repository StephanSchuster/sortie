#!/usr/bin/env bash
# Builds the dashboard before and after the polish and serves both on the same demo data.
# Usage: ./demo.sh [--fresh]     --fresh starts over: new clones, new binaries, new data.
# Everything stays in ./work. Ctrl-C stops all of it.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WORK="$HERE/work"

BEFORE_REPO=${BEFORE_REPO:-https://github.com/sortie-ai/sortie}
BEFORE_REF=${BEFORE_REF:-c5c35f31a}
AFTER_REPO=${AFTER_REPO:-https://github.com/StephanSchuster/sortie}
AFTER_REF=${AFTER_REF:-dashboard-consistency}

BEFORE_PORT=${BEFORE_PORT:-7740}
AFTER_PORT=${AFTER_PORT:-7741}
GH_PORT=${GH_PORT:-7750}
BUILD_PORT=${BUILD_PORT:-7749}

for tool in git go make python3; do
  command -v "$tool" >/dev/null || { echo "demo: $tool is required" >&2; exit 1; }
done
for port in "$BEFORE_PORT" "$AFTER_PORT" "$GH_PORT" "$BUILD_PORT"; do
  if ! python3 -c 'import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", int(sys.argv[1])))' "$port" 2>/dev/null; then
    echo "demo: port $port is in use; set BEFORE_PORT, AFTER_PORT, GH_PORT or BUILD_PORT" >&2
    exit 1
  fi
done

[[ "${1:-}" == "--fresh" ]] && rm -rf "$WORK"
mkdir -p "$WORK/logs"

build() { # name repo ref
  local name=$1 repo=$2 ref=$3 dir="$WORK/$1"
  if [[ -x "$WORK/bin/sortie-$name" ]]; then return; fi
  echo "demo: building $name ($ref)"
  if [[ ! -d "$dir" ]]; then
    git clone -q --filter=blob:none "$repo" "$dir"
  fi
  git -C "$dir" checkout -q "$ref"
  mkdir -p "$WORK/bin"
  make -s -C "$dir" build BIN="$WORK/bin/sortie-$name" >"$WORK/logs/build-$name.log" 2>&1 || {
    cat "$WORK/logs/build-$name.log" >&2
    exit 1
  }
}
build before "$BEFORE_REPO" "$BEFORE_REF"
build after "$AFTER_REPO" "$AFTER_REF"

if [[ ! -d "$WORK/seed" ]]; then
  echo "demo: creating ten days of demo data with the mock agent (a few minutes, no model, no network)"
  DEMO_BIN="$WORK/bin/sortie-before" DEMO_SEED="$WORK/seed" DEMO_BUILD_PORT="$BUILD_PORT" DEMO_GH_PORT="$GH_PORT" \
    python3 "$HERE/tools/build.py" >"$WORK/logs/seed.log"
  python3 "$HERE/tools/multi-model.py" "$WORK/seed" >>"$WORK/logs/seed.log"
fi
rm -rf "$WORK/state-before" "$WORK/state-after"
cp -R "$WORK/seed" "$WORK/state-before"
cp -R "$WORK/seed" "$WORK/state-after"

pids=()
stop() {
  trap - INT TERM EXIT
  if [[ ${#pids[@]} -gt 0 ]]; then kill "${pids[@]}" 2>/dev/null || true; fi
  wait 2>/dev/null || true
  echo
  echo "demo: stopped"
}
trap stop INT TERM EXIT

python3 "$HERE/tools/fakegh.py" "$GH_PORT" >"$WORK/logs/fakegh.log" 2>&1 &
pids+=($!)
(cd "$WORK/state-before" && exec "$WORK/bin/sortie-before" --port "$BEFORE_PORT" WORKFLOW.md) >"$WORK/logs/before.log" 2>&1 &
pids+=($!)
(cd "$WORK/state-after" && exec "$WORK/bin/sortie-after" --port "$AFTER_PORT" WORKFLOW.md) >"$WORK/logs/after.log" 2>&1 &
pids+=($!)

cat <<MSG

  Before  http://127.0.0.1:$BEFORE_PORT/ui/
  After   http://127.0.0.1:$AFTER_PORT/ui/

Ctrl-C stops both. Logs are in work/logs.
MSG
wait
