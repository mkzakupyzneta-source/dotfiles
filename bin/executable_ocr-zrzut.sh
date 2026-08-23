#!/bin/bash
# OCR z zaznaczonego obszaru ekranu: Flameshot (zaznacz, zatwierdź klawiszem S) -> Tesseract (pol+eng) -> schowek.
# Skrót GNOME: Super+Shift+D. Ustalone 2026-08-22 (Vostro). Plik zrzutu nie jest zapisywany.
T=$(mktemp --suffix=.png)
trap 'rm -f "$T"' EXIT
flameshot gui --raw > "$T" 2>/dev/null
[ -s "$T" ] || exit 0          # Esc / anulowane
TXT=$(tesseract "$T" stdout -l pol+eng 2>/dev/null | sed -e 's/[[:space:]]*$//' | sed -e '/^$/N;/^\n$/D')
if [ -n "$TXT" ]; then
  printf '%s' "$TXT" | xclip -selection clipboard
  notify-send -i edit-copy "OCR → schowek" "$(printf '%s' "$TXT" | head -c 200)"
else
  notify-send -i dialog-warning "OCR" "Nie rozpoznano tekstu."
fi
