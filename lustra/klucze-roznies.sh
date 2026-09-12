#!/bin/sh
# lustra/klucze-roznies.sh — MECHANIZM A (sprawa [389e] KROK 4, 2026-09-12, obszar 5).
#
# Porównaj i wyrównaj `~/.ssh/authorized_keys` maszyn NIELUSTRZANYCH — tych, których
# chezmoi nie stawia i gdzie klucze dotąd donosiło się ręcznie:
#   serwer (mk@serwer), Wyse/HAOS (root@192.168.1.48), Asus (kiosk@asus),
#   laptopy domowników (dell-ad, lenovo-nk).
#
# ⚠️ MASZYNY-LUSTRA (hp, vostro, katana) SĄ POZA ZAKRESEM TEGO SKRYPTU. Ich
# `~/.ssh/authorized_keys` wozi CHEZMOI (private_dot_ssh/private_authorized_keys.tmpl —
# glob po `lustra/klucze-publiczne/*.pub`, czyli automatycznie WSZYSTKIE klucze kanonu
# na każdej stacji-lustrze). Uruchamianie tego skryptu na stacji-lustrze nie ma sensu
# i skrypt jej nie zna — nie ma jej w danych (klucze-zestawy.toml).
#
# Dane:
#   lustra/klucze-zestawy.toml   — który zestaw kluczy ma być na której maszynie (i jak
#                                  się z nią połączyć — alias ~/.ssh/config albo user@host)
#   lustra/klucze-publiczne/*.pub — treść kluczy (ten sam katalog, z którego chezmoi
#                                  składa authorized_keys stacji-luster)
#
# Użycie:
#   klucze-roznies.sh [--pokaz|--wyrownaj] [maszyna]
#
#   --pokaz     (DOMYŚLNY) — nic nie zmienia. Dla każdej maszyny z danych (albo tylko
#               tej podanej jako argument) łączy się przez SSH, czyta ~/.ssh/authorized_keys,
#               porównuje z zestawem PO ODCISKACH kluczy (nie po komentarzach — komentarz
#               w pliku i tak, i tak bywa inny niż nazwa pliku w kanonie) i wypisuje różnice:
#               czego BRAKUJE i co jest NADMIAROWE.
#   --wyrownaj  — zapisuje na maszynie DOKŁADNIE zestaw z danych: nic mniej, nic więcej.
#               Przed zapisem robi kopię istniejącego pliku jako
#               `authorized_keys.przed-<RRRR-MM-DD>` (nie nadpisuje kopii z tego samego dnia
#               drugi raz — nie ma potrzeby, treść i tak jest w git jako `klucze-zestawy.toml`).
#
# Przykłady:
#   klucze-roznies.sh                    # --pokaz na wszystkich pięciu maszynach
#   klucze-roznies.sh --pokaz wyse       # --pokaz tylko na Wyse
#   klucze-roznies.sh --wyrownaj asus    # wyrównaj tylko Asusa
#
# Wymaga: klucz `~/.ssh/id_ed25519_dom` już zaufany na maszynie docelowej (ten skrypt
# NIE zakłada dostępu od zera — do tego procedura „NOWA MASZYNA" w README tego katalogu).

set -eu

TU="$(cd "$(dirname "$0")" && pwd)"
DANE="$TU/klucze-zestawy.toml"
KATALOG_KLUCZY="$TU/klucze-publiczne"

TRYB="--pokaz"
MASZYNA=""
for a in "$@"; do
    case "$a" in
        --pokaz|--wyrownaj) TRYB="$a" ;;
        --*) echo "Nieznany przełącznik: $a" >&2; exit 2 ;;
        *) MASZYNA="$a" ;;
    esac
done

echo "ℹ Zakres: tylko maszyny nielustrzane (dane niżej). Stacje-lustra (hp, vostro,"
echo "  katana) wozi chezmoi (private_dot_ssh/private_authorized_keys.tmpl) — pomijam je."
echo "  Tryb: $TRYB${MASZYNA:+ (tylko: $MASZYNA)}"
echo

