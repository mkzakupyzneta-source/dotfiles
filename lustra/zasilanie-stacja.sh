#!/bin/sh
# Ustawienia ZASILANIA tej maszyny budowane z DANYCH (`lustra/maszyny.toml`), nie z zaszytej
# listy maszyn. Sprawa [267c] (reguła sudo na wyłączanie, 2026-08-29) i [279] (klapa, 2026-08-30).
# Obszar 5_Wspolna_konfiguracja.
#
# Skrypt robi TRZY rzeczy, każdą sterowaną osobnym polem danych:
#
#   1. REGUŁA SUDO NA WYŁĄCZANIE      ← pole `wolno_wylaczac`
#      /etc/sudoers.d/91-lustro-zasilanie: `<user> ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff`
#      Po co: panel menadżera sieci (obszar 1_Serwer) wyłącza maszynę przez SSH poleceniem
#      `sudo -n systemctl poweroff || systemctl poweroff`. Sam `systemctl poweroff` przez SSH
#      odbija się od polkit (sesja zdalna nie jest „aktywna"), a `sudo` z hasłem nie ma komu
#      odpowiedzieć. Wąsko z rozmysłem: dokładnie jedno polecenie z jednym argumentem — nie
#      `systemctl` w ogóle (to byłoby oddanie roota), nie `reboot`, nie `suspend`.
#      Brak pola albo false = reguła ma NIE istnieć i skrypt ją ZDEJMUJE.
#
#   2. ZACHOWANIE PO ZAMKNIĘCIU KLAPY ← pole `klapa_zamkniecie`
#      /etc/systemd/logind.conf.d/50-lustro-klapa.conf z trzema `HandleLidSwitch*=ignore`.
#        "ignoruj"      → drop-in zakładany (klapa nie robi nic)
#        "ekran-gasnie" → drop-in zakładany (logind ma się nie wtrącać; ekran gasi i po
#                         `klapa_usyp_po_min` minutach usypia usługa użytkownika
#                         `klapa-straznik.service`, wożona przez chezmoi)
#        "usyp" / brak  → drop-in ZDEJMOWANY (wraca domyślne zachowanie systemu)
#      Drop-in wchodzi w życie po restarcie maszyny albo po `systemctl restart systemd-logind`
#      — tego drugiego skrypt NIE robi sam (patrz `--przeladuj-logind` niżej).
#
#   3. CZY OTWARCIE KLAPY BUDZI       ← pole `klapa_otwarcie_budzi`
#      false → wyłączamy źródło wybudzeń o nazwie zaczynającej się od `LID` w /proc/acpi/wakeup.
#      ⚠️ Wpis w /proc/acpi/wakeup jest PRZEŁĄCZNIKIEM (echo NAZWA > plik zmienia stan na
#      przeciwny) i po restarcie wraca do stanu z BIOS-u — dlatego stan sprawdzamy PRZED zapisem,
#      a trwałość daje jednostka systemowa `lustro-klapa-wakeup.service` (Type=oneshot przy każdym
#      starcie woła ten sam skrypt z `--przy-starcie`).
#      ⚠️ Nie każda maszyna ma taki wpis. Na HP (zmierzone 2026-08-30) w /proc/acpi/wakeup NIE MA
#      żadnej pozycji LID*, a `PNP0C0D:00` (klapa) nie jest zarejestrowana jako źródło wybudzeń —
#      skrypt mówi to wprost i NIE udaje, że coś ustawił.
#
# O tym, CO ta maszyna dostaje, decydują POLA, nie ten skrypt — to te same dane, które czyta
# panel menadżera sieci i strażnik klapy. Jedno miejsce prawdy, zero rozjazdu.
#
# Użycie:
#   zasilanie-stacja.sh                   podgląd (nic nie zmienia, nie potrzebuje roota)
#   zasilanie-stacja.sh --wykonaj         wykonanie przez sudo (zapyta o hasło)
#   zasilanie-stacja.sh --wykonaj --przeladuj-logind
#                                         dodatkowo `systemctl restart systemd-logind`, żeby
#                                         ustawienie klapy weszło BEZ restartu maszyny
#                                         (sesja graficzna zwykle to przeżywa — bez gwarancji)
#   zasilanie-stacja.sh --przy-starcie    tylko krok 3, po cichu; woła to jednostka systemowa
#
# Zmienne: LUSTRO_HOSTNAME=<nazwa> udaje inną maszynę (podgląd/testy).
# Sprawdzenie po wgraniu:  sudo -l | grep poweroff ; cat /etc/systemd/logind.conf.d/50-lustro-klapa.conf
set -eu

