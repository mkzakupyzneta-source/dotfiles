#!/bin/bash
# Katalog roboczy AI (AI-katalog-roboczy -> ~/OneDrive-AI na SSD).
#   wznow  - kontynuuje pobieranie od miejsca, w ktorym stanelo (BEZ --resync!)
#   postep - podglad
LOG="$HOME/onedrive-roboczy.log"
case "$1" in
  wznow)  nohup onedrive --sync --download-only --verbose > "$LOG" 2>&1 &
          echo "Wznowione w tle. Log: $LOG" ;;
  postep) echo "pobrane: $(grep -cE '^Downloading file|^Downloaded file' "$LOG" 2>/dev/null) plikow"
          echo "rozmiar: $(du -sh ~/OneDrive-AI 2>/dev/null | cut -f1)"
          pgrep -x onedrive >/dev/null && echo "status: PRACUJE" || echo "status: ZAKONCZONE" ;;
  *) echo "uzycie: $0 wznow|postep" ;;
esac
