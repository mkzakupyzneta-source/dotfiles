#!/bin/bash
# nowa-stacja.sh — jedna komenda na świeżym Ubuntu 24.04: maszyna → stacja-lustro.
# Obszar 5_Wspolna_konfiguracja, 2026-08-27. Zastępuje ~20 ręcznych kroków Etapu 2
# z procedura-nowej-stacji.md (bootstrap.sh z Przesiadka_Linux nie istnieje od 22.08).
#
# JEDNA LINIA NA ŚWIEŻEJ MASZYNIE (serwer udostępnia ten plik po LAN — obszar 1):
#   wget -qO /tmp/nowa-stacja.sh http://192.168.1.49:8100/nowa-stacja.sh && bash /tmp/nowa-stacja.sh
# (wget, NIE curl: świeże Ubuntu 24.04 Desktop nie ma curla — zmierzone na HP 29.08; curl dochodzi w K1)
#
# Co wymaga człowieka przy klawiaturze (i NIC więcej):
#   1. hasło sudo tej maszyny (raz, na początku),
#   2. fraza do klucza osobistego id_ed25519 (ssh-keygen pyta; Enter = bez frazy — NIE zalecane),
#   3. hasło konta na SERWERZE — raz, w K4b (ssh-copy-id klucza domowego; potem wszystko wchodzi kluczem),
#   4. logowanie Tailscale w przeglądarce (skrypt wypisze adres i poczeka),
#   5. wklejenie klucza id_ed25519_github.pub na koncie GitHub — w K16b, przy klawiaturze;
#      bez tego commity tej maszyny zostają lokalnie i na serwerze, a GitHub (dom kanoniczny
#      repozytorium) ich nie widzi ([259], 2026-08-29).
# Na końcu skrypt wypisuje RAPORT: klucze publiczne tej maszyny, ID Syncthinga, wynik
# `lustro status` i listę rzeczy, które trzeba zrobić ręcznie (logowania itp.).
# Potem na SERWERZE: lustra/przyjmij-maszyne.sh <nazwa> <adres> — roznosi klucze i Syncthing.
#
# Skrypt jest IDEMPOTENTNY: przerwany — uruchom ponownie, kroki zrobione pomija.
# Dane (nie kod): maszyny.toml, siec.toml, syncthing.toml, klucze-publiczne/, zrodla-apt.toml,
# .chezmoidata/packages.yaml — nowa maszyna/podsieć/folder to wpis w danych.
#
# Przełączniki (do testów i wyjątków):
#   --nazwa X        klucz maszyny w maszyny.toml (domyślnie: hostname małymi literami)
#   --paczka PLIK    repo z lokalnego tar.gz zamiast z HTTP
#   --galaz X        gałąź repo dla tej maszyny (domyślnie main; poligon/VM = gałąź testowa,
#                    żeby maszyna tymczasowa nie weszła do konsensusu luster na main)
#   --url-repo URL   skąd brać repo.tar.gz (domyślnie serwer LAN, patrz niżej)
#   --bez-pakietow   pomiń `lustro sync --auto` (116 pozycji, długie)
#   --bez-tailscale / --bez-syncthing / --bez-zapory / --bez-vpn / --bez-pulpitu / --bez-node
#   --kontener       tryb testu w kontenerze: bez systemd, GNOME, snap, ufw, Tailscale, nmcli
set -u

SERWER_LAN="${SERWER_LAN:-192.168.1.49}"
URL_SKRYPT="http://$SERWER_LAN:8100/nowa-stacja.sh"
URL_REPO="${URL_REPO:-http://$SERWER_LAN:8100/repo.tar.gz}"
SERWER_SSH="${SERWER_SSH:-mk@$SERWER_LAN}"
REPO_GITHUB="git@github.com:mkzakupyzneta-source/dotfiles.git"
REPO="$HOME/.local/share/chezmoi"
LUSTRA="$REPO/lustra"
LOG="$HOME/nowa-stacja.log"
# Git/ssh z tego skryptu (także z wnętrza lustro.py — dziedziczy środowisko) NIGDY nie pytają o hasło:
# HP 29.08 — prompt ssh wychodził z `subprocess.run(capture_output, timeout)`, user wpisywał hasło,
# timeout ubijał gita i następna operacja pytała od nowa. Brak klucza = natychmiastowy, czytelny błąd;
# jedynym miejscem na hasło serwera jest K4b. (accept-new: nowy odcisk hosta przyjmij, zmieniony odrzuć.)
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"

NAZWA=""; PACZKA=""; GALAZ="main"; KONTENER=0
BEZ_PAKIETOW=0; BEZ_TAILSCALE=0; BEZ_SYNCTHING=0; BEZ_ZAPORY=0; BEZ_VPN=0; BEZ_PULPITU=0; BEZ_NODE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --nazwa) NAZWA="$2"; shift ;;
        --paczka) PACZKA="$2"; shift ;;
        --galaz) GALAZ="$2"; shift ;;
        --url-repo) URL_REPO="$2"; shift ;;
        --bez-pakietow) BEZ_PAKIETOW=1 ;;
        --bez-tailscale) BEZ_TAILSCALE=1 ;;
        --bez-syncthing) BEZ_SYNCTHING=1 ;;
        --bez-zapory) BEZ_ZAPORY=1 ;;
        --bez-vpn) BEZ_VPN=1 ;;
        --bez-pulpitu) BEZ_PULPITU=1 ;;
        --bez-node) BEZ_NODE=1 ;;
        --kontener) KONTENER=1; BEZ_TAILSCALE=1; BEZ_ZAPORY=1; BEZ_VPN=1; BEZ_PULPITU=1 ;;
        -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
        *) echo "nieznany przełącznik: $1"; exit 2 ;;
    esac
    shift
done

# ------------------------------------------------------------------ narzędzia raportu
WYNIKI=()          # "krok|stan|uwaga"  stan: OK / POMINIĘTO / BŁĄD / RĘCZNIE
krok() { printf '\n\033[1;34m══ %s\033[0m\n' "$*"; echo "== $(date '+%H:%M:%S') $*" >>"$LOG"; }
ok()   { WYNIKI+=("$1|OK|${2:-}"); echo "   ✓ $1${2:+ — $2}"; }
pomin(){ WYNIKI+=("$1|POMINIĘTO|${2:-}"); echo "   ○ $1 — pominięte${2:+: $2}"; }
blad() { WYNIKI+=("$1|BŁĄD|${2:-}"); echo "   ✗ $1 — BŁĄD${2:+: $2}"; }
recznie(){ WYNIKI+=("$1|RĘCZNIE|${2:-}"); echo "   ☐ $1 — do zrobienia ręcznie${2:+: $2}"; }
uruchom() { echo "\$ $*" >>"$LOG"; "$@" >>"$LOG" 2>&1; }   # cicho: wynik w $LOG
PYTHON="${PYTHON:-python3}"

