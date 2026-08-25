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

reguly() {
    echo "ufw default deny incoming"
    echo "ufw default allow outgoing"
    echo "ufw allow in on tailscale0"
    echo "ufw allow 41641/udp"
    for s in $PODSIECI; do
        echo "ufw allow from $s to any port 22 proto tcp"
        echo "ufw allow from $s to any port 22000 proto tcp"
        echo "ufw allow from $s to any port 22000 proto udp"
        echo "ufw allow from $s to any port 21027 proto udp"
        echo "ufw allow from $s to any port 5353 proto udp"
        echo "ufw allow from $s to any port 1714:1764 proto tcp"
        echo "ufw allow from $s to any port 1714:1764 proto udp"
    done
    echo "ufw --force enable"
}

if [ "${1:-}" = "--wykonaj" ]; then
    reguly | while IFS= read -r cmd; do
        echo "→ sudo $cmd"
        # shellcheck disable=SC2086
        sudo $cmd
    done
    echo "Gotowe. Kontrola: grep ENABLED /etc/ufw/ufw.conf (ma być yes) i ufw status verbose."
else
    echo "# Podsieci LAN z siec.toml: $PODSIECI"
    echo "# PODGLĄD — nic nie zmieniam. Wykonanie: $0 --wykonaj"
    reguly | sed 's/^/sudo /'
fi
