#!/bin/bash
# vnc-otworz.sh — obsluga odsylaczy `vnc://<adres>` na stacji.
# Wozony przez lustro (chezmoi: bin/executable_vnc-otworz.sh). Rejestracje schematu
# (xdg-mime) robi ~/bin/vnc-rejestruj.sh, uruchamiany przez pozycje `vnc-handler`
# kanalu `skrypt` (lustra/skrypty.toml). Sprawa [258b], 2026-08-29, obszar 5.
#
# KONTRAKT Z PANELEM MENADZERA SIECI (obszar 1, app.py, rozdzial „ZDALNY PULPIT [258]"):
#   panel generuje WYLACZNIE `vnc://<adres maszyny>` — bez portu i bez nazwy uzytkownika.
#   Adres jest liczony „z miejsca, z ktorego user patrzy" (Tailscale → 100.x, LAN → 192.168.x).
# Ten skrypt dokleda reszte:
#   • uzytkownika bierze z lustra/maszyny.toml (pole `user` maszyny o tym adresie; domyslnie mk —
#     Asus ma `kiosk`, dlatego to DANA, nie stala),
#   • port zawsze 5900 PO STRONIE MASZYNY (chyba ze odsylacz jawnie poda inny),
#   • polaczenie idzie TUNELEM SSH: `vncviewer -via <user>@<adres> localhost:5900`.
#     TigerVNC `-via` sam stawia `ssh -f -L ...` (man vncviewer: „-via gateway", TigerVNC-specific;
#     nazwa hosta jest liczona Z PUNKTU WIDZENIA bramy, wiec `localhost` = maszyna docelowa).
#     Uwierzytelnieniem jest KLUCZ SSH — zadnego hasla VNC nie ma ([258a]).
#
# Odsylacz tolerujemy w kilku postaciach (przegladarki i panele roznie je skladaja):
#   vnc://192.168.1.65        vnc://192.168.1.65/        vnc://mk@100.125.21.112
#   vnc://192.168.1.65:5901   vnc://hp
set -u

LOG_KAT="$HOME/.local/share/lustro"
LOG="$LOG_KAT/vnc-otworz.log"
MASZYNY="$HOME/.local/share/chezmoi/lustra/maszyny.toml"
PORT_DOMYSLNY=5900
USER_DOMYSLNY=mk

mkdir -p "$LOG_KAT"
zapisz() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

# Komunikat dla czlowieka: w sesji graficznej powiadomienie, poza nia — na stderr.
powiedz() {
    zapisz "BLAD: $*"
    if command -v notify-send >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        notify-send -u critical "Zdalny pulpit" "$*" 2>/dev/null || true
    fi
    echo "vnc-otworz: $*" >&2
}

ODSYLACZ="${1:-}"
if [ -z "$ODSYLACZ" ]; then
    powiedz "brak adresu. Uzycie: vnc-otworz.sh vnc://<adres>"
    exit 2
fi

# --- rozbior odsylacza -------------------------------------------------------
CEL="${ODSYLACZ#vnc://}"          # zdejmij schemat, jesli jest
CEL="${CEL%%[?#]*}"               # utnij ?query i #fragment
CEL="${CEL%/}"                    # utnij koncowy ukosnik
UZYTKOWNIK=""
case "$CEL" in
    *@*) UZYTKOWNIK="${CEL%%@*}"; CEL="${CEL#*@}" ;;
esac
PORT="$PORT_DOMYSLNY"
case "$CEL" in
    \[*\]:*) PORT="${CEL##*]:}"; CEL="${CEL%]:*}"; CEL="${CEL#[}" ;;   # [IPv6]:port
    \[*\])   CEL="${CEL#[}"; CEL="${CEL%]}" ;;                          # [IPv6]
    *:*)     PORT="${CEL##*:}";  CEL="${CEL%:*}" ;;
esac
case "$PORT" in ''|*[!0-9]*) PORT="$PORT_DOMYSLNY" ;; esac

if [ -z "$CEL" ]; then
    powiedz "nie umiem odczytac adresu z odsylacza: $ODSYLACZ"
    exit 2
fi

# --- uzytkownik z DANYCH (maszyny.toml), gdy odsylacz go nie podal -----------
if [ -z "$UZYTKOWNIK" ] && [ -r "$MASZYNY" ]; then
    UZYTKOWNIK="$(python3 - "$MASZYNY" "$CEL" <<'PY' 2>/dev/null
import sys, tomllib
try:
    with open(sys.argv[1], "rb") as f:
        dane = tomllib.load(f)
except Exception:
    sys.exit(0)
szukany = sys.argv[2].strip().lower()
for m in dane.get("maszyna", []):
    kandydaci = [str(m.get(p, "")).strip().lower()
                 for p in ("host_lan", "ip_tailscale", "host_tailscale", "nazwa_hosta", "klucz")]
    if szukany in [k for k in kandydaci if k]:
        if m.get("user"):
            print(m["user"])
        break
PY
)"
fi
[ -z "$UZYTKOWNIK" ] && UZYTKOWNIK="$USER_DOMYSLNY"

# --- klient VNC --------------------------------------------------------------
KLIENT="$(command -v vncviewer || true)"
if [ -z "$KLIENT" ]; then
    powiedz "nie ma programu vncviewer (pakiet tigervnc-viewer). Zainstaluj: lustro dodaj tigervnc-viewer"
    exit 3
fi

zapisz "otwieram $ODSYLACZ → $KLIENT -via $UZYTKOWNIK@$CEL localhost:$PORT"
exec "$KLIENT" -via "$UZYTKOWNIK@$CEL" "localhost:$PORT"