echo "nowa-stacja.sh — start $(date '+%F %T'), log: $LOG" | tee -a "$LOG"

# ------------------------------------------------------------------ K0 sprawdzenia
krok "K0 Sprawdzenia wstępne"
if [ "$(id -u)" = 0 ]; then echo "Uruchom jako zwykły user (ten, który ma być właścicielem stacji), nie root."; exit 1; fi
. /etc/os-release 2>/dev/null || true
if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    echo "   ⚠ To nie jest Ubuntu 24.04 (${PRETTY_NAME:-?}) — lustra są na 24.04; jadę dalej, ale bez gwarancji."
fi
if ! command -v sudo >/dev/null; then echo "brak sudo — zainstaluj: apt-get install sudo"; exit 1; fi
# `sudo -n true` najpierw: przy regule NOPASSWD (VM/poligon, [194]) `sudo -v` i tak żądałoby hasła
# (domyślne verifypw=all — wystarczy, że pasuje też `%sudo … ALL`), a bez terminala to koniec.
if ! sudo -n true 2>/dev/null; then
    echo "   Potrzebuję sudo (hasło tej maszyny) — raz, potem podtrzymuję w tle."
    sudo -v || { echo "sudo odmówiło — stop."; exit 1; }
fi
( while true; do sudo -n true 2>/dev/null; sleep 50; done ) &
SUDO_PODTRZYMANIE=$!
trap 'kill $SUDO_PODTRZYMANIE 2>/dev/null' EXIT
[ -z "$NAZWA" ] && NAZWA="$(hostname | tr '[:upper:]' '[:lower:]')"
HOSTNAME_TU="$(hostname)"
UZYTKOWNIK="$(id -un)"
TTY=0; { : </dev/tty; } 2>/dev/null && TTY=1
# Uruchomienie przez SSH (bez zmiennych sesji graficznej): podepnij się pod sesję usera, jeśli jest
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ] && export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
[ -z "${DISPLAY:-}" ] && [ -d /tmp/.X11-unix ] && X1="$(ls /tmp/.X11-unix 2>/dev/null | head -1)" && [ -n "$X1" ] && export DISPLAY=":${X1#X}"
ok "sudo działa" "maszyna: $NAZWA (hostname $HOSTNAME_TU), user: $UZYTKOWNIK, terminal: $TTY"

# ------------------------------------------------------------------ K1 minimum apt
krok "K1 Minimum z apt: git curl python3 openssh-server (świeże Ubuntu nie ma gita)"
export DEBIAN_FRONTEND=noninteractive
BRAK=""
for p in git curl python3 ca-certificates openssh-server gpg xdg-user-dirs; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || BRAK="$BRAK $p"
done
if [ -n "$BRAK" ]; then
    uruchom sudo apt-get update -qq
    # shellcheck disable=SC2086
    if uruchom sudo apt-get install -y -qq $BRAK; then ok "apt: zainstalowane$BRAK"; else blad "apt install$BRAK"; exit 1; fi
else
    ok "apt: minimum już było"
fi
[ $KONTENER = 0 ] && sudo systemctl enable --now ssh >/dev/null 2>&1 || true

# ------------------------------------------------------------------ K2 repozytorium
krok "K2 Repozytorium konfiguracji (chezmoi) → $REPO"
if [ -d "$REPO/.git" ]; then
    ok "repozytorium już jest" "$(git -C "$REPO" log --oneline -1)"
else
    mkdir -p "$(dirname "$REPO")"
    TMP="$(mktemp -d)"
    ZRODLO=""
    if [ -n "$PACZKA" ] && [ -f "$PACZKA" ]; then
        cp "$PACZKA" "$TMP/repo.tar.gz" && ZRODLO="paczka $PACZKA"
    elif curl -fsSL --connect-timeout 10 "$URL_REPO" -o "$TMP/repo.tar.gz"; then
        ZRODLO="HTTP $URL_REPO"
    fi
    if [ -n "$ZRODLO" ]; then
        mkdir -p "$TMP/x" && tar -xzf "$TMP/repo.tar.gz" -C "$TMP/x"
        KAT="$(find "$TMP/x" -maxdepth 2 -name .git -type d | head -1)"
        if [ -n "$KAT" ]; then mv "$(dirname "$KAT")" "$REPO"; ok "repozytorium rozpakowane" "$ZRODLO"; else blad "paczka bez .git"; fi
    else
        echo "   HTTP nie odpowiada — próbuję git clone po SSH z serwera ($SERWER_SSH, pyta o hasło konta na serwerze)"
        # jedyny git PRZED K4b (klucza jeszcze nie ma) — tu wyjątkowo bez BatchMode, ssh może spytać o hasło
        if GIT_SSH_COMMAND="ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new" git clone -q "$SERWER_SSH:.local/share/chezmoi" "$REPO"; then ok "repozytorium sklonowane po SSH"; else blad "nie umiem pobrać repozytorium (HTTP i SSH)"; exit 1; fi
    fi
    rm -rf "$TMP"
fi
# Zdalne: origin = GitHub (kanoniczne; zadziała po dodaniu klucza — osobna komenda),
# serwer = klon na OptiPlexie po SSH (działa po przyjęciu maszyny, kluczem domowym).
# Do czasu klucza GitHub gałąź main śledzi `serwer` — pull/push idą przez serwer.
git -C "$REPO" remote get-url origin >/dev/null 2>&1 || git -C "$REPO" remote add origin "$REPO_GITHUB"
git -C "$REPO" remote set-url origin "$REPO_GITHUB"
git -C "$REPO" remote get-url serwer >/dev/null 2>&1 || git -C "$REPO" remote add serwer "$SERWER_SSH:.local/share/chezmoi"
if [ "$GALAZ" != "main" ] && [ "$(git -C "$REPO" branch --show-current)" != "$GALAZ" ]; then
    git -C "$REPO" checkout -q -B "$GALAZ" && echo "   gałąź testowa: $GALAZ (nie main — maszyna tymczasowa nie trafi do konsensusu luster)"
