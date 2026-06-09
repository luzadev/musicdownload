#!/bin/bash
# Rimuove la quarantena Gatekeeper da MusicTools.app
# Doppio click in macOS apre Terminal ed esegue questo script.

set -e

APP_NAME="MusicTools.app"

# Cerca l'app in /Applications, poi nella stessa cartella del DMG montato.
if [ -d "/Applications/${APP_NAME}" ]; then
    APP="/Applications/${APP_NAME}"
elif [ -d "$(dirname "$0")/${APP_NAME}" ]; then
    APP="$(dirname "$0")/${APP_NAME}"
else
    osascript -e "display alert \"${APP_NAME} non trovata\" message \"Trascina MusicTools.app nella cartella Applicazioni prima di eseguire questo script.\" as critical"
    exit 1
fi

echo "Rimuovo la quarantena da: ${APP}"
xattr -dr com.apple.quarantine "${APP}" 2>/dev/null || true

# Notifica visuale
osascript -e "display notification \"MusicTools puo' essere aperta normalmente con doppio click.\" with title \"Fix completato\""

echo ""
echo "Fatto. Ora puoi aprire MusicTools normalmente con doppio click."
echo "Puoi chiudere questa finestra."
