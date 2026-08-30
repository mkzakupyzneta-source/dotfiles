#!/bin/bash
# przyjmij-maszyne.sh — „przyjęcie maszyny" PO STRONIE SERWERA (OptiPlex), po tym jak
# na nowej stacji przeszedł nowa-stacja.sh. Obszar 5_Wspolna_konfiguracja, 2026-08-27.
#
#   ~/.local/share/chezmoi/lustra/przyjmij-maszyne.sh <nazwa> <adres> [--user mk] [--port 22]
#                                                     [--tylko-serwer] [--bez-syncthing] [--galaz main] [--odswiez-stacje]
#   --galaz X        maszyna TESTOWA (VM poligon) pracuje na gałęzi X — serwer tylko ją pobiera jako
#                    gałąź (bez scalania z main, bez commitu klucza na GitHub)
#   --odswiez-stacje po pushu uruchom `chezmoi update --force` na stacjach (Vostro, Katana), żeby
#                    dostały nowy authorized_keys od razu, nie dopiero z timera (≤60 min)
#
# Co robi (idempotentnie — można powtarzać):
#   P1 wchodzi na nową maszynę kluczem serwera (nowa-stacja.sh wpisał go do jej authorized_keys
#      z lustra/klucze-publiczne/serwer.pub) i pobiera jej klucz DOMOWY (id_ed25519_dom.pub);
#   P2 zapisuje go jako DANĄ: lustra/klucze-publiczne/<nazwa>-dom.pub (konwencja obszaru 2, [222]);
#      kasuje <nazwa>-windows.pub, jeśli był (HP po formacie);
#   P3 dopisuje go WPROST do authorized_keys maszyn spoza lustra z kontem SSH (serwer, Asus/kiosk);
#      STACJE (profil stacja) dostają go z chezmoi (szablon authorized_keys.tmpl) po pushu —
#      przy najbliższym biegu timera (≤60 min) albo od razu z --odswiez-stacje;
#      Wyse celowo nie — HAOS, klucze w konfiguracji dodatku „Terminal & SSH";
#   P4 known_hosts: odcisk nowej maszyny u serwera i u tamtych maszyn; odciski tamtych u nowej;
#   P5 git: dociąga commity z nowej maszyny (jej blok w maszyny.toml, dziennik, inwentarz),
#      commituje klucz, push na GitHub; włącza `receive.denyCurrentBranch=updateInstead`, żeby
#      nowa maszyna mogła pushować do serwera zanim dostanie klucz GitHub;
#   P6 Syncthing: ID nowej maszyny → urządzenie + oba foldery na serwerze (REST) i na
#      stacjach z syncthing.toml, które są osiągalne; ID zapisane w syncthing.toml.
# Wymaga: klucz serwera już wpuszczony na nowej maszynie (robi to nowa-stacja.sh) — jeśli nie,
# skrypt proponuje `ssh-copy-id` (pyta o hasło konta na nowej maszynie).
set -u
REPO="${LUSTRA_REPO:-$HOME/.local/share/chezmoi}"; LUSTRA="$REPO/lustra"; PY=python3   # LUSTRA_REPO = tylko do testów
LOCK=/home/mk/.cache/lustra-repo.lock   # ten sam flock co timery serwera ([217])

NAZWA="${1:-}"; HOST="${2:-}"; shift 2 2>/dev/null || { sed -n '2,25p' "$0"; exit 2; }
USER_N=mk; PORT=22; TYLKO_SERWER=0; BEZ_SYNC=0; GALAZ=main; ODSWIEZ=0
while [ $# -gt 0 ]; do case "$1" in
    --user) USER_N="$2"; shift ;; --port) PORT="$2"; shift ;;
    --tylko-serwer) TYLKO_SERWER=1 ;; --bez-syncthing) BEZ_SYNC=1 ;; --galaz) GALAZ="$2"; shift ;; --odswiez-stacje) ODSWIEZ=1 ;;
    *) echo "nieznany przełącznik $1"; exit 2 ;; esac; shift; done
