#!/bin/bash
# ============================================
# Upgrade Quality - Cerca versioni HQ dei brani
# Sovrascrive i file originali
# Con progress bar e ripresa automatica
# ============================================

# Requisiti: yt-dlp, ffmpeg, ffprobe
# Installazione: brew install yt-dlp ffmpeg

# Percorso script (per trovare cookies.txt nella stessa cartella)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COOKIE_FILE="$SCRIPT_DIR/cookies.txt"

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

# Soglia qualita (kbps) - sopra questa aggiorna solo copertina
HQ_THRESHOLD=310

# ============================================
# Funzione progress bar
# ============================================
progress_bar() {
    local current=$1
    local total=$2
    local width=30
    local percent=$((current * 100 / total))
    local filled=$((current * width / total))
    local empty=$((width - filled))

    printf "\r  ["
    printf "%${filled}s" | tr ' ' '#'
    printf "%${empty}s" | tr ' ' '-'
    printf "] %3d%% (%d/%d)" "$percent" "$current" "$total"
}

# ============================================
# Funzione per aggiornare solo la copertina
# ============================================
update_cover_only() {
    local FILE="$1"
    local VIDEO_URL="$2"
    local TEMP_DIR="$3"
    local FILENAME="$4"

    # Scarica thumbnail
    yt-dlp \
        --skip-download \
        --write-thumbnail \
        --convert-thumbnails jpg \
        --no-warnings \
        $COOKIE_OPTS \
        --output "$TEMP_DIR/cover" \
        "$VIDEO_URL" 2>/dev/null

    local COVER_FILE=$(ls "$TEMP_DIR"/cover*.jpg 2>/dev/null | head -n 1)

    if [ -n "$COVER_FILE" ] && [ -f "$COVER_FILE" ]; then
        # Applica copertina con ffmpeg
        local TEMP_OUTPUT="$TEMP_DIR/temp_output.mp3"

        ffmpeg -y -i "$FILE" -i "$COVER_FILE" \
            -map 0:a -map 1:0 \
            -c:a copy \
            -id3v2_version 3 \
            -metadata:s:v title="Album cover" \
            -metadata:s:v comment="Cover (front)" \
            "$TEMP_OUTPUT" 2>/dev/null

        if [ -f "$TEMP_OUTPUT" ]; then
            mv "$TEMP_OUTPUT" "$FILE"
            rm -f "$COVER_FILE"
            return 0
        fi
    fi

    rm -f "$TEMP_DIR"/cover*.jpg 2>/dev/null
    return 1
}

