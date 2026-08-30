#!/bin/sh
# Zapora ufw STACJI — reguły budowane z DANYCH (lustra/siec.toml), nie z zaszytych
# adresów (poprawka 7 planu 25.08, brak 17 z Katany: dom ma DWIE podsieci LAN).
#
# Wzorzec reguł: audyt Vostro 24.08 (7_Bezpieczenstwo/zapora-vostro-audyt-2026-08-24.md)
# + procedura-nowej-stacji.md, Etap 2:
#   deny incoming; allow in on tailscale0; 41641/udp (Tailscale bezpośrednio);
#   z KAŻDEJ podsieci LAN: SSH 22/tcp, Syncthing 22000/tcp+udp i 21027/udp,
#   mDNS 5353/udp, GSConnect 1714–1764/tcp+udp.
# Dotyczy STACJI — zapora serwera to sprawa obszaru 1_Serwer.
#
# ⛔ Port 5900 (VNC) NIE jest otwierany — zmiana [258a] z 2026-08-29 (obszar 5).
#    Od tej daty x11vnc słucha wyłącznie na 127.0.0.1 i bez hasła; jedyna droga do
#    niego prowadzi tunelem SSH (port 22, już otwarty), więc otwarty port 5900 był
#    tylko powierzchnią ataku bez zastosowania. Reguła z 27.08 jest zdejmowana —
#    patrz `reguly_sprzatajace()` niżej: to jedyne miejsce, gdzie trzymamy listę
#    reguł HISTORYCZNYCH do usunięcia (nowa taka sytuacja = dopisanie linii tutaj,
#    nie ręczne komendy w meldunku).
#
# Domyślnie tylko WYPISUJE komendy (nic nie zmienia). `--wykonaj` uruchamia je
# przez sudo i włącza zaporę (`ufw --force enable`), po czym sprawdź:
#   grep ENABLED /etc/ufw/ufw.conf   # ma być ENABLED=yes
set -eu

TU="$(cd "$(dirname "$0")" && pwd)"
PODSIECI="$(python3 -c "
import tomllib
with open('$TU/siec.toml', 'rb') as f:
    print(' '.join(tomllib.load(f)['podsieci_lan']))
")"
# Podsieci wycofane — reguły dla nich mają ze stacji ZNIKNĄĆ (patrz siec.toml).
PODSIECI_WYCOFANE="$(python3 -c "
import tomllib
with open('$TU/siec.toml', 'rb') as f:
    print(' '.join(tomllib.load(f).get('podsieci_wycofane', [])))
")"

# Porty, które otwieramy KAŻDEJ podsieci domowej. Jedna lista — używa jej i zakładanie
# reguł, i sprzątanie po podsieci wycofanej (inaczej sprzątanie zawsze by się rozjeżdżało
# z tym, co naprawdę zakładamy).
porty_podsieci() {
    echo "22 tcp"
    echo "22000 tcp"
    echo "22000 udp"
    echo "21027 udp"
    echo "5353 udp"
    echo "1714:1764 tcp"
    echo "1714:1764 udp"
}

reguly() {
    echo "ufw default deny incoming"
    echo "ufw default allow outgoing"
    echo "ufw allow in on tailscale0"
    echo "ufw allow 41641/udp"
    for s in $PODSIECI; do
        porty_podsieci | while read -r port proto; do
            echo "ufw allow from $s to any port $port proto $proto"
        done
    done
    echo "ufw --force enable"
}

# Reguły, które kiedyś zakładaliśmy, a dziś mają zniknąć. `ufw delete` na regule,
# której nie ma, kończy się komunikatem „Could not delete non-existent rule"
# i kodem != 0 — dlatego te komendy puszczamy osobno i tolerujemy błąd.
reguly_sprzatajace() {
    for s in $PODSIECI; do
        # [258a] 2026-08-29 — zdalny pulpit tylko przez tunel SSH, port 5900 zamknięty
        echo "ufw delete allow from $s to any port 5900 proto tcp"
    done
    # [286] 2026-08-30 — podsieć wycofana z siec.toml: zdejmujemy KOMPLET reguł, które
    # kiedykolwiek dla niej zakładaliśmy (te same porty co `reguly()` + historyczny 5900).
    for s in $PODSIECI_WYCOFANE; do
        porty_podsieci | while read -r port proto; do
            echo "ufw delete allow from $s to any port $port proto $proto"
        done
        echo "ufw delete allow from $s to any port 5900 proto tcp"
    done
}

if [ "${1:-}" = "--wykonaj" ]; then
    reguly_sprzatajace | while IFS= read -r cmd; do
        echo "→ sudo $cmd   (błąd = takiej reguły już nie ma, to w porządku)"
        # shellcheck disable=SC2086
        sudo $cmd || true
    done
    reguly | while IFS= read -r cmd; do
        echo "→ sudo $cmd"
        # shellcheck disable=SC2086
        sudo $cmd
    done
    echo "Gotowe. Kontrola: grep ENABLED /etc/ufw/ufw.conf (ma być yes) i ufw status verbose."
    echo "Port 5900 ma NIE występować w 'sudo ufw status' — patrz [258a]."
else
    echo "# Podsieci LAN z siec.toml: $PODSIECI"
    echo "# Podsieci WYCOFANE (reguły do zdjęcia): ${PODSIECI_WYCOFANE:-brak}"
    echo "# PODGLĄD — nic nie zmieniam. Wykonanie: $0 --wykonaj"
    echo "# najpierw sprzątanie reguł historycznych (błąd = reguły już nie ma):"
    reguly_sprzatajace | sed 's/^/sudo /'
    echo "# potem reguły docelowe:"
    reguly | sed 's/^/sudo /'
fi