fi
git -C "$REPO" config "branch.$GALAZ.remote" serwer
git -C "$REPO" config "branch.$GALAZ.merge" "refs/heads/$GALAZ"
git -C "$REPO" config user.name  >/dev/null || git -C "$REPO" config user.name "mk@$NAZWA"
git -C "$REPO" config user.email >/dev/null || git -C "$REPO" config user.email "mk@$NAZWA.local"
echo "   UWAGA: do kroku K16b commity tej maszyny NIE trafiają na GitHub — idą tylko do"
echo "   lokalnego repozytorium i (gdy klucz domowy zadziała) na serwer. GitHub jest domem"
echo "   kanonicznym repozytorium; przełączy na niego K16b, po dodaniu klucza na koncie."
ok "git: gałąź $GALAZ, origin=GitHub (jeszcze bez klucza), upstream=serwer" "dom repozytorium ustawi K16b"

if [ ! -f "$LUSTRA/lustro.py" ]; then blad "w repozytorium nie ma lustra/lustro.py — to nie jest repo konfiguracji"; exit 1; fi

# ------------------------------------------------------------------ K3 sudoers [194]
krok "K3 Reguła sudo bez hasła dla apt/dpkg/snap/flatpak ([194] — potrzebna timerowi lustra)"
SUDOERS=/etc/sudoers.d/90-lustro-pakiety
if sudo test -f $SUDOERS; then
    ok "reguła [194] już jest"
else
    printf '%s ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt, /usr/bin/dpkg, /usr/bin/snap, /usr/bin/flatpak\n' "$UZYTKOWNIK" >/tmp/90-lustro-pakiety
    if sudo visudo -cf /tmp/90-lustro-pakiety >/dev/null && sudo install -m 440 -o root -g root /tmp/90-lustro-pakiety $SUDOERS; then
        ok "reguła [194] założona" "$SUDOERS"
    else blad "sudoers [194]"; fi
    rm -f /tmp/90-lustro-pakiety
fi

# ------------------------------------------------------------------ K3b ustawienia zasilania [267c][279]
# Trzy rzeczy naraz, każda sterowana osobnym polem w lustra/maszyny.toml:
#   wolno_wylaczac       → reguła sudo /etc/sudoers.d/91-lustro-zasilanie
#   klapa_zamkniecie     → drop-in /etc/systemd/logind.conf.d/50-lustro-klapa.conf
#   klapa_otwarcie_budzi → wybudzanie klapą (/proc/acpi/wakeup + lustro-klapa-wakeup.service)
# Skrypt sam pyta danych — my tu tylko decydujemy, CZY go wołać, żeby maszyna bez żadnego
# z tych ustawień nie dostała niepotrzebnego pytania o hasło sudo. Pytamy jego własnego
# podglądu (ostatnia linia: `# jest-co-robic` albo `# nic-do-zrobienia`) — nie zgadujemy
# tu drugi raz tego, co on już policzył z danych.
# UWAGA: ten krok idzie PRZED K5, który dopisuje maszynę do maszyny.toml — świeża maszyna
# nie ma tam jeszcze bloku, więc krok wyjdzie „pominięte". To POPRAWNE: brak danych = brak
# zgody i brak wyjątków. Gdy user później nada maszynie któreś z pól, wszystko zakłada
# jedno uruchomienie `lustra/zasilanie-stacja.sh --wykonaj` (pyta o hasło sudo).
krok "K3b Ustawienia zasilania: wyłączanie i klapa ([267c][279] — z danych maszyny.toml)"
ZASILANIE="$LUSTRA/zasilanie-stacja.sh"
if [ ! -f "$ZASILANIE" ]; then
    pomin "zasilanie-stacja.sh" "brak skryptu w repozytorium"
elif LUSTRO_HOSTNAME=$NAZWA sh "$ZASILANIE" 2>/dev/null | grep -q '^# jest-co-robic'; then
    if LUSTRO_HOSTNAME=$NAZWA sh "$ZASILANIE" --wykonaj >>"$LOG" 2>&1; then
        ok "ustawienia zasilania [267c][279] wgrane" "szczegóły w $LOG"
    else blad "zasilanie-stacja.sh --wykonaj"; fi
else
    pomin "ustawienia zasilania" "$NAZWA nie ma w maszyny.toml ani wolno_wylaczac, ani wyjątku klapy"
fi

# ------------------------------------------------------------------ K4 klucze SSH
krok "K4 Trzy klucze SSH (wzorzec obszaru 7, etap S1) + known_hosts maszyn domowych"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [ -f "$HOME/.ssh/id_ed25519" ]; then ok "klucz osobisty id_ed25519 już jest"; else
    if [ $TTY = 1 ]; then
        echo "   Klucz OSOBISTY (do świata zewnętrznego) — podaj FRAZĘ (hasło klucza), gdy ssh-keygen zapyta:"
        if ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -C "mk@$NAZWA" </dev/tty; then ok "klucz osobisty id_ed25519 (z frazą)"; else blad "ssh-keygen id_ed25519"; fi
    else
        ssh-keygen -q -t ed25519 -f "$HOME/.ssh/id_ed25519" -N "" -C "mk@$NAZWA" && recznie "klucz osobisty id_ed25519 BEZ frazy (brak terminala)" "nadaj frazę: ssh-keygen -p -f ~/.ssh/id_ed25519"
    fi
fi
if [ -f "$HOME/.ssh/id_ed25519_github" ]; then ok "klucz GitHub już jest"; else
    ssh-keygen -q -t ed25519 -f "$HOME/.ssh/id_ed25519_github" -N "" -C "mk@$NAZWA-github" && ok "klucz GitHub id_ed25519_github (bez frazy)" || blad "ssh-keygen github"
fi
if [ -f "$HOME/.ssh/id_ed25519_dom" ]; then ok "klucz domowy już jest"; else
    ssh-keygen -q -t ed25519 -f "$HOME/.ssh/id_ed25519_dom" -N "" -C "mk@$NAZWA-dom" && ok "klucz domowy id_ed25519_dom (bez frazy, osobny per stacja — L2)" || blad "ssh-keygen dom"
