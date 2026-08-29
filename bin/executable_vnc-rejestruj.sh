#!/bin/bash
# vnc-rejestruj.sh — rejestruje ~/.local/share/applications/vnc-otworz.desktop jako program
# otwierajacy odsylacze `vnc://`. Uruchamiane przez pozycje `vnc-handler` kanalu `skrypt`
# (lustra/skrypty.toml) — takze nieinteraktywnie, z timera `lustro-sync`. Sprawa [258b].
#
# Dlaczego osobny skrypt, a nie jedna linia w skrypty.toml: `xdg-mime` w roznych kontekstach
# uzywa roznych implementacji (w sesji GNOME wola `gio`, poza nia — wersje ogolna). Chcemy
# jednego, sprawdzalnego skutku: linii `x-scheme-handler/vnc=vnc-otworz.desktop` w sekcji
# [Default Applications] pliku ~/.config/mimeapps.list. Najpierw probujemy narzedziem
# systemowym, a gdy ono zapisalo gdzie indziej (albo wcale) — dopisujemy sami.
set -u

PLIK_DESKTOP="vnc-otworz.desktop"
KAT_APP="$HOME/.local/share/applications"
MIMEAPPS="$HOME/.config/mimeapps.list"
SCHEMAT="x-scheme-handler/vnc"

# --wyrejestruj: zdejmij przypisanie (uzywane przez `lustro usun vnc-handler`)
if [ "${1:-}" = "--wyrejestruj" ]; then
    if [ -f "$MIMEAPPS" ]; then
        grep -v "^$SCHEMAT=" "$MIMEAPPS" >"$MIMEAPPS.tmp" && mv "$MIMEAPPS.tmp" "$MIMEAPPS"
    fi
    echo "wyrejestrowane: $SCHEMAT"
    exit 0
fi

if [ ! -f "$KAT_APP/$PLIK_DESKTOP" ]; then
    echo "brak $KAT_APP/$PLIK_DESKTOP — najpierw 'chezmoi apply' (plik wozi lustro)"
    exit 1
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$KAT_APP" >/dev/null 2>&1 || true
command -v xdg-mime >/dev/null 2>&1 && xdg-mime default "$PLIK_DESKTOP" "$SCHEMAT" >/dev/null 2>&1 || true

if grep -qs "^$SCHEMAT=$PLIK_DESKTOP" "$MIMEAPPS"; then
    echo "zarejestrowane: $SCHEMAT → $PLIK_DESKTOP (xdg-mime)"
    exit 0
fi

# Zapasowa droga: wpis prosto do [Default Applications] w ~/.config/mimeapps.list.
mkdir -p "$(dirname "$MIMEAPPS")"
python3 - "$MIMEAPPS" "$SCHEMAT" "$PLIK_DESKTOP" <<'PY'
import sys, pathlib
plik, schemat, desktop = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
linie = plik.read_text(encoding="utf-8").splitlines() if plik.exists() else []
# usun stare przypisania tego schematu w sekcji domyslnych
wynik, w_sekcji, wstawione = [], False, False
for linia in linie:
    if linia.strip().startswith("["):
        if w_sekcji and not wstawione:
            wynik.append(f"{schemat}={desktop}"); wstawione = True
        w_sekcji = linia.strip() == "[Default Applications]"
    elif w_sekcji and linia.split("=", 1)[0].strip() == schemat:
        continue
    wynik.append(linia)
if w_sekcji and not wstawione:
    wynik.append(f"{schemat}={desktop}"); wstawione = True
if not wstawione:
    if wynik and wynik[-1].strip():
        wynik.append("")
    wynik += ["[Default Applications]", f"{schemat}={desktop}"]
plik.write_text("\n".join(wynik).rstrip("\n") + "\n", encoding="utf-8")
PY

if grep -qs "^$SCHEMAT=$PLIK_DESKTOP" "$MIMEAPPS"; then
    echo "zarejestrowane: $SCHEMAT → $PLIK_DESKTOP (wpis w $MIMEAPPS)"
    exit 0
fi
echo "NIE UDALO SIE zarejestrowac $SCHEMAT"
exit 1