[ -z "$NAZWA" ] || [ -z "$HOST" ] && { sed -n '2,25p' "$0"; exit 2; }

S="ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -p $PORT $USER_N@$HOST"
URL_GIT="ssh://$USER_N@$HOST:$PORT/home/$USER_N/.local/share/chezmoi"
echo "── przyjmij-maszyne: $NAZWA ($USER_N@$HOST:$PORT) ──"

# P1 dostęp
if ! $S true 2>/dev/null; then
    echo "   serwer nie wchodzi kluczem na $USER_N@$HOST — próbuję ssh-copy-id (hasło konta na nowej maszynie):"
    ssh-copy-id -p "$PORT" -i "$HOME/.ssh/id_rsa.pub" "$USER_N@$HOST" </dev/tty || { echo "brak dostępu — stop"; exit 1; }
    $S true || { echo "nadal brak dostępu — stop"; exit 1; }
fi
KLUCZ_DOM="$($S cat .ssh/id_ed25519_dom.pub 2>/dev/null)"
[ -z "$KLUCZ_DOM" ] && { echo "   na $HOST nie ma ~/.ssh/id_ed25519_dom.pub — najpierw nowa-stacja.sh"; exit 1; }
HOSTNAME_N="$($S hostname)"
echo "P1 ✓ klucz domowy pobrany ($HOSTNAME_N): ${KLUCZ_DOM%% *} …${KLUCZ_DOM##* }"

# P2 klucz jako dana (konwencja [222]: <maszyna>-<rola>.pub)
mkdir -p "$LUSTRA/klucze-publiczne"
PLIK="$LUSTRA/klucze-publiczne/$NAZWA-dom.pub"
if [ -f "$PLIK" ] && grep -qF "$KLUCZ_DOM" "$PLIK"; then echo "P2 ✓ $PLIK już zawiera ten klucz"; else
    printf '%s\n' "$KLUCZ_DOM" >"$PLIK"; echo "P2 ✓ zapisany $PLIK"; fi
STARY="$LUSTRA/klucze-publiczne/$NAZWA-windows.pub"
[ -f "$STARY" ] && { rm -f "$STARY"; echo "P2 ✓ usunięty $STARY (maszyna po formacie — stary klucz z Windows)"; }

# P3 roznoszenie wprost (maszyny spoza lustra); stacje — przez chezmoi
dopisz_klucz() { # user host port klucz
    ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new -p "$3" "$1@$2" \
        "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; grep -qF '$4' ~/.ssh/authorized_keys || echo '$4' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys" 2>/dev/null
}
touch "$HOME/.ssh/authorized_keys"; grep -qF "$KLUCZ_DOM" "$HOME/.ssh/authorized_keys" || echo "$KLUCZ_DOM" >>"$HOME/.ssh/authorized_keys"
echo "P3 ✓ authorized_keys serwera"
STACJE=""
while read -r klucz user host profil; do
    [ "$klucz" = "$NAZWA" ] || [ "$klucz" = "serwer" ] && continue
    if [ "$profil" = "stacja" ]; then STACJE="$STACJE $klucz:$user@$host"; echo "P3 ○ $klucz — stacja: authorized_keys składa chezmoi po pushu (timer ≤60 min$([ $ODSWIEZ = 1 ] && echo ', tu: --odswiez-stacje'))"; continue; fi
    [ $TYLKO_SERWER = 1 ] && { echo "P3 ○ $klucz pominięta (--tylko-serwer)"; continue; }
    if dopisz_klucz "$user" "$host" 22 "$KLUCZ_DOM"; then echo "P3 ✓ $klucz ($user@$host) — wpisane wprost"; else echo "P3 ✗ $klucz ($user@$host) — nieosiągalna, powtórz skrypt później"; fi
