#!/bin/bash
# panel-sieci.sh — otwiera PANEL MENADZERA SIECI (usluga `menadzer-sieci` na serwerze).
# Wozony przez lustro (chezmoi: bin/executable_panel-sieci.sh); pozycja `panel-sieci`
# kanalu `skrypt` (lustra/skrypty.toml) pilnuje, ze plik, ikona i wpis .desktop sa na
# kazdej stacji. Sprawa [262], 2026-08-29, obszar 5 (decyzja usera: „skrot do menadzera
# sieci — najlepiej na pasku, tak jak AI Launcher, z odpowiednia ikona, lustrzanie").
#
# ADRES I PORT SA DANYMI, NIE STALA. Bierzemy je z:
#   lustra/siec.toml   → sekcja [panel]: ktora maszyna, ktory port, ktora sciezka,
#                        ktorymi polami adresu isc (`pola_adresu`) i w jakim trybie otworzyc,
#   lustra/maszyny.toml → blok [[maszyna]] o `klucz` = panel.maszyna; z niego adres.
# Przeprowadzka panelu na inna maszyne albo zmiana portu = zmiana JEDNEJ linii danych.
#
# DLACZEGO TAILSCALE, A NIE ADRES LAN: przyciski panelu („Pulpit", „terminal SSH")
# generuja odsylacze do adresow Tailscale floty — panel otwarty pod adresem LAN dzialalby
# tylko w domu. Kolejnosc pol adresu stoi w `pola_adresu` (dzis: ip_tailscale, potem
# host_tailscale) — dopisanie "host_lan" na koniec to zmiana danych, nie kodu.
#
# TRYB OKNA (dana `panel.tryb`):
#   "app"   — osobne okno Chrome bez paska adresu (`--app=`), wlasna pozycja w doku;
#             wtedy dokladamy `--class=panel-sieci`, bo po tym GNOME dopina okno do
#             naszego panel-sieci.desktop (StartupWMClass=panel-sieci).
#             UWAGA (wyczytane z kodu Chromium, nie zmierzone oknem): przelacznik
#             `--class` czyta `GetProgramClassClass()` z linii polecen PROCESU, ktory
#             okno tworzy. Gdy zwykly Chrome juz chodzi, nasze wywolanie tylko przekazuje
#             mu polecenie i klasa byla by Chrome'a. Dlatego okno panelu dostaje WLASNY
#             katalog profilu (`--user-data-dir`) — wtedy zawsze powstaje osobny proces
#             i klasa jest nasza. Profil jest pusty i jednorazowy (panel nie ma logowania).
#   "karta" — zwykla karta w domyslnej przegladarce (`xdg-open`); tak samo dziala fallback,
#             gdy na maszynie nie ma Chrome'a.
#
# Uzycie:
#   panel-sieci.sh          — otwiera panel
#   panel-sieci.sh --url    — tylko wypisuje adres (do testow; NIC nie otwiera)
set -u

LOG_KAT="$HOME/.local/share/lustro"
LOG="$LOG_KAT/panel-sieci.log"
SIEC="${LUSTRO_SIEC:-$HOME/.local/share/chezmoi/lustra/siec.toml}"
MASZYNY="${LUSTRO_MASZYNY:-$HOME/.local/share/chezmoi/lustra/maszyny.toml}"
PROFIL_CHROME="$HOME/.local/share/panel-sieci/chrome"
KLASA_WM="panel-sieci"

mkdir -p "$LOG_KAT"
zapisz() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

powiedz() {
    zapisz "BLAD: $*"
    if command -v notify-send >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        notify-send -u critical "Panel sieci" "$*" 2>/dev/null || true
    fi
    echo "panel-sieci: $*" >&2
}

# --- adres, port i tryb z DANYCH --------------------------------------------
# Wypisuje dwie linie: URL i tryb. Pusto = nie dalo sie zlozyc adresu.
ODCZYT="$(python3 - "$SIEC" "$MASZYNY" <<'PY' 2>/dev/null
import sys, tomllib

def wczytaj(sciezka):
    try:
        with open(sciezka, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}

siec = wczytaj(sys.argv[1])
maszyny = wczytaj(sys.argv[2])
panel = siec.get("panel", {})

klucz = str(panel.get("maszyna", "serwer"))
port = panel.get("port", 8100)
sciezka = str(panel.get("sciezka", "/")) or "/"
pola = panel.get("pola_adresu") or ["ip_tailscale", "host_tailscale", "host_lan"]
tryb = str(panel.get("tryb", "app"))

adres = ""
for m in maszyny.get("maszyna", []):
    if str(m.get("klucz", "")).strip().lower() == klucz.strip().lower():
        for pole in pola:
            wartosc = str(m.get(pole, "")).strip()
            if wartosc:
                adres = wartosc
                break
        break

if not adres:
    sys.exit(1)
if ":" in adres and not adres.startswith("["):      # gole IPv6 → w nawiasy
    adres = f"[{adres}]"
if not sciezka.startswith("/"):
    sciezka = "/" + sciezka
print(f"http://{adres}:{port}{sciezka}")
print(tryb)
PY
)"

URL="$(printf '%s\n' "$ODCZYT" | sed -n '1p')"
TRYB="$(printf '%s\n' "$ODCZYT" | sed -n '2p')"
[ -z "$TRYB" ] && TRYB="app"

if [ -z "$URL" ]; then
    powiedz "nie umiem zlozyc adresu panelu — sprawdz sekcje [panel] w $SIEC i wpis maszyny w $MASZYNY"
    exit 2
fi

if [ "${1:-}" = "--url" ]; then
    printf '%s\n' "$URL"
    exit 0
fi

# --- otwarcie ----------------------------------------------------------------
CHROME=""
for k in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$k" >/dev/null 2>&1; then CHROME="$k"; break; fi
done
# do testow bez okna: LUSTRO_PANEL_PRZEGLADARKA=atrapa
[ -n "${LUSTRO_PANEL_PRZEGLADARKA:-}" ] && CHROME="$LUSTRO_PANEL_PRZEGLADARKA"

if [ "$TRYB" = "app" ] && [ -n "$CHROME" ]; then
    mkdir -p "$PROFIL_CHROME"
    zapisz "otwieram (app, $CHROME): $URL"
    exec "$CHROME" --app="$URL" --class="$KLASA_WM" \
        --user-data-dir="$PROFIL_CHROME" \
        --no-first-run --no-default-browser-check
fi

if command -v xdg-open >/dev/null 2>&1; then
    zapisz "otwieram (karta, xdg-open): $URL"
    exec xdg-open "$URL"
fi

powiedz "nie znalazlem czym otworzyc $URL (brak Chrome'a i xdg-open)"
exit 3