# ============================================
# Funzione per processare una singola cartella
# ============================================
process_folder() {
    local SOURCE_DIR="$1"
    local LOGFILE="$SOURCE_DIR/upgrade.log"
    local DONE_FILE="$SOURCE_DIR/.upgraded_tracks"
    local TEMP_DIR="$SOURCE_DIR/.temp_download"

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  Cartella: ${YELLOW}$(basename "$SOURCE_DIR")${NC}"
    echo -e "${CYAN}========================================${NC}"

    # Crea file done se non esiste
    touch "$DONE_FILE"

    # Conta file totali e da processare
    local ALL_FILES=$(find "$SOURCE_DIR" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.wav" -o -iname "*.flac" \) | wc -l | tr -d ' ')

    if [ "$ALL_FILES" -eq 0 ]; then
        echo -e "  ${YELLOW}Nessun file audio, salto${NC}"
        return
    fi

    # Conta quanti sono gia stati convertiti
    local ALREADY_DONE=0
    while IFS= read -r FILE; do
        local BASENAME=$(basename "$FILE")
        local FILENAME="${BASENAME%.*}"
        if grep -qxF "$FILENAME" "$DONE_FILE" 2>/dev/null; then
            ((ALREADY_DONE++))
        fi
    done < <(find "$SOURCE_DIR" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.wav" -o -iname "*.flac" \))

    local TO_PROCESS=$((ALL_FILES - ALREADY_DONE))

    if [ "$TO_PROCESS" -eq 0 ]; then
        echo -e "  ${GREEN}Tutti i $ALL_FILES brani sono gia stati convertiti${NC}"
        return
    fi

    if [ "$ALREADY_DONE" -gt 0 ]; then
        echo -e "  Totale: $ALL_FILES file | ${GREEN}Gia convertiti: $ALREADY_DONE${NC} | Da fare: $TO_PROCESS"
    else
        echo "  Trovati $ALL_FILES file audio da processare"
    fi

    # Crea directory temporanea
    mkdir -p "$TEMP_DIR"

    local INDEX=0
    local SUCCESS=0
    local FAILED=0
    local SKIPPED=0

    # Processa ogni file audio
    while IFS= read -r FILE; do
        ((INDEX++))

        # Estrai nome file senza estensione
        local BASENAME=$(basename "$FILE")
        local FILENAME="${BASENAME%.*}"

        # Controlla se gia convertito
        if grep -qxF "$FILENAME" "$DONE_FILE" 2>/dev/null; then
            ((SKIPPED++))
            continue
        fi

        # Analizza qualita attuale
        local CURRENT_BITRATE=$(ffprobe -v quiet -print_format json -show_format "$FILE" 2>/dev/null | grep -o '"bit_rate": "[^"]*"' | grep -o '[0-9]*')
        local CURRENT_KBPS=$((CURRENT_BITRATE / 1000))

        # Mostra stato
        echo ""
        local DONE_COUNT=$((SKIPPED + SUCCESS + FAILED))
        echo -e "  ${YELLOW}[$((DONE_COUNT + 1))/$ALL_FILES]${NC} $FILENAME"
        echo -e "  ${GRAY}Qualita attuale: ${CURRENT_KBPS}kbps${NC}"

        # Cerca su YouTube
        echo -ne "  ${GRAY}Cercando su YouTube...${NC}"
        local VIDEO_INFO=$(yt-dlp "ytsearch1:$FILENAME" \
            --get-id --get-title \
            --no-warnings 2>/dev/null)

        if [ -z "$VIDEO_INFO" ]; then
            echo -e "\r  ${RED}Non trovato su YouTube                    ${NC}"
            echo "FALLITO: $FILENAME - Non trovato" >> "$LOGFILE"
            # Segna come fatto comunque per non riprovare
            echo "$FILENAME" >> "$DONE_FILE"
            ((FAILED++))
            continue
        fi

        local VIDEO_TITLE=$(echo "$VIDEO_INFO" | head -n 1)
        local VIDEO_ID=$(echo "$VIDEO_INFO" | tail -n 1)
        local VIDEO_URL="https://www.youtube.com/watch?v=$VIDEO_ID"

        echo -e "\r  ${GRAY}Trovato: ${VIDEO_TITLE:0:50}...${NC}          "

        # Se qualita gia alta, aggiorna solo copertina
        if [ "$CURRENT_KBPS" -ge "$HQ_THRESHOLD" ]; then
            echo -ne "  ${BLUE}Qualita gia alta, aggiorno solo copertina...${NC}"

            if update_cover_only "$FILE" "$VIDEO_URL" "$TEMP_DIR" "$FILENAME"; then
                echo -e "\r  ${GREEN}Copertina aggiornata (audio ${CURRENT_KBPS}kbps mantenuto)      ${NC}"
                echo "COVER: $FILENAME - Copertina aggiornata (${CURRENT_KBPS}kbps)" >> "$LOGFILE"
            else
                echo -e "\r  ${YELLOW}Copertina non disponibile (audio ${CURRENT_KBPS}kbps ok)      ${NC}"
                echo "SKIP: $FILENAME - Gia HQ ${CURRENT_KBPS}kbps" >> "$LOGFILE"
            fi

            echo "$FILENAME" >> "$DONE_FILE"
            ((SUCCESS++))

            # Pulisci temp
            rm -f "$TEMP_DIR"/*.jpg 2>/dev/null
            rm -f "$TEMP_DIR"/*.webp 2>/dev/null
            continue
        fi

        # Scarica con progress
        echo -ne "  ${CYAN}Scaricando...${NC} "

        yt-dlp \
            --extract-audio \
            --audio-format mp3 \
            --audio-quality 0 \
            --embed-thumbnail \
            --add-metadata \
            --no-warnings \
            --progress \
            --newline \
            $COOKIE_OPTS \
            --output "$TEMP_DIR/%(title)s.%(ext)s" \
            "$VIDEO_URL" 2>&1 | while IFS= read -r line; do
                # Estrai percentuale dal output di yt-dlp
                if [[ "$line" =~ ([0-9]+\.[0-9]+)% ]]; then
                    pct="${BASH_REMATCH[1]}"
                    pct_int=${pct%.*}
                    bar_width=20
                    filled=$((pct_int * bar_width / 100))
                    empty=$((bar_width - filled))
                    printf "\r  ${CYAN}Scaricando${NC} ["
                    printf "%${filled}s" | tr ' ' '#'
                    printf "%${empty}s" | tr ' ' '-'
                    printf "] %3d%%" "$pct_int"
                fi
            done

        if [ $? -eq 0 ] || [ -n "$(ls -A "$TEMP_DIR" 2>/dev/null)" ]; then
            # Trova il file appena scaricato
            local NEWEST_FILE=$(ls -t "$TEMP_DIR"/*.mp3 2>/dev/null | head -n 1)

            if [ -n "$NEWEST_FILE" ] && [ -f "$NEWEST_FILE" ]; then
                local NEW_BITRATE=$(ffprobe -v quiet -print_format json -show_format "$NEWEST_FILE" 2>/dev/null | grep -o '"bit_rate": "[^"]*"' | grep -o '[0-9]*')
                local NEW_KBPS=$((NEW_BITRATE / 1000))

                # Elimina file originale e sposta quello nuovo
                rm -f "$FILE"
                mv "$NEWEST_FILE" "$SOURCE_DIR/$FILENAME.mp3"

                # Segna come completato
                echo "$FILENAME" >> "$DONE_FILE"

                local DIFF=$((NEW_KBPS - CURRENT_KBPS))
                if [ "$DIFF" -gt 0 ]; then
                    echo -e "\r  ${GREEN}Completato: ${NEW_KBPS}kbps (+${DIFF}kbps)                    ${NC}"
                else
                    echo -e "\r  ${GREEN}Completato: ${NEW_KBPS}kbps                                  ${NC}"
                fi

                echo "OK: $FILENAME - ${CURRENT_KBPS}kbps -> ${NEW_KBPS}kbps" >> "$LOGFILE"
                ((SUCCESS++))
            else
                echo -e "\r  ${RED}Errore: file non trovato dopo download          ${NC}"
                echo "$FILENAME" >> "$DONE_FILE"
                ((FAILED++))
            fi
        else
            echo -e "\r  ${RED}Errore durante il download                      ${NC}"
            echo "ERRORE: $FILENAME - Download fallito" >> "$LOGFILE"
            echo "$FILENAME" >> "$DONE_FILE"
            ((FAILED++))
        fi

        # Pulisci temp
        rm -f "$TEMP_DIR"/*.mp3 2>/dev/null
        rm -f "$TEMP_DIR"/*.webm 2>/dev/null
        rm -f "$TEMP_DIR"/*.m4a 2>/dev/null

    done < <(find "$SOURCE_DIR" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.wav" -o -iname "*.flac" \))

    # Rimuovi directory temporanea
    rmdir "$TEMP_DIR" 2>/dev/null

    # Sommario cartella
    echo ""
    echo -e "  ${GRAY}---${NC}"
    echo -e "  Convertiti: ${GREEN}$SUCCESS${NC} | Falliti: ${RED}$FAILED${NC} | Saltati: ${GRAY}$SKIPPED${NC}"
}

# ============================================
# MAIN
# ============================================

echo ""
echo "========================================"
echo "       UPGRADE QUALITY AUDIO"
echo "========================================"

# Verifica cookies YouTube Premium
if [ -f "$COOKIE_FILE" ]; then
    echo -e "Cookies: ${GREEN}YouTube Premium attivo${NC}"
    COOKIE_OPTS="--cookies $COOKIE_FILE"
else
    echo -e "Cookies: ${YELLOW}Non trovati (qualita standard)${NC}"
    COOKIE_OPTS=""
fi

# Gestione parametri
if [ "$1" = "-r" ] || [ "$1" = "--recursive" ]; then
    # Modalita ricorsiva: processa tutte le sottocartelle
    if [ -z "$2" ]; then
        echo -e "${CYAN}Inserisci la cartella principale:${NC}"
        read -r BASE_DIR
    else
        BASE_DIR="$2"
    fi

    if [ ! -d "$BASE_DIR" ]; then
        echo -e "${RED}Errore: Directory '$BASE_DIR' non trovata${NC}"
        exit 1
    fi

    # Trova tutte le sottocartelle con file audio
    echo ""
    echo "Scansione cartelle in: $BASE_DIR"

    FOLDERS=$(find "$BASE_DIR" -type d | while read -r dir; do
        count=$(find "$dir" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.wav" -o -iname "*.flac" \) 2>/dev/null | wc -l | tr -d ' ')
        if [ "$count" -gt 0 ]; then
            echo "$dir"
        fi
    done)

    if [ -z "$FOLDERS" ]; then
        echo -e "${RED}Nessuna cartella con file audio trovata${NC}"
        exit 1
    fi

    FOLDER_COUNT=$(echo "$FOLDERS" | wc -l | tr -d ' ')
    echo ""
    echo "Trovate $FOLDER_COUNT cartelle con file audio:"
    echo "$FOLDERS" | while read -r f; do
        count=$(find "$f" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.wav" -o -iname "*.flac" \) | wc -l | tr -d ' ')
        # Conta gia convertiti
        done_file="$f/.upgraded_tracks"
        if [ -f "$done_file" ]; then
            done_count=$(wc -l < "$done_file" | tr -d ' ')
            remaining=$((count - done_count))
            if [ "$remaining" -le 0 ]; then
                echo -e "  ${GREEN}$(basename "$f")${NC} ($count file - tutti convertiti)"
            else
                echo -e "  ${YELLOW}$(basename "$f")${NC} ($count file - $remaining da convertire)"
            fi
        else
            echo -e "  ${YELLOW}$(basename "$f")${NC} ($count file)"
        fi
    done

    echo ""
    echo -e "${YELLOW}I file originali verranno sovrascritti!${NC}"
    echo -e "${GRAY}I brani gia convertiti verranno saltati automaticamente.${NC}"
    read -p "Vuoi continuare? (s/n): " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[sS]$ ]]; then
        echo "Operazione annullata."
        exit 0
    fi

    # Processa ogni cartella
    FOLDER_INDEX=0
    echo "$FOLDERS" | while read -r folder; do
        ((FOLDER_INDEX++))
        echo ""
        echo -e "${BOLD}>>> Cartella $FOLDER_INDEX/$FOLDER_COUNT <<<${NC}"
        process_folder "$folder"
    done

else
    # Modalita singola cartella
    if [ -z "$1" ]; then
        echo -e "${CYAN}Inserisci il percorso della cartella da convertire:${NC}"
        read -r SOURCE_DIR
    else
        SOURCE_DIR="$1"
    fi

    if [ ! -d "$SOURCE_DIR" ]; then
        echo -e "${RED}Errore: Directory '$SOURCE_DIR' non trovata${NC}"
        exit 1
    fi

    # Conta file
    TOTAL=$(find "$SOURCE_DIR" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.wav" -o -iname "*.flac" \) | wc -l | tr -d ' ')

    if [ "$TOTAL" -eq 0 ]; then
        echo -e "${RED}Nessun file audio trovato nella cartella${NC}"
        exit 1
    fi

    # Conta gia convertiti
    DONE_FILE="$SOURCE_DIR/.upgraded_tracks"
    if [ -f "$DONE_FILE" ]; then
        DONE_COUNT=$(wc -l < "$DONE_FILE" | tr -d ' ')
        REMAINING=$((TOTAL - DONE_COUNT))
        echo -e "Cartella: ${YELLOW}$SOURCE_DIR${NC}"
        echo -e "Totale: $TOTAL file | ${GREEN}Gia convertiti: $DONE_COUNT${NC} | Da fare: $REMAINING"
    else
        echo -e "Cartella: ${YELLOW}$SOURCE_DIR${NC}"
        echo "Trovati $TOTAL file audio"
    fi

    echo ""
    echo -e "${YELLOW}I file originali verranno sovrascritti!${NC}"
    echo -e "${GRAY}I brani gia convertiti verranno saltati automaticamente.${NC}"
    read -p "Vuoi continuare? (s/n): " CONFIRM
    if [[ ! "$CONFIRM" =~ ^[sS]$ ]]; then
        echo "Operazione annullata."
        exit 0
    fi

    process_folder "$SOURCE_DIR"
fi

echo ""
echo "========================================"
echo -e "         ${GREEN}COMPLETATO${NC}"
echo "========================================"