TU="$(cd "$(dirname "$0")" && pwd)"
PLIK_SUDO=/etc/sudoers.d/91-lustro-zasilanie
PLIK_KLAPA=/etc/systemd/logind.conf.d/50-lustro-klapa.conf
PLIK_KLAPA_STARY=/etc/systemd/logind.conf.d/50-moc-obliczeniowa.conf   # [267d], poza mechanizmem
USLUGA_WAKE=/etc/systemd/system/lustro-klapa-wakeup.service
UZYTKOWNIK="${SUDO_USER:-$(id -un)}"
NAZWA_HOSTA="${LUSTRO_HOSTNAME:-$(hostname)}"

TRYB=podglad
PRZELADUJ=nie
for a in "$@"; do
    case "$a" in
        --wykonaj)          TRYB=wykonaj ;;
        --przy-starcie)     TRYB=przy-starcie ;;
        --przeladuj-logind) PRZELADUJ=tak ;;
        *) echo "nieznany argument: $a (dozwolone: --wykonaj, --przy-starcie, --przeladuj-logind)" >&2; exit 2 ;;
    esac
done

# Pod rootem (jednostka systemowa) nie ma po co wołać sudo.
if [ "$(id -u)" = 0 ]; then SUDO=""; else SUDO="sudo"; fi

# ---------------------------------------------------------------- DANE (jedno pytanie do TOML-a)
DANE="$(python3 -c "
import tomllib
host = '''$NAZWA_HOSTA'''.strip().lower()
with open('$TU/maszyny.toml', 'rb') as f:
    flota = tomllib.load(f)
for m in flota.get('maszyna', []):
    if str(m.get('nazwa_hosta', '')).strip().lower() == host:
        print('jest')
        print('tak' if m.get('wolno_wylaczac') else 'nie')
        print(str(m.get('klapa_zamkniecie') or 'usyp'))
        print(str(m.get('klapa_usyp_po_min', 5)))
        print('tak' if m.get('klapa_otwarcie_budzi', True) else 'nie')
        break
else:
    print('brak'); print('nie'); print('usyp'); print('5'); print('tak')
")"

WPIS=$(echo "$DANE"      | sed -n 1p)
WOLNO=$(echo "$DANE"     | sed -n 2p)
KLAPA=$(echo "$DANE"     | sed -n 3p)
KLAPA_MIN=$(echo "$DANE" | sed -n 4p)
BUDZI=$(echo "$DANE"     | sed -n 5p)

if [ "$WPIS" = brak ] && [ "$TRYB" != przy-starcie ]; then
    echo "maszyny.toml nie ma wpisu o nazwa_hosta = '$NAZWA_HOSTA' — nic nie robię."
    echo "(dopisz blok [[maszyna]] albo uruchom z LUSTRO_HOSTNAME=<nazwa z pliku>)"
    exit 0
fi

case "$KLAPA" in
    usyp|ekran-gasnie|ignoruj) : ;;
    *) echo "BŁĄD: klapa_zamkniecie = '$KLAPA' — dozwolone: usyp, ekran-gasnie, ignoruj." >&2
       echo "(popraw dane w lustra/maszyny.toml; nic nie zmieniam)" >&2; exit 2 ;;
esac
case "$KLAPA_MIN" in
    ''|*[!0-9]*) echo "BŁĄD: klapa_usyp_po_min = '$KLAPA_MIN' — ma być liczbą całkowitą minut." >&2; exit 2 ;;
esac

TRESC_SUDO="$UZYTKOWNIK ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff"
TRESC_KLAPA="# Zakłada lustra/zasilanie-stacja.sh z pola klapa_zamkniecie = \"$KLAPA\" ([279]).
# Ręczna edycja tego pliku nie ma sensu — najbliższe uruchomienie skryptu ją nadpisze.
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore"

