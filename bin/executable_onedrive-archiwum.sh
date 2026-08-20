#!/bin/bash
# Obsluga instancji "archiwum" OneDrive (caly OneDrive oprocz AI-katalog-roboczy -> /data/OneDrive).
# Uzycie:
#   onedrive-archiwum.sh logowanie  - jednorazowe logowanie (otworzy przegladarke)
#   onedrive-archiwum.sh test       - proba na sucho, nic nie pobiera
#   onedrive-archiwum.sh start      - prawdziwe pobieranie (tylko w dol, nic nie wysyla)
#   onedrive-archiwum.sh postep     - podglad postepu
C="$HOME/.config/onedrive-archiwum"
LOG="$HOME/onedrive-archiwum.log"
case "$1" in
  logowanie) onedrive --confdir="$C" ;;
  test)      onedrive --confdir="$C" --sync --dry-run --verbose --resync --resync-auth 2>&1 | tail -40 ;;
  start)     nohup onedrive --confdir="$C" --sync --download-only --verbose --resync --resync-auth > "$LOG" 2>&1 &
             echo "Ruszylo w tle. Log: $LOG"; echo "Postep: $0 postep" ;;
  postep)    echo "pobrane pliki: $(grep -c '^Downloading file' "$LOG" 2>/dev/null)"
             pgrep -x onedrive >/dev/null && echo "status: PRACUJE" || echo "status: ZAKONCZONE"
             tail -5 "$LOG" 2>/dev/null ;;
  *) sed -n '2,8p' "$0" ;;
esac
