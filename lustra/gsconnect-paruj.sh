#!/bin/sh
# Parowanie telefonu z GSConnectem na TEJ maszynie — sprawa [299], 2026-08-31.
#
# PO CO: ustawienia wtyczek GSConnecta jeżdżą lustrem (pulpit/pulpit.ini, gałąź
# .../gsconnect/device/<id telefonu>/plugin/), ale PAROWANIA lustrem przenieść się NIE DA
# i nie wolno — każda maszyna ma własny klucz i własny certyfikat (~/.config/gsconnect/),
# a parowanie to wymiana certyfikatów potwierdzona ręcznie na telefonie. Ten skrypt robi
# wszystko, co da się zrobić bez telefonu, i zostawia userowi JEDNO dotknięcie ekranu.
#
# UŻYCIE (na maszynie, która ma się sparować — także przez ssh):
#     lustra/gsconnect-paruj.sh                       # domyślny telefon (POCO X7 Pro)
#     lustra/gsconnect-paruj.sh <id-telefonu> [adres] # inny telefon / wymuszony adres LAN
#
# CO ROBI: (1) sprawdza, czy demon GSConnecta żyje, (2) jeśli maszyna nie zna telefonu
# albo stracila polaczenie — laczy sie z nim po LAN, (3) wysyła prośbę o parowanie,
# (4) przez 30 s co sekundę sprawdza, czy telefon potwierdził. Nic nie rusza na ekranie
# maszyny (żadnych okien, dźwięków, blokad).
#
# NA TELEFONIE (Android, apka „KDE Connect"): po uruchomieniu tego skryptu telefon pokazuje
# prośbę o sparowanie od komputera o tej nazwie, z przyciskami akceptacji i odrzucenia
# (widać ją i jako powiadomienie, i po wejściu w to urządzenie na liście w apce).
# Trzeba potwierdzić w ciągu 30 sekund — tyle trwa okno parowania w protokole KDE Connect
# (service/device.js, `_notifyPairRequest`). Po tym czasie po prostu uruchom skrypt jeszcze raz.
# Dokładnego brzmienia napisów w apce na Androidzie NIE sprawdzałem — nie zgaduję ich tutaj.
#
# ⛔ ID telefonu występuje też w TRZECH plikach danych pulpitu (ścieżki dconf nie umieją
#    czytać zmiennych): pulpit/dconf-lustro.txt, pulpit/dconf-wyjatki.txt,
#    pulpit/dconf-pomijane-klucze.txt. Przeinstalowanie KDE Connect na telefonie zmienia
#    id — poprawić we wszystkich czterech miejscach.
set -eu

ID="${1:-c7746d3650f644c1aca106b623fe8a98}"   # POCO X7 Pro
ADRES="${2:-}"

USL=org.gnome.Shell.Extensions.GSConnect
SCIEZKA_APKI=/org/gnome/Shell/Extensions/GSConnect
SCIEZKA_URZ="$SCIEZKA_APKI/Device/$ID"
GAL="/org/gnome/shell/extensions/gsconnect/device/$ID"

# przez ssh nie ma zmiennych sesji graficznej — dokładamy magistralę użytkownika
[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
export DBUS_SESSION_BUS_ADDRESS

czy_paruje() {
    gdbus call --session --dest "$USL" --object-path "$SCIEZKA_URZ" \
        --method org.freedesktop.DBus.Properties.Get \
        "$USL.Device" Paired 2>/dev/null | grep -q "true"
}

if ! gdbus call --session --dest "$USL" --object-path "$SCIEZKA_APKI" \
        --method org.gtk.Actions.List >/dev/null 2>&1; then
    echo "Demon GSConnecta nie odpowiada na tej maszynie."
    echo "Zwykle znaczy to, że rozszerzenie jest wyłączone albo nie ma sesji graficznej."
    echo "Sprawdź: gnome-extensions info gsconnect@andyholmes.github.io"
    exit 1
fi

if czy_paruje; then
    echo "Telefon ($ID) jest już sparowany z $(hostname) — nie ma nic do roboty."
    exit 0
fi

# Maszyna może w ogóle nie znać telefonu (nie złapała jego ogłoszenia po UDP).
# Wtedy łączymy się z nim wprost po LAN — adres bierzemy z ostatniego połączenia,
# a jeśli go nie ma, trzeba podać drugim argumentem.
if ! gdbus call --session --dest "$USL" --object-path "$SCIEZKA_APKI" \
        --method org.freedesktop.DBus.ObjectManager.GetManagedObjects 2>/dev/null \
        | grep -q "$ID"; then
    if [ -z "$ADRES" ]; then
        ADRES="$(dconf read "$GAL/last-connection" 2>/dev/null | tr -d "'" || true)"
    fi
    if [ -z "$ADRES" ]; then
        echo "Ta maszyna nie zna jeszcze telefonu i nie znam jego adresu."
        echo "Podaj go drugim argumentem, np.:  $0 $ID lan://192.168.1.81:1716"
        exit 1
    fi
    case "$ADRES" in lan://*) : ;; *) ADRES="lan://$ADRES" ;; esac
    echo "Łączę się z telefonem pod adresem $ADRES ..."
    gdbus call --session --dest "$USL" --object-path "$SCIEZKA_APKI" \
        --method org.gtk.Actions.Activate connect "[<\"$ADRES\">]" "{}" >/dev/null
    sleep 3
fi

echo "Wysyłam prośbę o sparowanie z $(hostname) do telefonu $ID ..."
gdbus call --session --dest "$USL" --object-path "$SCIEZKA_URZ" \
    --method org.gtk.Actions.Activate pair "[]" "{}" >/dev/null

echo "TERAZ NA TELEFONIE: prośba o sparowanie od komputera „$(hostname)” → potwierdź ją."
echo "Masz na to 30 sekund. Klucz weryfikacyjny tej maszyny widać w apce GSConnect."
i=0
while [ "$i" -lt 30 ]; do
    if czy_paruje; then
        echo "SPAROWANE. Telefon i $(hostname) widzą się nawzajem."
        exit 0
    fi
    sleep 1
    i=$((i + 1))
done

echo "Minęło 30 sekund bez potwierdzenia — okno parowania się zamknęło."
echo "Nic się nie zepsuło; uruchom skrypt jeszcze raz, mając telefon w ręku."
exit 2