if [ "$WOLNO" = tak ]; then AKCJA_SUDO=zaloz; else AKCJA_SUDO=zdejmij; fi
if [ "$KLAPA" = usyp ];  then AKCJA_KLAPA=zdejmij; else AKCJA_KLAPA=zaloz; fi

# ---------------------------------------------------------------- źródło wybudzeń klapy
# Nazwa urządzenia (LID, LID0, LID_) — szukamy w danych systemu, nie zgadujemy.
URZ_LID=""
STAN_LID=""
if [ -r /proc/acpi/wakeup ]; then
    URZ_LID=$(awk '$1 ~ /^LID/ {print $1; exit}' /proc/acpi/wakeup)
    if [ -n "$URZ_LID" ]; then
        STAN_LID=$(awk -v d="$URZ_LID" '$1==d {print $3}' /proc/acpi/wakeup | tr -d '*')
    fi
fi
# Czego chcemy: budzi=nie → disabled; budzi=tak → nie ruszamy (zostawiamy stan z BIOS-u).
if [ "$BUDZI" = nie ] && [ -n "$URZ_LID" ] && [ "$STAN_LID" = enabled ]; then
    AKCJA_LID=przelacz
elif [ "$BUDZI" = nie ] && [ -z "$URZ_LID" ]; then
    AKCJA_LID=brak-zrodla
elif [ "$BUDZI" = nie ]; then
    AKCJA_LID=juz-dobrze
else
    AKCJA_LID=nie-dotyczy
fi

# ---------------------------------------------------------------- tryb: tylko krok 3 (jednostka)
if [ "$TRYB" = przy-starcie ]; then
    case "$AKCJA_LID" in
        przelacz)
            echo "$URZ_LID" > /proc/acpi/wakeup
            logger -t lustro-klapa "wybudzanie klapą wyłączone ($URZ_LID)" 2>/dev/null || true
            echo "wyłączone wybudzanie klapą: $URZ_LID" ;;
        juz-dobrze)   echo "wybudzanie klapą już wyłączone ($URZ_LID) — bez zmian" ;;
        brak-zrodla)  echo "ta maszyna nie ma w /proc/acpi/wakeup pozycji LID* — nie ma czego wyłączać" ;;
        *)            echo "klapa_otwarcie_budzi = tak (albo brak wpisu maszyny) — nic nie robię" ;;
    esac
    exit 0
fi

# ---------------------------------------------------------------- PODGLĄD
if [ "$TRYB" = podglad ]; then
    echo "# PODGLĄD — nic nie zmieniam. Wykonanie: $0 --wykonaj"
    echo "# maszyna: $NAZWA_HOSTA, użytkownik: $UZYTKOWNIK"
    echo "# dane: wolno_wylaczac: $WOLNO | klapa_zamkniecie: $KLAPA | klapa_usyp_po_min: $KLAPA_MIN | klapa_otwarcie_budzi: $BUDZI"
    echo
    echo "1) reguła sudo na wyłączanie ($PLIK_SUDO): $AKCJA_SUDO"
    if [ $AKCJA_SUDO = zaloz ]; then
        echo "   treść:  $TRESC_SUDO"
        echo "   sudo install -m 440 -o root -g root <plik tymczasowy> $PLIK_SUDO   # po visudo -cf"
    else
        echo "   sudo rm -f $PLIK_SUDO   # ta maszyna nie ma wolno_wylaczac = true"
    fi
    echo
    echo "2) zachowanie klapy ($PLIK_KLAPA): $AKCJA_KLAPA"
    if [ $AKCJA_KLAPA = zaloz ]; then
        if [ -f "$PLIK_KLAPA" ] && [ "$(cat "$PLIK_KLAPA")" = "$TRESC_KLAPA" ]; then
            echo "   plik już ma dokładnie tę treść — nic do zrobienia"
        else
            echo "   treść:"
            echo "$TRESC_KLAPA" | sed 's/^/     /'
        fi
        [ "$KLAPA" = ekran-gasnie ] && echo "   + ekran gasi i po $KLAPA_MIN min usypia usługa użytkownika klapa-straznik.service"
    else
        echo "   sudo rm -f $PLIK_KLAPA   # ta maszyna ma wracać do domyślnego „klapa usypia\""
    fi
    if [ -f "$PLIK_KLAPA_STARY" ]; then
        echo "   ⚠️ ISTNIEJE STARY PLIK SPOZA MECHANIZMU: $PLIK_KLAPA_STARY ([267d], Katana)."
        echo "      Robi to samo. Nie kasuję go sam (cudzy) — po założeniu naszego można usunąć:"
        echo "      sudo rm -f $PLIK_KLAPA_STARY"
    fi
    echo
    echo "3) czy otwarcie klapy budzi (klapa_otwarcie_budzi = $BUDZI): $AKCJA_LID"
    case "$AKCJA_LID" in
        przelacz)    echo "   echo $URZ_LID > /proc/acpi/wakeup   # dziś: $STAN_LID → disabled"
                     echo "   + jednostka $USLUGA_WAKE (utrwalenie na restarty)" ;;
        juz-dobrze)  echo "   $URZ_LID już disabled; sprawdzę tylko, czy jest jednostka $USLUGA_WAKE" ;;
        brak-zrodla) echo "   /proc/acpi/wakeup NIE MA pozycji LID* — na tej maszynie klapa nie jest"
                     echo "   zarejestrowanym źródłem wybudzeń, więc NIE MA CZEGO wyłączać."
                     echo "   (To nie jest sukces ani porażka — to brak przedmiotu działania.)" ;;
        *)           echo "   nic nie robimy (pole na true albo brak pola = zostaw jak jest)" ;;
    esac
    echo
    # Znacznik dla automatu `nowa-stacja.sh` (krok K3b) i dla oka: czy w ogóle jest co robić.
    # Dzięki temu automat nie prosi o hasło sudo na maszynie, która nie ma żadnego z tych ustawień.
    if [ $AKCJA_SUDO = zdejmij ] && [ $AKCJA_KLAPA = zdejmij ] \
       && { [ "$AKCJA_LID" = nie-dotyczy ] || [ "$AKCJA_LID" = brak-zrodla ]; }; then
        echo "# nic-do-zrobienia (ta maszyna nie ma w danych żadnego ustawienia zasilania)"
    else
        echo "# jest-co-robic"
    fi
    exit 0