fi
# ~/.ssh/config i ~/.ssh/authorized_keys: SKŁADA CHEZMOI (szablony obszaru 2, [222]) z maszyny.toml,
# siec.toml i lustra/klucze-publiczne/*.pub — dlatego klucze muszą istnieć PRZED `chezmoi apply` (K6).
touch "$HOME/.ssh/known_hosts" && chmod 600 "$HOME/.ssh/known_hosts"
ZNANE=0
while IFS= read -r h; do
    [ -z "$h" ] && continue
    ssh-keygen -F "$h" -f "$HOME/.ssh/known_hosts" >/dev/null 2>&1 && continue
    if ssh-keyscan -T 4 -t ed25519,rsa "$h" 2>/dev/null >>"$HOME/.ssh/known_hosts"; then ZNANE=$((ZNANE+1)); fi
done < <($PYTHON "$LUSTRA/stacja-dane.py" hosty --bez "$NAZWA")
ok "known_hosts: odciski maszyn domowych (ssh-keyscan)" "nowe: $ZNANE (nieosiągalne pominięte)"

# ------------------------------------------------------------------ K4b klucz domowy → serwer
krok "K4b Klucz domowy tej maszyny na serwer (raz, hasłem konta na serwerze)"
# Do 28.08 klucz nowej stacji trafiał na serwer dopiero w przyjmij-maszyne.sh (NA KOŃCU, z serwera),
# więc K8/K11/K16 (git pull/push do zdalnego `serwer`) pytały o hasło z wnętrza lustro.py i padały
# na timeoucie (HP 29.08; na VM nie wyszło, bo VM miała klucz wpuszczony wcześniej). Serwer wpuszcza
# hasłem (PasswordAuthentication yes); ssh-copy-id nie dubluje linii (idempotentne). Przed K6 nie ma
# jeszcze ~/.ssh/config z chezmoi, dlatego klucz podany jawnie (-i, IdentitiesOnly).
SSH_SERWER="ssh -i $HOME/.ssh/id_ed25519_dom -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"
if $SSH_SERWER "$SERWER_SSH" true >>"$LOG" 2>&1; then
    ok "serwer $SERWER_SSH wpuszcza kluczem domowym (już było)"
elif [ ! -f "$HOME/.ssh/id_ed25519_dom.pub" ]; then
    blad "brak ~/.ssh/id_ed25519_dom.pub (K4 padł?) — nie mam czego wysłać na serwer"
elif [ $TTY = 1 ]; then
    echo "   To JEDYNE pytanie o hasło serwera w całym automacie: podaj hasło konta $SERWER_SSH."
    echo "   Klucz domowy tej maszyny wejdzie do authorized_keys serwera — potem wszystko wchodzi kluczem."
    ssh-copy-id -i "$HOME/.ssh/id_ed25519_dom.pub" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$SERWER_SSH" </dev/tty 2>&1 | tee -a "$LOG" | grep -v '^$' | sed 's/^/   /'
    if $SSH_SERWER "$SERWER_SSH" true >>"$LOG" 2>&1; then ok "klucz domowy wpisany na serwer (ssh-copy-id) — git/ssh do serwera bez hasła"
    else blad "serwer nadal nie wpuszcza kluczem domowym" "powtórz: ssh-copy-id -i ~/.ssh/id_ed25519_dom.pub $SERWER_SSH; do tego czasu git do serwera pada od razu (BatchMode)"; fi
else
    recznie "klucz domowy na serwer (brak terminala)" "w terminalu: ssh-copy-id -i ~/.ssh/id_ed25519_dom.pub $SERWER_SSH  (albo z serwera: przyjmij-maszyne.sh $NAZWA <adres>)"
fi

# ------------------------------------------------------------------ K5 wpis maszyny w danych
krok "K5 Maszyna jako DANA: blok [[maszyna]] w lustra/maszyny.toml"
IP_LAN="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -E '^192\.168\.' | head -1)"
IF_LAN="$(ip -4 -o addr show scope global 2>/dev/null | awk -v ip="$IP_LAN" '$4 ~ "^"ip"/" {print $2}' | head -1)"
MAC_LAN=""; [ -n "$IF_LAN" ] && MAC_LAN="$(cat "/sys/class/net/$IF_LAN/address" 2>/dev/null)"
if $PYTHON "$LUSTRA/stacja-dane.py" maszyna-wpisz --klucz "$NAZWA" --nazwa-hosta "$HOSTNAME_TU" \
        --host-lan "${IP_LAN:-}" --mac-lan "${MAC_LAN:-}" --user "$UZYTKOWNIK" \
        --katalog-roboczy "$HOME/AI-katalog-roboczy" --dostepna-jako-cel true --aktywna true \
        --profil stacja --czlonek-lustra true --rola "Stacja robocza" \
        --system "$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-}")"; then
    ok "maszyny.toml: $NAZWA (host $HOSTNAME_TU, LAN ${IP_LAN:-?}, MAC ${MAC_LAN:-?})"
else blad "maszyny.toml"; fi
# Asus: akcje panelu odblokowane — serwer wchodzi na kiosk@ od 27.08 (meldunek obszaru 1)

# ------------------------------------------------------------------ K6 chezmoi
krok "K6 chezmoi: binarka + init + apply (pliki; skrypt instalacji pakietów osobno, w K8)"
mkdir -p "$HOME/.local/bin"
if [ -x "$HOME/.local/bin/chezmoi" ] || command -v chezmoi >/dev/null; then ok "chezmoi już jest" "$(chezmoi --version 2>/dev/null || "$HOME/.local/bin/chezmoi" --version)"; else
    if sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin" >>"$LOG" 2>&1; then ok "chezmoi zainstalowany" "$("$HOME/.local/bin/chezmoi" --version | head -1)"; else blad "instalacja chezmoi (get.chezmoi.io)"; fi
fi
export PATH="$HOME/.local/bin:$PATH"
PROFIL="$(chezmoi execute-template '{{ includeTemplate "profil" . }}' 2>/dev/null | tr -d '[:space:]')"
if [ "$PROFIL" = "stacja" ]; then ok "profil chezmoi: stacja"; else blad "profil chezmoi = '$PROFIL' (ma być stacja) — sprawdź nazwa_hosta w maszyny.toml"; fi
if uruchom chezmoi apply --force --exclude scripts >/dev/null; then
    ok "chezmoi apply (pliki: .bashrc, .profile, bin/, .config/, ~/.local/bin/lustro, ~/.claude/settings.json)" "$(chezmoi managed | wc -l) pozycji"
