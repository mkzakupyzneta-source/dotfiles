#!/bin/bash
# Dozor archiwum OneDrive: co jakis czas sprawdza, czy pobieranie zyje, i wznawia je jesli padlo.
# Powstal po tym, jak w nocy 2026-08-21 pobieranie stanelo po kilkunastu minutach niezauwazone.
LOG="$HOME/onedrive-archiwum.log"
MARKER="$HOME/.onedrive-archiwum-ukonczone"
DZIENNIK="$HOME/onedrive-archiwum-dozor.log"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# 1. Czy proces zyje? Jesli tak - nic nie robimy.
for p in $(pgrep -x onedrive); do
    grep -qa archiwum /proc/$p/cmdline 2>/dev/null && exit 0
done

# 2. Czy juz skonczylismy? (marker zakladany po przebiegu, ktory nic nie pobral)
[ -f "$MARKER" ] && exit 0

# 3. Proces nie zyje. Ile pobral w ostatnim przebiegu?
POBRANE=$(grep -c 'Downloading file' "$LOG" 2>/dev/null || echo 0)
ROZMIAR=$(du -sh /data/OneDrive 2>/dev/null | cut -f1)

if [ "$POBRANE" -eq 0 ]; then
    # Przebieg nic nie pobral - albo wszystko juz jest, albo cos jest nie tak.
    # Nie wznawiamy w kolko; zakladamy marker i zostawiamy slad do obejrzenia.
    echo "$(ts)  STOP: ostatni przebieg pobral 0 plikow. Rozmiar /data/OneDrive: $ROZMIAR. Zakladam marker." >> "$DZIENNIK"
    touch "$MARKER"
    exit 0
fi

# 4. Byly pobrania, wiec praca trwa - wznawiamy.
mv "$LOG" "$LOG.$(date +%H%M%S)" 2>/dev/null
nohup onedrive --confdir="$HOME/.config/onedrive-archiwum" --sync --download-only --verbose > "$LOG" 2>&1 &
echo "$(ts)  WZNOWIONO (poprzedni przebieg: $POBRANE plikow, na dysku: $ROZMIAR)" >> "$DZIENNIK"
