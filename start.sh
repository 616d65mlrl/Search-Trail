#!/usr/bin/env sh
# Search-Trail を起動する（macOS / Linux）。必要なもの: uv と Node.js
set -e
cd "$(dirname "$0")/backend"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv が見つかりません。https://docs.astral.sh/uv/ から入れてください"
  exit 1
fi
exec uv run tadori start "$@"
