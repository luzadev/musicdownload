#!/bin/bash
# ============================================
# 🎵 Spotify → YouTube Downloader (API edition)
# by LuZa / GPT-5
# ============================================

# Requisiti: yt-dlp, ffmpeg, jq, curl
# Installazione rapida (macOS):
#   brew install yt-dlp ffmpeg jq curl

# ====== CONFIGURAZIONE ======
CLIENT_ID="379c38c32a5b43259cf55125e6efd472"
CLIENT_SECRET="e58c9a468b624eb3bdd27f701fef3aa2"
BITRATE="320K"
COOKIE_FILE="cookies.txt"
LOGFILE="download.log"

# ====== INPUT ======
if [ -z "$1" ]; then
    echo "Uso: $0 <link_playlist_spotify> [directory_output]"
    exit 1
fi

SPOTIFY_URL="$1"
CUSTOM_DIR="$2"

# ====== SCELTA DIRECTORY ======
if [ -z "$CUSTOM_DIR" ]; then
    echo "📁 Inserisci il percorso della cartella di destinazione:"
    read -r CUSTOM_DIR
fi

mkdir -p "$CUSTOM_DIR" || { echo "❌ Impossibile creare la directory $CUSTOM_DIR"; exit 1; }

# ====== OTTIENI TOKEN ACCESSO ======
echo "🔑 Recupero token di accesso Spotify..."
ACCESS_TOKEN=$(curl -s -X POST -u "$CLIENT_ID:$CLIENT_SECRET" \
  -d grant_type=client_credentials https://accounts.spotify.com/api/token \
  | jq -r '.access_token')

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
  echo "❌ Errore durante il recupero del token Spotify."
  exit 1
fi

# ====== ESTRAI ID PLAYLIST ======
PLAYLIST_ID=$(echo "$SPOTIFY_URL" | awk -F'playlist/' '{print $2}' | cut -d'?' -f1)
PLAYLIST_API="https://api.spotify.com/v1/playlists/$PLAYLIST_ID"

# ====== OTTIENI INFO PLAYLIST ======
PLAYLIST_NAME=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$PLAYLIST_API" | jq -r '.name')
if [ "$PLAYLIST_NAME" = "null" ] || [ -z "$PLAYLIST_NAME" ]; then
  echo "❌ Impossibile leggere la playlist. Controlla il link o le credenziali."
  exit 1
fi

DEST_DIR="$CUSTOM_DIR/$PLAYLIST_NAME"
mkdir -p "$DEST_DIR"

echo "🎧 Playlist: $PLAYLIST_NAME"
echo "📂 Download in: $DEST_DIR"
echo "------------------------------------------"
echo "📝 Log: $DEST_DIR/$LOGFILE"

# ====== OTTIENI TUTTI I BRANI (paginazione API) ======
OFFSET=0
LIMIT=100

while :; do
  TRACKS_JSON=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
    "$PLAYLIST_API/tracks?limit=$LIMIT&offset=$OFFSET")

  ITEMS=$(echo "$TRACKS_JSON" | jq -r '.items[]?.track.name + " - " + (.items[]?.track.artists[0].name // "Unknown")')
  if [ -z "$ITEMS" ]; then
    break
  fi

  echo "$TRACKS_JSON" | jq -r '.items[] | "\(.track.name) - \(.track.artists[0].name)"' >> "$DEST_DIR/tracks.txt"

  NEXT=$(echo "$TRACKS_JSON" | jq -r '.next')
  [ "$NEXT" = "null" ] && break
  OFFSET=$((OFFSET + LIMIT))
done

# ====== SCARICA I BRANI ======
INDEX=0
while IFS= read -r QUERY; do
    ((INDEX++))
    echo "🔍 [$INDEX] Cerco su YouTube: $QUERY"
    VIDEO_ID=$(yt-dlp "ytsearch1:$QUERY" --get-id 2>/dev/null | head -n 1)
    if [ -z "$VIDEO_ID" ]; then
        echo "❌ Non trovato: $QUERY" | tee -a "$DEST_DIR/$LOGFILE"
        continue
    fi
    VIDEO_URL="https://www.youtube.com/watch?v=$VIDEO_ID"
    echo "🎬 Trovato: $VIDEO_URL"

    yt-dlp \
        --extract-audio \
        --audio-format mp3 \
        --audio-quality "$BITRATE" \
        --embed-thumbnail \
        --add-metadata \
        --no-check-certificates \
        --cookies "$COOKIE_FILE" \
        --output "$DEST_DIR/%(title)s.%(ext)s" \
        "$VIDEO_URL" >>"$DEST_DIR/$LOGFILE" 2>&1

    echo "✅ Scaricato: $QUERY"
    echo "------------------------------------------"
done < "$DEST_DIR/tracks.txt"

echo "🏁 Download completato!"
echo "📂 File salvati in: $DEST_DIR"