else blad "chezmoi apply"; fi
if grep -q "id_ed25519_dom" "$HOME/.ssh/config" 2>/dev/null && grep -q "id_ed25519_github" "$HOME/.ssh/config"; then
    ok "~/.ssh/config z chezmoi (bloki GitHub + dom, IdentitiesOnly)" "$(grep -c '^Host ' "$HOME/.ssh/config") bloków Host"
else blad "~/.ssh/config bez bloków kluczy — szablon private_dot_ssh/private_config.tmpl nie widzi kluczy?"; fi
N_AUTH="$(grep -c '^ssh-' "$HOME/.ssh/authorized_keys" 2>/dev/null || echo 0)"
if [ "$N_AUTH" -ge 3 ]; then ok "~/.ssh/authorized_keys z chezmoi (lustra/klucze-publiczne/)" "$N_AUTH kluczy maszyn domowych"; else blad "authorized_keys ma $N_AUTH kluczy (szablon [222])"; fi
# drugie konto Claude: ten sam symlink co ~/.claude/settings.json (procedura Etap 2)
KONTO2="$HOME/.claude-konto1"; mkdir -p "$KONTO2"
if [ -L "$KONTO2/settings.json" ]; then ok "$KONTO2/settings.json już jest dowiązaniem"; else
    [ -f "$KONTO2/settings.json" ] && mv "$KONTO2/settings.json" "$KONTO2/settings.json.bak-lokalny-$(date +%F)"
    ln -s "$HOME/AI-katalog-roboczy/.claude-shared/settings.json" "$KONTO2/settings.json" && ok "dowiązanie settings.json dla drugiego konta ($KONTO2)"
fi

# ------------------------------------------------------------------ K7 zasiew dziennika
krok "K7 Zasiew dziennika lustra tej maszyny (append-only, idempotentne)"
if $PYTHON "$LUSTRA/zasiew-uzupelniajacy.py" --notatka "zasiew automatyczny — nowa-stacja.sh ($(date -I))" >>"$LOG" 2>&1; then
    ok "dziennik zasiany" "$(wc -l <"$LUSTRA/dziennik/$NAZWA.jsonl" 2>/dev/null || echo 0) zdarzeń w dziennik/$NAZWA.jsonl"
else blad "zasiew-uzupelniajacy.py (szczegóły w $LOG)"; fi

# ------------------------------------------------------------------ K8 pakiety lustra
krok "K8 Programy lustra: lustro sync --auto (apt/snap/flatpak + zewnętrzne źródła apt; pozycje skrypt z katalogu roboczego dopiero po K14 — dociągnie timer)"
LUSTRO="$PYTHON $LUSTRA/lustro.py"
if [ $BEZ_PAKIETOW = 1 ]; then pomin "lustro sync --auto" "--bez-pakietow"; else
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | sudo debconf-set-selections
    if [ $KONTENER = 0 ] && ! command -v flatpak >/dev/null; then sudo apt-get install -y -qq flatpak >>"$LOG" 2>&1; fi
    # zdalne flathub — bez niego KAŻDY flatpak z lustra pada („No remote refs found for flathub", VM 27.08)
    if command -v flatpak >/dev/null; then
        sudo flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo >>"$LOG" 2>&1 && ok "flatpak: zdalne flathub" || blad "flatpak remote-add flathub"
    fi
    if $LUSTRO sync --auto 2>&1 | tee -a "$LOG" | tail -25; then ok "lustro sync --auto"; else blad "lustro sync --auto zgłosił nieudane pozycje (patrz wyżej / $LOG)"; fi
fi

# ------------------------------------------------------------------ K9 Node, Claude Code, Bitwarden CLI
krok "K9 Node przez nvm → Claude Code → Bitwarden CLI (npm -g @bitwarden/cli)"
if [ $BEZ_NODE = 1 ]; then pomin "Node/Claude/bw" "--bez-node"; else
    export NVM_DIR="$HOME/.nvm"
    if [ -s "$NVM_DIR/nvm.sh" ]; then ok "nvm już jest"; else
        NVM_V="$(curl -fsSL https://api.github.com/repos/nvm-sh/nvm/releases/latest 2>/dev/null | $PYTHON -c 'import sys,json;print(json.load(sys.stdin)["tag_name"])' 2>/dev/null || echo v0.40.3)"
        if curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_V/install.sh" | PROFILE=/dev/null bash >>"$LOG" 2>&1; then ok "nvm $NVM_V (blok PATH jest już w .bashrc/.profile z chezmoi)"; else blad "instalacja nvm"; fi
    fi
    # shellcheck disable=SC1091
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
    if command -v node >/dev/null && [ -d "$NVM_DIR/versions/node" ]; then ok "Node już jest" "$(node --version)"; else
        if nvm install --lts >>"$LOG" 2>&1 && nvm alias default 'lts/*' >>"$LOG" 2>&1; then ok "Node LTS" "$(node --version)"; else blad "nvm install --lts"; fi
    fi
    if command -v claude >/dev/null; then ok "Claude Code już jest" "$(claude --version 2>/dev/null | head -1)"; else
        if curl -fsSL https://claude.ai/install.sh | bash >>"$LOG" 2>&1; then ok "Claude Code (instalator natywny → ~/.local/bin/claude)" "$("$HOME/.local/bin/claude" --version 2>/dev/null | head -1)"; else blad "instalator Claude Code"; fi
    fi
    if command -v bw >/dev/null; then ok "Bitwarden CLI już jest"; else
        if command -v npm >/dev/null && npm install -g @bitwarden/cli >>"$LOG" 2>&1; then ok "Bitwarden CLI (bw)" "$(bw --version 2>/dev/null)"; else blad "npm install -g @bitwarden/cli"; fi
    fi
    command -v bw >/dev/null && bw config server https://vault.bitwarden.eu >>"$LOG" 2>&1 && ok "bw: serwer vault.bitwarden.eu"
fi

# ------------------------------------------------------------------ K10 hook dpkg + timer
krok "K10 Hook dpkg (dziennik przy KAŻDEJ zmianie apt, [213]) + timer lustro-sync (60 min)"
if $LUSTRO hak-apt --zainstaluj >>"$LOG" 2>&1; then ok "hook dpkg lustro-hak-apt zainstalowany"; else blad "lustro hak-apt --zainstaluj (patrz $LOG)"; fi
if [ $KONTENER = 1 ]; then pomin "timer systemd usera lustro-sync" "kontener bez systemd"; else
    if systemctl --user daemon-reload && systemctl --user enable --now lustro-sync.timer >>"$LOG" 2>&1; then ok "lustro-sync.timer włączony" "$(systemctl --user list-timers lustro-sync.timer --no-legend | head -1)"; else blad "systemctl --user enable lustro-sync.timer"; fi
