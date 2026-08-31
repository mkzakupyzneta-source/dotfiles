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
# albo straciła połączenie — łączy się z nim po LAN, (3) wysyła prośbę o parowanie,
# (4) przez 30 s co sekundę sprawdza, czy telefon potwierdził, (5) po sparowaniu WGRYWA
# ustawienia wtyczek z wzorca pulpitu (lustra/pulpit/pulpit.ini). Nic nie rusza na ekranie
# maszyny (żadnych okien, dźwięków, blokad). Na maszynie już sparowanej robi od razu (5),
# więc jest idempotentny i nadaje się do ponownego wyrównania ustawień.
#
# ⚠️ DLACZEGO USTAWIENIA WGRYWAMY PO PAROWANIU, A NIE PRZED: GSConnect sam kasuje ustawienia
#    urządzenia, które jest NIESPAROWANE i się rozłączyło — `dconf reset -f .../device/<id>/`
#    w service/manager.js (`_removeDevice`, wołane cyklicznie z `_reconnect`). Zmierzone na
#    żywo 31.08: 18 kluczy zapisanych na Vostro zniknęło, gdy telefon zmienił adres w sieci.
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

case "${1:-}" in
    -h|--help|--pomoc)
        sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
        exit 0 ;;
esac

ID="${1:-c7746d3650f644c1aca106b623fe8a98}"   # POCO X7 Pro
ADRES="${2:-}"

USL=org.gnome.Shell.Extensions.GSConnect
SCIEZKA_APKI=/org/gnome/Shell/Extensions/GSConnect
SCIEZKA_URZ="$SCIEZKA_APKI/Device/$ID"
GAL="/org/gnome/shell/extensions/gsconnect/device/$ID"

# przez ssh nie ma zmiennych sesji graficznej — dokładamy magistralę użytkownika
[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
export DBUS_SESSION_BUS_ADDRESS

TU="$(cd "$(dirname "$0")" && pwd)"

# Ustawienia wtyczek dla TEGO urządzenia, wzięte z wzorca pulpitu (lustra/pulpit/pulpit.ini).
# Robimy to PO sparowaniu, a nie przed, bo GSConnect kasuje (`dconf reset -f`) ustawienia
# urządzenia niesparowanego, które się rozłączyło (service/manager.js, `_removeDevice`).
wgraj_ustawienia_z_lustra() {
    python3 - "$TU" "$ID" <<'PYEOF'
import importlib.util, subprocess, sys
tu, ident = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("lustro", tu + "/lustro.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
wzor = m.wczytaj_pulpit_z_lustra() or {}
przedrostek = "/org/gnome/shell/extensions/gsconnect/device/%s/" % ident
mapa = m.znaczniki_tej_maszyny()
zapisane, pominiete = 0, []
for klucz, wartosc in sorted(wzor.items()):
    if not klucz.startswith(przedrostek):
        continue
    tresc = m.rozwin_znaczniki(wartosc.replace("{{HOME}}", str(m.DOM)), mapa)
    if m.nierozwiazane_znaczniki(tresc, mapa):
        pominiete.append(klucz)
        continue
    if subprocess.run(["dconf", "write", klucz, tresc]).returncode == 0:
        zapisane += 1
    else:
        pominiete.append(klucz)
if not wzor:
    print("Wzorzec pulpitu jest pusty — nie ma czego wgrać.")
elif zapisane == 0 and not pominiete:
    print("Wzorzec nie ma ustawień dla tego urządzenia — nic nie wgrywam.")
else:
    print("Ustawienia wtyczek wgrane z lustra: %d kluczy." % zapisane)
    for k in pominiete:
        print("   POMINIĘTE:", k)
PYEOF
}

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
    echo "Telefon ($ID) jest już sparowany z $(hostname)."
    wgraj_ustawienia_z_lustra
    exit 0
fi

# Maszyna może w ogóle nie znać telefonu (nie złapała jego ogłoszenia po UDP).
# Wtedy łączymy się z nim wprost po LAN — adres bierzemy z ostatniego połączenia,
# a jeśli go nie ma, trzeba podać drugim argumentem.
if ! gdbus call --session --dest "$USL" --object-path "$SCIEZKA_APKI" \
        --method org.freedesktop.DBus.ObjectManager.GetManagedObjects 2>/dev/null \
        | grep -qF -- "$ID"; then
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
        wgraj_ustawienia_z_lustra
        exit 0
    fi
    sleep 1
    i=$((i + 1))
done

echo "Minęło 30 sekund bez potwierdzenia — okno parowania się zamknęło."
echo "Nic się nie zepsuło; uruchom skrypt jeszcze raz, mając telefon w ręku."
exit 2
