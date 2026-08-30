#!/bin/bash
# Strażnik klapy — sprawa [279], 2026-08-30, obszar 5_Wspolna_konfiguracja.
#
# PO CO: na maszynie z `klapa_zamkniecie = "ekran-gasnie"` (dziś: HP) zamknięcie klapy ma
# NATYCHMIAST zgasić ekran, ale NIE usypiać — user przenosi zamknięty laptop między pokojami
# i chce, żeby praca szła dalej. Uśpienie ma przyjść dopiero po `klapa_usyp_po_min` minutach,
# jeśli klapa nadal jest zamknięta. Otwarcie klapy w międzyczasie odwołuje odliczanie.
#
# CZEGO NIE ROBI: nie usypia, gdy podłączony jest monitor zewnętrzny (dok) — praca na
# monitorach z zamkniętą klapą ma trwać. Wtedy też nie gasi (jest na czym patrzeć).
#
# CO GO WŁĄCZA: usługa użytkownika `klapa-straznik.service` (wozi ją chezmoi; włącza/wyłącza
# `run_onchange_after_wlacz-klapa-straznik.sh.tmpl` na podstawie danych). Sam skrypt też
# sprawdza dane i na maszynie z inną wartością `klapa_zamkniecie` kończy się od razu —
# dwie niezależne zapory, żeby nigdy nie zgasił ekranu tam, gdzie nie powinien.
#
# GDZIE SĄ USTAWIENIA: `lustra/maszyny.toml`, blok tej maszyny (pola `klapa_zamkniecie`
# i `klapa_usyp_po_min`). W tym pliku NIE MA ani jednej nazwy maszyny — to dane, nie kod.
# Logind ma przy tym stać z boku: drop-in `50-lustro-klapa.conf` (HandleLidSwitch*=ignore)
# zakłada `lustra/zasilanie-stacja.sh --wykonaj`. Bez niego system uśpi laptop od razu
# i strażnik nie zdąży nic zrobić.
#
# DZIENNIK: journal, znacznik `klapa-straznik`.
#   journalctl --user -t klapa-straznik -n 50          (wpisy z tej sesji)
#   journalctl -t klapa-straznik --since today         (wszystko)
#
# TESTOWANIE NA SUCHO (nic nie dotyka ekranu ani zasilania) — wszystkie polecenia i dane
# są wstrzykiwane zmiennymi środowiskowymi, więc test nie wymaga zmiany kodu:
#   KLAPA_ZAMKNIECIE=ekran-gasnie KLAPA_USYP_PO_MIN=1 KLAPA_INTERWAL=1 KLAPA_KROKI=10 \
#   KLAPA_STAN_CMD='cat /tmp/klapa-test' KLAPA_MONITORY_CMD='echo 0' \
#   KLAPA_EKRAN_SWIECI_CMD='true' KLAPA_GAS_CMD='echo ATRAPA-gaszenie' \
#   KLAPA_USYP_CMD='echo ATRAPA-uspienie' ~/bin/klapa-straznik.sh
set -uo pipefail

MASZYNY="${LUSTRO_MASZYNY:-$HOME/.local/share/chezmoi/lustra/maszyny.toml}"
NAZWA_HOSTA="${LUSTRO_HOSTNAME:-$(hostname)}"
INTERWAL="${KLAPA_INTERWAL:-5}"     # co ile sekund pytamy o stan klapy
KROKI="${KLAPA_KROKI:-0}"           # 0 = bez końca; >0 = tyle przebiegów (do testów)

dziennik() { logger -t klapa-straznik "$*" 2>/dev/null; echo "[klapa-straznik] $*"; }

# ------------------------------------------------------------------ DANE
# Zawsze z pliku danych; zmienne środowiskowe tylko na testy.
czytaj_dane() {
    python3 - "$MASZYNY" "$NAZWA_HOSTA" <<'PY' 2>/dev/null
import sys, tomllib
plik, host = sys.argv[1], sys.argv[2].strip().lower()
try:
    with open(plik, "rb") as f:
        flota = tomllib.load(f)
except Exception:
    print("brak"); print("5"); raise SystemExit(0)
for m in flota.get("maszyna", []):
    if str(m.get("nazwa_hosta", "")).strip().lower() == host:
        print(str(m.get("klapa_zamkniecie") or "usyp"))
        print(str(m.get("klapa_usyp_po_min", 5)))
        break
else:
    print("brak"); print("5")
PY
}
DANE="$(czytaj_dane)"
ZAMKNIECIE="${KLAPA_ZAMKNIECIE:-$(sed -n 1p <<<"$DANE")}"
USYP_PO_MIN="${KLAPA_USYP_PO_MIN:-$(sed -n 2p <<<"$DANE")}"
[[ -z "$ZAMKNIECIE" ]] && ZAMKNIECIE=brak
[[ "$USYP_PO_MIN" =~ ^[0-9]+$ ]] || USYP_PO_MIN=5

if [[ "$ZAMKNIECIE" != "ekran-gasnie" ]]; then
    dziennik "maszyna '$NAZWA_HOSTA' ma klapa_zamkniecie = '$ZAMKNIECIE' — strażnik niepotrzebny, kończę"
    exit 0
fi

[[ -z "${DISPLAY:-}" ]] && export DISPLAY=:1

# ------------------------------------------------------------------ CZUJNIKI I DŹWIGNIE
# Każdy da się podmienić zmienną — stąd testy na atrapach bez dotykania maszyny.