# ── Odcisk lokalnego pliku klucza (kanon) ──────────────────────────────────────────
odcisk_lokalny() {
    nazwa="$1"
    plik="$KATALOG_KLUCZY/$nazwa.pub"
    if [ ! -f "$plik" ]; then
        echo "BRAK-PLIKU-KANONU:$nazwa"
        return
    fi
    ssh-keygen -lf "$plik" 2>/dev/null | awk '{print $2}'
}

# ── Odwrotne mapowanie: odcisk → nazwa pliku kanonu (do czytelnego opisu nadmiarów) ──
nazwa_po_odcisku() {
    szukany="$1"
    for p in "$KATALOG_KLUCZY"/*.pub; do
        [ -f "$p" ] || continue
        o="$(ssh-keygen -lf "$p" 2>/dev/null | awk '{print $2}')"
        if [ "$o" = "$szukany" ]; then
            basename "$p" .pub
            return
        fi
    done
    echo "(spoza kanonu klucze-publiczne/)"
}

# ── Wczytanie danych (klucze-zestawy.toml) jednym python3 -c, format wyjścia:
#    klucz<TAB>cel<TAB>klucz1,klucz2,klucz3   — po jednej linii na maszynę ──────────
WIERSZE="$(python3 -c "
import tomllib
with open('$DANE', 'rb') as f:
    dane = tomllib.load(f)
for m in dane.get('maszyna', []):
    print(m['klucz'] + '\t' + m['cel'] + '\t' + ','.join(m['klucze']))
")"

BRAK_MASZYNY=1
echo "$WIERSZE" | while IFS="$(printf '\t')" read -r KLUCZ CEL LISTA_KLUCZY; do
    [ -n "$KLUCZ" ] || continue
    if [ -n "$MASZYNA" ] && [ "$MASZYNA" != "$KLUCZ" ]; then
        continue
    fi
    echo "1" > /tmp/.klucze-roznies-znaleziono.$$  # sygnał na zewnątrz podpowłoki (patrz niżej)

    echo "── $KLUCZ ($CEL) ──────────────────────────────────────────"

    # Osiągalność — zanim zaczniemy porównywać, sprawdźmy, czy w ogóle wejdziemy.
    # ⚠️ `</dev/null` na KAŻDYM `ssh` w tej pętli jest obowiązkowe: bez tego ssh łapie
    # jako swój stdin resztę wierszy z $WIERSZE (ta pętla `while` czyta z potoku) i pętla
    # ucina się po pierwszej maszynie — zmierzone przy pierwszym teście na żywo 2026-09-12.
    if ! ssh -o BatchMode=yes -o ConnectTimeout=6 "$CEL" true </dev/null 2>/tmp/.klucze-roznies-blad.$$; then
        echo "  ✗ NIEOSIĄGALNA przez SSH (klucz domowy niezaufany, maszyna offline, albo inny błąd):"
        sed 's/^/    /' /tmp/.klucze-roznies-blad.$$
        rm -f /tmp/.klucze-roznies-blad.$$
        echo
        continue
    fi
    rm -f /tmp/.klucze-roznies-blad.$$

    # Odciski oczekiwane (z danych, po przecinku)
    OCZEKIWANE_NAZWY="$(echo "$LISTA_KLUCZY" | tr ',' ' ')"
    OCZEKIWANE_ODCISKI=""
    for n in $OCZEKIWANE_NAZWY; do
        o="$(odcisk_lokalny "$n")"
        OCZEKIWANE_ODCISKI="$OCZEKIWANE_ODCISKI$o|$n
"
    done

    # Odciski obecne na maszynie (może nie być pliku wcale — pusta lista, nie błąd)
    OBECNE_ODCISKI="$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$CEL" \
        'test -f ~/.ssh/authorized_keys && ssh-keygen -lf ~/.ssh/authorized_keys 2>/dev/null || true' \
        </dev/null | awk '{print $2}')"

    BRAKUJE=""
    for wpis in $(printf '%s' "$OCZEKIWANE_ODCISKI"); do
        o="${wpis%%|*}"
        n="${wpis##*|}"
        if ! printf '%s\n' "$OBECNE_ODCISKI" | grep -qx "$o"; then
            BRAKUJE="$BRAKUJE $n"
        fi
    done

    NADMIAR=""
    if [ -n "$OBECNE_ODCISKI" ]; then
        for o in $OBECNE_ODCISKI; do
            czy_oczekiwany=0
            for wpis in $(printf '%s' "$OCZEKIWANE_ODCISKI"); do
                oo="${wpis%%|*}"
                [ "$oo" = "$o" ] && czy_oczekiwany=1 && break
            done
            if [ "$czy_oczekiwany" = 0 ]; then
                NADMIAR="$NADMIAR$(nazwa_po_odcisku "$o") "
            fi
        done
    fi

    if [ -z "$BRAKUJE" ] && [ -z "$NADMIAR" ]; then
        echo "  ✓ zgodne (kluczy: $(echo "$OCZEKIWANE_NAZWY" | wc -w))"
    else
        [ -n "$BRAKUJE" ] && echo "  ✗ BRAKUJE:$BRAKUJE"
        [ -n "$NADMIAR" ] && echo "  ✗ NADMIAROWE:$NADMIAR"
    fi

    if [ "$TRYB" = "--wyrownaj" ]; then
        if [ -z "$BRAKUJE" ] && [ -z "$NADMIAR" ]; then
            echo "  (już zgodne — nic do wyrównania)"
        else
            DZIS="$(date +%Y-%m-%d)"
            PLIK_TMP="$(mktemp)"
            {
                echo "# ~/.ssh/authorized_keys — wyrównane przez lustra/klucze-roznies.sh --wyrownaj"
                echo "# na podstawie lustra/klucze-zestawy.toml (maszyna: $KLUCZ). $DZIS."
                echo "# Ręczny dopisek TU przetrwa do następnego --wyrownaj (w odróżnieniu od stacji-luster,"
                echo "# ten plik NIE jedzie automatycznie chezmoi) — ale przy następnym uruchomieniu"
                echo "# --wyrownaj zniknie, jeśli klucz nie jest w klucze-zestawy.toml."
                for n in $OCZEKIWANE_NAZWY; do
                    plik="$KATALOG_KLUCZY/$n.pub"
                    if [ -f "$plik" ]; then
                        cat "$plik"
                    fi
                done
            } > "$PLIK_TMP"

            ssh -o BatchMode=yes -o ConnectTimeout=6 "$CEL" \
                "umask 077; mkdir -p ~/.ssh; \
                 if [ -f ~/.ssh/authorized_keys ] && [ ! -f ~/.ssh/authorized_keys.przed-$DZIS ]; then \
                     cp -p ~/.ssh/authorized_keys ~/.ssh/authorized_keys.przed-$DZIS; \
                 fi; \
                 cat > ~/.ssh/authorized_keys.nowy" < "$PLIK_TMP"
            ssh -o BatchMode=yes -o ConnectTimeout=6 "$CEL" \
                'mv -f ~/.ssh/authorized_keys.nowy ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys' \
                </dev/null
            rm -f "$PLIK_TMP"
            echo "  → wyrównano (kopia sprzed zmiany: authorized_keys.przed-$DZIS, o ile plik już istniał)"
        fi
    fi
    echo
done

if [ -n "$MASZYNA" ] && [ ! -f /tmp/.klucze-roznies-znaleziono.$$ ]; then
    echo "Nieznana maszyna „$MASZYNA” — brak jej w lustra/klucze-zestawy.toml." >&2
    exit 2
fi
rm -f /tmp/.klucze-roznies-znaleziono.$$
