#!/bin/sh
# Restart contract: start SIGI Gestão (FastAPI) on 0.0.0.0:8080 if it is down.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
if curl -sf -o /dev/null --max-time 2 http://127.0.0.1:8080/auth/status; then
  exit 0
fi
mkdir -p "$ROOT/data" "$ROOT/app/static"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  python3 -m venv "$ROOT/.venv"
fi
export PATH="$ROOT/.venv/bin:$PATH"
if ! python -c "import fastapi,uvicorn,psycopg2" 2>/dev/null; then
  python -m pip install -q -r "$ROOT/requirements.txt"
fi
export TZ_OFFSET_HOURS="${TZ_OFFSET_HOURS:--3}"
export DB_PATH="${DB_PATH:-$ROOT/data/flux.db}"
nohup npm run dev \
  >/tmp/flux-gestao.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -sf -o /dev/null --max-time 1 http://127.0.0.1:8080/auth/status; then
    exit 0
  fi
  sleep 0.4
done
echo 'SIGI did not become ready; inspect /tmp/flux-gestao.log.' >&2
exit 1