fi

# ------------------------------------------------------------------ K11 pulpit GNOME
krok "K11 Pulpit GNOME z lustra (dconf) + rozszerzenia"
if [ $BEZ_PULPITU = 1 ]; then pomin "pulpit" "--bez-pulpitu/kontener"; elif ! command -v dconf >/dev/null || [ -z "${DBUS_SESSION_BUS_ADDRESS:-}${DISPLAY:-}" ]; then
    recznie "lustro pulpit wgraj" "brak sesji graficznej w tej powłoce — uruchom w terminalu na pulpicie"
else
    if $LUSTRO pulpit wgraj --zatwierdzam-wszystko 2>&1 | tee -a "$LOG" | tail -5; then ok "pulpit wgrany z lustra"; else blad "lustro pulpit wgraj"; fi
    $LUSTRO pulpit rozszerzenia --zatwierdzam-wszystko >>"$LOG" 2>&1 && ok "rozszerzenia GNOME (z ego) zainstalowane — aktywne po ponownym zalogowaniu" || recznie "lustro pulpit rozszerzenia" "część rozszerzeń wymaga sesji GNOME"
fi

# ------------------------------------------------------------------ K12 zapora
krok "K12 Zapora ufw stacji (podsieci z lustra/siec.toml)"
if [ $BEZ_ZAPORY = 1 ]; then pomin "ufw" "--bez-zapory/kontener"; else
    if sh "$LUSTRA/ufw-stacja.sh" --wykonaj >>"$LOG" 2>&1 && grep -q '^ENABLED=yes' /etc/ufw/ufw.conf; then ok "ufw: ENABLED=yes, reguły z siec.toml"; else blad "ufw-stacja.sh --wykonaj"; fi
fi

# ------------------------------------------------------------------ K12b sesja X11
krok "K12b Sesja X11 zamiast Wayland (GDM) — jak Vostro/Katana; zdalny pulpit [222] to x11vnc"
GDM=/etc/gdm3/custom.conf
if [ $KONTENER = 1 ] || [ ! -f $GDM ]; then pomin "WaylandEnable=false" "brak $GDM (kontener / nie GDM)"; else
    if grep -qE '^\s*WaylandEnable\s*=\s*false' $GDM; then ok "GDM: WaylandEnable=false już jest"; else
        if grep -qE '^\s*#?\s*WaylandEnable\s*=' $GDM; then sudo sed -i -E 's/^\s*#?\s*WaylandEnable\s*=.*/WaylandEnable=false/' $GDM
        else sudo sed -i -E 's/^\[daemon\]/[daemon]
WaylandEnable=false/' $GDM; fi
        grep -qE '^WaylandEnable=false' $GDM && ok "GDM: WaylandEnable=false" "obowiązuje od następnego logowania (bieżąca sesja: $(loginctl show-session "$(loginctl list-sessions --no-legend | awk '$3=="'"$UZYTKOWNIK"'"{print $1; exit}')" -p Type --value 2>/dev/null || echo ?))" || blad "edycja $GDM"
    fi
fi

# ------------------------------------------------------------------ K13 Tailscale
krok "K13 Tailscale (logowanie w przeglądarce — jedyny krok ręczny w sieci)"
if [ $BEZ_TAILSCALE = 1 ]; then pomin "tailscale" "--bez-tailscale/kontener"; else
    if ! command -v tailscale >/dev/null; then
        # zwykle już jest z K8 (pakiet `tailscale` w lustrze + źródło z zrodla-apt.toml); awaryjnie oficjalny instalator
        curl -fsSL https://tailscale.com/install.sh | sh >>"$LOG" 2>&1 || true
    fi
    if command -v tailscale >/dev/null; then
        sudo systemctl enable --now tailscaled >>"$LOG" 2>&1
        if [ "$(tailscale status --json 2>/dev/null | $PYTHON -c 'import sys,json;print(json.load(sys.stdin).get("BackendState",""))' 2>/dev/null)" = "Running" ]; then
            ok "Tailscale już zalogowany" "$(tailscale ip -4 2>/dev/null)"
        else
            if [ $TTY = 1 ]; then
                echo "   Otwórz adres, który wypisze Tailscale, zaloguj się kontem mkzakupyzneta@ — skrypt czeka."
                if sudo tailscale up --hostname "$NAZWA" </dev/tty; then ok "Tailscale zalogowany" "$(tailscale ip -4 2>/dev/null)"; else blad "tailscale up"; fi
            else
                # bez terminala (SSH/agent): `tailscale up` w tle, adres logowania do pliku — wzorzec z [149]
                nohup sudo tailscale up --hostname "$NAZWA" >"$HOME/tailscale-up.log" 2>&1 &
                URL=""; for _ in $(seq 1 120); do URL="$(grep -o 'https://login.tailscale.com/[^ ]*' "$HOME/tailscale-up.log" 2>/dev/null | head -1)"; [ -n "$URL" ] && break; sleep 1; done
                if [ -n "$URL" ]; then echo "$URL" >"$HOME/tailscale-login-url.txt"; recznie "Tailscale czeka na logowanie" "otwórz: $URL (także w ~/tailscale-login-url.txt)"; else blad "tailscale up nie wypisał adresu logowania (patrz ~/tailscale-up.log)"; fi
            fi
        fi
        TS_IP="$(tailscale ip -4 2>/dev/null | head -1)"
        [ -n "$TS_IP" ] && $PYTHON "$LUSTRA/stacja-dane.py" maszyna-wpisz --klucz "$NAZWA" --host-tailscale "$NAZWA" --ip-tailscale "$TS_IP" >>"$LOG" 2>&1
    else blad "tailscale nie zainstalowany"; fi
fi