fi

# ---------------------------------------------------------------- WYKONANIE
echo "== 1) reguła sudo na wyłączanie =="
if [ $AKCJA_SUDO = zdejmij ]; then
    # `rm -f` jest idempotentne — nie sprawdzamy wcześniej `test -f`, bo katalog
    # /etc/sudoers.d/ czyta tylko root i sam sprawdzian kosztowałby drugie pytanie o hasło.
    $SUDO rm -f "$PLIK_SUDO"
    echo "dopilnowane: $PLIK_SUDO nie istnieje (brak wolno_wylaczac = true)"
else
    TMP=/tmp/91-lustro-zasilanie.$$
    printf '%s\n' "$TRESC_SUDO" >"$TMP"
    if $SUDO visudo -cf "$TMP" >/dev/null; then
        $SUDO install -m 440 -o root -g root "$TMP" "$PLIK_SUDO"
        rm -f "$TMP"
        echo "wgrane: $PLIK_SUDO"
        echo "  $TRESC_SUDO"
        $SUDO -l 2>/dev/null | grep -i poweroff || echo "  (uwaga: sudo -l nie pokazuje reguły — sprawdź ręcznie)"
    else
        rm -f "$TMP"
        echo "BŁĄD: visudo odrzucił treść reguły — NIC nie wgrałem." >&2
        exit 1
    fi
fi

echo
echo "== 2) zachowanie klapy (klapa_zamkniecie = $KLAPA) =="
ZMIENIONO_KLAPE=nie
if [ $AKCJA_KLAPA = zdejmij ]; then
    if [ -f "$PLIK_KLAPA" ]; then
        $SUDO rm -f "$PLIK_KLAPA"; ZMIENIONO_KLAPE=tak
        echo "zdjęte: $PLIK_KLAPA (wraca domyślne „zamknięcie klapy usypia\")"
    else
        echo "bez zmian: $PLIK_KLAPA i tak nie istnieje"
    fi
