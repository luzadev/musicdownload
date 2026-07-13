#!/usr/bin/env bash
# Genera una licenza MusicTools da locale, eseguendo lo script sul server.
#
# Uso:
#   ./server/scripts/gen-license.sh <email> [plan]
#
# plan: annual (default, "full" — no limite, no scadenza)
#       basic | pro | premium (con daily_limit e period_end mensile)
#
# Richiede:
#   - ssh con chiave configurata verso musictools@musictools.djluza.com
#   - lo script server-side viene sincronizzato in automatico prima dell'esecuzione

set -euo pipefail

EMAIL="${1:-}"
PLAN="${2:-annual}"

if [ -z "$EMAIL" ]; then
  echo "Uso: $0 <email> [plan]" >&2
  echo "plan: annual (default) | basic | pro | premium" >&2
  exit 1
fi

SSH_TARGET="musictools@musictools.djluza.com"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ssh "$SSH_TARGET" 'mkdir -p ~/api/scripts'
rsync -a --quiet \
  "$SCRIPT_DIR/gen-license.mjs" \
  "${SSH_TARGET}:api/scripts/gen-license.mjs"

ssh "$SSH_TARGET" "cd ~/api && node scripts/gen-license.mjs '$EMAIL' '$PLAN'"