stan_klapy() {
    if [[ -n "${KLAPA_STAN_CMD:-}" ]]; then
        local w; w="$(eval "$KLAPA_STAN_CMD" 2>/dev/null)"
        [[ "$w" == *close* ]] && echo closed || echo open
        return
    fi
    # 1. jądro: /proc/acpi/button/lid/*/state  → "state: open" / "state: closed"
    local plik
    for plik in /proc/acpi/button/lid/*/state; do
        if [[ -r "$plik" ]]; then
            grep -q closed "$plik" && echo closed || echo open
            return
        fi
    done
    # 2. zapas: UPower przez D-Bus
    local o
    o="$(gdbus call --system --dest org.freedesktop.UPower \
           --object-path /org/freedesktop/UPower \
           --method org.freedesktop.DBus.Properties.Get \
           org.freedesktop.UPower LidIsClosed 2>/dev/null)"
    [[ "$o" == *true* ]] && echo closed || echo open
}

# Ile ekranów ZEWNĘTRZNYCH jest podłączonych (wbudowany panel to eDP*/LVDS*).
monitory_zewnetrzne() {
    if [[ -n "${KLAPA_MONITORY_CMD:-}" ]]; then eval "$KLAPA_MONITORY_CMD" 2>/dev/null; return; fi
    xrandr --query 2>/dev/null \
        | awk '$2=="connected" && $1 !~ /^(eDP|LVDS)/ {n++} END {print n+0}'
}

ekran_swieci() {
    if [[ -n "${KLAPA_EKRAN_SWIECI_CMD:-}" ]]; then eval "$KLAPA_EKRAN_SWIECI_CMD"; return; fi
    xset q 2>/dev/null | grep -q "Monitor is On"
}

gas_ekran() {
    if [[ -n "${KLAPA_GAS_CMD:-}" ]]; then eval "$KLAPA_GAS_CMD"; return; fi
    xset dpms force off 2>/dev/null
}

usyp() {
    if [[ -n "${KLAPA_USYP_CMD:-}" ]]; then eval "$KLAPA_USYP_CMD"; return; fi
    # Aktywna sesja lokalna ma na to zgodę polkit — bez sudo (sprawdzone na HP:
    # `busctl call org.freedesktop.login1 … CanSuspend` = "yes").
    systemctl suspend
}

# ------------------------------------------------------------------ PĘTLA
dziennik "start: maszyna=$NAZWA_HOSTA, usypiam po ${USYP_PO_MIN} min zamkniętej klapy, pytam co ${INTERWAL}s"
POPRZEDNI="$(stan_klapy)"
dziennik "klapa na starcie: $POPRZEDNI"
DO_USPIENIA=0        # epoch, 0 = nie odliczamy
PRZEBIEG=0

while true; do
    STAN="$(stan_klapy)"
    ZEWN="$(monitory_zewnetrzne)"; [[ "$ZEWN" =~ ^[0-9]+$ ]] || ZEWN=0

    if [[ "$STAN" == closed ]]; then
        if [[ "$POPRZEDNI" != closed ]]; then
            dziennik "klapa ZAMKNIĘTA (monitory zewnętrzne: $ZEWN)"
            if (( ZEWN > 0 )); then
                dziennik "monitor zewnętrzny podłączony — nie gaszę i nie odliczam do uśpienia"
                DO_USPIENIA=0
            else
                gas_ekran; dziennik "ekran zgaszony"
                if (( USYP_PO_MIN > 0 )); then
                    # KLAPA_USYP_PO_SEK — wylacznie do testow na sucho (zwloka w sekundach
                    # zamiast minut, zeby test nie trwal 5 minut). W pracy nieustawione.
                    DO_USPIENIA=$(( $(date +%s) + ${KLAPA_USYP_PO_SEK:-$(( USYP_PO_MIN * 60 ))} ))
                    dziennik "odliczanie: uśpię za ${USYP_PO_MIN} min, jeśli klapa zostanie zamknięta"
                else
                    dziennik "klapa_usyp_po_min = 0 — nie usypiam wcale"
                fi
            fi
        else
            # nadal zamknięta
            if (( ZEWN > 0 )); then
                if (( DO_USPIENIA != 0 )); then
                    dziennik "podłączono monitor zewnętrzny — odliczanie ODWOŁANE"
                    DO_USPIENIA=0
                fi
            else
                # mutter potrafi zapalić panel z powrotem — pilnujemy, żeby był zgaszony
                if ekran_swieci; then gas_ekran; dziennik "ekran znów świecił — zgaszony ponownie"; fi
                if (( DO_USPIENIA != 0 )) && (( $(date +%s) >= DO_USPIENIA )); then
                    dziennik "klapa zamknięta od ${USYP_PO_MIN} min — USYPIAM"
                    DO_USPIENIA=0
                    usyp
                fi
            fi
        fi
    else
        if [[ "$POPRZEDNI" != open ]]; then
            if (( DO_USPIENIA != 0 )); then
                dziennik "klapa OTWARTA — odliczanie ODWOŁANE, nie usypiam"
            else
                dziennik "klapa OTWARTA"
            fi
            DO_USPIENIA=0
        fi
    fi

    POPRZEDNI="$STAN"
    PRZEBIEG=$(( PRZEBIEG + 1 ))
    if (( KROKI > 0 )) && (( PRZEBIEG >= KROKI )); then
        dziennik "koniec: wykonano $PRZEBIEG przebiegów (KLAPA_KROKI)"
        break
    fi
    sleep "$INTERWAL"
done