# ------------------------------------------------------------------ K14 Syncthing
krok "K14 Syncthing: instalacja, usługa usera, urządzenia i foldery z lustra/syncthing.toml"
SYNC_ID=""
if [ $BEZ_SYNCTHING = 1 ]; then pomin "syncthing" "--bez-syncthing"; else
    command -v syncthing >/dev/null || uruchom sudo apt-get install -y -qq syncthing >/dev/null
    ST_DOM="$HOME/.local/state/syncthing"
    if [ $KONTENER = 1 ]; then
        pgrep -u "$UZYTKOWNIK" -x syncthing >/dev/null || (nohup syncthing serve --no-browser --no-restart --home "$ST_DOM" >>"$LOG" 2>&1 &)
    else
        systemctl --user enable --now syncthing.service >>"$LOG" 2>&1
    fi
    for _ in $(seq 1 30); do [ -f "$ST_DOM/config.xml" ] && curl -fs -o /dev/null http://127.0.0.1:8384/rest/noauth/health && break; sleep 1; done
    KLUCZ_API="$(grep -o '<apikey>[^<]*' "$ST_DOM/config.xml" 2>/dev/null | cut -c9-)"
    if [ -n "$KLUCZ_API" ] && command -v xdg-user-dir >/dev/null; then
        PULPIT="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
        WYJ="$($PYTHON "$LUSTRA/stacja-dane.py" syncthing-konfiguruj --klucz-api "$KLUCZ_API" --dom "$HOME" --pulpit "$PULPIT" 2>&1)"
        echo "$WYJ" >>"$LOG"; echo "$WYJ" | grep -v '^MOJE_ID=' | sed 's/^/   /'
        SYNC_ID="$(echo "$WYJ" | sed -n 's/^MOJE_ID=//p')"
        [ -n "$SYNC_ID" ] && ok "Syncthing skonfigurowany (serwer, Vostro, Katana; foldery ai-katalog-roboczy, duperele)" "ID $SYNC_ID" || blad "konfiguracja Syncthinga przez REST"
        recznie "Syncthing: przyjęcie tej maszyny po stronie serwera" "na serwerze: lustra/przyjmij-maszyne.sh $NAZWA <adres> (dodaje ID do folderów; bez tego nic się nie zsynchronizuje)"
    else blad "Syncthing nie wstał (brak config.xml/klucza API)"; fi
fi

# ------------------------------------------------------------------ K15 VPN ITLiMS
krok "K15 Profil VPN uczelniany ITLiMS (nmcli, split tunnel [176b])"
if [ $BEZ_VPN = 1 ]; then pomin "VPN ITLiMS" "--bez-vpn/kontener"; elif ! command -v nmcli >/dev/null; then blad "brak nmcli"; else
    # sudo: przez SSH (bez aktywnej sesji lokalnej) polkit odmawia („Insufficient privileges", VM 27.08); w sesji graficznej też przejdzie
    if nmcli -t -f NAME connection show 2>/dev/null | grep -qx ITLiMS; then ok "profil ITLiMS już jest"; else
        if sudo nmcli connection add type vpn ifname '*' con-name ITLiMS vpn-type fortisslvpn \
              vpn.data "gateway = vpn1.meil.pw.edu.pl:10443, realm = zpk, password-flags = 2, user = mkowalik" >>"$LOG" 2>&1 \
           && sudo nmcli connection modify ITLiMS ipv4.never-default yes ipv6.never-default yes >>"$LOG" 2>&1 \
           && sudo nmcli connection modify ITLiMS +ipv4.routes "194.29.128.0/17" >>"$LOG" 2>&1; then ok "profil VPN ITLiMS (hasło pyta przy łączeniu)"; else blad "nmcli ITLiMS (wtyczka fortisslvpn zainstalowana? — jedzie z lustrem w K8)"; fi
    fi
fi

# ------------------------------------------------------------------ K16 migawka + commit
krok "K16 Migawka inwentarza, commit danych maszyny, próba wysłania na serwer"
if chezmoi apply --force >>"$LOG" 2>&1; then ok "chezmoi apply (pełny, ze skryptami run_onchange — instalator tylko raportuje, dziennik już jest)"; else blad "chezmoi apply ze skryptami (szczegóły w $LOG; w kontenerze normalne — skrypty wymagają systemd)"; fi
$LUSTRO inwentarz eksportuj >>"$LOG" 2>&1 && ok "migawka lustra/inwentarz/$NAZWA.json" || blad "lustro inwentarz eksportuj"
# [283] tylko dane maszyny w lustra/ (dziennik, inwentarz, maszyny.toml, klucze) —
# nie `git add -A`, żeby commit nie zabierał cudzej, niezacommitowanej pracy w repo.
if [ -n "$(git -C "$REPO" status --porcelain -- lustra)" ]; then
    git -C "$REPO" add -- lustra && git -C "$REPO" commit -q -m "lustra: nowa stacja $NAZWA — nowa-stacja.sh ($(date -I))" -- lustra && ok "commit lokalny danych maszyny"
fi
if git -C "$REPO" push -q serwer "$GALAZ" >>"$LOG" 2>&1; then ok "git push na serwer ($GALAZ)"; else
    recznie "git push" "serwer nie wpuścił kluczem (K4b?) — przyjmij-maszyne.sh na serwerze sam dociągnie commity z tej maszyny"
fi

# ------------------------------------------------------------------ K16b dom repozytorium = GitHub
krok "K16b Dom repozytorium: GitHub (origin) — wypchnięcie i przełączenie gałęzi"
# Dlaczego ten krok istnieje ([259], 2026-08-29): HP po instalacji miało `branch -u serwer/main`
# (repozytorium przyszło klonem z serwera), więc jego commity szły na serwer, a Vostro, Katana
# i serwer ciągną z GitHuba — powstały DWA „domy" tego samego repozytorium i zmiany się rozjeżdżały.
# Kanoniczny zdalny jest JEDEN: origin = GitHub. Serwer zostaje jako droga awaryjna (klon po SSH).
# Ten krok wymaga, żeby klucz `id_ed25519_github.pub` był już dodany na koncie GitHub — dlatego
# przy terminalu pytamy o to TUTAJ (klucz wypisujemy), a bez terminalu zostawiamy gotową komendę.
proba_github() {
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new" \
        ssh -T -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new git@github.com 2>&1 \
        | grep -q "successfully authenticated"
}
GH=0
proba_github && GH=1
if [ $GH = 0 ] && [ $TTY = 1 ]; then
    echo "   GitHub jeszcze nie zna klucza tej maszyny. Klucz publiczny (skopiuj CAŁĄ linię):"
    [ -f "$HOME/.ssh/id_ed25519_github.pub" ] && sed 's/^/      /' "$HOME/.ssh/id_ed25519_github.pub"
    echo "   → github.com → Settings → SSH and GPG keys → New SSH key → wklej → Add SSH key"
    PROBA=0
    while [ $PROBA -lt 3 ]; do
        PROBA=$((PROBA+1))
        printf '   Dodane? [Enter = sprawdzam, p = pomijam ten krok] '
        read -r ODP </dev/tty || ODP=p
        [ "$ODP" = "p" ] && break
        if proba_github; then GH=1; break; fi
        echo "   GitHub nadal nie wpuszcza tym kluczem (próba $PROBA z 3)."
    done
