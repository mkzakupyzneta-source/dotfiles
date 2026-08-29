#!/bin/bash
# zdalny-pulpit.sh — podglad i sterowanie ZYWA sesja graficzna tej maszyny przez VNC (x11vnc).
# Wozony przez lustro (chezmoi: bin/executable_zdalny-pulpit.sh), uruchamiany przez usluge USER
# systemd `zdalny-pulpit.service`. Zalozone 2026-08-27 (obszar 2, sprawa [221]);
# PRZEBUDOWANE 2026-08-29 (obszar 5, sprawa [258a], decyzja usera „zero dodatkowych hasel").
#
# ZASADA: x11vnc NIE ma wlasnego hasla i NIE jest widoczny w sieci. Sluchа wylacznie na
# 127.0.0.1 (`-localhost`). Jedyna droga do niego prowadzi przez TUNEL SSH, wiec
# uwierzytelnieniem jest KLUCZ SSH — ten sam, ktorym maszyny juz sie znaja:
#   • panel menadzera sieci (serwer):  ssh -N -L 127.0.0.1:<port>:127.0.0.1:5900 mk@<maszyna>
#     i dalej noVNC w karcie przegladarki (wariant A, [258]);
#   • stacja, przycisk „otworz w programie": odsylacz vnc://<adres> → ~/bin/vnc-otworz.sh →
#     `vncviewer -via mk@<adres> localhost:5900` (wariant B, [258b]).
# Skutki uboczne, celowe:
#   • zadnego hasla VNC w sejfie ani w pliku — pozycja `haslo_vnc` i mapowanie VNC_HASLO
#     sa zbedne (do zdjecia przez obszar 7);
#   • port 5900 NIE musi byc otwarty w zaporze (ani z LAN, ani z Tailscale) — reguly
#     zdjete z `lustra/ufw-stacja.sh` ta sama zmiana;
#   • obraz jedzie szyfrowanym tunelem SSH, a nie golym RFB — to mocniejsze niz dawne
#     8-znakowe haslo VNC bez szyfrowania.
#
# Numer ekranu X i plik Xauthority sa WYKRYWANE, nie zaszyte (GDM: ekran :1 i
# /run/user/UID/gdm/Xauthority; LightDM: ekran :0 i ~/.Xauthority) — jeden plik dziala
# na kazdej maszynie.
set -u

KAT_VNC="$HOME/.vnc"
LOG="$KAT_VNC/x11vnc.log"
PORT=5900

mkdir -p "$KAT_VNC" && chmod 700 "$KAT_VNC"

# Pozostalosc po wersji z haslem: plik ~/.vnc/passwd nie jest juz do niczego uzywany.
# Zostawiamy go w spokoju (nie kasujemy cudzych danych), ale x11vnc go nie czyta.

# 1. poczekaj na serwer X (gniazdo /tmp/.X11-unix/X<N>) — numer ekranu wykrywany, nie zaszyty
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

# 2. plik autoryzacji X — GDM trzyma go w /run/user/UID/gdm/Xauthority, LightDM w ~/.Xauthority;
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

# 3. start: tylko petla zwrotna, bez hasla (-nopw wylacza wielka ostrzegawcza ramke w logu;
#    samo `-localhost` juz ogranicza polaczenia do 127.0.0.1 i do tego adresu przypina nasluch)
echo "start: ekran $EKRAN, auth $AUTH, 127.0.0.1:$PORT, bez hasla (wejscie tylko tunelem SSH)"
exec /usr/bin/x11vnc -display "$EKRAN" -auth "$AUTH" \
    -rfbport "$PORT" -rfbportv6 -1 \
    -localhost -nopw \
    -forever -shared -repeat -noxrecord -noipv6 -o "$LOG"