done < <($PY "$LUSTRA/stacja-dane.py" cele)

# P4 known_hosts
ssh-keygen -F "[$HOST]:$PORT" >/dev/null 2>&1 || ssh-keygen -F "$HOST" >/dev/null 2>&1 || ssh-keyscan -H -p "$PORT" -T 5 "$HOST" 2>/dev/null >>"$HOME/.ssh/known_hosts"
echo "P4 ✓ known_hosts serwera zna $HOST"
if [ $TYLKO_SERWER = 0 ]; then
    ODCISK="$(ssh-keyscan -H -p "$PORT" -T 5 "$HOST" 2>/dev/null)"
    while read -r klucz user host profil; do
        [ "$klucz" = "$NAZWA" ] || [ "$klucz" = "serwer" ] && continue
        ssh -o BatchMode=yes -o ConnectTimeout=8 -p 22 "$user@$host" "umask 077; mkdir -p ~/.ssh; ssh-keygen -F '$HOST' -f ~/.ssh/known_hosts >/dev/null 2>&1 || printf '%s\n' '$ODCISK' >> ~/.ssh/known_hosts" 2>/dev/null && echo "P4 ✓ known_hosts na $klucz"
    done < <($PY "$LUSTRA/stacja-dane.py" cele)
fi
$S "ssh-keygen -F 192.168.1.49 -f ~/.ssh/known_hosts >/dev/null 2>&1 || ssh-keyscan -T 4 192.168.1.49 >> ~/.ssh/known_hosts 2>/dev/null" >/dev/null 2>&1 || true

# P5 git — pod tym samym flockiem co timery serwera
(
  flock -w 120 9 || { echo "P5 ✗ repo zajęte (flock) — powtórz za chwilę"; exit 1; }
  cd "$REPO" || exit 1
  git config receive.denyCurrentBranch updateInstead
  if [ "$GALAZ" != "main" ]; then
      if git fetch -q "$URL_GIT" "+$GALAZ:$GALAZ" 2>/dev/null; then echo "P5 ✓ gałąź testowa $GALAZ pobrana z $NAZWA (bez scalania z main): $(git log --oneline -1 "$GALAZ")"; else echo "P5 ✗ nie udało się pobrać gałęzi $GALAZ z $NAZWA"; fi
      echo "P5 ○ klucz $NAZWA zapisany tylko lokalnie w $PLIK (maszyna testowa — bez commitu na main)"
  else
      git pull -q --rebase --autostash origin main 2>/dev/null || echo "P5 ⚠ pull z GitHuba nie przeszedł (offline?) — jadę na stanie lokalnym"
      if git pull -q --rebase --autostash "$URL_GIT" main >/dev/null 2>&1; then echo "P5 ✓ dociągnięte commity z $NAZWA ($(git log --oneline -1))"; else echo "P5 ✗ pull z $NAZWA nie przeszedł (jej commity dojadą, gdy sama zrobi push do serwera)"; fi
      # [283] TYLKO własna ścieżka (klucz publiczny) — nie `git add -A`: repo serwera
      # jest współdzielone z timerami i sesjami, cudze zmiany zostają w drzewie.
      if [ -n "$(git status --porcelain -- lustra/klucze-publiczne)" ]; then
          git add -- lustra/klucze-publiczne && git commit -q -m "lustra: przyjęcie maszyny $NAZWA — klucz domowy w klucze-publiczne/ ($(date -I))" -- lustra/klucze-publiczne && echo "P5 ✓ commit klucza"
      fi
      if git push -q origin main 2>/dev/null || { git pull -q --rebase --autostash origin main && git push -q origin main; }; then echo "P5 ✓ push na GitHub"; else echo "P5 ✗ push na GitHub nie przeszedł (commit został lokalnie)"; fi
      if [ $ODSWIEZ = 1 ]; then
          for st in $STACJE; do
              k="${st%%:*}"; cel="${st#*:}"
              ssh -o BatchMode=yes -o ConnectTimeout=8 "$cel" 'PATH=$HOME/.local/bin:$PATH chezmoi update --force >/dev/null 2>&1 && grep -c "^ssh-" ~/.ssh/authorized_keys' 2>/dev/null | sed "s/^/P5 ✓ $k: chezmoi update, authorized_keys ma teraz kluczy: /" || echo "P5 ✗ $k: chezmoi update nie przeszedł"
          done
      fi
  fi
) 9>"$LOCK"

