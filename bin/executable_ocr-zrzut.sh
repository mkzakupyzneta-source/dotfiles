#!/bin/bash
# OCR z zaznaczonego obszaru ekranu: Flameshot (zaznacz, zatwierdź klawiszem S) -> Tesseract (pol+eng) -> schowek.
# Skrót GNOME: Super+Shift+D. Ustalone 2026-08-22 (Vostro). Plik zrzutu nie jest zapisywany.
T=$(mktemp --suffix=.png)
trap 'rm -f "$T"' EXIT
flameshot gui --raw > "$T" 2>/dev/null
[ -s "$T" ] || exit 0          # Esc / anulowane
TXT=$(tesseract "$T" stdout -l pol+eng 2>/dev/null | sed -e 's/[[:space:]]*$//' | sed -e '/^$/N;/^\n$/D')
# Schowek: na Wayland kopiuje `wl-copy` (pakiet wl-clipboard), na X11 `xclip`.
# Gałąź `ubuntu-2604` ([423], 14.09): xclip WYPADŁ z kanonu razem z resztą rodziny X11,
# a wl-clipboard NIE jest instalowany z automatu (zamienniki dociągamy na żądanie —
# lustra/lista-brakow-wayland.md). Dlatego skrypt sam wybiera, co ma pod ręką, a gdy
# nie ma NICZEGO, mówi to wprost zamiast po cichu nic nie skopiować.
do_schowka() {
  if command -v wl-copy >/dev/null 2>&1; then wl-copy
  elif command -v xclip >/dev/null 2>&1; then xclip -selection clipboard
  else
    cat >/dev/null
    notify-send -i dialog-warning "OCR" "Tekst rozpoznany, ale nie mam czym go wkleić do schowka. Zainstaluj: sudo apt install wl-clipboard"
    return 1
  fi
}

if [ -n "$TXT" ]; then
  printf '%s' "$TXT" | do_schowka || exit 1
  notify-send -i edit-copy "OCR → schowek" "$(printf '%s' "$TXT" | head -c 200)"
else
  notify-send -i dialog-warning "OCR" "Nie rozpoznano tekstu."
fi
