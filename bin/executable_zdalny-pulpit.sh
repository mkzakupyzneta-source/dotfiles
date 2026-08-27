#!/bin/bash
# zdalny-pulpit.sh — podglad i sterowanie ZYWA sesja graficzna tej maszyny przez VNC (x11vnc).
# Wozony przez lustro (chezmoi: bin/executable_zdalny-pulpit.sh), uruchamiany przez usluge USER
# systemd `zdalny-pulpit.service`. Zalozone 2026-08-27, obszar 2_Stacje_lustra, sprawa [221].
#
# Schemat z Asusa (3_Maszyny_pozostale/_MEMORY/asus.md), z trzema roznicami — wszystkie
# po to, zeby JEDEN plik dzialal na kazdej maszynie:
#   1. numer ekranu X i plik Xauthority sa WYKRYWANE (GDM: ekran :1 i /run/user/UID/gdm/Xauthority;
#      LightDM na serwerze: ekran :0 i ~/.Xauthority), nie zaszyte;
#   2. nasluch na 0.0.0.0 zamiast na jednym adresie — Katana wedruje miedzy dwiema podsieciami
#      (adres Wi-Fi zmienny); kto moze sie laczyc, ogranicza -allow (podsieci LAN z lustra/siec.toml
#      + Tailscale 100.*), a na stacjach dodatkowo zapora ufw;
#   3. haslo NIE lezy w repozytorium: skrypt czyta VNC_HASLO z ~/.config/sekrety/zdalny-pulpit.env
#      (plik 600, wypelniany przez `sekrety-odswiez` z sejfu Bitwarden — pozycja maszyny,
#      linia `haslo_vnc:` w notatce; mapowanie: ~/.config/sekrety/sekrety-map.toml) i sam buduje
#      z niego ~/.vnc/passwd (`x11vnc -storepasswd`).
# Uczciwie: klasyczna autoryzacja VNC to slabe haslo (max 8 znakow) i BRAK szyfrowania obrazu —
# w domowym LAN/Tailscale akceptowalne, przez internet NIE wystawiac (tunel SSH albo Tailscale).
set -u

KAT_VNC="$HOME/.vnc"
PLIK_HASLA="$HOME/.config/sekrety/zdalny-pulpit.env"
SIEC_TOML="$HOME/.local/share/chezmoi/lustra/siec.toml"
LOG="$KAT_VNC/x11vnc.log"
PORT=5900

mkdir -p "$KAT_VNC" && chmod 700 "$KAT_VNC"

# 1. haslo — bez niego NIE startujemy (x11vnc bez hasla wpuscilby kazdego)
VNC_HASLO=""
if [ -r "$PLIK_HASLA" ]; then
    # shellcheck disable=SC1090
    . "$PLIK_HASLA"
fi
if [ -z "${VNC_HASLO:-}" ]; then
    echo "brak VNC_HASLO w $PLIK_HASLA — uruchom sekrety-odswiez (sejf: pozycja tej maszyny, linia haslo_vnc). Koncze, systemd sprobuje ponownie."
    sleep 55
    exit 1
fi
if ! x11vnc -storepasswd "$VNC_HASLO" "$KAT_VNC/passwd" >/dev/null 2>&1; then
    echo "x11vnc -storepasswd nie zapisal $KAT_VNC/passwd"
    exit 1
fi
chmod 600 "$KAT_VNC/passwd"
unset VNC_HASLO

# 2. poczekaj na serwer X (gniazdo /tmp/.X11-unix/X<N>) — numer ekranu wykrywany, nie zaszyty
EKRAN=""
for _ in $(seq 1 60); do
    for g in /tmp/.X11-unix/X*; do
        [ -S "$g" ] || continue
        EKRAN=":${g##*/X}"
        break
    done
    [ -n "$EKRAN" ] && break
    sleep 2
done
if [ -z "$EKRAN" ]; then
    echo "brak serwera X po 2 minutach — koncze, systemd wznowi"
    exit 1
fi

# 3. plik autoryzacji X — GDM trzyma go w /run/user/UID/gdm/Xauthority, LightDM w ~/.Xauthority;
#    ostatnia deska: argument -auth procesu Xorg
AUTH=""
for kandydat in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/gdm/Xauthority" "$HOME/.Xauthority"; do
    [ -r "$kandydat" ] && { AUTH="$kandydat"; break; }
done
if [ -z "$AUTH" ]; then
    AUTH="$(pgrep -a Xorg 2>/dev/null | grep -oP -- '-auth \K\S+' | head -1)"
fi
if [ -z "$AUTH" ] || [ ! -r "$AUTH" ]; then
    echo "nie znalazlem czytelnego pliku Xauthority (ekran $EKRAN) — koncze, systemd wznowi"
    exit 1
fi

# 4. kto moze sie laczyc: podsieci LAN z lustra/siec.toml (dane) + Tailscale; awaryjnie stala lista
ALLOW="$(python3 -c '
import sys, tomllib
try:
    with open(sys.argv[1], "rb") as f:
        podsieci = tomllib.load(f)["podsieci_lan"]
    print(",".join(s.split("/")[0].rsplit(".", 1)[0] + "." for s in podsieci) + ",100.")
except Exception:
    pass
' "$SIEC_TOML" 2>/dev/null)"
[ -z "$ALLOW" ] && ALLOW="192.168.1.,192.168.100.,100."

echo "start: ekran $EKRAN, auth $AUTH, port $PORT, allow $ALLOW"
exec /usr/bin/x11vnc -display "$EKRAN" -auth "$AUTH" \
    -rfbauth "$KAT_VNC/passwd" -rfbport "$PORT" -rfbportv6 -1 \
    -listen 0.0.0.0 -allow "$ALLOW" \
    -forever -shared -repeat -noxrecord -noipv6 -o "$LOG"