else
    if [ -f "$PLIK_KLAPA" ] && [ "$(cat "$PLIK_KLAPA")" = "$TRESC_KLAPA" ]; then
        echo "bez zmian: $PLIK_KLAPA ma już dokładnie tę treść"
    else
        TMPK=/tmp/50-lustro-klapa.$$
        printf '%s\n' "$TRESC_KLAPA" >"$TMPK"
        $SUDO install -d -m 755 /etc/systemd/logind.conf.d
        $SUDO install -m 644 -o root -g root "$TMPK" "$PLIK_KLAPA"
        rm -f "$TMPK"; ZMIENIONO_KLAPE=tak
        echo "wgrane: $PLIK_KLAPA (HandleLidSwitch/ExternalPower/Docked = ignore)"
    fi
fi
if [ -f "$PLIK_KLAPA_STARY" ]; then
    echo "⚠️ istnieje też $PLIK_KLAPA_STARY (spoza mechanizmu, [267d]) — robi to samo."
    echo "   Nie kasuję go sam. Do usunięcia ręcznie:  sudo rm -f $PLIK_KLAPA_STARY"
fi
if [ $ZMIENIONO_KLAPE = tak ]; then
    if [ $PRZELADUJ = tak ]; then
        $SUDO systemctl restart systemd-logind
        echo "systemd-logind przeładowany — ustawienie działa OD ZARAZ"
    else
        echo "⏳ ustawienie wejdzie po restarcie maszyny."
        echo "   Bez restartu:  sudo systemctl restart systemd-logind"
        echo "   (sesja graficzna zwykle to przeżywa, ale gwarancji nie ma — dlatego nie robię tego sam)"
    fi
fi

echo
echo "== 3) czy otwarcie klapy budzi (klapa_otwarcie_budzi = $BUDZI) =="
case "$AKCJA_LID" in
    brak-zrodla)
        echo "ta maszyna NIE MA w /proc/acpi/wakeup pozycji LID* — nie ma czego wyłączać."
        echo "Zamiar z danych zapisany, ale mechanizm nic tu nie zmienił (i nie udaje, że zmienił)."
        echo "Jednostki $USLUGA_WAKE nie zakładam — nie miałaby co robić." ;;
    nie-dotyczy)
        echo "pole na true (albo brak) — zostawiam wybudzanie tak, jak jest."
        if [ -f "$USLUGA_WAKE" ]; then
            $SUDO systemctl disable --now lustro-klapa-wakeup.service >/dev/null 2>&1 || true
            $SUDO rm -f "$USLUGA_WAKE"; $SUDO systemctl daemon-reload
            echo "zdjęta zbędna jednostka $USLUGA_WAKE"
        fi ;;
    przelacz|juz-dobrze)
        if [ "$AKCJA_LID" = przelacz ]; then
            echo "$URZ_LID" | $SUDO tee /proc/acpi/wakeup >/dev/null
            TERAZ=$(awk -v d="$URZ_LID" '$1==d {print $3}' /proc/acpi/wakeup | tr -d '*')
            if [ "$TERAZ" = disabled ]; then
                echo "wyłączone: $URZ_LID ($STAN_LID → $TERAZ)"
            else
                echo "⚠️ po przełączeniu $URZ_LID nadal jest '$TERAZ' — sprawdź ręcznie /proc/acpi/wakeup" >&2
            fi
        else
            echo "bez zmian: $URZ_LID już disabled"
        fi
        TMPU=/tmp/lustro-klapa-wakeup.$$
        cat >"$TMPU" <<UNIT
[Unit]
Description=Klapa nie budzi tej maszyny (mechanizm luster, sprawa [279])
Documentation=file://$TU/zasilanie-stacja.sh
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh $TU/zasilanie-stacja.sh --przy-starcie

[Install]
WantedBy=multi-user.target
UNIT
        if [ -f "$USLUGA_WAKE" ] && [ "$(cat "$USLUGA_WAKE")" = "$(cat "$TMPU")" ]; then
            echo "bez zmian: $USLUGA_WAKE"
        else
            $SUDO install -m 644 -o root -g root "$TMPU" "$USLUGA_WAKE"
            $SUDO systemctl daemon-reload
            echo "wgrane: $USLUGA_WAKE"
        fi
        rm -f "$TMPU"
        $SUDO systemctl enable lustro-klapa-wakeup.service >/dev/null 2>&1 \
            && echo "jednostka włączona (utrwala wyłączenie po każdym starcie)" \
            || echo "⚠️ nie udało się włączyć lustro-klapa-wakeup.service — sprawdź ręcznie" ;;
esac
