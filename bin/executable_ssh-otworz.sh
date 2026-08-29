#!/bin/bash
# ssh-otworz.sh — obsluga odsylaczy `ssh://<adres>` na stacji: otwiera TERMINAL
# z polaczeniem SSH do wskazanej maszyny. Wozony przez lustro
# (chezmoi: bin/executable_ssh-otworz.sh). Rejestracje schematu robi ogolny
# ~/bin/schemat-rejestruj.sh, uruchamiany przez pozycje `ssh-handler` kanalu `skrypt`
# (lustra/skrypty.toml). Sprawa [260b], 2026-08-29, obszar 5.
#
# KONTRAKT Z PANELEM MENADZERA SIECI (obszar 1):
#   panel generuje `ssh://<user>@<adres>` w standardowej postaci `ssh://user@host[:port]`;
#   uzytkownik jest OPCJONALNY — gdy go nie ma, dokladamy go tak samo jak w vnc-otworz.sh
#   (z lustra/maszyny.toml, pole `user` maszyny o tym adresie; domyslnie `mk` — Asus ma
#   `kiosk`, dlatego to DANA, nie stala). Port domyslny 22.
#
# Odsylacz tolerujemy w kilku postaciach (przegladarki i panele roznie je skladaja):
#   ssh://mk@192.168.1.65   ssh://192.168.1.65/   ssh://mk@katana:2222   ssh://[fd7a::1]
#
# Odciski hostow: `StrictHostKeyChecking=accept-new` — pierwsze polaczenie przyjmuje odcisk
# i go ZAPISUJE, przy pozniejszej PODMIANIE odciska odmawia. To nasza siec, a odsylacz
# klika sie z panelu, wiec nie ma tu miejsca na dialog „yes/no" w tle.
set -u

LOG_KAT="$HOME/.local/share/lustro"
LOG="$LOG_KAT/ssh-otworz.log"
MASZYNY="$HOME/.local/share/chezmoi/lustra/maszyny.toml"
TERMINAL_KONF="$HOME/.config/lustro/terminal"
PORT_DOMYSLNY=22
USER_DOMYSLNY=mk

mkdir -p "$LOG_KAT"
zapisz() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

# Komunikat dla czlowieka: w sesji graficznej powiadomienie, poza nia — na stderr.
powiedz() {
    zapisz "BLAD: $*"
    if command -v notify-send >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        notify-send -u critical "Terminal SSH" "$*" 2>/dev/null || true
    fi
    echo "ssh-otworz: $*" >&2
}

ODSYLACZ="${1:-}"
if [ -z "$ODSYLACZ" ]; then
    powiedz "brak adresu. Uzycie: ssh-otworz.sh ssh://<user>@<adres>[:port]"
    exit 2
fi

# --- rozbior odsylacza -------------------------------------------------------
CEL="${ODSYLACZ#ssh://}"          # zdejmij schemat, jesli jest
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
    *:*:*)   : ;;                                                       # gole IPv6 bez portu (2+ dwukropkow) — nie ma tu portu
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

# Adres IPv6 w nawiasy kwadratowe — inaczej ssh wezmie ostatni dwukropek za port.
ADRES="$CEL"
case "$CEL" in *:*) ADRES="[$CEL]" ;; esac

# --- polecenie do uruchomienia w terminalu -----------------------------------
SSH_ARGS=(ssh -t -o StrictHostKeyChecking=accept-new)
[ "$PORT" != "$PORT_DOMYSLNY" ] && SSH_ARGS+=(-p "$PORT")
SSH_ARGS+=("$UZYTKOWNIK@$ADRES")
POLECENIE="$(printf '%q ' "${SSH_ARGS[@]}")"
# Gdy polaczenie padnie od razu (maszyna spi, brak klucza), okno terminala zamknie sie
# szybciej, niz user zdazy przeczytac blad — dlatego przy bledzie czekamy na Enter.
W_TERMINALU="$POLECENIE; rc=\$?; if [ \$rc -ne 0 ]; then printf '\n[ssh-otworz] polaczenie zakonczone bledem (%s). Enter zamyka okno.\n' \"\$rc\"; read -r _; fi"
TYTUL="SSH: $UZYTKOWNIK@$CEL"

