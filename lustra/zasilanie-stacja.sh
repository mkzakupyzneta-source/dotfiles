#!/bin/sh
# Reguły sudo BEZ HASŁA dotyczące ZASILANIA tej maszyny — budowane z DANYCH
# (`lustra/maszyny.toml`), nie z zaszytej listy maszyn. Sprawa [267c], 2026-08-29, obszar 5.
#
# Po co: panel menadżera sieci (obszar 1_Serwer) wyłącza maszynę przez SSH poleceniem
# `sudo -n systemctl poweroff || systemctl poweroff`. Sam `systemctl poweroff` przez SSH
# odbija się od polkit (sesja zdalna nie jest „aktywna"), a `sudo` z hasłem nie ma komu
# odpowiedzieć — bez tej reguły przycisk „wyłącz" nie zadziała.
#
# CZY ta maszyna ma regułę dostać, decyduje POLE, nie ten skrypt:
#   wolno_wylaczac = true  w jej bloku [[maszyna]] pliku lustra/maszyny.toml.
# Brak pola albo false = reguła ma NIE istnieć (i skrypt ją zdejmie, gdyby została po zmianie
# decyzji). To ta sama dana, którą czyta panel — jedno miejsce prawdy, zero rozjazdu.
#
# Wąsko z rozmysłem: NOPASSWD obejmuje wyłącznie `/usr/bin/systemctl poweroff` — dokładnie
# jedno polecenie z jednym argumentem. Nie `systemctl` w ogóle (to byłoby oddanie roota),
# nie `reboot`, nie `suspend` (usypianie idzie dziś inną drogą — patrz TODO obszaru 5).
#
# Domyślnie tylko WYPISUJE, co by zrobił (nic nie zmienia). `--wykonaj` wykonuje przez sudo
# (zapyta o hasło — NOPASSWD dla pakietów z /etc/sudoers.d/90-lustro-pakiety tego nie obejmuje).
# Sprawdzenie po wgraniu:  sudo -n systemctl --help >/dev/null && sudo -l | grep poweroff
set -eu

TU="$(cd "$(dirname "$0")" && pwd)"
PLIK=/etc/sudoers.d/91-lustro-zasilanie
UZYTKOWNIK="${SUDO_USER:-$(id -un)}"
NAZWA_HOSTA="${LUSTRO_HOSTNAME:-$(hostname)}"

# Czy ta maszyna ma zgodę na wyłączanie — pytamy DANYCH, nie kodu.
WOLNO="$(python3 -c "
import tomllib, sys
host = '$NAZWA_HOSTA'.strip().lower()
with open('$TU/maszyny.toml', 'rb') as f:
    dane = tomllib.load(f)
for m in dane.get('maszyna', []):
    if str(m.get('nazwa_hosta', '')).strip().lower() == host:
        print('tak' if m.get('wolno_wylaczac') else 'nie')
        break
else:
    print('brak-wpisu')
")"

TRESC="$UZYTKOWNIK ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff"

case "$WOLNO" in
    tak)
        AKCJA=zaloz ;;
    nie)
        AKCJA=zdejmij ;;
    *)
        echo "maszyny.toml nie ma wpisu o nazwa_hosta = '$NAZWA_HOSTA' — nic nie robię."
        echo "(dopisz blok [[maszyna]] albo uruchom z LUSTRO_HOSTNAME=<nazwa z pliku>)"
        exit 0 ;;
esac

if [ "${1:-}" != "--wykonaj" ]; then
    echo "# PODGLĄD — nic nie zmieniam. Wykonanie: $0 --wykonaj"
    echo "# maszyna: $NAZWA_HOSTA, wolno_wylaczac: $WOLNO, użytkownik: $UZYTKOWNIK"
    if [ $AKCJA = zaloz ]; then
        echo "# treść $PLIK:"
        echo "#   $TRESC"
        echo "sudo install -m 440 -o root -g root <plik tymczasowy> $PLIK   # po visudo -cf"
    else
        echo "sudo rm -f $PLIK   # ta maszyna nie ma zgody na wyłączanie"
    fi
    exit 0
fi

if [ $AKCJA = zdejmij ]; then
    # `rm -f` jest idempotentne — nie sprawdzamy wcześniej `test -f`, bo katalog
    # /etc/sudoers.d/ czyta tylko root i sam sprawdzian kosztowałby drugie pytanie o hasło.
    sudo rm -f "$PLIK"
    echo "dopilnowane: $PLIK nie istnieje (ta maszyna nie ma wolno_wylaczac = true)"
    exit 0
fi

TMP=/tmp/91-lustro-zasilanie.$$
printf '%s\n' "$TRESC" >"$TMP"
if sudo visudo -cf "$TMP" >/dev/null; then
    sudo install -m 440 -o root -g root "$TMP" "$PLIK"
    rm -f "$TMP"
    echo "wgrane: $PLIK"
    echo "  $TRESC"
    sudo -l 2>/dev/null | grep -i poweroff || echo "  (uwaga: sudo -l nie pokazuje reguły — sprawdź ręcznie)"
else
    rm -f "$TMP"
    echo "BŁĄD: visudo odrzucił treść reguły — NIC nie wgrałem." >&2
    exit 1
fi