fi
if [ $GH = 1 ]; then
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new" \
        git -C "$REPO" fetch -q origin "$GALAZ" >>"$LOG" 2>&1 || true
    if git -C "$REPO" rev-parse --verify -q "origin/$GALAZ" >/dev/null; then
        git -C "$REPO" rebase -q "origin/$GALAZ" >>"$LOG" 2>&1 \
            || { git -C "$REPO" rebase --abort >>"$LOG" 2>&1 || true; echo "   (rebase na origin/$GALAZ nie przeszedł — push może odmówić, szczegóły w $LOG)"; }
    fi
    if git -C "$REPO" push -q origin "$GALAZ" >>"$LOG" 2>&1 && git -C "$REPO" branch -u "origin/$GALAZ" >>"$LOG" 2>&1; then
        ok "GitHub = dom repozytorium tej maszyny" "push origin/$GALAZ + upstream przełączony"
    else
        recznie "push na GitHub" "ssh wpuszcza, ale push/branch -u nie przeszedł — patrz $LOG; komenda: git -C $REPO push origin $GALAZ && git -C $REPO branch -u origin/$GALAZ"
    fi
else
    recznie "klucz GitHub na koncie" "DOPÓKI tego nie zrobisz, commity tej maszyny zostają lokalnie (i na serwerze) — GitHub ich NIE widzi. Po dodaniu klucza: git -C $REPO push origin $GALAZ && git -C $REPO branch -u origin/$GALAZ"
fi

# ------------------------------------------------------------------ RAPORT
krok "RAPORT — $NAZWA, $(date '+%F %T')"
printf '\n%-72s %-10s %s\n' "krok" "stan" "uwaga"; printf '%0.s─' $(seq 1 110); echo
for w in "${WYNIKI[@]}"; do IFS='|' read -r k s u <<<"$w"; printf '%-72s %-10s %s\n' "${k:0:72}" "$s" "${u:0:60}"; done
echo
echo "KLUCZE PUBLICZNE TEJ MASZYNY (pełne linie — nigdy nie skracać):"
for f in id_ed25519_dom id_ed25519_github id_ed25519; do [ -f "$HOME/.ssh/$f.pub" ] && { printf '  %-20s ' "$f:"; cat "$HOME/.ssh/$f.pub"; }; done
[ -n "$SYNC_ID" ] && echo "SYNCTHING ID: $SYNC_ID"
echo
echo "lustro status (skrót):"; $LUSTRO status 2>/dev/null | grep -i -E "rozbie|brak|obce|niezapis" | head -12 | sed 's/^/   /'
cat <<KONIEC

DO ZROBIENIA RĘCZNIE (automat tu się kończy — spec rozdz. 10.3):
  1. NA SERWERZE:  ~/.local/share/chezmoi/lustra/przyjmij-maszyne.sh $NAZWA ${IP_LAN:-<adres>}
     → klucz domowy tej maszyny do authorized_keys wszystkich maszyn, known_hosts, Syncthing,
       commit kluczy i wpisu maszyny do repo + push na GitHub.
       (Na serwer sam klucz poszedł już w K4b — przyjmij roznosi go na RESZTĘ maszyn i robi Syncthing.
        Można to uruchomić także W TRAKCIE automatu, z serwera, po K8 — tak zrobiono na HP 29.08;
        wtedy drugi bieg po K14 domyka Syncthing.)
  2. GitHub → Settings → SSH and GPG keys → dodać klucz id_ed25519_github.pub (wyżej)
     — TYLKO jeśli krok K16b wypisał „RĘCZNIE". Po dodaniu klucza:
       git -C ~/.local/share/chezmoi push origin $GALAZ && git -C ~/.local/share/chezmoi branch -u origin/$GALAZ
     Do tej chwili commity tej maszyny NIE są widoczne dla pozostałych maszyn przez GitHuba ([259]).
  3. Sejf (Bitwarden):  bw login  → sekrety-odswiez.  Do sejfu idą DWIE pozycje ([270], 29.08):
     • wpis maszyny o nazwie „$NAZWA" (login konta) — folder Siec_domowa;
     • „SSH — $NAZWA (id_ed25519)" — TYLKO klucz osobisty (ten z frazą).
     Kluczy id_ed25519_dom i id_ed25519_github do sejfu NIE wkładamy: automat generuje je
     od nowa przy każdej instalacji, więc kopia niczego nie ratuje.
     Konwencja nazw i pól: 10_Siec_domowa/7_Bezpieczenstwo/sejf-konwencja.md.
  4. Logowania: Chrome (synchronizacja + Zotero Connector), Zotero (+Better BibTeX), Teams,
     Claude Code ×2 konta (pierwsze uruchomienie claude w ~/AI-katalog-roboczy: zatwierdzić MCP), Bitwarden.
  5. Speech Note: modele (polski Whisper + Vosk), „wpisuj do aktywnego okna".
  6. Sprzęt tej maszyny (obszar 2): monitory, zasilanie, klawisz zrzutu, szyfrowanie dysku (S2).
  7. WYLOGUJ SIĘ I ZALOGUJ PONOWNIE: sesja przechodzi na X11 (GDM WaylandEnable=false) i dopiero
     wtedy rozszerzenia GNOME z lustra są aktywne, a zdalny pulpit (x11vnc, 5900) startuje.
     ~/AI-katalog-roboczy pojawi się po synchronizacji (ok. 25 GB z serwera).
  8. Pozycje kanału `skrypt` (lustra/skrypty.toml — np. AI Launcher), których źródło leży
     w katalogu roboczym, dociągnie SAM timer lustro-sync (co 60 min) po synchronizacji
     katalogu roboczego — w K8 są „odłożone", to nie błąd. Podgląd: lustro status.
Pełny log: $LOG
KONIEC