# P6 Syncthing
if [ $BEZ_SYNC = 1 ]; then echo "P6 ○ Syncthing pominięty"; else
    ID_N="$($S "syncthing --device-id 2>/dev/null || grep -o 'id=\"[A-Z0-9-]\{63\}\"' ~/.local/state/syncthing/config.xml | head -1 | cut -d'\"' -f2")"
    if [ -z "$ID_N" ]; then echo "P6 ✗ nie umiem odczytać ID Syncthinga z $HOST (Syncthing nie wstał?)"; else
        ADRESY="tcp://$HOST:22000,dynamic"
        IP_TS="$($S "tailscale ip -4 2>/dev/null | head -1")"; [ -n "$IP_TS" ] && ADRESY="tcp://$HOST:22000,tcp://$IP_TS:22000,dynamic"
        KLUCZ_API="$(grep -o '<apikey>[^<]*' "$HOME/.local/state/syncthing/config.xml" | cut -c9-)"
        if $PY "$LUSTRA/stacja-dane.py" syncthing-przyjmij --klucz-api "$KLUCZ_API" --id "$ID_N" --nazwa "$NAZWA" --adresy "$ADRESY"; then echo "P6 ✓ Syncthing serwera: $NAZWA ($ID_N)"; else echo "P6 ✗ REST Syncthinga na serwerze"; fi
        if [ $TYLKO_SERWER = 0 ]; then
            while read -r klucz user host profil; do
                [ "$klucz" = "$NAZWA" ] || [ "$klucz" = "serwer" ] && continue
                grep -q "klucz = \"$klucz\"" "$LUSTRA/syncthing.toml" || continue   # tylko maszyny, które mają Syncthinga w danych
                if ssh -o BatchMode=yes -o ConnectTimeout=8 "$user@$host" "K=\$(grep -o '<apikey>[^<]*' ~/.local/state/syncthing/config.xml | cut -c9-); python3 - syncthing-przyjmij --klucz-api \$K --id $ID_N --nazwa $NAZWA --adresy $ADRESY" <"$LUSTRA/stacja-dane.py" 2>/dev/null; then echo "P6 ✓ Syncthing na $klucz"; else echo "P6 ✗ Syncthing na $klucz (nieosiągalna / brak API) — powtórz później"; fi
            done < <($PY "$LUSTRA/stacja-dane.py" cele)
        fi
        if [ "$GALAZ" = "main" ]; then
        ( flock -w 60 9; cd "$REPO" && $PY "$LUSTRA/stacja-dane.py" syncthing-urzadzenie-wpisz --klucz "$NAZWA" --id "$ID_N" --nazwa "$HOSTNAME_N" --adresy "$ADRESY" \
          && git add -- lustra/syncthing.toml && git commit -q -m "lustra: syncthing.toml — urządzenie $NAZWA" -- lustra/syncthing.toml && git push -q origin main 2>/dev/null; ) 9>"$LOCK"   # [283] tylko własny plik
        else echo "P6 ○ syncthing.toml bez zmian (maszyna testowa, gałąź $GALAZ)"; fi
    fi
fi

echo "── gotowe. Test drogi awaryjnej (S5): z INNEJ maszyny:  ssh $USER_N@$HOST hostname"
echo "   Z tej maszyny teraz:  ssh -i ~/.ssh/id_rsa $USER_N@$HOST hostname  → $($S hostname 2>/dev/null || echo '?')"