# --- ktory terminal ----------------------------------------------------------
# Kolejnosc (od najbardziej „czyjejs decyzji" do zgadywania):
#   1. zmienna LUSTRO_TERMINAL (do testow i wyjatkow),
#   2. plik ~/.config/lustro/terminal — jedna linia z nazwa programu (DANA maszyny,
#      nie zmiana kodu; celowo poza chezmoi, bo to wybor lokalny),
#   3. `x-terminal-emulator` — systemowe „domyslny terminal tej maszyny"
#      (Debian/Ubuntu update-alternatives; na naszych stacjach → gnome-terminal),
#   4. lista awaryjna — pierwszy, ktory jest na maszynie.
# Kazdy terminal ma inna skladnie „uruchom to polecenie", dlatego nizej tabela.
WYBOR="${LUSTRO_TERMINAL:-}"
if [ -z "$WYBOR" ] && [ -r "$TERMINAL_KONF" ]; then
    WYBOR="$(head -n1 "$TERMINAL_KONF" | tr -d '[:space:]')"
fi
if [ -z "$WYBOR" ] && command -v x-terminal-emulator >/dev/null 2>&1; then
    ROZWIN="$(readlink -f "$(command -v x-terminal-emulator)" 2>/dev/null)"
    WYBOR="$(basename "${ROZWIN:-}")"
    WYBOR="${WYBOR%.wrapper}"      # /usr/bin/gnome-terminal.wrapper → gnome-terminal
fi
if [ -z "$WYBOR" ] || ! command -v "$WYBOR" >/dev/null 2>&1; then
    WYBOR=""
    for k in gnome-terminal ptyxis konsole xfce4-terminal mate-terminal tilix terminator \
             kitty wezterm alacritty foot xterm; do
        if command -v "$k" >/dev/null 2>&1; then WYBOR="$k"; break; fi
    done
fi
if [ -z "$WYBOR" ]; then
    powiedz "nie znalazlem zadnego terminala. Wskaz go: echo gnome-terminal > $TERMINAL_KONF"
    exit 3
fi

zapisz "otwieram $ODSYLACZ → [$WYBOR] ${SSH_ARGS[*]}"

case "$WYBOR" in
    gnome-terminal)  exec "$WYBOR" --title="$TYTUL" -- bash -c "$W_TERMINALU" ;;
    ptyxis)          exec "$WYBOR" --title="$TYTUL" -- bash -c "$W_TERMINALU" ;;
    mate-terminal)   exec "$WYBOR" --title="$TYTUL" -- bash -c "$W_TERMINALU" ;;
    tilix)           exec "$WYBOR" --title="$TYTUL" -e bash -c "$W_TERMINALU" ;;
    konsole)         exec "$WYBOR" -p "tabtitle=$TYTUL" -e bash -c "$W_TERMINALU" ;;
    xfce4-terminal)  exec "$WYBOR" --title="$TYTUL" -x bash -c "$W_TERMINALU" ;;
    terminator)      exec "$WYBOR" --title="$TYTUL" -x bash -c "$W_TERMINALU" ;;
    kitty)           exec "$WYBOR" --title "$TYTUL" bash -c "$W_TERMINALU" ;;
    wezterm)         exec "$WYBOR" start -- bash -c "$W_TERMINALU" ;;
    alacritty)       exec "$WYBOR" --title "$TYTUL" -e bash -c "$W_TERMINALU" ;;
    foot)            exec "$WYBOR" --title="$TYTUL" bash -c "$W_TERMINALU" ;;
    xterm)           exec "$WYBOR" -title "$TYTUL" -e bash -c "$W_TERMINALU" ;;
    *)               # nieznany terminal: sprobuj konwencji Debiana (-e)
                     exec "$WYBOR" -e bash -c "$W_TERMINALU" ;;
esac
