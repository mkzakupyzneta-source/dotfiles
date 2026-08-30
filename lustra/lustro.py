#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lustro — porównywarka domowych komputerów ("luster").

ETAP E2 (2026-08-23): apka umie już ZMIENIAĆ system, ale wyłącznie po pytaniu.
Zasada nadrzędna: NAJPIERW ROBIMY, POTEM ZAPISUJEMY. Zdarzenie trafia do dziennika
dopiero po ponownej inwentaryzacji potwierdzającej, że operacja naprawdę się udała.

Specyfikacja: 10_Siec_domowa/5_Wspolna_konfiguracja/mechanizm-luster-spec.md
Biblioteka standardowa Pythona 3, bez zależności zewnętrznych.

Uprawnienia roota: domyślnie `sudo` (user uruchamia apkę w terminalu).
Przełącznik `--root pkexec` (albo zmienna LUSTRO_ROOT=pkexec) przełącza na okienko
systemowe — przydatne, gdy apkę uruchamia sesja bez terminala.
"""

import argparse
import fnmatch
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- ustawienia

KATALOG = Path(__file__).resolve().parent          # …/chezmoi/lustra
REPO = KATALOG.parent                              # …/chezmoi
DOM = Path.home()

DZIENNIKI = KATALOG / "dziennik"
WYKLUCZENIA = KATALOG / "wykluczenia"
PULPIT = KATALOG / "pulpit"
MAPA_USTAWIEN = KATALOG / "ustawienia-map.txt"
PLIK_PULPITU = PULPIT / "pulpit.ini"
PLIK_ROZSZERZEN = PULPIT / "dconf-rozszerzenia.txt"
PLIK_ROZSZERZEN_GNOME = PULPIT / "rozszerzenia-gnome.txt"
ZRODLA_APT = KATALOG / "zrodla-apt.toml"           # zewnętrzne repozytoria apt [176]
STATUSY_POZYCJI = KATALOG / "statusy-pozycji.toml" # wspolne/testowe + override/wylacznie_na [209]
MASZYNY_TOML = KATALOG / "maszyny.toml"            # czlonek_lustra [209] 2.1
PROFILE_TOML = KATALOG / "profile.toml"            # co dotyczy maszyny danego profilu [284]
ZRODLA_GALEZI = PULPIT / "zrodla-galezi.toml"      # źródło per gałąź pulpitu [209] 2.3.2
PULPIT_STAN = PULPIT / "stan"                      # migawki <maszyna>.ini [209] 2.3.1
SKRYPTY_TOML = KATALOG / "skrypty.toml"            # pozycje instalowane skryptem [252]
SOURCES_D = Path("/etc/apt/sources.list.d")
# Pakiety, które przyjechały z obrazem instalatora (Debian/Ubuntu/Mint) — patrz
# `_pakiety_bazowe_instalatora()` niżej, sprawa [213] p. 2/uwaga o serwerze.
PLIK_INSTALATORA = Path("/var/log/installer/initial-status.gz")
KOPIE = DOM / ".local/share/lustro/kopie"

# --- dziennik przy KAŻDEJ zmianie [213] -------------------------------------
# Znacznik podnoszony PRZEZ lustro.py TUŻ PRZED wywołaniem apt-get install/remove
# (funkcja `_z_tlumikiem_haka`) i zdejmowany zaraz po — mówi hookowi dpkg
# (`polecenie_hak_apt`), że apka SAMA zaraz zapisze zdarzenie (zrodlo: apka/sync),
# więc hook ma tylko odświeżyć swoją migawkę, NIC nie logując (bez tego byłby
# podwójny wpis dla każdej instalacji zrobionej przez `lustro dodaj`/`usun`/`sync`).
HAK_APT_MARKER = Path("/tmp/.lustro-hak-apt-suppress")
# Migawka ostatniego znanego `inwentarz_apt()` (poza gitem — to techniczny stan
# hooka, nie zdarzenie do współdzielenia między maszynami).
HAK_APT_STAN = DOM / ".local/share/lustro/hak-apt-stan.json"
# Pełne wyjście skryptów instalacyjnych kanału `skrypt` [252] — <id>.log, nadpisywany
# przy każdym uruchomieniu (poza gitem, jak stan hooka wyżej).
LOG_SKRYPTOW = DOM / ".local/share/lustro/skrypty"

EXTENSIONS_GNOME_ORG = "https://extensions.gnome.org"

KANALY = ("apt", "snap", "flatpak")

# Kanał `skrypt` [252] (29.08): pozycje stawiane SKRYPTEM, nie menedżerem pakietów
# (pierwsza: AI Launcher). Definicje = DANE w lustra/skrypty.toml (jak zrodla-apt.toml).
# Celowo POZA `KANALY`: `KANALY` to menedżery pakietów, z których `lustro lista` buduje
# .chezmoidata/packages.yaml dla szablonu bootstrapu; pozycje `skrypt` dociąga
# `sync --auto` (K8 nowej stacji i timer co 60 min), nie szablon chezmoi. Tam, gdzie
# chodzi o „co apka umie postawić", używać KANALY_INSTALOWALNE.
KANAL_SKRYPT = "skrypt"
KANALY_INSTALOWALNE = KANALY + (KANAL_SKRYPT,)

# Wszystko w programy.md poniżej tej linii jest RĘCZNE — `lustro lista` przepisuje to
# bez zmian. Nad nią rządzi generator, pod nią człowiek.
ZNACZNIK_RECZNY = "<!-- PONIŻEJ TEJ LINII PISZE CZŁOWIEK — generator tego nie rusza -->"

# tryb roota: "sudo" (domyślnie) albo "pkexec"; ustawiany w main()
TRYB_ROOT = os.environ.get("LUSTRO_ROOT", "sudo")

# błędy odczytu dconf zebrane w trakcie jednego przebiegu — patrz _wypisz_pulpit
_BLEDY_DCONF = []


# ---------------------------------------------------------------- narzędzia

def uruchom(cmd, wejscie=None, timeout=120):
    """Uruchamia polecenie i zwraca (kod, stdout). Nigdy nie rzuca wyjątkiem."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=wejscie,
                           timeout=timeout)
        return p.returncode, p.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def uruchom_widoczne(cmd):
    """Uruchamia polecenie POKAZUJĄC jego wyjście (instalacje potrafią trwać)."""
    print(f"    → {' '.join(cmd)}")
    sys.stdout.flush()
    try:
        p = subprocess.run(cmd)
        return p.returncode
    except FileNotFoundError:
        print(f"    ⚠ brak programu: {cmd[0]}")
        return 127


def jako_root(cmd):
    """Dokleja `sudo` albo `pkexec` (przełącznik --root / zmienna LUSTRO_ROOT).

    `pkexec` wymaga pełnej ścieżki do programu — inaczej potrafi odmówić."""
    if os.geteuid() == 0:
        return list(cmd)
    if TRYB_ROOT == "pkexec":
        pelna = shutil.which(cmd[0]) or cmd[0]
        return ["pkexec", pelna] + list(cmd[1:])
    return ["sudo"] + list(cmd)


def _z_tlumikiem_haka(cmd):
    """Jak `uruchom_widoczne`, ale PODNOSI `HAK_APT_MARKER` na czas komendy [213].

    Wszystkie miejsca, gdzie APKA SAMA wykonuje `apt-get install/remove` (przez
    `lustro dodaj`/`usun`/`sync`), muszą przejść przez to opakowanie — inaczej
    hook dpkg (`polecenie_hak_apt`, wołany PRZEZ TĘ SAMĄ transakcję apt-get)
    dopisałby do dziennika DRUGIE, zbędne zdarzenie (zrodlo: wykryte) dla
    dokładnie tej instalacji, o której apka i tak zaraz sama zapisze zdarzenie
    (zrodlo: apka/sync) po własnej weryfikacji. Znacznik jest plikiem w /tmp,
    nie zmienną środowiskową — `sudo` domyślnie czyści środowisko dziecka,
    a apt-get i tak zawsze jest wywoływane pod rootem (`jako_root`)."""
    try:
        HAK_APT_MARKER.touch()
    except OSError:
        pass
    try:
        return uruchom_widoczne(cmd)
    finally:
        try:
            HAK_APT_MARKER.unlink(missing_ok=True)
        except OSError:
            pass


def czy_jest(program):
    return shutil.which(program) is not None


def wczytaj_wzorce(plik):
    """Czyta plik wzorców: jeden na linię, '#' zaczyna komentarz, puste pomijane."""
    if not plik.exists():
        return []
    wynik = []
    for linia in plik.read_text(encoding="utf-8").splitlines():
        linia = linia.split("#", 1)[0].strip()
        if linia:
            wynik.append(linia)
    return wynik


def pasuje(nazwa, wzorce):
    return any(fnmatch.fnmatch(nazwa, w) for w in wzorce)


def rozwin_dom(sciezka):
    """'~/bin/x' -> '/home/mk/bin/x'."""
    return sciezka.replace("~", str(DOM), 1) if sciezka.startswith("~") else sciezka


def pelna_sciezka(s):
    """Ścieżka z mapy ustawień (względna do domu, '~/…' albo bezwzględna) → Path."""
    s = str(s)
    if s.startswith("/"):
        return Path(s)
    if s.startswith("~"):
        return Path(rozwin_dom(s))
    return DOM / s


def skroc_dom(sciezka):
    return str(sciezka).replace(str(DOM), "~", 1)


def teraz_iso():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def nazwa_maszyny():
    """Nazwa lustra. Priorytet: plik lustra/maszyna.txt, potem dopasowanie
    `nazwa_hosta` → `klucz` w `maszyny.toml` (ta sama reguła, po której chezmoi
    już wybiera profil maszyny — `procedura-nowej-stacji.md`), na końcu nazwa
    hosta wprost.

    Dopisane 26.08 (dziura dzienników — serwer): hostname serwera to
    `mk-OptiPlex-7050`, ale jego klucz/dziennik w reszcie mechanizmu to
    `serwer`. Bez tego mapowania `lustro status`/`sync`/`dodaj` uruchomione
    WPROST na serwerze szukałyby dziennika `mk-optiplex-7050.jsonl` (nie
    istnieje) i domyślnie liczyłyby serwer jako członka lustra —
    `czy_czlonek_lustra` dla NIEZNANEJ maszyny domyślnie zwraca `True`
    (bezpieczny wybór dla maszyny naprawdę nieznanej), ale serwer akurat JEST
    znany, tylko pod innym kluczem. Dla Vostro/Katany `nazwa_hosta` już dziś
    równa się `klucz` (małymi literami) — to mapowanie nic im nie zmienia."""
    plik = KATALOG / "maszyna.txt"
    if plik.exists():
        n = plik.read_text(encoding="utf-8").strip()
        if n:
            return n
    kod, out = uruchom(["hostname"])
    host = out.strip().lower()
    if not host:
        return "nieznana"
    if MASZYNY_TOML.exists():
        import tomllib
        try:
            dane = tomllib.loads(MASZYNY_TOML.read_text(encoding="utf-8"))
            for m in dane.get("maszyna", []):
                if (m.get("nazwa_hosta") or "").strip().lower() == host:
                    klucz = (m.get("klucz") or "").strip()
                    if klucz:
                        return klucz
                    break
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return host or "nieznana"


def chezmoi_sciezka():
    return shutil.which("chezmoi") or str(DOM / ".local/bin/chezmoi")


# ---------------------------------------------------------------- pytania do usera

def pytaj(tresc, opcje="Tnps", domyslna="n"):
    """
    Zadaje JEDNO pytanie i zwraca małą literę odpowiedzi.
    `opcje` to litery dozwolonych odpowiedzi; wielka litera = wartość domyślna.

    ⚠️ Gdy nie ma z kim rozmawiać (stdin zamknięty/wyczerpany) — zwraca odpowiedź
    BEZPIECZNĄ: „n", jeśli jest wśród opcji, inaczej wartość domyślną (brak 15
    z Katany, 25.08: `pulpit wgraj` bez terminala odpowiadał sam sobie „t"
    i wgrywał pulpit bez realnego pytania). Zasada „nic bez zgody": tryb
    automatyczny mówi zgodę JAWNIE, flagą `--zatwierdzam-wszystko`.
    """
    litery = [o.lower() for o in opcje]
    bezpieczna = "n" if "n" in litery else domyslna
    podpowiedz = "/".join(opcje)
    while True:
        try:
            odp = input(f"    {tresc} [{podpowiedz}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"    (brak odpowiedzi z terminala — przyjmuję „{bezpieczna}”, "
                  f"nic-bez-zgody)")
            return bezpieczna
        if not odp:
            return domyslna
        if odp[0] in litery:
            return odp[0]
        print(f"    Nie rozumiem. Dozwolone: {podpowiedz}")


def pytaj_tekst(tresc, domyslna=""):
    try:
        odp = input(f"    {tresc}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return domyslna
    return odp or domyslna


# ---------------------------------------------------------------- inwentaryzacja

def _pakiety_bazowe_instalatora():
    """Zbiór nazw pakietów apt, które przyjechały z obrazem systemu (nie są
    świadomą instalacją usera) — z `PLIK_INSTALATORA`, jeśli istnieje na tej
    maszynie. Pusty zbiór (plik nieobecny) = brak filtra, dokładnie dotychczasowe
    zachowanie (Vostro/Katana — sprawdzone 26.08, oba bez tego logu).

    Scalone tutaj 27.08 (sprawa [213]) — do tej pory ta sama logika żyła
    WYŁĄCZNIE w `zasiew-uzupelniajacy.py` (rozdz. 17 spec: na Linux Mint, serwer,
    `apt-mark showmanual` oznacza niemal cały pulpit jako „ręczny", ~1900
    pozycji). Dopóki jedyną konsumentką inwentarza apt bez tego filtra były
    `status`/`sync` w trybie WYŁĄCZNIE RAPORTUJĄCYM, rozjazd „dwóch definicji
    tego, co się liczy" był kosmetyczny (dużo szumu w sekcji informacyjnej).
    Od [213] `inwentarz_apt()` karmi też funkcje, które PISZĄ do dziennika same
    (hook dpkg, `sync --auto` p. 2) — bez tego filtra zalałyby dziennik serwera
    tysiącami zdarzeń „dodano" dla pakietów systemowych. Stąd przeniesione do
    jednego, wspólnego miejsca zamiast łatania każdego nowego konsumenta osobno."""
    if not PLIK_INSTALATORA.exists():
        return set()
    try:
        import gzip
        with gzip.open(PLIK_INSTALATORA, "rt", encoding="utf-8", errors="replace") as f:
            return {linia.split(":", 1)[1].strip()
                    for linia in f if linia.startswith("Package:")}
    except OSError:
        return set()


def inwentarz_apt():
    """Pakiety oznaczone jako zainstalowane RĘCZNIE (bez zależności), po odsianiu
    wykluczen/apt.txt ORAZ pakietów bazowych obrazu instalatora (patrz wyżej)."""
    if not czy_jest("apt-mark"):
        return {}
    _, out = uruchom(["apt-mark", "showmanual"])
    reczne = [w.strip() for w in out.splitlines() if w.strip()]

    wersje = {}
    _, out = uruchom(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"])
    for linia in out.splitlines():
        if "\t" in linia:
            p, v = linia.split("\t", 1)
            wersje[p] = v

    wykl = wczytaj_wzorce(WYKLUCZENIA / "apt.txt")
    bazowe = _pakiety_bazowe_instalatora()
    return {p: wersje.get(p, "?") for p in reczne
            if not pasuje(p, wykl) and p not in bazowe}


def inwentarz_snap():
    """Programy usera ze snapa. Odrzuca podkłady systemowe (Notes: base/snapd)."""
    if not czy_jest("snap"):
        return {}
    _, out = uruchom(["snap", "list"])
    linie = out.splitlines()
    if len(linie) < 2:
        return {}
    wykl = wczytaj_wzorce(WYKLUCZENIA / "snap.txt")
    wynik = {}
    for linia in linie[1:]:
        pola = linia.split()
        if len(pola) < 2:
            continue
        nazwa, wersja = pola[0], pola[1]
        notes = pola[-1] if len(pola) >= 6 else "-"
        if notes in ("base", "snapd"):          # podkład systemowy, nie warsztat
            continue
        if pasuje(nazwa, wykl):
            continue
        wynik[nazwa] = wersja
    return wynik


def _flatpak_lista(przelacznik):
    """[(id, wersja)] z `flatpak list <przełącznik> --columns=application,version`."""
    _, out = uruchom(["flatpak", "list", przelacznik,
                      "--columns=application,version"])
    pary = []
    for linia in out.splitlines():
        if not linia.strip():
            continue
        pola = linia.split("\t")
        nazwa = pola[0].strip()
        wersja = (pola[1].strip() if len(pola) > 1 else "") or "?"
        if nazwa:
            pary.append((nazwa, wersja))
    return pary


def inwentarz_flatpak():
    """Programy flatpak: APLIKACJE (`--app`) oraz DODATKI aplikacji, które lustro
    już liczy (`--runtime`) — [268], 29.08.

    Dlaczego samo `--app` nie wystarczało. Dodatek do aplikacji jest we flatpaku
    RUNTIME-em, nie aplikacją: `net.mkiol.SpeechNote.Addon.nvidia` ma
    `Ref: runtime/net.mkiol.SpeechNote.Addon.nvidia/x86_64/stable`, więc
    `flatpak list --app` go nie pokazuje. Taka pozycja była dla mechanizmu
    NIEWIDZIALNA i nie dało się jej wprowadzić do lustra: `lustro dodaj` co
    prawda by ją zainstalował, ale `sprawdz_jedna_pozycje()` nie znalazłby
    wersji, a gdyby wpis do dziennika jednak powstał — każdy następny `status`
    krzyczałby „brak-tutaj" mimo dodatku leżącego na dysku (dziennik mówi „jest",
    inwentarz mówi „nie ma").

    Dlaczego NIE wszystkie runtime'y. `org.freedesktop.Platform`,
    `org.gnome.Platform`, `org.kde.Platform`, sterowniki `…Platform.GL.nvidia-…`
    i motywy `org.gtk.Gtk3theme.*` instalują się SAME jako zależności aplikacji,
    mają po kilka gałęzi naraz (24.08, 25.08, 25.08-extra…) i zmieniają się przy
    każdej aktualizacji. To nie są pozycje, które user wybiera — wpuszczenie ich
    do lustra zamieniłoby dziennik w śmietnik i kazałoby maszynom „dociągać"
    cudze wersje platform.

    Reguła (DANE z maszyny, nie lista identyfikatorów w kodzie): runtime wchodzi
    do inwentarza wtedy, gdy jest DODATKIEM APLIKACJI, którą lustro już liczy —
    czyli jego identyfikator zaczyna się od „<id aplikacji z tej samej listy>.".
    `net.mkiol.SpeechNote.Addon.nvidia` wchodzi (aplikacja `net.mkiol.SpeechNote`
    jest wyżej), `org.freedesktop.Platform.GL.default` nie wchodzi
    (`org.freedesktop.Platform` nie jest aplikacją). Dzięki temu działa też
    dodatek nazwany inaczej niż „Addon" (bywa `.Extension.`, `.Plugin`,
    `.Codecs`) i dodatek do dowolnej przyszłej aplikacji — bez ruszania kodu.

    Rodzaju pozycji (aplikacja/dodatek) CELOWO nie zapisujemy w dzienniku ani
    w statusy-pozycji.toml: instalacja, usunięcie i sprawdzenie idą po samym
    identyfikatorze (`flatpak install/uninstall/info <id>` radzą sobie z jednym
    i drugim), więc takie pole byłoby drugim źródłem prawdy do pilnowania.

    Wykluczenia z `wykluczenia/flatpak.txt` działają na obie listy — to jest
    miejsce (DANE), w którym wycisza się dodatki dociągane przez flatpaka SAM
    jako zależność aplikacji, np. `*.Locale`.
    """
    if not czy_jest("flatpak"):
        return {}
    wykl = wczytaj_wzorce(WYKLUCZENIA / "flatpak.txt")
    wynik = {nazwa: wersja for nazwa, wersja in _flatpak_lista("--app")
             if not pasuje(nazwa, wykl)}
    aplikacje = tuple(f"{n}." for n in wynik)
    for nazwa, wersja in _flatpak_lista("--runtime"):
        if pasuje(nazwa, wykl) or not nazwa.startswith(aplikacje):
            continue
        wynik[nazwa] = wersja          # dodatek w kilku gałęziach: ostatnia wygrywa
    return wynik


# ---------------------------------------------------------------- kanał skrypt [252]

def wczytaj_skrypty():
    """Czyta lustra/skrypty.toml → {id: definicja} (kanał `skrypt`, [252], 29.08).

    Pozycja kanału `skrypt` to program, którego nie stawia żaden menedżer pakietów,
    tylko skrypt (np. AI Launcher: `install.sh` kopiuje pliki do ~/.local/share).
    Definicja mówi apce, JAK poznać, że pozycja jest (`sprawdz`, kod 0 = obecna)
    i JAK ją postawić (`zainstaluj`). Cała reszta — konsensus z dziennika,
    rozbieżności, księgowanie „wykryte”, migawka inwentarza — idzie dokładnie tą samą
    drogą co apt/snap/flatpak; definicja jest tylko „sterownikiem” kanału.
    Nowa pozycja = nowy blok [[skrypt]] w pliku, bez ruszania kodu (pola → nagłówek
    pliku).

    Zduplikowany `id` = twardy błąd (jak sprzeczne override w statusy-pozycji.toml):
    dwie definicje tej samej pozycji to dwuznaczność w działaniu na systemie.
    Brak pliku = pusty słownik (kanał po prostu nie ma pozycji)."""
    if not SKRYPTY_TOML.exists():
        return {}
    import tomllib
    try:
        dane = tomllib.loads(SKRYPTY_TOML.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"⚠ nie umiem odczytać {SKRYPTY_TOML.name}: {e} — kanał skrypt pomijam")
        return {}
    wynik = {}
    for s in dane.get("skrypt", []):
        ident = (s.get("id") or "").strip()
        if not ident:
            continue
        if not s.get("sprawdz") or not s.get("zainstaluj"):
            print(f"⚠ {SKRYPTY_TOML.name}: pozycja „{ident}” bez pola `sprawdz` albo "
                  f"`zainstaluj` — pomijam")
            continue
        if ident in wynik:
            sys.exit(f"BŁĄD w {SKRYPTY_TOML.name}: DWIE definicje pozycji „{ident}” — "
                     f"zostaw dokładnie jedną.")
        wymaga = s.get("wymaga") or []
        if isinstance(wymaga, str):
            wymaga = [wymaga]
        wynik[ident] = {
            "id": ident,
            "opis": s.get("opis", ""),
            "sprawdz": s["sprawdz"],
            "zainstaluj": s["zainstaluj"],
            "usun": s.get("usun"),
            "wersja": s.get("wersja"),
            "wymaga": [str(w) for w in wymaga],
            "uwagi": s.get("uwagi", ""),
        }
    return wynik


def _srodowisko_skryptu():
    """Środowisko dla poleceń z skrypty.toml — jak w terminalu usera. Z timera
    systemd PATH nie ma ~/.local/bin ani ~/bin, a tam żyją claude, chezmoi, lustro."""
    env = dict(os.environ)
    env["HOME"] = str(DOM)
    dodatki = [str(DOM / ".local/bin"), str(DOM / "bin")]
    env["PATH"] = ":".join(dodatki + [env.get("PATH", "/usr/bin:/bin")])
    return env


def uruchom_skrypt(polecenie, timeout=60):
    """Polecenie z skrypty.toml przez `bash -c`, NIEINTERAKTYWNIE: stdin z /dev/null
    (skrypt, który chciałby o coś zapytać, dostaje koniec pliku zamiast wisieć),
    limit czasu, wyjście przechwycone. Zwraca (kod, wyjście). `~` w poleceniu
    rozwija bash — dlatego ścieżki w skrypty.toml pisze się względem katalogu
    domowego, a nie z `/home/mk`."""
    try:
        p = subprocess.run(["bash", "-c", polecenie], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=timeout, cwd=str(DOM),
                           env=_srodowisko_skryptu())
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"(przerwane: przekroczony limit {timeout} s)\n"
    except FileNotFoundError:
        return 127, "(brak programu bash)\n"


def inwentarz_skrypt(definicje=None):
    """{id: wersja} — pozycje kanału `skrypt`, które NA TEJ MASZYNIE są (kod 0
    z `sprawdz`). Wersja z polecenia `wersja` (pierwsza niepusta linia), inaczej "?".
    Pozycja bez definicji w skrypty.toml nie jest widziana wcale — apka nie ma
    jak jej sprawdzić."""
    definicje = wczytaj_skrypty() if definicje is None else definicje
    wynik = {}
    for ident, d in definicje.items():
        kod, _ = uruchom_skrypt(d["sprawdz"], timeout=30)
        if kod != 0:
            continue
        wersja = "?"
        if d.get("wersja"):
            kod, out = uruchom_skrypt(d["wersja"], timeout=30)
            linie = [l.strip() for l in out.splitlines() if l.strip()]
            if kod == 0 and linie:
                wersja = linie[0][:60]
        wynik[ident] = wersja
    return wynik


def katalog_roboczy_tej_maszyny():
    """Katalog roboczy z pola `katalog_roboczy` bloku TEJ maszyny w maszyny.toml
    (to samo pole czyta AI Launcher); gdy brak — ~/AI-katalog-roboczy."""
    domyslna = DOM / "AI-katalog-roboczy"
    if not MASZYNY_TOML.exists():
        return domyslna
    import tomllib
    try:
        dane = tomllib.loads(MASZYNY_TOML.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return domyslna
    klucz = nazwa_maszyny().lower()
    for m in dane.get("maszyna", []):
        if (m.get("klucz") or "").lower() == klucz and m.get("katalog_roboczy"):
            return pelna_sciezka(m["katalog_roboczy"])
    return domyslna


def wymagania_niespelnione(definicja):
    """Lista powodów (po ludzku), dla których pozycji `skrypt` NIE DA SIĘ JESZCZE
    postawić na tej maszynie; pusta = można. Wpisy pola `wymaga`:
      • "katalog-roboczy" — katalog roboczy (maszyny.toml → `katalog_roboczy`,
        domyślnie ~/AI-katalog-roboczy) istnieje i nie jest pusty; na nowej stacji
        pojawia się dopiero po synchronizacji Syncthinga (K14 nowa-stacja.sh, ~25 GB);
      • ścieżka (`~/…` albo `/…`) — ten plik/katalog istnieje (np. sam skrypt
        instalacyjny, który Syncthing musi najpierw dowieźć — katalog może już być,
        a konkretny plik jeszcze nie).
    Niespełnione wymaganie to POWÓD DO ODŁOŻENIA, nie błąd — timer spróbuje za godzinę."""
    powody = []
    for w in definicja.get("wymaga") or []:
        if w == "katalog-roboczy":
            kat = katalog_roboczy_tej_maszyny()
            try:
                jest = kat.is_dir() and any(kat.iterdir())
            except OSError:
                jest = False
            if not jest:
                powody.append(f"czeka na katalog roboczy {skroc_dom(kat)} "
                              f"(Syncthing jeszcze go nie dowiózł)")
        elif w.startswith("~") or w.startswith("/"):
            if not pelna_sciezka(w).exists():
                powody.append(f"czeka na plik {w} (jeszcze go tu nie ma)")
        else:
            powody.append(f"nieznane wymaganie „{w}” w {SKRYPTY_TOML.name}")
    return powody


def zainstaluj_skrypt(definicja, pokaz_wszystko=False):
    """Uruchamia `zainstaluj` pozycji kanału `skrypt` (nieinteraktywnie, limit 15 min),
    pełne wyjście zapisuje do LOG_SKRYPTOW/<id>.log, na ekran daje ogon (albo całość
    przy `pokaz_wszystko`, dla `lustro dodaj` w terminalu). Zwraca kod wyjścia.
    Sam NIE ocenia, czy się udało — o tym decyduje ponowny `sprawdz` u wołającego
    (zasada „najpierw robimy, potem sprawdzamy, dopiero potem dziennik”).
    Hooka dpkg NIE tłumimy: jeśli skrypt sam woła `apt install` (np. python3-tk),
    to jest PRAWDZIWA instalacja apt na tej maszynie i ma trafić do dziennika
    jako osobna pozycja apt."""
    ident = definicja["id"]
    kod, out = uruchom_skrypt(definicja["zainstaluj"], timeout=900)
    try:
        LOG_SKRYPTOW.mkdir(parents=True, exist_ok=True)
        (LOG_SKRYPTOW / f"{ident}.log").write_text(
            f"# {teraz_iso()}  {definicja['zainstaluj']}\n# kod wyjścia: {kod}\n{out}",
            encoding="utf-8")
    except OSError:
        pass
    linie = out.rstrip().splitlines()
    for l in (linie if pokaz_wszystko else linie[-12:]):
        print(f"      {l}")
    if not pokaz_wszystko and len(linie) > 12:
        print(f"      (… całość: {skroc_dom(LOG_SKRYPTOW / (ident + '.log'))})")
    return kod


def inwentaryzacja():
    """Zwraca {(kanal, id): wersja} — to, co na maszynie FAKTYCZNIE jest
    (apt/snap/flatpak + kanał `skrypt` wg `sprawdz` z skrypty.toml [252])."""
    stan = {}
    for k, f in (("apt", inwentarz_apt), ("snap", inwentarz_snap),
                 ("flatpak", inwentarz_flatpak), (KANAL_SKRYPT, inwentarz_skrypt)):
        for nazwa, wersja in f().items():
            stan[(k, nazwa)] = wersja
    return stan


def sprawdz_jedna_pozycje(kanal, ident):
    """Ponowna inwentaryzacja JEDNEJ pozycji (spec 9.3, punkt 2).
    Zwraca wersję (str) albo None, jeśli programu nie ma."""
    if kanal == "apt":
        kod, out = uruchom(["dpkg-query", "-W", "-f=${Status}\t${Version}", ident])
        if kod == 0 and out.startswith("install ok installed"):
            return out.split("\t", 1)[1].strip() or "?"
        return None
    if kanal == "snap":
        return inwentarz_snap().get(ident)
    if kanal == "flatpak":
        kod, _ = uruchom(["flatpak", "info", "--show-ref", ident])
        if kod != 0:
            return None
        return inwentarz_flatpak().get(ident, "?")
    if kanal == KANAL_SKRYPT:
        d = wczytaj_skrypty().get(ident)
        return inwentarz_skrypt({ident: d}).get(ident) if d else None
    return None


# ---------------------------------------------------------------- instalacje obce

def _nalezy_do_pakietu(sciezka):
    """`dpkg -S` — bez tego /opt/google daje fałszywy alarm (spec 6)."""
    if not czy_jest("dpkg"):
        return None
    kod, out = uruchom(["dpkg", "-S", str(sciezka)])
    if kod == 0 and ":" in out:
        return out.split(":", 1)[0].strip()
    return None


def instalacje_obce():
    """
    Wykrywa programy spoza apt/snap/flatpak. NIC z nimi nie robi — tylko pokazuje.
    Zwraca listę (sciezka_do_pokazania, opis).
    """
    wykl = wczytaj_wzorce(WYKLUCZENIA / "obce.txt")
    wykl_pelne = [rozwin_dom(w) for w in wykl]
    znalezione = []

    def pusty_katalog(sciezka):
        """Katalog bez ANI JEDNEGO pliku w środku (same puste podkatalogi też się liczą)
        to nie jest zainstalowany program.
        Na Vostro /usr/local/lib/python3.12/ zawiera wyłącznie pusty dist-packages —
        zakłada go sam system. Bez tej reguły dawał fałszywy alarm przy każdym `status`."""
        try:
            if not sciezka.is_dir():
                return False
            return not any(p.is_file() or p.is_symlink() for p in sciezka.rglob("*"))
        except OSError:
            return False

    def dodaj(sciezka, opis):
        s = str(sciezka)
        if pasuje(s, wykl_pelne):
            return
        skrot = skroc_dom(s)
        if pasuje(skrot, wykl):
            return
        znalezione.append((skrot, opis))

    # katalogi z programami użytkownika
    for kat, opis in ((DOM / ".local/bin", "instalator typu curl | sh"),
                      (DOM / "bin", "własny skrypt usera"),
                      (DOM / ".cargo/bin", "program z języka Rust")):
        if kat.is_dir():
            for p in sorted(kat.iterdir()):
                dodaj(p, opis)

    # miejsca systemowe — TU obowiązkowe krzyżowe sprawdzenie dpkg -S
    for kat, opis in ((Path("/usr/local/bin"), "wgrane ręcznie z sudo"),
                      (Path("/usr/local/lib"), "wgrane ręcznie z sudo")):
        if kat.is_dir():
            for p in sorted(kat.iterdir()):
                if _nalezy_do_pakietu(p):
                    continue                     # to jednak pakiet apt
                if pusty_katalog(p):
                    continue                     # pusty katalog = nic nie zainstalowano
                dodaj(p, opis)

    if Path("/opt").is_dir():
        for p in sorted(Path("/opt").iterdir()):
            if _nalezy_do_pakietu(p):
                continue                         # np. /opt/google → google-chrome-stable
            if pusty_katalog(p):
                continue
            dodaj(p, "duży program poza systemem pakietów")

    # AppImage w katalogu domowym, do 3 poziomów w głąb
    for wzor in ("*.AppImage", "*.appimage"):
        for poziom in ("", "*/", "*/*/"):
            for p in sorted(DOM.glob(poziom + wzor)):
                dodaj(p, "AppImage")

    # Python: pip --user oraz pipx
    for p in sorted(DOM.glob(".local/lib/python*/site-packages")):
        if p.is_dir() and any(p.iterdir()):
            dodaj(p, "biblioteki Pythona z pip --user")
    if czy_jest("pipx"):
        _, out = uruchom(["pipx", "list", "--short"])
        for linia in out.splitlines():
            if linia.strip():
                dodaj(DOM / ".local/bin" / linia.split()[0], "program z pipx")

    # Node przez nvm i pakiety globalne npm
    if (DOM / ".nvm").is_dir():
        dodaj(DOM / ".nvm", "Node.js przez nvm")
        kod, out = uruchom(["bash", "-lc", "npm ls -g --depth=0 --parseable"])
        if kod == 0:
            for linia in out.splitlines()[1:]:
                nazwa = Path(linia.strip()).name
                if nazwa and nazwa not in ("npm", "corepack"):
                    dodaj(DOM / ".nvm" / nazwa, "pakiet globalny npm")

    return znalezione


# Programy w wykluczenia/obce.txt oznaczone komentarzem "świadomie" — `status`
# je dlatego WYCISZA (`instalacje_obce()` je odsiewa, user już wie, że tu są),
# ale migawka inwentarza (`inwentarz_poza()`, niżej) ma PRZECIWNY cel: pokazać
# panelowi [202]/obszarowi 1 PRAWDZIWĄ wersję, właśnie DLATEGO że są legalne,
# świadome pozycje warsztatu, nie niespodzianki. Stąd osobna, mała, ręcznie
# utrzymywana lista — nie każdy program spoza kanałów da się odpytać o wersję
# jednym uniwersalnym sposobem. 27.08 (zlecenie Architekta, naprawa (b):
# "chezmoi na Vostro/Katanie niewidoczny w danych, bo dpkg o nim nie wie").
_POZA_WERSJONOWANE = {
    "chezmoi": (("chezmoi", "--version"), r"version\s+v?([^\s,]+)"),
    "claude": (("claude", "--version"), r"(\d+\.\d+\.\d+)"),
}


def inwentarz_poza(znane_id=frozenset()):
    """{(kanal, id): wersja} — instalacje SPOZA apt/snap/flatpak/gnome-extension/skrypt,
    do migawki inwentarza (`eksport_inwentarza()`/`lustra/inwentarz/<maszyna>.json`,
    27.08). Kanał `poza`. Dwa źródła:

      1. `_POZA_WERSJONOWANE` — programy świadomie zaakceptowane jako "poza"
         (wykluczenia/obce.txt) — wersja PRAWDZIWA, z `<program> --version`.
      2. Reszta `instalacje_obce()` (dokładnie to, co `status` i tak pokazuje
         w sekcji "INSTALACJE SPOZA…") — wersja nieznana ("?"), bo to
         różnorodne programy (skrypty ~/bin, AppImage, pipx, npm…) bez
         wspólnego sposobu odpytania o wersję; identyfikator to nazwa pliku
         ze ścieżki, żeby klucz był krótki i stabilny między maszynami.

    Celowo NIEZALEŻNE od filtra wykluczenia/obce.txt dla pozycji z (1) — tam
    filtr ma sens (nie straszyć usera znaną rzeczą), tutaj byłby błędem
    (schowałby dokładnie to, co ta migawka ma pokazać).

    `znane_id` — identyfikatory JUŻ obecne w innym kanale tej samej migawki
    (np. `chezmoi` na serwerze jest prawdziwym pakietem apt — patrz `dpkg -l`,
    26/27.08). Bez tego filtra ten sam program dublowałby się w migawce jako
    DWIE pozycje (`apt/chezmoi` i `poza/chezmoi`) na maszynie, gdzie akurat
    jest zainstalowany „prawidłowym” kanałem — znalezione 27.08 przy migawce
    serwera. Pomijamy takie duplikaty tutaj, nie w `_POZA_WERSJONOWANE` — to
    utrzymuje jedną definicję "co to za program", niezależną od tego, którym
    kanałem akurat trafił na daną maszynę."""
    wynik = {}
    for nazwa, (cmd, wzorzec) in _POZA_WERSJONOWANE.items():
        if nazwa in znane_id:
            continue
        if not czy_jest(cmd[0]):
            continue
        kod, out = uruchom(list(cmd))
        if kod != 0:
            continue
        m = re.search(wzorzec, out)
        wynik[("poza", nazwa)] = m.group(1) if m else "?"

    for sciezka, _opis in instalacje_obce():
        nazwa = Path(sciezka).name
        if nazwa in znane_id:
            continue
        wynik.setdefault(("poza", nazwa), "?")

    # [252] uzup. 2 (29.08): aplikacje postawione RĘKĄ z ikoną w menu — pliki
    # ~/.local/share/applications/*.desktop usera. Dotąd niewidoczne (skan wyżej
    # patrzy tylko na katalogi z programami), więc AI Launcher i jego ikona „ginęły"
    # w panelu. Identyfikator = nazwa pliku bez `.desktop`, wersja nieznana;
    # pomijamy to, co migawka zna już w innym kanale (np. `ailauncher` jako pozycja
    # `skrypt`) oraz wzorce z wykluczenia/obce.txt (żeby dało się wyciszyć np. pliki
    # generowane przez rozszerzenia GNOME) — DANE, nie kod.
    kat_desktop = DOM / ".local/share/applications"
    if kat_desktop.is_dir():
        wykl = wczytaj_wzorce(WYKLUCZENIA / "obce.txt")
        for p in sorted(kat_desktop.glob("*.desktop")):
            nazwa = p.stem
            if nazwa in znane_id or pasuje(skroc_dom(p), wykl):
                continue
            wynik.setdefault(("poza", nazwa), "?")
    return wynik


def eksport_inwentarza():
    """{(kanal, id): wersja} — KOMPLETNY obraz TEJ maszyny w tej chwili, do
    migawki `lustra/inwentarz/<maszyna>.json` (27.08, zlecenie Architekta,
    naprawa (b)/(c) z incydentu 27.08: panel widział chezmoi „tylko na
    serwerze" i nie miał żywego źródła do porównania WERSJI między maszynami
    — dziennik zna wyłącznie wersję z chwili instalacji zdarzenia, nie
    aktualną). Różni się od `inwentaryzacja()` (rdzeń `status`/`sync`, tylko
    apt/snap/flatpak) dwoma dołożeniami:

      • gnome-extension — z dysku, tylko rozszerzenia usera. Ten sam blok co
        w `zbierz_pozycje()`, ŚWIADOMIE zduplikowany zamiast wydzielony do
        wspólnej funkcji — `zbierz_pozycje()` jest rdzeniem `status`/`sync`
        z własnym testem ochronnym (bit-identyczny wynik); ta zmiana go
        nie dotyka.
      • kanał `poza` — `inwentarz_poza()`, patrz tam.
    """
    stan = dict(inwentaryzacja())
    if any(k.is_dir() for k in KATALOGI_ROZSZERZEN) or czy_jest("gnome-shell"):
        for uuid, wersja in rozszerzenia_na_dysku(tylko_uzytkownika=True).items():
            stan[("gnome-extension", uuid)] = wersja
    znane_id = {ident for _kanal, ident in stan}
    stan.update(inwentarz_poza(znane_id))
    return stan


# ------------------------------------------------- pole `zrodlo` w migawce [257b]

def _nazwij_zrodlo_apt(url, wg_url):
    """Adres repozytorium → krótki napis dla człowieka.

    Kolejność (od najbardziej do najmniej konkretnej wiedzy):
      1. adres pasuje do bloku [[zrodlo]] w zrodla-apt.toml → jego pole `nazwa`
         (najlepsze: ta sama etykieta, którą apka posługuje się wszędzie indziej),
      2. archiwum Ubuntu (host *.ubuntu.com) → "ubuntu" — WSZYSTKIE lustra tego
         archiwum (pl.archive…, security…, archive…) to dla człowieka jedno źródło,
      3. inaczej → sam host adresu (np. "download.opensuse.org") — uczciwe „nie
         wiem, jak to nazwać", ale widać, skąd pakiet przyszedł.
    """
    czysty = (url or "").rstrip("/")
    for u, nazwa in wg_url.items():
        if czysty.startswith(u):
            return nazwa
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host == "ubuntu.com" or host.endswith(".ubuntu.com"):
        return "ubuntu"
    return host


def _zrodla_apt(pakiety):
    """{pakiet: "napis"} — skąd pochodzi ZAINSTALOWANA wersja pakietu apt.

    Czytamy `apt-cache policy` (wiersz `***` = wersja zainstalowana, pod nim
    wiersze „priorytet adres …”). Pierwszy adres http(s) pod `***` to repozytorium,
    z którego ta wersja jest. Wiersz `100 /var/lib/dpkg/status` przeskakujemy —
    mówi tylko „to jest zainstalowane", nie „skąd".

    Pakiet zainstalowany z pliku .deb ma pod `***` wyłącznie `/var/lib/dpkg/status`
    — wtedy zwracamy pusty napis (panel pokaże „—"), bo źródła po prostu nie ma.

    JEDNO wywołanie na wszystkie pakiety naraz (ok. 120 na stację) — `apt-cache
    policy` przyjmuje listę; wołanie w pętli kosztowałoby ok. 120 uruchomień apta.
    """
    if not pakiety or not czy_jest("apt-cache"):
        return {}
    wg_url = {}
    for z in wczytaj_zrodla_apt():
        u = (z.get("url") or "").rstrip("/")
        if u and z.get("nazwa"):
            wg_url[u] = z["nazwa"]

    _, out = uruchom(["apt-cache", "policy", *sorted(pakiety)], timeout=180)
    wynik, biezacy, pod_gwiazdkami = {}, None, False
    for linia in out.splitlines():
        if linia[:1] not in (" ", "\t") and linia.rstrip().endswith(":"):
            biezacy = linia.rstrip()[:-1]
            pod_gwiazdkami = False
            continue
        if biezacy is None:
            continue
        tresc = linia.strip()
        if tresc.startswith("***"):
            pod_gwiazdkami = True
            continue
        if not pod_gwiazdkami:
            continue
        pola = tresc.split()
        if len(pola) >= 2 and pola[0].isdigit():
            if pola[1].startswith(("http://", "https://")):
                wynik[biezacy] = _nazwij_zrodlo_apt(pola[1], wg_url)
                pod_gwiazdkami = False
            continue        # np. „100 /var/lib/dpkg/status" — szukamy dalej
        pod_gwiazdkami = False
    return wynik


def _zrodla_snap():
    """{nazwa: kanał} — śledzony kanał snapa (kolumna „Tracking").

    `snap list` przycina tę kolumnę na sztywno i zamiast
    `latest/stable/ubuntu-24.04` pisze `latest/stable/…` (sprawdzone 29.08: to NIE
    jest szerokość terminala, COLUMNS=200 daje to samo). Dla przyciętych — i tylko
    dla nich — dopytujemy `snap info <nazwa>`, gdzie pełna wartość stoi w polu
    `tracking:`. Na HP dotyczyło to 6 z 13 snapów, koszt ok. 1,4 s raz na migawkę."""
    if not czy_jest("snap"):
        return {}
    _, out = uruchom(["snap", "list"])
    linie = out.splitlines()
    if len(linie) < 2:
        return {}
    naglowek = linie[0].split()
    try:
        kol = naglowek.index("Tracking")
    except ValueError:
        return {}
    wynik = {}
    for linia in linie[1:]:
        pola = linia.split()
        if len(pola) > kol:
            wynik[pola[0]] = pola[kol]
    for nazwa, kanal in list(wynik.items()):
        if "…" not in kanal and "..." not in kanal:
            continue
        kod, info = uruchom(["snap", "info", nazwa], timeout=30)
        if kod != 0:
            continue
        for w in info.splitlines():
            if w.startswith("tracking:"):
                pelny = w.split(":", 1)[1].strip()
                if pelny:
                    wynik[nazwa] = pelny
                break
    return wynik


def _zrodla_flatpak():
    """{id: zdalne repo} — nazwa remote'a flatpaka (np. „flathub").

    Bez `--app` ([268], 29.08) — inaczej DODATEK aplikacji (runtime, patrz
    `inwentarz_flatpak`) trafiałby do migawki inwentarza z pustym polem `zrodlo`
    („—" w panelu), mimo że pochodzi z tego samego Flathuba co aplikacja.
    Wpisy runtime'ów platformy są tu nieszkodliwe: to mapa do odpytania, czytana
    tylko dla identyfikatorów, które i tak są w migawce."""
    if not czy_jest("flatpak"):
        return {}
    _, out = uruchom(["flatpak", "list", "--columns=application,origin"])
    wynik = {}
    for linia in out.splitlines():
        pola = [c.strip() for c in linia.split("\t")]
        if len(pola) >= 2 and pola[0]:
            wynik[pola[0]] = pola[1]
    return wynik


def zrodla_pozycji(stan):
    """{(kanal, id): "napis"} — SKĄD pochodzi to, co na maszynie stoi. [257b], 29.08.

    Kontrakt z panelem (obszar 1): pole `zrodlo` przy każdej pozycji migawki,
    krótki napis dla człowieka, wyprowadzony z DANYCH maszyny (nie z listy zaszytej
    w kodzie):
      • apt             — `nazwa` bloku z zrodla-apt.toml, gdy adres pasuje;
                          "ubuntu" dla archiwum Ubuntu; inaczej host adresu;
                          "" gdy pakiet nie pochodzi z żadnego repozytorium (.deb z pliku)
      • snap            — śledzony kanał (np. "latest/stable")
      • flatpak         — nazwa zdalnego repo (np. "flathub")
      • gnome-extension, skrypt, poza — "" (nie ma sensownego „skąd"; dla `skrypt`
                          źródłem jest definicja w skrypty.toml, dla `poza` — ręka)

    Pusty napis i brak pola znaczą dla panelu to samo: „—".
    Liczone TYLKO przy zapisie migawki, nie w `status`/`sync` — rdzeń
    (`inwentaryzacja()`/`zbierz_pozycje()`) zostaje nietknięty.
    """
    apt_pakiety = [ident for kanal, ident in stan if kanal == "apt"]
    z_apt = _zrodla_apt(apt_pakiety)
    z_snap = _zrodla_snap() if any(k == "snap" for k, _ in stan) else {}
    z_flat = _zrodla_flatpak() if any(k == "flatpak" for k, _ in stan) else {}
    wynik = {}
    for kanal, ident in stan:
        if kanal == "apt":
            wynik[(kanal, ident)] = z_apt.get(ident, "")
        elif kanal == "snap":
            wynik[(kanal, ident)] = z_snap.get(ident, "")
        elif kanal == "flatpak":
            wynik[(kanal, ident)] = z_flat.get(ident, "")
        else:
            wynik[(kanal, ident)] = ""
    return wynik


INWENTARZ_DIR = KATALOG / "inwentarz"   # migawki <maszyna>.json, 27.08


def zapisz_migawke_inwentarza():
    """Zapisuje `lustra/inwentarz/<maszyna>.json`, TYLKO gdy `pozycje` się
    zmieniły względem poprzedniej migawki (porównanie POMIJA `ts` — inaczej
    każdy bieg timera nadpisywałby plik samym nowym znacznikiem czasu i
    zaśmiecał historię gita identycznymi commitami co godzinę, wbrew
    zleceniu "commit+push przy zmianie, bez commitu gdy identyczna").

    Format pliku: {"maszyna": ..., "ts": ISO,
                   "pozycje": [{"kanal","id","wersja","zrodlo"}, …]}
    (pole `zrodlo` doszło 29.08, [257b] — patrz `zrodla_pozycji()`; pole DODATKOWE,
    stary czytelnik migawki działa dalej, brak pola = panel pokazuje „—")
    — lista, posortowana po (kanal, id), żeby diff gita był czytelny i stabilny.

    Nie rusza gita — wołający decyduje (`polecenie_inwentarz_eksportuj` woła
    `git_zapisz` od razu; `sync --auto` woła to PRZED swoim bezwarunkowym
    `git_zapisz()` na końcu przebiegu, żeby nie było dwóch commitów za jeden
    bieg timera).

    Zwraca (zmienione: bool, liczba_pozycji: int).
    """
    maszyna = nazwa_maszyny()
    stan = eksport_inwentarza()
    zrodla = zrodla_pozycji(stan)               # [257b] — skąd to jest
    pozycje = [{"kanal": k, "id": i, "wersja": w, "zrodlo": zrodla.get((k, i), "")}
               for (k, i), w in sorted(stan.items())]

    plik = INWENTARZ_DIR / f"{maszyna}.json"
    stara_tresc = None
    if plik.exists():
        try:
            stara_tresc = json.loads(plik.read_text(encoding="utf-8")).get("pozycje")
        except (json.JSONDecodeError, OSError):
            stara_tresc = None

    if stara_tresc == pozycje:
        return False, len(pozycje)

    INWENTARZ_DIR.mkdir(parents=True, exist_ok=True)
    dane = {"maszyna": maszyna, "ts": teraz_iso(), "pozycje": pozycje}
    plik.write_text(json.dumps(dane, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    return True, len(pozycje)


def polecenie_inwentarz_eksportuj(args):
    """`lustro inwentarz eksportuj` — wywołanie RĘCZNE (bootstrap nowej maszyny,
    jednorazowa migawka serwera, weryfikacja) — zapisuje i OD RAZU commituje/
    pushuje, żeby user widział efekt bez czekania na timer. Dla wywołania z
    timera patrz `polecenie_sync_auto` (tam `zapisz_migawke_inwentarza()` bez
    osobnego commitu — łączy się z commitem końca przebiegu)."""
    git_pull_rebase()
    maszyna = nazwa_maszyny()
    zmienione, n = zapisz_migawke_inwentarza()
    plik = INWENTARZ_DIR / f"{maszyna}.json"
    if zmienione:
        print(f"Migawka inwentarza zapisana: {plik} ({n} pozycji).")
        git_zapisz(f"lustra: migawka inwentarza {maszyna} ({n} pozycji)")
    else:
        print(f"Migawka inwentarza bez zmian ({n} pozycji) — nic do zapisania.")
    return 0


# ---------------------------------------------------------------- dziennik

def wczytaj_dzienniki():
    """Wczytuje wszystkie dziennik/*.jsonl. Zwraca listę zdarzeń posortowaną po ts."""
    zdarzenia = []
    if not DZIENNIKI.is_dir():
        return zdarzenia
    for plik in sorted(DZIENNIKI.glob("*.jsonl")):
        for nr, linia in enumerate(plik.read_text(encoding="utf-8").splitlines(), 1):
            linia = linia.strip()
            if not linia or linia.startswith("#"):
                continue
            try:
                z = json.loads(linia)
            except json.JSONDecodeError as e:
                print(f"UWAGA: {plik.name}:{nr} — nieczytelna linia dziennika ({e})",
                      file=sys.stderr)
                continue
            z.setdefault("maszyna", plik.stem)
            zdarzenia.append(z)
    zdarzenia.sort(key=lambda z: z.get("ts", ""))
    return zdarzenia


def dopisz_zdarzenie(zdarzenie, kanal=None, ident=None, wersja=None,
                     zrodlo="apka", za=None, pliki=None, notatka=None, maszyna=None):
    """
    Dopisuje JEDNĄ linię do dziennika (append-only, spec 4.1).
    Kolejność pól jak w spec 4.2 — żeby dziennik czytało się okiem.

    `maszyna` domyślnie to ta, na której apka aktualnie działa (`nazwa_maszyny()`).
    Wyjątek świadomy (kontrakt [209] 2.3.3, `pulpit skladaj`): kiedy gałąź pulpitu
    zostaje przejęta ze ŹRÓDŁOWEJ maszyny, zdarzenie ma trafić do JEJ dziennika
    (żeby było wiadomo „skąd i kiedy"), nie do dziennika maszyny, która akurat
    uruchomiła `skladaj` — stąd ten parametr.
    """
    docelowa = maszyna or nazwa_maszyny()
    z = {"ts": teraz_iso(), "maszyna": docelowa, "zdarzenie": zdarzenie}
    if kanal:
        z["kanal"] = kanal
    if ident is not None:
        z["id"] = ident
    if wersja:
        z["wersja"] = wersja
    z["zrodlo"] = zrodlo
    if za:
        z["za"] = za
    if pliki:
        z["pliki"] = pliki
    if notatka:
        z["notatka"] = notatka

    DZIENNIKI.mkdir(parents=True, exist_ok=True)
    plik = DZIENNIKI / f"{docelowa}.jsonl"
    with plik.open("a", encoding="utf-8") as f:
        f.write(json.dumps(z, ensure_ascii=False) + "\n")
    return z


def stan_oczekiwany(zdarzenia):
    """
    Liczy stan oczekiwany z historii WSZYSTKICH luster (spec 4.4).
    Nigdy nie jest zapisywany do pliku — zawsze liczony na świeżo.
    """
    ostatnie, historia = {}, {}
    for z in zdarzenia:
        if z.get("zdarzenie") not in ("dodano", "usunieto"):
            continue
        klucz = (z.get("kanal"), z.get("id"))
        if None in klucz:
            continue
        historia.setdefault(klucz, []).append(z)
        ostatnie[klucz] = z            # zdarzenia są posortowane → wygrywa najnowsze
    return ostatnie, historia


def stan_wg_tej_maszyny(zdarzenia, maszyna):
    """Ostatnie zdarzenie dla każdej pary (kanal,id) w dzienniku TEJ maszyny."""
    ostatnie = {}
    for z in zdarzenia:
        if z.get("maszyna") != maszyna:
            continue
        if z.get("zdarzenie") not in ("dodano", "usunieto"):
            continue
        klucz = (z.get("kanal"), z.get("id"))
        if None not in klucz:
            ostatnie[klucz] = z
    return ostatnie


def data_ludzka(ts):
    try:
        d = datetime.fromisoformat(ts)
        return d.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return str(ts)


# ---------------------------------------------------------------- pomijane na zawsze

def plik_pomijanych():
    return KATALOG / f"pomijane-{nazwa_maszyny()}.txt"


def wczytaj_pomijane():
    """Zwraca zbiór (kanal, id) świadomie pomijanych NA TEJ maszynie (spec 9.3)."""
    wynik = set()
    for linia in wczytaj_wzorce(plik_pomijanych()):
        pola = linia.split()
        if len(pola) >= 2:
            wynik.add((pola[0], " ".join(pola[1:])))
    return wynik


def dopisz_pomijane(kanal, ident, powod=""):
    plik = plik_pomijanych()
    if not plik.exists():
        plik.write_text(
            "# Pozycje świadomie POMIJANE na tej maszynie (spec 9.3, „pomiń na zawsze”).\n"
            "# To NIE jest zdarzenie instalacji — plik jest lokalny dla tej maszyny.\n"
            "# Format: <kanal> <id>   # powód\n", encoding="utf-8")
    with plik.open("a", encoding="utf-8") as f:
        f.write(f"{kanal} {ident}" + (f"    # {powod}\n" if powod else "\n"))


# ---------------------------------------------------------------- statusy pozycji (poprawka 11)

def wczytaj_statusy_pozycji():
    """
    Czyta lustra/statusy-pozycji.toml →
    {(kanal, id): {"status", "uwagi", "wylacznie_na": [...], "override": {maszyna: {...}}}}.

    Schemat kontraktu „menadżer konfiguracji" [209], rozdz. 2.2 (zastępuje płaskie
    pole `wyjatek`+`maszyna` z poprawki 11 — dzień zmiany plik był pusty, zero
    wierszy do migracji):
    brak wpisu = "wspolne" (pozycja propaguje się normalnie w konsensusie lustra);
    "testowe"  = kwarantanna — automat NIE propaguje, dopóki user nie skasuje wpisu
                 (bez zmian, pierwszeństwo przed wszystkim poniższym — rozdz. 3, 8p9);
    `wylacznie_na` = lista kluczy maszyn — konsensus lustra dla tej pozycji liczony
                 tylko w przecięciu z tą listą (rozdz. 3 reguła 3);
    `[[pozycja.override]]` = nadpisanie kierunkowe dla JEDNEJ (pozycja, maszyna) —
                 wygrywa zawsze, niezależnie od członkostwa w lustrze (rozdz. 3
                 reguła 2, dwukierunkowość z decyzji usera 26.08).

    Błąd wczytania (nieznany `status`, wpis override bez poprawnego `maszyna`/`stan`,
    albo DWA sprzeczne `[[pozycja.override]]` dla tej samej pary pozycja×maszyna —
    kontrakt rozdz. 8, przypadek 3) → apka ODMAWIA wczytania i kończy z czytelnym
    komunikatem (`sys.exit(1)`), zamiast po cichu wybierać któryś wpis: dwuznaczność
    tutaj dotyczy działania na systemie, nie tylko raportu.

    Brak pliku = pusty słownik (nic nie blokuje, wszystko "wspolne").
    """
    if not STATUSY_POZYCJI.exists():
        return {}
    import tomllib
    try:
        dane = tomllib.loads(STATUSY_POZYCJI.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"⚠ nie umiem odczytać {STATUSY_POZYCJI.name}: {e} — statusy pozycji pomijam")
        return {}
    wynik = {}
    for p in dane.get("pozycja", []):
        kanal, ident = p.get("kanal"), p.get("id")
        if not kanal or not ident:
            continue
        status = p.get("status", "wspolne")
        if status not in ("wspolne", "testowe"):
            print(f"⚠ {STATUSY_POZYCJI.name}: nieznany status „{status}” dla "
                  f"{ident} ({kanal}) — traktuję jak wspolne "
                  f"(pole „wyjatek” zostało zastąpione przez [[pozycja.override]], "
                  f"kontrakt [209] — jeśli o to chodziło, popraw wpis)")
            status = "wspolne"

        override = {}
        for o in p.get("override", []):
            maszyna_o = (o.get("maszyna") or "").lower()
            stan = o.get("stan")
            if not maszyna_o or stan not in ("obecne", "nieobecne"):
                sys.exit(
                    f"BŁĄD w {STATUSY_POZYCJI.name}: pozycja {ident} ({kanal}) ma "
                    f"[[pozycja.override]] bez poprawnych pól — wymagane "
                    f"`maszyna` (niepuste) i `stan` = \"obecne\" albo \"nieobecne\" "
                    f"(dostałem: maszyna={o.get('maszyna')!r}, stan={stan!r}). "
                    f"Nic nie liczę, dopóki plik nie jest poprawny.")
            if maszyna_o in override:
                sys.exit(
                    f"BŁĄD w {STATUSY_POZYCJI.name}: DWA sprzeczne [[pozycja.override]] "
                    f"dla tej samej pary (pozycja={ident} [{kanal}], maszyna={maszyna_o}) "
                    f"— pierwszy wpis: stan={override[maszyna_o]['stan']!r}, "
                    f"drugi wpis: stan={stan!r}. Kontrakt [209], rozdz. 8 przypadek 3: "
                    f"to twardy błąd, nie cichy wybór ostatniego — zostaw dokładnie "
                    f"JEDEN wpis override na parę (pozycja, maszyna).")
            override[maszyna_o] = {"stan": stan, "uwagi": o.get("uwagi", "")}

        wylacznie_na = [str(x).lower() for x in (p.get("wylacznie_na") or [])]

        wynik[(kanal, ident)] = {
            "status": status,
            "uwagi": p.get("uwagi", ""),
            "wylacznie_na": wylacznie_na,
            "override": override,
        }
    return wynik


def wczytaj_czlonkow_lustra():
    """
    Czyta lustra/maszyny.toml → {klucz_maszyny: bool} — czy maszyna jest członkiem
    lustra (kontrakt [209] 2.1). Wartość domyślna, gdy pole `czlonek_lustra`
    nieobecne w bloku [[maszyna]]: `profil == "stacja"` (albo brak pola `profil`,
    które też domyślnie znaczy "stacja" — patrz komentarz w maszyny.toml) → True;
    każdy inny profil (np. "serwer") → False. To jest dzisiejszy stan faktyczny
    zapisany jawnie jako dana, więc dzień wdrożenia (bez pola `czlonek_lustra`
    nigdzie) daje IDENTYCZNY wynik jak przed zmianą.

    Brak pliku / błąd odczytu = pusty słownik — `czy_czlonek_lustra` wtedy
    domyślnie liczy każdą maszynę jako członka (patrz tam), czyli zachowanie
    sprzed kontraktu [209] (wszystkie dzienniki liczą się do konsensusu).
    """
    if not MASZYNY_TOML.exists():
        return {}
    import tomllib
    try:
        dane = tomllib.loads(MASZYNY_TOML.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"⚠ nie umiem odczytać {MASZYNY_TOML.name}: {e} — członkostwo w lustrze pomijam")
        return {}
    wynik = {}
    for m in dane.get("maszyna", []):
        klucz = (m.get("klucz") or "").lower()
        if not klucz:
            continue
        domyslne = m.get("profil", "stacja") == "stacja"
        wynik[klucz] = bool(m.get("czlonek_lustra", domyslne))
    return wynik


def wczytaj_profile():
    """
    Czyta lustra/profile.toml → {nazwa_profilu: [wzorce "kanal:id"]} (sprawa [284]).

    Brak pliku, błąd odczytu albo nieznany profil = BRAK OGRANICZEŃ (wzorzec "*").
    To jest świadomy wybór bezpiecznego domyślnego zachowania: pomyłka w tym pliku
    ma najwyżej sprawić, że maszyna dostanie ZA DUŻO propozycji (jak przed [284]),
    a nie że mechanizm po cichu przestanie pilnować połowy programów.
    """
    if not PROFILE_TOML.exists():
        return {}
    import tomllib
    try:
        dane = tomllib.loads(PROFILE_TOML.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"⚠ nie umiem odczytać {PROFILE_TOML.name}: {e} — ograniczeń profilu nie stosuję")
        return {}
    wynik = {}
    for nazwa, d in (dane.get("profil") or {}).items():
        wzorce = d.get("zostaja")
        wynik[nazwa.lower()] = list(wzorce) if wzorce is not None else ["*"]
    return wynik


def profil_maszyny(maszyna=None):
    """Nazwa profilu maszyny wg pola `profil` bloku [[maszyna]] w maszyny.toml.
    Ta sama reguła, po której profil wybiera chezmoi (.chezmoitemplates/profil),
    tylko dopasowanie idzie po `klucz` lustra, a nie po `nazwa_hosta` — apka zna
    maszynę pod kluczem (patrz `nazwa_maszyny`). Brak wpisu = "stacja"."""
    maszyna = (maszyna or nazwa_maszyny()).lower()
    if not MASZYNY_TOML.exists():
        return "stacja"
    import tomllib
    try:
        dane = tomllib.loads(MASZYNY_TOML.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return "stacja"
    for m in dane.get("maszyna", []):
        if (m.get("klucz") or "").lower() == maszyna:
            return (m.get("profil") or "stacja").lower()
    return "stacja"


def wzorce_profilu(maszyna=None, profile=None):
    """Wzorce `zostaja` dla profilu TEJ maszyny. `["*"]` = bez ograniczeń."""
    profile = wczytaj_profile() if profile is None else profile
    if not profile:
        return ["*"]
    nazwa = profil_maszyny(maszyna)
    if nazwa not in profile:
        print(f"⚠ {PROFILE_TOML.name}: nie ma definicji profilu „{nazwa}” — "
              f"nie stosuję żadnych ograniczeń (dopisz blok [profil.{nazwa}])")
        return ["*"]
    return profile[nazwa]


def pozycja_w_profilu(kanal, ident, wzorce):
    """Czy pozycja mieści się w profilu maszyny. Wzorce jak w powłoce (fnmatch),
    porównywane z napisem „kanal:identyfikator”. `"*"` przepuszcza wszystko."""
    if not wzorce or "*" in wzorce:
        return True
    tekst = f"{kanal}:{ident}"
    return any(fnmatch.fnmatch(tekst, w) for w in wzorce)


def czy_czlonek_lustra(maszyna, czlonkowie=None):
    """
    Czy dana maszyna (identyfikator jak w dzienniku/`klucz` z maszyny.toml) jest
    członkiem lustra. Maszyna NIEZNANA w maszyny.toml (np. świeżo postawiona,
    jeszcze bez wpisu) → domyślnie True: dzisiejsze zachowanie liczy do konsensusu
    KAŻDĄ maszynę z dziennikiem, więc brak wpisu nie może po cichu wyciszyć jej
    historii — bezpieczniejszy domyślny wybór niż ciche wykluczenie.
    """
    if czlonkowie is None:
        czlonkowie = wczytaj_czlonkow_lustra()
    return czlonkowie.get((maszyna or "").lower(), True)


# ---------------------------------------------------------------- zewnętrzne źródła apt [176]

def wczytaj_zrodla_apt():
    """
    Czyta lustra/zrodla-apt.toml → lista słowników [[zrodlo]] (patrz nagłówek pliku).
    Zastępniki {codename} i {wersja_systemu} podstawiane od razu.
    Brak pliku = pusta lista (nic nie blokuje).
    """
    if not ZRODLA_APT.exists():
        return []
    import tomllib
    try:
        dane = tomllib.loads(ZRODLA_APT.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"⚠ nie umiem odczytać {ZRODLA_APT.name}: {e} — źródła apt pomijam")
        return []
    podstawienia = {"{codename}": _codename_wydania(),
                    "{wersja_systemu}": _wersja_wydania()}
    wynik = []
    for z in dane.get("zrodlo", []):
        z = dict(z)
        for pole in ("url", "klucz_url", "linia_deb"):
            if isinstance(z.get(pole), str):
                for znacznik, wartosc in podstawienia.items():
                    z[pole] = z[pole].replace(znacznik, wartosc)
        z.setdefault("pakiety", [])
        z.setdefault("klucz_format", "ascii")
        z.setdefault("pakiet_zaklada_zrodlo", False)
        wynik.append(z)
    return wynik


def _pole_os_release(klucz):
    """Wartość pola z /etc/os-release; gdy brak pliku albo pola — pusty napis."""
    try:
        for linia in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if linia.startswith(klucz + "="):
                return linia.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _pole_upstream_lsb(klucz):
    """Wartość pola z /etc/upstream-release/lsb-release; gdy brak pliku albo pola — pusty napis.

    Plik zakładają dystrybucje POCHODNE (Linux Mint) i sam zapisuje w nim, na jakim
    wydaniu Ubuntu stoi: DISTRIB_ID=Ubuntu, DISTRIB_RELEASE=24.04, DISTRIB_CODENAME=noble.
    To deklaracja samego systemu, a nie nasza tabela przeliczeniowa — dlatego z niej
    korzystamy zamiast zaszywać mapę „nazwa wydania → numer"."""
    try:
        for linia in Path("/etc/upstream-release/lsb-release").read_text(encoding="utf-8").splitlines():
            if linia.startswith(klucz + "="):
                return linia.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _codename_wydania():
    """Nazwa wydania UBUNTU, na którym stoi ten system (np. noble); gdy brak — pusty napis.

    Na czystym Ubuntu to po prostu VERSION_CODENAME. Na dystrybucji pochodnej (serwer
    domowy: Linux Mint 22.3 „zena") VERSION_CODENAME to nazwa POCHODNEJ, której żadne
    zewnętrzne repozytorium nie zna — a /etc/os-release ma tam obok pole UBUNTU_CODENAME
    z nazwą bazy (`noble`). Bierzemy więc bazę, gdy system sam ją deklaruje
    (decyzja Architekta 2026-08-29, [258]/drobiazgi)."""
    return _pole_os_release("UBUNTU_CODENAME") or _pole_os_release("VERSION_CODENAME")


def _wersja_wydania():
    """Numer wydania UBUNTU, na którym stoi ten system (np. 24.04); gdy brak — pusty napis.

    Potrzebne, bo część producentów numeruje repozytoria WERSJĄ, nie nazwą wydania
    (OBS: `xUbuntu_24.04`), a część nazwą (`noble`). Jeden zastępnik nie wystarcza —
    stąd dwa, oba jako DANE w polach `url`/`klucz_url`/`linia_deb`.

    Na dystrybucji pochodnej VERSION_ID to numer POCHODNEJ (Mint: 22.3) — dla repozytorium
    zbudowanego dla Ubuntu dałoby nieistniejące `xUbuntu_22.3`. Rozpoznajemy taki system po
    tym, że deklaruje UBUNTU_CODENAME inny niż własny VERSION_CODENAME, i wtedy bierzemy
    numer bazy z /etc/upstream-release/lsb-release (Mint 22.3 → 24.04, zmierzone na serwerze
    2026-08-29). Gdy tego pliku nie ma, zostaje VERSION_ID — lepszy niż nic, ale wtedy adres
    źródła trzeba obejrzeć ręcznie."""
    ubuntu_cn = _pole_os_release("UBUNTU_CODENAME")
    wlasny_cn = _pole_os_release("VERSION_CODENAME")
    if ubuntu_cn and ubuntu_cn != wlasny_cn:
        z_bazy = _pole_upstream_lsb("DISTRIB_RELEASE")
        if z_bazy:
            return z_bazy
    return _pole_os_release("VERSION_ID")


def _tresc_zrodel_apt():
    """Sklejona treść wszystkich plików .list/.sources w /etc/apt/sources.list.d/
    (linie-komentarze pominięte). Po niej poznajemy, czy źródło już jest."""
    kawalki = []
    if SOURCES_D.is_dir():
        for plik in sorted(SOURCES_D.iterdir()):
            if plik.suffix not in (".list", ".sources"):
                continue
            try:
                for linia in plik.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not linia.lstrip().startswith("#"):
                        kawalki.append(linia)
            except OSError:
                continue
    return "\n".join(kawalki)


def zrodlo_obecne(zrodlo, tresc=None):
    """Źródło uznajemy za dodane, gdy jego `url` stoi w którymś pliku źródeł
    (bez końcowego ukośnika, żeby `…/ubuntu22/` i `…/ubuntu22` były tym samym)
    ORAZ plik `keyring` istnieje. Samo `url` bez klucza = apt i tak odrzuci repo."""
    tresc = _tresc_zrodel_apt() if tresc is None else tresc
    url = (zrodlo.get("url") or "").rstrip("/")
    jest_url = bool(url) and url in tresc
    jest_klucz = bool(zrodlo.get("keyring")) and Path(zrodlo["keyring"]).exists()
    return jest_url and jest_klucz


def zrodla_brakujace(zrodla=None):
    """Lista bloków z zrodla-apt.toml, których na tej maszynie nie ma."""
    zrodla = wczytaj_zrodla_apt() if zrodla is None else zrodla
    tresc = _tresc_zrodel_apt()
    return [z for z in zrodla if not zrodlo_obecne(z, tresc)]


def zrodla_nalezne_tej_maszynie(brak=None, maszyna=None, czlonkowie=None):
    """
    Które z BRAKUJĄCYCH źródeł apt (`zrodla_brakujace`) NALEŻĄ SIĘ tej maszynie.

    Sprawa [218b], decyzja usera 27.08: „serwer nie ma dostawać wszystkiego”.
    Źródła z `zrodla-apt.toml` są częścią wspólnego zestawu lustra, więc — jak
    pakiety z konsensusu — dostają je maszyny będące CZŁONKAMI lustra
    (`czlonek_lustra = true`, kontrakt [209] 2.1). Maszyna spoza lustra nie
    dostaje ich hurtem: to dokładnie reguła 4 z kontraktu [209] rozdz. 3
    („brak override + nie-członek = dowolny, nie sprawdzamy”), która do 27.08
    obowiązywała pakiety, ale nie źródła — stąd pierwszy bieg timera
    `lustro-sync-serwer` dołożył serwerowi repozytoria fortinet/vscode/wezterm,
    których nikt tam nie zamawiał.

    Furtka z kontraktu (reguła 2, dwukierunkowość): jeśli NIE-członek ma jawny
    `[[pozycja.override]] stan = "obecne"` na pakiet apt pochodzący z danego
    źródła, to źródło mu się należy — bez niego `apt` tego pakietu nie znajdzie,
    a override jest jawnym zamówieniem. (Druga warstwa tej samej furtki to
    `zapewnij_zrodlo_dla()`, wołane tuż przed każdą instalacją apt; ta funkcja
    jest po to, żeby `lustro status` mówił prawdę już PRZED instalacją.)

    Zwraca podlistę `brak` (kolejność zachowana). Dla członka lustra = całe `brak`,
    więc na dzisiejszych stacjach wynik jest identyczny jak przed zmianą.
    """
    brak = zrodla_brakujace() if brak is None else brak
    if not brak:
        return []
    maszyna = nazwa_maszyny() if maszyna is None else maszyna
    if czy_czlonek_lustra(maszyna, czlonkowie):
        return list(brak)

    # nie-członek: tylko źródła pakietów z jawnym `override obecne` dla tej maszyny
    zamowione = set()
    for (kanal, ident), st in wczytaj_statusy_pozycji().items():
        if kanal != "apt" or st.get("status") == "testowe":
            continue
        ovr = (st.get("override") or {}).get(maszyna)
        if ovr and ovr.get("stan") == "obecne":
            zamowione.add(ident)
    if not zamowione:
        return []
    return [z for z in brak if zamowione.intersection(z.get("pakiety") or [])]


def zrodlo_dla_pakietu(pakiet, zrodla=None):
    """Blok źródła, w którego polu `pakiety` stoi ten pakiet; None gdy żaden."""
    zrodla = wczytaj_zrodla_apt() if zrodla is None else zrodla
    for z in zrodla:
        if pakiet in z.get("pakiety", []):
            return z
    return None


def dodaj_zrodlo_apt(zrodlo):
    """
    Dodaje zewnętrzne źródło apt: klucz + plik listy.

    Sposób od 26.08 (Faza 3 automatu, sprawa dociągania [194]): pliki NIE lecą
    rootem przez `sudo sh skrypt.sh` (jak do 25.08) — zmierzone na Katanie, że
    NOPASSWD z [194] obejmuje TYLKO literalnie `apt-get, apt, dpkg, snap, flatpak`
    (`/etc/sudoers.d/90-lustro-pakiety`); `sudo sh …`, `sudo install …`, `sudo tee …`
    nie pasują do żadnej z tych pozycji i sudo i tak pyta o hasło (`sudo -n sh -c
    'echo x'` → „a password is required”, sprawdzone empirycznie). Zamiast tego
    budujemy MINIMALNY pakiet .deb (`dpkg-deb --root-owner-group`, bez roota —
    ta flaga wymusza właściciela root:root w archiwum BEZ potrzeby fakeroot,
    dpkg ≥ 1.19, jest na Ubuntu 24.04) zawierający klucz i plik listy, i kładziemy
    go poleceniem `dpkg -i` — `dpkg` JEST na liście NOPASSWD. Efekt identyczny jak
    poprzednio (klucz w /usr/share/keyrings, linia `deb` w sources.list.d), ale
    w całości mieszczący się w uprawnieniach [194] — działa też w pełni automatycznie
    (`lustro sync --auto`, timer), bez okienka i bez hasła. Ten sam kod obsługuje
    też wywołanie ręczne (`lustro dodaj`) — jeden mechanizm, nie dwa.

    Ślad w systemie: pakiet `lustro-zrodlo-<nazwa>` widoczny w `dpkg -l` (czytelniejsze
    niż niewidoczny ręczny zapis) — wzorzec `lustro-zrodlo-*` wykluczony w
    wykluczenia/apt.txt, żeby `lustro status` nie zgłaszał go jako obcej instalacji.

    Zwraca True, gdy po wszystkim `zrodlo_obecne` potwierdza obecność.
    Idempotentne — ponowne uruchomienie tylko nadpisze te same pliki (ta sama
    wersja pakietu, `dpkg -i` reinstaluje bez pytań).
    """
    import tempfile
    import urllib.error
    import urllib.request

    nazwa = zrodlo.get("nazwa", "?")
    for pole in ("klucz_url", "keyring", "plik_listy", "linia_deb"):
        if not zrodlo.get(pole):
            print(f"    ⚠ źródło „{nazwa}”: brak pola `{pole}` w {ZRODLA_APT.name} — nie dodaję")
            return False

    katalog_tmp = Path(tempfile.mkdtemp(prefix="lustro-zrodlo-"))
    try:
        surowy = katalog_tmp / "klucz.pobrany"
        print(f"    → pobieram klucz: {zrodlo['klucz_url']}")
        try:
            with urllib.request.urlopen(zrodlo["klucz_url"], timeout=30) as odp:
                surowy.write_bytes(odp.read())
        except (urllib.error.URLError, OSError) as e:
            print(f"    ⚠ nie udało się pobrać klucza: {e}")
            return False
        if surowy.stat().st_size == 0:
            print("    ⚠ pobrany klucz jest pusty — nie dodaję")
            return False

        if zrodlo.get("klucz_format") == "binarny":
            klucz_bajty = surowy.read_bytes()
        else:
            if not czy_jest("gpg"):
                print("    ⚠ brak programu gpg (potrzebny do `--dearmor`) — nie dodaję")
                return False
            gotowy = katalog_tmp / "klucz.gpg"
            kod, _ = uruchom(["gpg", "--batch", "--yes", "--dearmor", "-o", str(gotowy),
                              str(surowy)])
            if kod != 0 or not gotowy.exists():
                print(f"    ⚠ `gpg --dearmor` nie powiodło się (kod {kod}) — nie dodaję")
                return False
            klucz_bajty = gotowy.read_bytes()

        if not czy_jest("dpkg-deb"):
            print("    ⚠ brak programu dpkg-deb — nie umiem zbudować pakietu źródła")
            return False

        pakiet_id = f"lustro-zrodlo-{nazwa}"
        korzen = katalog_tmp / "pakiet"
        (korzen / "DEBIAN").mkdir(parents=True)

        cel_keyring = korzen / Path(zrodlo["keyring"]).relative_to("/")
        cel_keyring.parent.mkdir(parents=True, exist_ok=True)
        cel_keyring.write_bytes(klucz_bajty)
        cel_keyring.chmod(0o644)

        cel_lista = korzen / Path(zrodlo["plik_listy"]).relative_to("/")
        cel_lista.parent.mkdir(parents=True, exist_ok=True)
        cel_lista.write_text(zrodlo["linia_deb"] + "\n", encoding="utf-8")
        cel_lista.chmod(0o644)

        (korzen / "DEBIAN" / "control").write_text(
            f"Package: {pakiet_id}\n"
            "Version: 1\n"
            "Section: misc\n"
            "Priority: optional\n"
            "Architecture: all\n"
            "Maintainer: lustro (mechanizm luster) <mk@localhost>\n"
            f"Description: Zrodlo apt „{nazwa}” dodane przez mechanizm luster\n"
            f" Klucz i wpis .list z lustra/{ZRODLA_APT.name}. Zarzadzany przez apke\n"
            " `lustro`, nie ruszac recznie.\n",
            encoding="utf-8")

        deb = katalog_tmp / f"{pakiet_id}.deb"
        kod, out = uruchom(["dpkg-deb", "--root-owner-group", "--build",
                            str(korzen), str(deb)])
        if kod != 0 or not deb.exists():
            print(f"    ⚠ budowa pakietu .deb nie powiodła się (kod {kod}): {out.strip()}")
            return False

        print(f"    → instaluję jako pakiet {pakiet_id} (dpkg -i — w zakresie NOPASSWD [194])")
        kod = uruchom_widoczne(jako_root(["dpkg", "-i", str(deb)]))
        if kod != 0:
            print(f"    ⚠ `dpkg -i` zakończone kodem {kod}")

        print("    → apt-get update")
        kod = uruchom_widoczne(jako_root(["apt-get", "update"]))
        if kod != 0:
            print(f"    ⚠ `apt-get update` zakończone kodem {kod}")
    finally:
        shutil.rmtree(katalog_tmp, ignore_errors=True)

    if zrodlo_obecne(zrodlo):
        print(f"    ✓ źródło „{nazwa}” jest na maszynie")
        return True
    print(f"    ⚠ po wykonaniu nadal nie widzę źródła „{nazwa}”")
    return False


def _pliki_zrodel_z_url(url):
    """Ścieżki plików .list/.sources w /etc/apt/sources.list.d/, w których stoi ten
    adres (linie-komentarze pominięte). Odpowiada na pytanie „ile razy apt ma to
    repozytorium skonfigurowane"."""
    czysty = (url or "").rstrip("/")
    znalezione = []
    if not czysty or not SOURCES_D.is_dir():
        return znalezione
    for plik in sorted(SOURCES_D.iterdir()):
        if plik.suffix not in (".list", ".sources"):
            continue
        try:
            tresc = "\n".join(l for l in plik.read_text(encoding="utf-8",
                                                        errors="replace").splitlines()
                              if not l.lstrip().startswith("#"))
        except OSError:
            continue
        if czysty in tresc:
            znalezione.append(plik)
    return znalezione


def _wlasciciel_dpkg(sciezka):
    """Nazwa pakietu dpkg, do którego należy plik; "" gdy do żadnego."""
    kod, out = uruchom(["dpkg-query", "-S", str(sciezka)])
    if kod != 0 or ":" not in out:
        return ""
    return out.split(":", 1)[0].strip()


def posprzataj_zdublowane_zrodla(tylko_pokaz=False):
    """[257c], 29.08 — usuwa PODWÓJNY wpis tego samego repozytorium apt.

    Problem (zmierzony na HP 29.08): apka dodaje `/etc/apt/sources.list.d/
    google-chrome.list` PRZED pierwszą instalacją Chrome (bez tego `apt install
    google-chrome-stable` nic nie znajdzie). Instalator Chrome zakłada zaraz potem
    SWÓJ `google-chrome.sources` z tym samym adresem — i apt przy każdym `update`
    ostrzega „Target Packages … is configured multiple times". Na Vostro i Katanie
    problemu nie ma tylko dlatego, że tam Chrome był PRZED apką.

    Dlaczego naprawa jest tutaj, a nie „nie zakładaj .list, gdy istnieje .sources"
    (to apka już sprawdza, `zrodlo_obecne`): w chwili zakładania `.list` pliku
    `.sources` jeszcze NIE MA — powstaje dopiero przy instalacji pakietu. Sprawdzenie
    „przed" nie ma czego znaleźć. Duplikat da się usunąć wyłącznie PO instalacji.

    Dlaczego zdejmujemy sam plik listy, a nie cały mikro-pakiet `lustro-zrodlo-*`:
    ten pakiet niesie TEŻ keyring, a na HP `/usr/share/keyrings/google-chrome.gpg`
    należy właśnie do niego (`dpkg -S`, 29.08). `apt remove` zabrałby klucz i repo
    Chrome przestałoby działać do najbliższego biegu codziennego skryptu Google.
    Zamiast tego przebudowujemy mikro-pakiet w NOWEJ wersji, już bez pliku listy,
    i kładziemy `dpkg -i` — dpkg przy podniesieniu wersji usuwa pliki, których
    w nowej wersji nie ma, a keyring zostawia. `dpkg` mieści się w NOPASSWD [194],
    więc sprzątanie działa też z timera, bez hasła i bez okienka.

    Warunki bezpieczeństwa (wszystkie muszą być spełnione, inaczej nic nie ruszamy):
      • blok ma `pakiet_zaklada_zrodlo = true` (DANA w zrodla-apt.toml),
      • nasz `plik_listy` istnieje I należy do pakietu `lustro-zrodlo-<nazwa>`,
      • ten sam adres stoi w CO NAJMNIEJ jednym INNYM pliku źródeł (czyli po
        zdjęciu naszego repozytorium nie zniknie).

    Zwraca listę nazw posprzątanych źródeł.
    """
    import tempfile

    posprzatane = []
    for z in wczytaj_zrodla_apt():
        if not z.get("pakiet_zaklada_zrodlo"):
            continue
        nazwa = z.get("nazwa", "?")
        sciezka_listy = z.get("plik_listy") or ""
        if not sciezka_listy:
            continue
        nasz = Path(sciezka_listy)
        if not nasz.exists():
            continue
        inne = [p for p in _pliki_zrodel_z_url(z.get("url")) if p != nasz]
        if not inne:
            continue        # jesteśmy jedynym wpisem — bez nas apt nie ma tego repo

        pakiet_id = f"lustro-zrodlo-{nazwa}"
        wlasciciel = _wlasciciel_dpkg(nasz)
        if wlasciciel != pakiet_id:
            print(f"⚠ źródło „{nazwa}”: {nasz} jest zdublowane z "
                  f"{', '.join(str(i) for i in inne)}, ale nie należy do {pakiet_id} "
                  f"(właściciel: {wlasciciel or 'brak'}) — NIE ruszam, zdejmij ręcznie")
            continue

        print(f"ŹRÓDŁO ZDUBLOWANE: „{nazwa}” stoi w {nasz.name} (nasz) "
              f"i w {', '.join(i.name for i in inne)} (pakietu) [257c]")
        if tylko_pokaz:
            print("    apt ostrzega „configured multiple times”; `lustro sync` "
                  "zdejmie nasz wpis sam")
            print()
            continue

        keyring = Path(z.get("keyring") or "")
        if not keyring.is_file():
            print(f"    ⚠ nie widzę keyringu {keyring} — nie przebudowuję pakietu")
            continue
        _, obecna = uruchom(["dpkg-query", "-W", "-f=${Version}", pakiet_id])
        try:
            wersja = str(int((obecna or "1").strip().split(".")[0]) + 1)
        except ValueError:
            wersja = "2"

        katalog_tmp = Path(tempfile.mkdtemp(prefix="lustro-zrodlo-przytnij-"))
        try:
            korzen = katalog_tmp / "pakiet"
            (korzen / "DEBIAN").mkdir(parents=True)
            cel = korzen / keyring.relative_to("/")
            cel.parent.mkdir(parents=True, exist_ok=True)
            cel.write_bytes(keyring.read_bytes())
            cel.chmod(0o644)
            (korzen / "DEBIAN" / "control").write_text(
                f"Package: {pakiet_id}\n"
                f"Version: {wersja}\n"
                "Section: misc\n"
                "Priority: optional\n"
                "Architecture: all\n"
                "Maintainer: lustro (mechanizm luster) <mk@localhost>\n"
                f"Description: Klucz zrodla apt „{nazwa}” (bez wpisu .list)\n"
                " Sam keyring. Wpis w sources.list.d utrzymuje juz pakiet\n"
                " producenta — nasz plik listy zdjety, zeby apt nie mial tego\n"
                " repozytorium skonfigurowanego dwa razy [257c].\n",
                encoding="utf-8")
            deb = katalog_tmp / f"{pakiet_id}.deb"
            kod, out = uruchom(["dpkg-deb", "--root-owner-group", "--build",
                                str(korzen), str(deb)])
            if kod != 0 or not deb.exists():
                print(f"    ⚠ budowa pakietu nie powiodła się (kod {kod}): {out.strip()}")
                continue
            print(f"    → {pakiet_id} w wersji {wersja} (sam klucz, bez {nasz.name})")
            kod = uruchom_widoczne(jako_root(["dpkg", "-i", str(deb)]))
            if kod != 0:
                print(f"    ⚠ `dpkg -i` zakończone kodem {kod}")
                continue
        finally:
            shutil.rmtree(katalog_tmp, ignore_errors=True)

        if nasz.exists():
            print(f"    ⚠ {nasz} nadal istnieje — nie udało się zdjąć")
            continue
        print(f"    ✓ zdublowanie źródła „{nazwa}” usunięte (klucz {keyring.name} został)")
        uruchom_widoczne(jako_root(["apt-get", "update"]))
        posprzatane.append(nazwa)
    return posprzatane


def zapewnij_zrodlo_dla(pakiet, args):
    """
    Wołane z `dodaj` PRZED wykrywaniem kanału. Jeśli pakiet ma przypisane źródło
    w zrodla-apt.toml, a źródła nie ma — mówi to jasno, pyta i dodaje.
    Zwraca False tylko, gdy źródło było potrzebne i NIE udało się go dodać
    (albo user odmówił); w każdym innym przypadku True.
    """
    z = zrodlo_dla_pakietu(pakiet)
    if z is None or zrodlo_obecne(z):
        return True
    print(f"„{pakiet}” pochodzi z zewnętrznego repozytorium „{z.get('nazwa')}” "
          f"({z.get('url')}),")
    print(f"którego NIE MA jeszcze na tej maszynie (wpis w lustra/{ZRODLA_APT.name}).")
    if z.get("uwagi"):
        print(f"    uwagi: {z['uwagi']}")
    print("Bez tego źródła apt nie znajdzie pakietu.")
    if not getattr(args, "zatwierdzam_wszystko", False):
        if pytaj("Dodać źródło (klucz + lista + apt-get update)?", "Tn", "t") != "t":
            print("Nic nie zmieniam. Źródło można dodać ręcznie wg zrodla-apt.toml.")
            return False
    return dodaj_zrodlo_apt(z)


# ---------------------------------------------------------------- hook dpkg — dziennik przy KAŻDEJ zmianie [213]

def _wczytaj_stan_hak_apt():
    """Migawka poprzedniego `inwentarz_apt()`. `None` = hook jeszcze nigdy nie
    zapisał migawki (pierwsze uruchomienie po instalacji pakietu `lustro-hak-apt`,
    albo plik skasowany) — w tym wypadku hook SEEDUJE bez logowania (patrz
    `polecenie_hak_apt`), żeby nie zalać dziennika „nowościami”, które są w
    rzeczywistości starymi, dawno zainstalowanymi pakietami."""
    if not HAK_APT_STAN.exists():
        return None
    try:
        return json.loads(HAK_APT_STAN.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _zapisz_stan_hak_apt(inwentarz):
    try:
        HAK_APT_STAN.parent.mkdir(parents=True, exist_ok=True)
        HAK_APT_STAN.write_text(json.dumps(inwentarz, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def polecenie_hak_apt(args):
    """
    Wołane z hooka dpkg (`/etc/apt/apt.conf.d/90lustro-hak-apt`, `DPkg::Post-Invoke`,
    pakiet `lustro-hak-apt` — sprawa [213]) PO KAŻDEJ transakcji apt-get/apt/aptitude,
    niezależnie od tego, kto ją zaczął (terminal usera, sklep GNOME, inny skrypt) —
    to jest właśnie rozszerzenie „dziennik aktualizuje się przy każdej zmianie",
    nie tylko przez `lustro dodaj`.

    ZASADA: LEKKO i ODPORNIE. Żaden wyjątek stąd nie może wyjść na zewnątrz — apt/
    dpkg NIE MOGĄ się wywalić z naszego powodu (stąd `except Exception: pass` na
    końcu, a w pliku apt.conf.d dodatkowo `timeout` + `|| true` na wszelki wypadek
    po stronie powłoki). Zero sieci, zero gita — tylko lokalny dopisek do pliku;
    commit+push zrobi najbliższy bieg `lustro sync --auto` z timera (od [283]
    commituje wyłącznie pliki apki — `sciezki_apki()` — a nie całe drzewo).

    Porównuje BIEŻĄCY `inwentarz_apt()` (dokładnie ten sam kod co reszta mechanizmu
    — te same wykluczenia/apt.txt) z zapisaną MIGAWKĄ poprzedniego stanu:
      • nowa pozycja  → „dodano”   (zrodlo: wykryte)
      • zniknięta     → „usunieto” (zrodlo: wykryte)

    Kierunek „usunieto” TUTAJ jest bezpieczny (w odróżnieniu od okresowego
    `sync`/`sync --auto` — patrz decyzja [213] pkt 3 w dokumentacji): to nie jest
    zgadywanie z różnicy inwentarza po czasie, tylko zapis PRAWDZIWEJ, właśnie
    zakończonej transakcji apt — dokładnie ta sama pewność co przy ręcznym
    `lustro usun`. Zmienia to globalny konsensus lustra tak samo, jak zmieniłoby
    go ręczne `lustro usun` — to znany i zaakceptowany skutek uboczny mechanizmu
    „nowsze zdarzenie wygrywa" (spec 4.5), nie nowe ryzyko.

    Gdy `HAK_APT_MARKER` jest podniesiony — apka SAMA (`lustro dodaj`/`usun`/`sync`)
    właśnie wykonuje tę transakcję i zaraz zapisze zdarzenie sama (zrodlo: apka/
    sync) — migawka jest odświeżana, ale NIC nie jest logowane (unikamy podwójnego
    wpisu; test (c) w sprawie [213]).
    """
    try:
        biezacy = inwentarz_apt()

        if HAK_APT_MARKER.exists():
            _zapisz_stan_hak_apt(biezacy)
            return 0

        poprzedni = _wczytaj_stan_hak_apt()
        if poprzedni is None:
            _zapisz_stan_hak_apt(biezacy)
            return 0

        for pkg in sorted(set(biezacy) - set(poprzedni)):
            dopisz_zdarzenie("dodano", kanal="apt", ident=pkg, wersja=biezacy[pkg],
                             zrodlo="wykryte",
                             notatka="wykryte automatycznie hookiem dpkg — "
                                     "zainstalowane poza `lustro dodaj` [213]")
        for pkg in sorted(set(poprzedni) - set(biezacy)):
            dopisz_zdarzenie("usunieto", kanal="apt", ident=pkg, zrodlo="wykryte",
                             notatka="wykryte automatycznie hookiem dpkg — "
                                     "usunięte poza `lustro usun` [213]")
        _zapisz_stan_hak_apt(biezacy)
    except Exception:
        pass
    return 0


def polecenie_hak_apt_instaluj(args):
    """
    `lustro hak-apt --zainstaluj` — buduje i kładzie na TEJ maszynie mikro-pakiet
    `.deb` z hookiem dpkg (sprawa [213]). Ten sam wzorzec co `dodaj_zrodlo_apt()`
    (25/26.08, [176]/[194]): `dpkg-deb --root-owner-group` bez roota, `dpkg -i`
    pod `jako_root` — `dpkg` JEST na liście NOPASSWD [194], `sudo install`/`tee`
    NIE są. Jeden mechanizm, ten sam trik, druga sprawa.

    Zawartość pakietu:
      • /etc/apt/apt.conf.d/90lustro-hak-apt   — DPkg::Post-Invoke
      • /usr/local/lib/lustro/hak-apt-hook.sh  — woła `lustro hak-apt` jako user
        (nie root — dziennik i repozytorium chezmoi są WŁASNOŚCIĄ usera, hook
        NIGDY nie ma pisać do nich jako root)

    Idempotentne: ponowne uruchomienie nadpisuje te same pliki (ta sama wersja
    pakietu, `dpkg -i` reinstaluje bez pytań).
    """
    import tempfile

    if not czy_jest("dpkg-deb"):
        print("⚠ brak programu dpkg-deb — nie umiem zbudować pakietu hooka")
        return 1

    user = getpass.getuser()
    lustro_bin = str(DOM / ".local/bin/lustro")

    skrypt = f"""#!/bin/sh
# Hook dpkg (DPkg::Post-Invoke) — mechanizm luster [213], obszar 5_Wspolna_konfiguracja.
# Wolany przez apt/apt-get/aptitude PO KAZDEJ transakcji dpkg (instalacja, usuniecie,
# aktualizacja) — niezaleznie od tego, kto ja zaczal. Musi byc szybki i nigdy nie
# zepsuc/nie zawiesic apt (timeout + `|| true` sa w apt.conf.d, na zewnatrz tego pliku).
# Uruchamia `lustro` jako zwykly user ({user}), NIE jako root — dziennik i
# repozytorium chezmoi naleza do usera, hook nie ma prawa zapisywac tam jako root.
LUSTRO="{lustro_bin}"
[ -x "$LUSTRO" ] || exit 0
runuser -u {user} -- "$LUSTRO" hak-apt >/dev/null 2>&1
exit 0
"""

    apt_conf = (
        "// Hook mechanizmu luster [213] — dopisuje zdarzenia apt do dziennika `lustro`\n"
        "// (zrodlo: wykryte) przy KAZDEJ zmianie, niezaleznie od tego, kto ja zaczal\n"
        "// (terminal usera, sklep, skrypt) — nie tylko przez `lustro dodaj`/`usun`.\n"
        "// Zarzadzany przez pakiet lustro-hak-apt, NIE edytowac recznie.\n"
        "// timeout+|| true: apt/dpkg NIGDY nie moga zawiesic sie ani zawiesc z\n"
        "// naszego powodu, nawet gdyby hak-apt-hook.sh kiedys zaczal dzialac zle.\n"
        'DPkg::Post-Invoke {"timeout 10 /usr/local/lib/lustro/hak-apt-hook.sh '
        '>/dev/null 2>&1 || true";};\n'
    )

    katalog_tmp = Path(tempfile.mkdtemp(prefix="lustro-hak-apt-"))
    try:
        korzen = katalog_tmp / "pakiet"
        (korzen / "DEBIAN").mkdir(parents=True)

        cel_skrypt = korzen / "usr/local/lib/lustro/hak-apt-hook.sh"
        cel_skrypt.parent.mkdir(parents=True, exist_ok=True)
        cel_skrypt.write_text(skrypt, encoding="utf-8")
        cel_skrypt.chmod(0o755)

        cel_conf = korzen / "etc/apt/apt.conf.d/90lustro-hak-apt"
        cel_conf.parent.mkdir(parents=True, exist_ok=True)
        cel_conf.write_text(apt_conf, encoding="utf-8")
        cel_conf.chmod(0o644)

        (korzen / "DEBIAN" / "control").write_text(
            "Package: lustro-hak-apt\n"
            "Version: 1\n"
            "Section: misc\n"
            "Priority: optional\n"
            "Architecture: all\n"
            "Maintainer: lustro (mechanizm luster) <mk@localhost>\n"
            "Description: Hook dpkg mechanizmu luster — dziennik przy KAZDEJ zmianie apt\n"
            " Dopisuje do dziennika lustra (zrodlo: wykryte) pakiety zainstalowane\n"
            " lub usuniete golym apt-get/apt/aptitude, niezaleznie od `lustro dodaj`/\n"
            " `usun` [213]. Zarzadzany przez apke `lustro`, nie ruszac recznie.\n",
            encoding="utf-8")

        deb = katalog_tmp / "lustro-hak-apt.deb"
        kod, out = uruchom(["dpkg-deb", "--root-owner-group", "--build",
                            str(korzen), str(deb)])
        if kod != 0 or not deb.exists():
            print(f"⚠ budowa pakietu .deb nie powiodła się (kod {kod}): {out.strip()}")
            return 1

        print("→ instaluję jako pakiet lustro-hak-apt (dpkg -i — w zakresie NOPASSWD [194])")
        kod = uruchom_widoczne(jako_root(["dpkg", "-i", str(deb)]))
        if kod != 0:
            print(f"⚠ `dpkg -i` zakończone kodem {kod}")
            return 1
    finally:
        shutil.rmtree(katalog_tmp, ignore_errors=True)

    print("✓ hook dpkg zainstalowany. Pierwsza transakcja apt tylko SEEDUJE migawkę")
    print("  (bez logowania) — patrz `polecenie_hak_apt`. Od drugiej transakcji hook")
    print("  dopisuje zdarzenia do dziennika automatycznie.")
    return 0


# ---------------------------------------------------------------- pulpit (dconf)

def _dconf_dump(sciezka):
    """
    Zwraca {pelny_klucz: wartosc} dla jednej ścieżki dconf.
    `dconf dump` wypisuje TYLKO to, co user zmienił wobec ustawień fabrycznych.
    Nieudany odczyt jest ZAPAMIĘTYWANY (_BLEDY_DCONF) — bez tego pusty wynik
    udawałby „user niczego tu nie ustawił" i produkował fałszywe rozbieżności.
    """
    if not czy_jest("dconf"):
        _BLEDY_DCONF.append("brak programu `dconf` — warstwa pulpitu nieczytelna")
        return {}
    kod, out = uruchom(["dconf", "dump", sciezka])
    if kod != 0:
        _BLEDY_DCONF.append(f"`dconf dump {sciezka}` zakończone błędem (kod {kod})")
        return {}
    wynik, sekcja = {}, "/"
    for linia in out.splitlines():
        linia = linia.rstrip()
        if not linia or linia.startswith("#"):
            continue
        if linia.startswith("[") and linia.endswith("]"):
            sekcja = linia[1:-1]
            continue
        if "=" not in linia:
            continue
        k, v = linia.split("=", 1)
        podkatalog = "" if sekcja == "/" else sekcja.strip("/") + "/"
        wynik[sciezka + podkatalog + k.strip()] = v.strip()
    return wynik


def klucze_rozszerzen():
    """
    ⚠️ NAPRAWA FAŁSZYWEGO ALARMU (2026-08-23, etap E2).

    Rozszerzenia GNOME potrafią WŁAŚCICIELSKO nadpisywać cudze klucze dconf:
    przy włączeniu zapisują swoją wartość, przy wyłączeniu ją KASUJĄ (`reset`).
    Wyłączenie zdarza się samo — przy restarcie GNOME Shell, wylogowaniu i na
    ekranie blokady (rozszerzenie bez trybu `unlock-dialog` jest wtedy wyłączane).
    W takiej chwili klucz znika z `dconf dump`, a lustro widzi „tutaj: brak,
    w lustrze: wartość" — mimo że user niczego nie ruszał.

    Tak było na Vostro 23.08 o 16:40 z trzema kluczami Ubuntu Tiling Assistant
    (`edge-tiling`, `toggle-tiled-left`, `toggle-tiled-right`).

    Rozwiązanie OGÓLNE, nie pod te trzy klucze: takie klucze NIE NALEŻĄ DO USERA,
    tylko do rozszerzenia — więc nie wchodzą do lustra wcale. Rozszerzenia
    zapisują listę przejętych kluczy w swoim własnym kluczu `overridden-settings`
    (wzorzec `SettingsOverrider`, szeroko kopiowany między rozszerzeniami).
    Czytamy WSZYSTKIE takie klucze spod /org/gnome/shell/extensions/.

    Ponieważ znacznik `overridden-settings` znika razem z rozszerzeniem, raz
    wykryte klucze DOPISUJEMY do pliku pulpit/dconf-rozszerzenia.txt i bierzemy
    z niego również wtedy, gdy rozszerzenie akurat jest wyłączone.

    Skutek dla nowej maszyny: lustro nie wozi wartości `edge-tiling=false`, ale
    wozi listę włączonych rozszerzeń — a rozszerzenie ustawi sobie te klucze samo.
    """
    znalezione = set()

    dump = _dconf_dump("/org/gnome/shell/extensions/")
    for klucz, wartosc in dump.items():
        if not klucz.endswith("/overridden-settings"):
            continue
        # wartość to słownik GVariant: {'org.gnome.mutter.edge-tiling': <@mb nothing>, …}
        for nazwa in re.findall(r"'([A-Za-z0-9][A-Za-z0-9._-]*)'\s*:", wartosc):
            if "." not in nazwa:
                continue
            schemat, _, ostatni = nazwa.rpartition(".")
            znalezione.add("/" + schemat.replace(".", "/") + "/" + ostatni)

    zapamietane = set(wczytaj_wzorce(PLIK_ROZSZERZEN))
    nowe = znalezione - zapamietane
    if nowe:
        if not PLIK_ROZSZERZEN.exists():
            PLIK_ROZSZERZEN.write_text(
                "# Klucze dconf PRZEJĘTE PRZEZ ROZSZERZENIA GNOME — plik GENEROWANY.\n"
                "# Nie należą do usera: rozszerzenie zapisuje je przy włączeniu i KASUJE\n"
                "# przy wyłączeniu (restart powłoki, wylogowanie, ekran blokady).\n"
                "# Dlatego są POZA lustrem — inaczej `lustro status` zgłaszałby rozbieżność\n"
                "# za każdym razem, gdy rozszerzenie akurat jest wyłączone.\n"
                "# Źródło: klucze `overridden-settings` rozszerzeń (/org/gnome/shell/extensions/).\n"
                "# Lista tylko rośnie — raz wykryty klucz zostaje, bo znacznik znika razem\n"
                "# z wyłączonym rozszerzeniem.\n", encoding="utf-8")
        with PLIK_ROZSZERZEN.open("a", encoding="utf-8") as f:
            for k in sorted(nowe):
                f.write(k + "\n")
        zapamietane |= nowe

    return znalezione | zapamietane


def rozszerzenia_chwilowo_nieaktywne():
    """
    ⚠️ DRUGI BEZPIECZNIK przeciw fałszywemu alarmowi pulpitu (2026-08-23, E2).

    GNOME potrafi mieć rozszerzenie WŁĄCZONE (`Enabled: Yes`), a jednocześnie
    chwilowo NIEURUCHOMIONE (`State: INACTIVE`) — dzieje się tak na ekranie blokady,
    przy restarcie powłoki i chwilę po zalogowaniu. Rozszerzenie, wyłączając się,
    sprząta po sobie: kasuje klucze dconf, które przejęło. W tym oknie czasowym
    obraz pulpitu w dconf jest NIEPEŁNY i każde porównanie z lustrem kłamie.

    Sprawdzone na Vostro 23.08 o 17:45: `gnome-extensions info tiling-assistant@ubuntu.com`
    → `Enabled: Yes`, `State: INACTIVE`, a trzy klucze mutter zniknęły z dconf.
    To jest ten sam stan, w którym o 16:40 zapaliła się fałszywa rozbieżność.

    Reguła ogólna: dopóki jakiekolwiek włączone rozszerzenie nie wstało,
    warstwy pulpitu NIE PORÓWNUJEMY — mówimy userowi, dlaczego, i każemy powtórzyć.
    Dotyczy to również rozszerzeń, które nie prowadzą znacznika `overridden-settings`.
    """
    if not czy_jest("gnome-extensions"):
        return []
    kod, out = uruchom(["gnome-extensions", "list", "--enabled"])
    if kod != 0:
        return []
    nieaktywne = []
    for uuid in out.split():
        kod, info = uruchom(["gnome-extensions", "info", uuid])
        if kod != 0:
            continue
        stan = re.search(r"State:\s*(\S+)", info)
        wlaczone = re.search(r"Enabled:\s*(\S+)", info)
        if stan and wlaczone and wlaczone.group(1) == "Yes" \
                and stan.group(1) == "INACTIVE":
            nieaktywne.append(uuid)
    return nieaktywne


def powody_niepewnosci():
    """Zbiera wszystkie powody, dla których warstwy pulpitu nie wolno teraz porównywać."""
    powody = sorted(set(_BLEDY_DCONF))
    spiace = rozszerzenia_chwilowo_nieaktywne()
    if spiace:
        powody.append(
            "rozszerzenia GNOME są włączone, ale chwilowo nieuruchomione "
            "(State: INACTIVE) — w tym stanie kasują klucze, które przejęły; "
            "zwykle znaczy to zgaszony/zablokowany ekran albo świeży restart powłoki.\n"
            "      dotyczy: " + ", ".join(spiace))
    return powody


def wczytaj_rozszerzenia_gnome():
    """
    Czyta pulpit/rozszerzenia-gnome.txt: {uuid: {"zrodlo": ..., "komentarz": ...}}.
    Format jednej linii: `<uuid> <zrodlo> [# komentarz]`. Linie-komentarze i puste — pominięte.
    Nieznana/pusta wartość zrodlo -> "?", żeby wołający wyraźnie zobaczył błąd danych,
    a nie potraktował to po cichu jako "ego" (co skłoniłoby apkę do instalacji).
    """
    wynik = {}
    if not PLIK_ROZSZERZEN_GNOME.exists():
        return wynik
    for linia in PLIK_ROZSZERZEN_GNOME.read_text(encoding="utf-8").splitlines():
        goly, _, komentarz = linia.partition("#")
        goly = goly.strip()
        if not goly:
            continue
        pola = goly.split()
        uuid = pola[0]
        zrodlo = pola[1] if len(pola) > 1 else "?"
        wynik[uuid] = {"zrodlo": zrodlo, "komentarz": komentarz.strip()}
    return wynik


KATALOGI_ROZSZERZEN = (DOM / ".local/share/gnome-shell/extensions",
                       Path("/usr/share/gnome-shell/extensions"))


def _rozszerzenia_z_katalogu(kat):
    """{uuid: wersja} z jednego katalogu rozszerzeń (katalog z metadata.json = rozszerzenie)."""
    wynik = {}
    if not kat.is_dir():
        return wynik
    for p in sorted(kat.iterdir()):
        meta = p / "metadata.json"
        if not meta.is_file():
            continue
        uuid, wersja = p.name, "?"
        try:
            dane = json.loads(meta.read_text(encoding="utf-8"))
            uuid = dane.get("uuid") or p.name
            wersja = str(dane.get("version", "?"))
        except (json.JSONDecodeError, OSError):
            pass
        wynik[uuid] = wersja
    return wynik


def rozszerzenia_na_dysku(tylko_uzytkownika=False):
    """
    ⚠️ NAPRAWA braku 14 z Katany (25.08): inwentaryzacja rozszerzeń GNOME Z DYSKU,
    nie z żywej powłoki. `gnome-extensions list` NIE WIDZI świeżo zainstalowanych
    rozszerzeń aż do przelogowania (na Katanie: 3 zainstalowane, apka widziała 0,
    zdarzenia nie trafiły do dziennika, `status` fałszywie meldował brak).
    Dysk widzi zawsze. Żywa powłoka zostaje źródłem stanu „uruchomione"
    (rozszerzenia_chwilowo_nieaktywne) — nie „zainstalowane".

    Zwraca {uuid: wersja}. `tylko_uzytkownika=True` = tylko ~/.local/share/…
    (rozszerzenia systemowe w /usr/share należą do pakietów apt, nie do usera —
    do porównania z dziennikiem liczą się tylko instalacje usera).
    """
    katalogi = KATALOGI_ROZSZERZEN[:1] if tylko_uzytkownika else KATALOGI_ROZSZERZEN
    wynik = {}
    for kat in katalogi:
        for uuid, wersja in _rozszerzenia_z_katalogu(kat).items():
            wynik.setdefault(uuid, wersja)
    return wynik


def rozszerzenia_zainstalowane_lokalnie():
    """
    Zbiór UUID rozszerzeń GNOME Shell zainstalowanych na TEJ maszynie — Z DYSKU
    (~/.local/share/gnome-shell/extensions/ + /usr/share/gnome-shell/extensions/).
    None = maszyna bez GNOME (nie ma ani katalogów rozszerzeń, ani gnome-shell).
    """
    if not any(k.is_dir() for k in KATALOGI_ROZSZERZEN) and not czy_jest("gnome-shell"):
        return None
    return set(rozszerzenia_na_dysku())


def gnome_shell_wersja():
    """Np. '46.0' z `gnome-shell --version`. None gdy gnome-shell nie jest zainstalowany."""
    if not czy_jest("gnome-shell"):
        return None
    kod, out = uruchom(["gnome-shell", "--version"])
    if kod != 0:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", out)
    return m.group(1) if m else None


def rozszerzenia_brakujace():
    """
    Porównuje pulpit/rozszerzenia-gnome.txt z tym, co jest NAPRAWDĘ zainstalowane na tej
    maszynie (nie z dziennikiem — rozszerzenia GNOME nie są kanałem apt/snap/flatpak).

    Zwraca (brakujace_ego, brakujace_inne):
      brakujace_ego  — [(uuid, komentarz)]         zrodlo == "ego", apka umie doinstalować
      brakujace_inne — [(uuid, zrodlo, komentarz)]  zrodlo != "ego", apka tylko zgłasza
    (None, None) — nie umiem sprawdzić (brak `gnome-extensions` na tej maszynie).
    """
    docelowe = wczytaj_rozszerzenia_gnome()
    if not docelowe:
        return [], []
    zainstalowane = rozszerzenia_zainstalowane_lokalnie()
    if zainstalowane is None:
        return None, None
    ego, inne = [], []
    for uuid, info in docelowe.items():
        if uuid in zainstalowane:
            continue
        if info["zrodlo"] == "ego":
            ego.append((uuid, info["komentarz"]))
        else:
            inne.append((uuid, info["zrodlo"], info["komentarz"]))
    return ego, inne


def pobierz_i_zainstaluj_rozszerzenie(uuid, wersja_shell):
    """
    Pobiera paczkę rozszerzenia z extensions.gnome.org i instaluje ją lokalnie
    (`gnome-extensions install`, bez sudo — instalacja per-user).

    NIE włącza rozszerzenia — włączanie to warstwa dconf/`enabled-extensions`,
    którą wozi `pulpit wgraj` (spec 8, decyzja: nie dublować dwóch źródeł prawdy
    o tym, co ma być włączone).

    Zweryfikowane na żywo 24.08.2026 dla Vitals@CoreCoding.com: endpoint zwraca
    JSON z polem `download_url` (ścieżka względna), pobrany plik jest prawidłowym
    zip-em. `gnome-extensions install --force <zip>` — składnia sprawdzona
    (`gnome-extensions install --help`).

    Zwraca (True, komunikat) albo (False, komunikat_bledu).
    """
    import tempfile
    import urllib.error
    import urllib.request

    if not wersja_shell:
        return False, "nie znam wersji GNOME Shell (gnome-shell --version) — pomijam"

    url_info = (f"{EXTENSIONS_GNOME_ORG}/extension-info/"
                f"?uuid={uuid}&shell_version={wersja_shell}")
    try:
        with urllib.request.urlopen(url_info, timeout=20) as odp:
            dane = json.loads(odp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return False, f"nie udało się zapytać extensions.gnome.org: {e}"

    download_url = dane.get("download_url")
    if not download_url:
        return False, (f"extensions.gnome.org nie ma paczki dla {uuid} "
                        f"pod GNOME Shell {wersja_shell} (odpowiedź bez download_url)")
    if download_url.startswith("/"):
        download_url = EXTENSIONS_GNOME_ORG + download_url

    tmp_path = None
    try:
        with urllib.request.urlopen(download_url, timeout=60) as odp:
            zawartosc = odp.read()
        with tempfile.NamedTemporaryFile(
                suffix=".shell-extension.zip", delete=False) as tmp:
            tmp.write(zawartosc)
            tmp_path = tmp.name
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"nie udało się pobrać paczki: {e}"

    kod, out = uruchom(["gnome-extensions", "install", "--force", tmp_path])
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if kod != 0:
        return False, f"`gnome-extensions install` zakończone błędem: {out.strip()}"
    return True, f"zainstalowane (wersja {dane.get('version', '?')}, uuid {uuid})"


def eksport_pulpitu():
    """
    Eksportuje wybrane ścieżki dconf (spec 8.3) z podmianą katalogu domowego
    na znacznik {{HOME}} (spec 8.4). Zwraca {pelny_klucz: wartosc}.
    """
    sciezki = wczytaj_wzorce(PULPIT / "dconf-lustro.txt")
    pomijane = set(wczytaj_wzorce(PULPIT / "dconf-pomijane-klucze.txt"))
    wyjatki = wczytaj_wzorce(PULPIT / "dconf-wyjatki.txt")
    rozszerzen = klucze_rozszerzen()

    stan = {}
    for s in sciezki:
        if not s.endswith("/"):
            s += "/"
        stan.update(_dconf_dump(s))

    # klucze wożone mimo że ich ścieżka nie jest na liście (spec 8.3)
    for klucz in wyjatki:
        kod, out = uruchom(["dconf", "read", klucz])
        if kod == 0 and out.strip():
            stan[klucz] = out.strip()

    # pojedyncze klucze do pominięcia + ścieżki spoza lustra + klucze rozszerzeń
    poza = wczytaj_wzorce(PULPIT / "dconf-poza-lustrem.txt")
    stan = {k: v for k, v in stan.items()
            if k not in pomijane
            and k not in rozszerzen
            and not any(k.startswith(p) for p in poza)}

    # podmiana katalogu domowego na znacznik — bez tego skrót po cichu przestanie
    # działać na maszynie, na której konto nazywa się inaczej niż `mk` (spec 8.4)
    dom = str(DOM)
    return {k: v.replace(dom, "{{HOME}}") for k, v in stan.items()}


def zapisz_pulpit(stan, plik, naglowek_linie=None):
    """Zapisuje eksport w formacie zgodnym z `dconf dump /` (sekcje bez wiodącego /).
    `naglowek_linie` pozwala podmienić domyślny komentarz nagłówkowy (używane przez
    migawki `pulpit/stan/<maszyna>.ini`, które NIE są wzorcem do `pulpit wgraj`,
    kontrakt [209] 2.3.1)."""
    grupy = {}
    for klucz, wartosc in stan.items():
        sekcja, nazwa = klucz.rsplit("/", 1)
        grupy.setdefault(sekcja.strip("/"), {})[nazwa] = wartosc
    linie = list(naglowek_linie) if naglowek_linie is not None else [
        "# Ustawienia pulpitu GNOME objęte lustrem — plik GENEROWANY przez lustro.py.",
        "# Ścieżki wybrane w pulpit/dconf-lustro.txt; {{HOME}} = katalog domowy maszyny.",
        "# Klucze przejęte przez rozszerzenia GNOME są POZA lustrem — patrz",
        "# pulpit/dconf-rozszerzenia.txt (naprawa fałszywego alarmu z 23.08).",
        "# Format zgodny z `dconf dump /` — do wczytania: `lustro pulpit wgraj`",
        "# (robi kopię poprzedniego stanu przed nadpisaniem — spec 8.11).",
        "",
    ]
    for sekcja in sorted(grupy):
        linie.append(f"[{sekcja}]")
        for nazwa in sorted(grupy[sekcja]):
            linie.append(f"{nazwa}={grupy[sekcja][nazwa]}")
        linie.append("")
    plik.write_text("\n".join(linie), encoding="utf-8")


def wczytaj_ini_pulpitu(plik):
    """Czyta plik w formacie `dconf dump` (jak zapisuje `zapisz_pulpit`) → {klucz: wartość}.
    Brak pliku → None. Współdzielone przez `pulpit.ini` i migawki `pulpit/stan/*.ini`
    (kontrakt [209] 2.3)."""
    if not plik.exists():
        return None
    stan, sekcja = {}, ""
    for linia in plik.read_text(encoding="utf-8").splitlines():
        linia = linia.rstrip()
        if not linia or linia.startswith("#"):
            continue
        if linia.startswith("[") and linia.endswith("]"):
            sekcja = linia[1:-1]
            continue
        if "=" in linia:
            k, v = linia.split("=", 1)
            stan["/" + sekcja + "/" + k.strip()] = v.strip()
    return stan


def wczytaj_pulpit_z_lustra():
    return wczytaj_ini_pulpitu(PLIK_PULPITU)


def wczytaj_stan_maszyny(maszyna):
    """Migawka JEDNEJ maszyny: lustra/pulpit/stan/<maszyna>.ini → {klucz: wartość}
    albo None, gdy ta maszyna jeszcze nie uruchomiła `lustro pulpit oddaj-stan`
    (kontrakt [209] 2.3.1)."""
    return wczytaj_ini_pulpitu(PULPIT_STAN / f"{maszyna}.ini")


def wczytaj_zrodla_galezi():
    """
    Czyta lustra/pulpit/zrodla-galezi.toml → [{"sciezka", "zrodlo", "uwagi"}, ...]
    (kontrakt [209] 2.3.2). Brak pliku / brak wpisów `[[galaz]]` = pusta lista —
    `pulpit skladaj` wtedy nie zmienia w `pulpit.ini` ANI JEDNEGO klucza (warunek
    wdrożenia bez niespodzianek, kontrakt rozdz. 6).
    """
    if not ZRODLA_GALEZI.exists():
        return []
    import tomllib
    try:
        dane = tomllib.loads(ZRODLA_GALEZI.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"⚠ nie umiem odczytać {ZRODLA_GALEZI.name}: {e} — źródła gałęzi pomijam")
        return []
    wynik = []
    for g in dane.get("galaz", []):
        sciezka, zrodlo = g.get("sciezka"), g.get("zrodlo")
        if not sciezka or not zrodlo:
            continue
        wynik.append({"sciezka": sciezka, "zrodlo": str(zrodlo).lower(),
                      "uwagi": g.get("uwagi", "")})
    return wynik


def roznice_pulpitu():
    """Zwraca listę (klucz, tutaj, w_lustrze) — tylko realne różnice; None = brak lustra."""
    tutaj = eksport_pulpitu()
    w_lustrze = wczytaj_pulpit_z_lustra()
    if w_lustrze is None:
        return None
    rozne = []
    for klucz in sorted(set(tutaj) | set(w_lustrze)):
        a, b = tutaj.get(klucz), w_lustrze.get(klucz)
        if a != b:
            rozne.append((klucz, a, b))
    return rozne


def kontrola_pulpitu():
    """
    Kontroler poprawności (spec 8.5, 8.7, 8.6) — sam odczyt:
    czy skróty wskazują na pliki wożone przez lustro, czy czcionki są, czy tapeta jest,
    czy zakładki menedżera plików nie wskazują w próżnię.
    """
    uwagi = []

    # 1. skróty własne → skrypty w ~/bin muszą być wożone przez chezmoi
    wozone = set()
    chez = chezmoi_sciezka()
    if Path(chez).exists() or czy_jest("chezmoi"):
        _, out = uruchom([chez, "managed"])
        wozone = {linia.strip() for linia in out.splitlines() if linia.strip()}

    skroty = _dconf_dump("/org/gnome/settings-daemon/plugins/media-keys/")
    for klucz, wartosc in skroty.items():
        if not klucz.endswith("/command"):
            continue
        komenda = wartosc.strip("'\"")
        plik = komenda.split()[0] if komenda else ""
        if plik.startswith(str(DOM)):
            wzgledna = plik[len(str(DOM)) + 1:]
            if not Path(plik).exists():
                uwagi.append(f"skrót wskazuje na nieistniejący plik: {plik}")
            elif wzgledna not in wozone:
                uwagi.append(
                    f"skrót wskazuje na {skroc_dom(plik)}, którego lustro nie wozi\n"
                    f"    propozycja: dołożyć skrypt do lustra "
                    f"(chezmoi add {skroc_dom(plik)})")

    # 2. czcionki nazwane w ustawieniach muszą być zainstalowane
    if czy_jest("fc-list"):
        interfejs = _dconf_dump("/org/gnome/desktop/interface/")
        for klucz in ("font-name", "document-font-name", "monospace-font-name"):
            wartosc = interfejs.get("/org/gnome/desktop/interface/" + klucz)
            if not wartosc:
                continue
            rodzina = re.sub(r"\s+\d+$", "", wartosc.strip("'\"")).strip()
            kod, _ = uruchom(["fc-list", "-q", rodzina])
            if kod != 0:
                uwagi.append(f"czcionka '{rodzina}' ({klucz}) nie jest zainstalowana "
                             f"— GNOME po cichu podstawi zamiennik")

    # 3. plik tapety musi istnieć
    tlo = _dconf_dump("/org/gnome/desktop/background/")
    for klucz in ("picture-uri", "picture-uri-dark"):
        uri = tlo.get("/org/gnome/desktop/background/" + klucz, "").strip("'\"")
        if uri.startswith("file://"):
            sciezka = uri[len("file://"):]
            if not Path(sciezka).exists():
                uwagi.append(f"tapeta ({klucz}) wskazuje na nieistniejący plik: {sciezka}")

    # 4. zakładki menedżera plików wskazujące w próżnię (zadanie z decyzji [125])
    zakladki = DOM / ".config/gtk-3.0/bookmarks"
    if zakladki.exists():
        for linia in zakladki.read_text(encoding="utf-8").splitlines():
            pola = linia.split()
            adres = pola[0] if pola else ""
            if adres.startswith("file://"):
                sciezka = adres[len("file://"):]
                if not Path(sciezka).exists():
                    uwagi.append(f"zakładka menedżera plików wskazuje na nieistniejące "
                                 f"miejsce: {sciezka} (nie kasuję — decyzja usera)")

    # 5. rozszerzenia GNOME zadeklarowane w lustrze (pulpit/rozszerzenia-gnome.txt),
    #    których nie ma zainstalowanych na tej maszynie (sprawa [150], 24.08).
    #    Lustro wozi listę WŁĄCZONYCH rozszerzeń (enabled-extensions, warstwa dconf) — na
    #    nowej maszynie to nie wystarcza, jeśli samego rozszerzenia nie ma na dysku.
    ego_brak, inne_brak = rozszerzenia_brakujace()
    if ego_brak is None:
        pass  # brak `gnome-extensions` na tej maszynie — nie umiem sprawdzić, nie zgłaszam
    else:
        for uuid, komentarz in ego_brak:
            uwagi.append(
                f"rozszerzenie GNOME „{uuid}” jest w lustrze (źródło: extensions.gnome.org), "
                f"ale NIE jest zainstalowane na tej maszynie\n"
                f"      propozycja: lustro pulpit rozszerzenia")
        for uuid, zrodlo, komentarz in inne_brak:
            dopisek = f" ({komentarz})" if komentarz else ""
            uwagi.append(
                f"rozszerzenie GNOME „{uuid}” (źródło: {zrodlo}) jest w lustrze, "
                f"ale NIE jest zainstalowane — apka nie umie go zainstalować sama, "
                f"zainstaluj ręcznie{dopisek}")
    return uwagi


# ---------------------------------------------------------------- mapa ustawień

def wczytaj_mape_ustawien():
    """
    Zwraca {program: [ścieżki względem katalogu domowego]}.
    Program bez ścieżek (sam komentarz „nie wozimy") → pusta lista: apka nie pyta drugi raz.
    """
    mapa = {}
    if not MAPA_USTAWIEN.exists():
        return mapa
    for linia in MAPA_USTAWIEN.read_text(encoding="utf-8").splitlines():
        goly = linia.split("#", 1)[0].strip()
        if not goly:
            continue
        pola = goly.split()
        mapa[pola[0]] = pola[1:]
    return mapa


def dopisz_do_mapy(program, sciezki, komentarz=""):
    with MAPA_USTAWIEN.open("a", encoding="utf-8") as f:
        f.write(f"{program:<16} {' '.join(sciezki)}"
                + (f"    # {komentarz}\n" if komentarz else "\n"))


# ---------------------------------------------------------------- git / chezmoi

def git_ma_remote():
    kod, out = uruchom(["git", "-C", str(REPO), "remote"])
    return kod == 0 and bool(out.strip())


def git_pull_rebase():
    """
    Dociąga cudze commity z GitHuba PRZED operacją zapisującą (brak 16 z Katany,
    poprawka 1 planu 25.08). Dzienniki są per maszyna, więc konflikt z założenia
    nie powstaje; `--autostash` chroni przed zastanym, niezacommitowanym dryfem.

    ODPORNOŚĆ NA OFFLINE: nieudane pobranie NIE blokuje operacji — apka mówi o tym
    i pracuje na stanie lokalnym; commit wyjedzie przy najbliższym udanym pushu.
    """
    if not git_ma_remote():
        return
    kod, _ = uruchom(["git", "-C", str(REPO), "pull", "--rebase", "--autostash"],
                     timeout=90)
    if kod == 0:
        print("Repozytorium dociągnięte z serwera (git pull --rebase).")
    else:
        print("⚠ Nie udało się pobrać z serwera (offline?) — pracuję na stanie "
              "lokalnym; zmiany wyślą się przy najbliższej okazji.")


# --- CO WOLNO APCE ZACOMMITOWAĆ (sprawa [283], 30.08) -----------------------
# Apka commituje WYŁĄCZNIE własne pliki, pathspec-em. Nigdy `git add -A`.
# Why: 30.08 o 10:17 `lustro dodaj dev.deedles.Trayscale` zrobiło `git add -A`
# i wciągnęło do commitu „lustra: dodano dev.deedles.Trayscale (flatpak) na hp"
# siedem plików innego agenta, pisanych w tej samej chwili (sprawa [279]:
# klapa-straznik.sh, zasilanie-stacja.sh, maszyny.toml, …). Treść przeżyła, ale
# historia skłamała o zawartości commitu, a commit był już na `origin`, więc
# przepisanie historii odpadło. Repozytorium jest współdzielone (kilka sesji,
# timer `lustro-sync` co 60 min, hook dpkg) — cudza, niezacommitowana praca
# w drzewie jest STANEM NORMALNYM i apka ma ją zostawić w spokoju.
_SCIEZKI_DODATKOWE = set()   # dołożone w trakcie przebiegu (chezmoi add / forget)


def oznacz_sciezki_apki(sciezki):
    """Dopisuje ścieżki (względne wobec REPO) do puli commitowanej przez `git_zapisz`."""
    for s in sciezki:
        s = str(s).strip()
        if s:
            _SCIEZKI_DODATKOWE.add(s)


def sciezki_apki():
    """Pliki w repozytorium, które APKA sama zapisuje — jedyne, jakie wolno jej
    zacommitować. Lista STAŁA (poniżej) + to, co w tym przebiegu wyprodukował
    `chezmoi add`/`forget` (te sypią plikami po całym repo, więc są rejestrowane
    dynamicznie — patrz `_zarejestruj_zmiany_repo`)."""
    maszyna = nazwa_maszyny()
    stale = [
        f"lustra/dziennik/{maszyna}.jsonl",       # dziennik zdarzeń TEJ maszyny
        f"lustra/inwentarz/{maszyna}.json",       # migawka inwentarza TEJ maszyny
        f"lustra/pomijane-{maszyna}.txt",         # „pomiń na zawsze" TEJ maszyny
        "lustra/pulpit/pulpit.ini",               # wzorzec pulpitu (`pulpit oddaj`/`skladaj`)
        f"lustra/pulpit/stan/{maszyna}.ini",      # migawka pulpitu TEJ maszyny (`oddaj-stan`)
        "lustra/pulpit/dconf-rozszerzenia.txt",   # klucze przejęte przez rozszerzenia GNOME
        "lustra/ustawienia-map.txt",              # mapa program → pliki ustawień
        ".chezmoidata/packages.yaml",             # lista wykonawcza dla bootstrapu (`lustro lista`)
    ]
    # Świadomie NIE MA tu plików-danych, które pisze CZŁOWIEK (maszyny.toml,
    # statusy-pozycji.toml, zrodla-apt.toml, skrypty.toml, syncthing.toml,
    # siec.toml, pulpit/dconf-*.txt poza rozszerzeniami, zrodla-galezi.toml)
    # ani kodu apki — apka ich nie zapisuje, więc nie ma ich commitować.
    return list(dict.fromkeys(stale + sorted(_SCIEZKI_DODATKOWE)))


def _zmienione_sciezki(sciezki):
    """Które z podanych ścieżek git widzi jako zmienione (zmodyfikowane, usunięte,
    nieznane). Pathspec, który nic nie trafia, NIE jest dla `git status` błędem —
    dlatego wolno tu podawać pliki, których na tej maszynie w ogóle nie ma."""
    if not sciezki:
        return []
    kod, out = uruchom(["git", "-C", str(REPO), "status", "--porcelain", "-z", "--"]
                       + list(sciezki))
    if kod != 0:
        return []
    wpisy = [w for w in out.split("\0") if w]
    wynik, i = [], 0
    while i < len(wpisy):
        w = wpisy[i]
        i += 1
        if len(w) <= 3:
            continue
        status, sciezka = w[:2], w[3:]
        if "R" in status or "C" in status:   # zmiana nazwy: następny wpis to źródło
            i += 1
        wynik.append(sciezka)
    return wynik


def _stan_repo():
    kod, out = uruchom(["git", "-C", str(REPO), "status", "--porcelain"])
    return out if kod == 0 else None


def _zarejestruj_zmiany_repo(przed):
    """Różnica `git status` sprzed i po operacji `chezmoi add`/`forget` → pula apki.
    Statycznej listy tu być nie może: chezmoi zapisuje pliki tam, gdzie każe mu
    ścieżka w katalogu domowym (private_dot_config/…, bin/…, dot_local/…).
    Plik, który JUŻ przed operacją miał ten sam status (bo zmienił go ktoś inny),
    zostaje poza pulą — celowo, to cudza praca."""
    po = _stan_repo()
    if przed is None or po is None:
        return
    byly = set(przed.splitlines())
    nowe = []
    for linia in po.splitlines():
        if linia in byly or len(linia) <= 3:
            continue
        nowe.append(linia[3:].strip('"'))
    oznacz_sciezki_apki(nowe)


def git_zapisz(wiadomosc):
    """Jeden commit na koniec przebiegu + push, jeśli repozytorium ma remote (spec 9.3).
    Gdy push odbije się o cudze świeże commity — jedna próba `pull --rebase` + push
    jeszcze raz; dalej nieudany push zostawia commit lokalnie (wyśle się później).

    ⚠ Commituje TYLKO ścieżki z `sciezki_apki()` ([283]) — cudze zmiany zostają
    w drzewie nietknięte, także niezacommitowane."""
    moje = _zmienione_sciezki(sciezki_apki())
    if not moje:
        stan = _stan_repo()
        if stan is None:
            print("⚠ Nie umiem sprawdzić stanu repozytorium — pomijam commit.")
        elif stan.strip():
            print("Żaden z MOICH plików się nie zmienił — nie ma czego zapisywać "
                  "(w drzewie są cudze zmiany, ich nie ruszam).")
        else:
            print("Repozytorium bez zmian — nie ma czego zapisywać.")
        return
    uruchom(["git", "-C", str(REPO), "add", "--"] + moje)
    uruchom(["git", "-C", str(REPO), "commit", "-m", wiadomosc, "--"] + moje)
    print(f"Commit w repozytorium konfiguracji: {wiadomosc}")
    print("   pliki w commicie: " + ", ".join(moje))
    if git_ma_remote():
        kod, _ = uruchom(["git", "-C", str(REPO), "push"], timeout=180)
        if kod != 0:
            uruchom(["git", "-C", str(REPO), "pull", "--rebase", "--autostash"],
                    timeout=120)
            kod, _ = uruchom(["git", "-C", str(REPO), "push"], timeout=180)
        print("Wysłane na serwer (git push)." if kod == 0
              else "⚠ `git push` się nie udał (offline?) — commit został lokalnie, "
                   "wyśle się przy następnej operacji z siecią.")
    else:
        print("Repozytorium nie ma jeszcze serwera (remote) — commit został lokalnie.")


def chezmoi_dodaj(sciezki):
    """`chezmoi add` na liście ścieżek. Zwraca listę tych, które weszły.
    Pliki, które chezmoi w ten sposób wsypał do repozytorium, trafiają do puli
    commitowanej przez `git_zapisz` ([283]) — nie zgadujemy ich ścieżek, tylko
    czytamy różnicę `git status` przed i po."""
    przed = _stan_repo()
    weszly = []
    for s in sciezki:
        pelna = pelna_sciezka(s)
        if not pelna.exists():
            print(f"    ⚠ {skroc_dom(pelna)} nie istnieje — pomijam")
            continue
        kod, _ = uruchom([chezmoi_sciezka(), "add", str(pelna)])
        if kod == 0:
            weszly.append(str(pelna).replace(str(DOM) + "/", ""))
            print(f"    ✓ do lustra: {skroc_dom(pelna)}")
        else:
            print(f"    ⚠ chezmoi add nie dał rady: {skroc_dom(pelna)}")
    _zarejestruj_zmiany_repo(przed)
    return weszly


def chezmoi_zapomnij(sciezki):
    przed = _stan_repo()
    zapomniane = []
    for s in sciezki:
        pelna = pelna_sciezka(s)
        kod, _ = uruchom([chezmoi_sciezka(), "forget", "--force", str(pelna)])
        if kod == 0:
            zapomniane.append(str(pelna).replace(str(DOM) + "/", ""))
            print(f"    ✓ zdjęte z lustra: {skroc_dom(pelna)}")
    _zarejestruj_zmiany_repo(przed)   # usunięte pliki źródłowe też są MOJE ([283])
    return zapomniane


# ---------------------------------------------------------------- kanały: instalacja

def czy_flatpak_systemowy(ident):
    """Flatpak zainstalowany systemowo wymaga roota; --user nie wymaga.

    Bez `--app` ([268], 29.08): pozycją lustra bywa też DODATEK aplikacji, który
    jest runtime'em (patrz `inwentarz_flatpak`). Z `--app` dodatek nie znajdował
    się na liście i funkcja wpadała w gałąź „ostrożnie: zakładamy systemowy" —
    tu akurat z dobrym skutkiem, ale dla dodatku zainstalowanego per-user dałaby
    `sudo flatpak uninstall`, które usuwa Z SYSTEMU, nie z konta usera."""
    kod, out = uruchom(["flatpak", "list",
                        "--columns=application,installation"])
    if kod != 0:
        return True                        # ostrożnie: zakładamy systemowy
    for linia in out.splitlines():
        pola = [p.strip() for p in linia.split("\t")]
        if pola and pola[0] == ident:
            return len(pola) < 2 or pola[1] == "system"
    return True


def komenda_instalacji(kanal, ident):
    if kanal == "apt":
        return jako_root(["apt-get", "install", "-y", ident])
    if kanal == "snap":
        return jako_root(["snap", "install", ident])
    if kanal == "flatpak":
        return jako_root(["flatpak", "install", "-y", "flathub", ident])
    if kanal == KANAL_SKRYPT:                       # tylko do POKAZANIA (szczegóły);
        d = wczytaj_skrypty().get(ident)            # wykonanie: zainstaluj_skrypt()
        return ["bash", "-c", d["zainstaluj"]] if d else None
    return None


def komenda_usuniecia(kanal, ident):
    if kanal == "apt":
        return jako_root(["apt-get", "remove", "-y", ident])
    if kanal == "snap":
        return jako_root(["snap", "remove", ident])
    if kanal == "flatpak":
        if czy_flatpak_systemowy(ident):
            return jako_root(["flatpak", "uninstall", "-y", ident])
        return ["flatpak", "uninstall", "-y", "--user", ident]
    if kanal == KANAL_SKRYPT:
        d = wczytaj_skrypty().get(ident)
        return ["bash", "-c", d["usun"]] if d and d.get("usun") else None
    return None


def wykryj_kanal(nazwa):
    """
    Zwraca listę kanałów, w których program da się zainstalować.
    Kolejność ma znaczenie: apt przed snapem przed flatpakiem.
    """
    kandydaci = []
    if nazwa in wczytaj_skrypty():
        kandydaci.append(KANAL_SKRYPT)          # definicja w skrypty.toml [252]
    if czy_jest("apt-cache"):
        kod, out = uruchom(["apt-cache", "policy", nazwa])
        if kod == 0 and "Candidate:" in out:
            for linia in out.splitlines():
                if "Candidate:" in linia and "(none)" not in linia:
                    kandydaci.append("apt")
                    break
    if czy_jest("snap"):
        kod, out = uruchom(["snap", "info", nazwa], timeout=60)
        if kod == 0 and "channels:" in out:
            kandydaci.append("snap")
    if czy_jest("flatpak") and ("." in nazwa or not kandydaci):
        kod, _ = uruchom(["flatpak", "remote-info", "flathub", nazwa], timeout=90)
        if kod == 0:
            kandydaci.append("flatpak")
    return kandydaci


def znajdz_zainstalowany(nazwa, inw=None):
    """Zwraca listę (kanal, id) pasujących do podanej nazwy wśród ZAINSTALOWANYCH."""
    inw = inw if inw is not None else inwentaryzacja()
    dokladne = [(k, i) for (k, i) in inw if i == nazwa]
    if dokladne:
        return dokladne
    male = nazwa.lower()
    return [(k, i) for (k, i) in inw
            if i.lower() == male or i.lower().endswith("." + male)]


# ---------------------------------------------------------------- ustawienia programu

MIEJSCA_USTAWIEN = (".config", ".local/share", ".var/app")


def zdjecie_katalogow():
    """Lista wpisów w typowych miejscach ustawień — do porównania przed/po (spec 7.5)."""
    stan = set()
    for m in MIEJSCA_USTAWIEN:
        kat = DOM / m
        if kat.is_dir():
            for p in kat.iterdir():
                stan.add(str(p))
    for p in DOM.iterdir():
        if p.name.startswith(".") and p.is_dir():
            stan.add(str(p))
    return stan


def kandydaci_ustawien(nazwa, przed, po):
    """Co przybyło po instalacji + co pasuje nazwą (gdy program już wcześniej coś założył)."""
    nowe = sorted(po - przed)
    male = nazwa.lower().split(".")[-1]
    pasujace = [s for s in sorted(po) if male and male in Path(s).name.lower()]
    wynik = []
    for s in nowe + pasujace:
        if s not in wynik:
            wynik.append(s)
    return wynik


def zapytaj_o_ustawienia(program, kandydaci):
    """Krok 3–5 ze spec 7.5. Zwraca listę ścieżek oddanych do lustra."""
    mapa = wczytaj_mape_ustawien()
    if program in mapa:
        if mapa[program]:
            print(f"    Ustawienia „{program}” już są w lustrze: {' '.join(mapa[program])}")
        else:
            print(f"    Ustawienia „{program}” — decyzja usera: nie wozimy. Nie pytam.")
        return []

    if not kandydaci:
        print("    Program nic jeszcze nie założył. Uruchom go, ustaw po swojemu")
        print(f"    i wywołaj: lustro ustawienia {program}")
        return []

    wykl = wczytaj_wzorce(WYKLUCZENIA / "ustawienia.txt")
    kandydaci = [k for k in kandydaci
                 if not pasuje(skroc_dom(k).lstrip("~/"), wykl)]
    if not kandydaci:
        print("    Wszystko, co program założył, siedzi w wykluczeniach (cache/stan).")
        return []

    print(f"    „{program}” założył:")
    for k in kandydaci:
        print(f"      • {skroc_dom(k)}")
    while True:
        odp = pytaj("Wozić jego ustawienia na pozostałe maszyny?", "Tnp", "t")
        if odp == "p":
            for k in kandydaci:
                print(f"    --- {skroc_dom(k)} ---")
                _, out = uruchom(["ls", "-la", k])
                print("    " + out.replace("\n", "\n    "))
            continue
        break
    if odp == "t":
        weszly = chezmoi_dodaj(kandydaci)
        if weszly:
            dopisz_do_mapy(program, weszly,
                           f"dodane przez lustro {datetime.now():%Y-%m-%d}")
        return weszly
    dopisz_do_mapy(program, [], f"nie wozimy — decyzja usera {datetime.now():%Y-%m-%d}")
    return []


# ---------------------------------------------------------------- zbieranie pozycji

def zbierz_pozycje():
    """
    Wspólny rdzeń `status` i `sync`.

    Semantyka rozstrzygania od kontraktu „menadżer konfiguracji" [209], rozdz. 3
    (pierwsza pasująca reguła wygrywa):
      1. `status = "testowe"` → kwarantanna, bez zmian.
      2. Jawny `[[pozycja.override]]` DLA TEJ MASZYNY → wygrywa zawsze, niezależnie
         od członkostwa w lustrze (dwukierunkowość — override "obecne" działa też
         na maszynie, która NIE jest lustrem).
      3. Brak override, maszyna JEST członkiem lustra → konsensus z dziennika,
         liczony TYLKO z dzienników maszyn-członków (rozdz. 4), ew. ograniczony do
         przecięcia z `wylacznie_na`.
      4. Brak override, maszyna NIE jest członkiem lustra → „dowolny": pozycja
         w ogóle nie jest sprawdzana, nie ma szans na rozbieżność.

    Reguła 2a (sprawa [284], 2026-08-30) wchodzi MIĘDZY 2 a 3: pozycja spoza
    `zostaja` profilu tej maszyny (lustra/profile.toml) nie jest sprawdzana —
    tak samo jak w regule 4. Kolejność jest istotna: jawny `[[pozycja.override]]`
    stoi WYŻEJ, więc pojedynczy wyjątek („ta jedna rzecz jednak ma tu być”) nadal
    robi się jednym wpisem i wygrywa z profilem. Pozycje odsiane profilem wracają
    w wyniku jako `poza_profilem` — to z nich `lustro profil` buduje listę
    „stoi tutaj, a do tej maszyny nie należy”.
    """
    maszyna = nazwa_maszyny()
    zdarzenia = wczytaj_dzienniki()
    inw = inwentaryzacja()

    # Kanał gnome-extension w inwentarzu (naprawa braku 14 + luki „wieczny fałszywy
    # alarm" z 25.08): dziennik ma zdarzenia `kanal: gnome-extension`, więc porównanie
    # musi widzieć, co jest NAPRAWDĘ na dysku. Tylko katalog USERA — rozszerzenia
    # systemowe (/usr/share) należą do pakietów apt i nie są instalacjami usera.
    if any(k.is_dir() for k in KATALOGI_ROZSZERZEN) or czy_jest("gnome-shell"):
        for uuid, wersja in rozszerzenia_na_dysku(tylko_uzytkownika=True).items():
            inw[("gnome-extension", uuid)] = wersja

    czlonkowie = wczytaj_czlonkow_lustra()
    ta_maszyna_czlonek = czy_czlonek_lustra(maszyna, czlonkowie)

    # Konsensus liczony TYLKO z dzienników maszyn-członków lustra (kontrakt [209],
    # rozdz. 4) — dziennik maszyny nie-członka nadal fizycznie istnieje i jest
    # czytany niżej (`moje`, „niezapisane"), tylko nie wpływa na oczekiwania INNYCH
    # maszyn. Dziś (dzień wdrożenia, brak jawnych `czlonek_lustra`) każda maszyna
    # z dziennikiem jest członkiem domyślnie — filtr nie zmienia niczego.
    zdarzenia_czlonkow = [z for z in zdarzenia
                          if czy_czlonek_lustra(z.get("maszyna"), czlonkowie)]
    ostatnie, historia = stan_oczekiwany(zdarzenia_czlonkow)
    moje = stan_wg_tej_maszyny(zdarzenia, maszyna)
    pomijane = wczytaj_pomijane()
    statusy = wczytaj_statusy_pozycji()

    rozbieznosci, niezapisane, usuniete_poza, kwarantanna = [], [], [], []
    wzorce = wzorce_profilu(maszyna)      # [284] — reguła 2a, patrz docstring
    poza_profilem = []

    # Zbiór pozycji do oceny: konsensus (już przefiltrowany) PLUS pozycje, które
    # mają jawny override dla TEJ maszyny, nawet jeśli w konsensusie w ogóle nie
    # występują (przypadek brzegowy: pozycja tylko na maszynie spoza lustra,
    # kontrakt rozdz. 8, przypadek 5/11 — „ktoś przygotowuje wyjątek zanim maszyna
    # jeszcze istnieje").
    klucze_do_oceny = set(ostatnie)
    for klucz, st in statusy.items():
        if maszyna in st.get("override", {}):
            klucze_do_oceny.add(klucz)

    for klucz in sorted(klucze_do_oceny):
        if klucz in pomijane:
            continue
        st = statusy.get(klucz)

        # reguła 1: testowe (kwarantanna) — pierwszeństwo przed wszystkim, override
        # się w ogóle nie odczytuje (kontrakt rozdz. 8, przypadek 9)
        if st and st["status"] == "testowe":
            if klucz in ostatnie:
                kwarantanna.append((klucz, st))
            continue

        override_tu = (st or {}).get("override", {}).get(maszyna)

        if override_tu is not None:
            # reguła 2: override dla tej maszyny wygrywa zawsze
            ma_byc = override_tu["stan"] == "obecne"
            jest_tutaj = klucz in inw
            if ma_byc and not jest_tutaj:
                zdarz = ostatnie.get(klucz) or {
                    "maszyna": "(brak zdarzenia — tylko override)", "ts": "",
                    "notatka": override_tu.get("uwagi", "")}
                rozbieznosci.append((klucz, zdarz, "brak-tutaj"))
            # (not ma_byc) i jest_tutaj: bierne WYCISZENIE (rozdz. 5) — apka nigdy
            # nic nie usuwa i o tej pozycji tu już nie wspomina; zgodne (ma_byc ==
            # jest_tutaj): też nic do zrobienia.
            continue

        # reguła 2a [284]: pozycja spoza profilu tej maszyny — nie sprawdzamy jej
        # wcale. Jeśli mimo to fizycznie tu stoi, odkładamy ją do `poza_profilem`
        # (materiał dla `lustro profil sprzataj`), ale NIGDY nie zgłaszamy jako
        # rozbieżności i nigdy nie usuwamy z automatu.
        if not pozycja_w_profilu(klucz[0], klucz[1], wzorce):
            if klucz in inw:
                poza_profilem.append((klucz, inw[klucz]))
            continue

        if not ta_maszyna_czlonek:
            continue   # reguła 4: „dowolny" — pozycja w ogóle nie jest sprawdzana

        # reguła 3: konsensus (już ograniczony do członków), ew. przecięty z wylacznie_na
        zdarz = ostatnie.get(klucz)
        if zdarz is None:
            continue
        wylacznie_na = (st or {}).get("wylacznie_na") or []
        if wylacznie_na and maszyna not in wylacznie_na:
            continue

        jest_tutaj = klucz in inw
        ma_byc = zdarz.get("zdarzenie") == "dodano"
        czyje = zdarz.get("maszyna")

        if ma_byc and not jest_tutaj:
            if czyje == maszyna:
                usuniete_poza.append((klucz, zdarz))
            else:
                rozbieznosci.append((klucz, zdarz, "brak-tutaj"))
        elif (not ma_byc) and jest_tutaj:
            if czyje == maszyna:
                niezapisane.append((klucz, inw[klucz]))
            else:
                rozbieznosci.append((klucz, zdarz, "usuniety-gdzie-indziej"))

    for klucz, wersja in sorted(inw.items()):
        if klucz in pomijane:
            continue
        if klucz not in moje and klucz not in ostatnie:
            niezapisane.append((klucz, wersja))
        # [284] pozycja stojąca tutaj, a spoza profilu, której konsensus w ogóle
        # nie zna (nie weszła w pętlę wyżej) — też należy do „nie moja sprawa”
        if (klucz not in ostatnie
                and not pozycja_w_profilu(klucz[0], klucz[1], wzorce)
                and maszyna not in (statusy.get(klucz) or {}).get("override", {})):
            poza_profilem.append((klucz, wersja))   # override > profil, kontrakt [209] r.2

    return {"maszyna": maszyna, "zdarzenia": zdarzenia, "inwentarz": inw,
            "rozbieznosci": rozbieznosci, "niezapisane": niezapisane,
            "usuniete_poza": usuniete_poza, "pomijane": pomijane,
            "historia": historia, "kwarantanna": kwarantanna,
            "profil": profil_maszyny(maszyna), "wzorce_profilu": wzorce,
            "poza_profilem": sorted(set(poza_profilem))}


# ---------------------------------------------------------------- polecenie: status

def naglowek(dane):
    maszyna = dane["maszyna"]
    zdarzenia = dane["zdarzenia"]
    inne = sorted({z.get("maszyna") for z in zdarzenia} - {maszyna})
    opis = []
    for m in inne:
        ost = max((z["ts"] for z in zdarzenia if z.get("maszyna") == m), default="?")
        opis.append(f"{m} (dziennik do {data_ludzka(ost)})")
    if not opis:
        opis = ["brak innych luster — jedyne lustro w dziennikach to ta maszyna"]
    print(f"LUSTRO — {maszyna} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Porównanie z: {', '.join(opis)}")
    if dane["pomijane"]:
        print(f"Świadomie pomijane na tej maszynie: {len(dane['pomijane'])} "
              f"(plik {plik_pomijanych().name})")
    if dane.get("kwarantanna"):
        print(f"Kwarantanna (status `testowe`, automat nie propaguje — "
              f"plik statusy-pozycji.toml): {len(dane['kwarantanna'])}")
        for (kanal, ident), st in dane["kwarantanna"]:
            # [218a] naprawa: do 27.08 stało tu `st["maszyna"]` — pole ze STAREGO
            # schematu (`status = "wyjatek"` + `maszyna`), skasowanego kontraktem
            # [209] 2.2. `wczytaj_statusy_pozycji` takiego klucza już nie zwraca,
            # więc pierwszy wpis `status = "testowe"` wywracał `lustro status`
            # na KeyError. Dziś odpowiednikiem jest lista `wylacznie_na`.
            gdzie = (f" — dotyczy maszyn: {', '.join(st['wylacznie_na'])}"
                     if st.get("wylacznie_na") else "")
            uwagi = f" ({st['uwagi']})" if st["uwagi"] else ""
            print(f"   ⏳ {ident} ({kanal}){gdzie}{uwagi}")
    print()


def polecenie_status(args):
    dane = zbierz_pozycje()
    naglowek(dane)
    numer = 0

    if dane["rozbieznosci"]:
        print(f"ROZBIEŻNOŚCI ({len(dane['rozbieznosci'])})")
        print()
        for (kanal, ident), zdarz, rodzaj in dane["rozbieznosci"]:
            numer += 1
            if rodzaj == "brak-tutaj":
                print(f"{numer:2}. {ident} — NIE MA tutaj, JEST na {zdarz['maszyna']}")
                print(f"    źródło: {zdarz['maszyna']} dodał {data_ludzka(zdarz['ts'])} "
                      f"({kanal}, {ident})")
                print("    propozycja: zainstalować tutaj")
            else:
                print(f"{numer:2}. {ident} — JEST tutaj, USUNIĘTY na {zdarz['maszyna']}")
                print(f"    źródło: {zdarz['maszyna']} usunął "
                      f"{data_ludzka(zdarz['ts'])} ({kanal})")
                if zdarz.get("notatka"):
                    print(f"            notatka: \"{zdarz['notatka']}\"")
                print("    propozycja: odinstalować tutaj")
            print()
    else:
        print("ROZBIEŻNOŚCI (0) — nic")
        print()

    if dane["niezapisane"]:
        print(f"ZAINSTALOWANE POZA APKĄ, JESZCZE NIEZAPISANE W DZIENNIKU "
              f"({len(dane['niezapisane'])})")
        print()
        for (kanal, ident), wersja in dane["niezapisane"]:
            numer += 1
            print(f"{numer:2}. {ident} ({kanal}, {wersja}) — jest na maszynie, "
                  f"brak zdarzenia w dzienniku")
            print("    propozycja: dopisać do dziennika jako \"dodano … zrodlo: reczne\"")
            print()

    if dane.get("poza_profilem"):
        print(f"STOI TUTAJ, A NIE NALEŻY DO PROFILU „{dane['profil']}” "
              f"({len(dane['poza_profilem'])}) — informacja, nic nie robimy")
        print()
        for (kanal, ident), wersja in dane["poza_profilem"]:
            numer += 1
            print(f"{numer:2}. {ident} ({kanal}, {wersja})")
        print("    Ta maszyna nie jest o te pozycje pytana i automat ich nie dociąga.")
        print("    Żeby je USUNĄĆ (z pytaniem przy każdej): lustro profil sprzataj")
        print()

    if dane["usuniete_poza"]:
        print(f"USUNIĘTE POZA APKĄ, JESZCZE NIEZAPISANE W DZIENNIKU "
              f"({len(dane['usuniete_poza'])})")
        print()
        for (kanal, ident), zdarz in dane["usuniete_poza"]:
            numer += 1
            print(f"{numer:2}. {ident} ({kanal}) — dziennik mówi \"jest\" "
                  f"(od {data_ludzka(zdarz['ts'])}), na maszynie go nie ma")
            print("    propozycja: dopisać do dziennika \"usunieto … zrodlo: reczne\"")
            print()

    # [218b] — nie-członek lustra nie dostaje źródeł hurtem (patrz
    # `zrodla_nalezne_tej_maszynie`); mówimy o tym wprost, żeby pominięcie nie
    # było ciche i żeby nikt nie „naprawiał" brakującego wpisu ręcznie.
    wszystkie_brakujace = zrodla_brakujace()
    brak_zrodel = zrodla_nalezne_tej_maszynie(wszystkie_brakujace)
    pominiete_zrodla = len(wszystkie_brakujace) - len(brak_zrodel)
    if pominiete_zrodla:
        print(f"ZEWNĘTRZNE ŹRÓDŁA APT — pominięte ({pominiete_zrodla}): ta maszyna "
              f"nie jest członkiem lustra")
        print(f"    (`czlonek_lustra = false` w {MASZYNY_TOML.name}), więc nie dostaje "
              f"źródeł z lustra/{ZRODLA_APT.name} hurtem [218b].")
        print("    Pojedyncze źródło trafi tu tylko wtedy, gdy jego pakiet dostanie "
              "jawny")
        print("    `[[pozycja.override]] stan = \"obecne\"` w statusy-pozycji.toml.")
        print()
    if brak_zrodel:
        print(f"ZEWNĘTRZNE ŹRÓDŁA APT, KTÓRYCH TU NIE MA ({len(brak_zrodel)}) "
              f"— wg lustra/{ZRODLA_APT.name}")
        print()
        for z in brak_zrodel:
            numer += 1
            pak = ", ".join(z.get("pakiety") or []) or "—"
            print(f"{numer:2}. źródło „{z.get('nazwa')}” ({z.get('url')}) — brak klucza "
                  f"lub wpisu w /etc/apt/sources.list.d/")
            print(f"    pakiety z tego źródła: {pak}")
            print("    propozycja: `lustro dodaj <pakiet>` doda je samo przed instalacją")
            print()

    posprzataj_zdublowane_zrodla(tylko_pokaz=True)   # [257c] — sam meldunek

    numer = _wypisz_pulpit(numer)

    obce = instalacje_obce()
    print(f"INSTALACJE SPOZA apt/snap/flatpak — INFORMACJA, nic nie robimy ({len(obce)})")
    print()
    if obce:
        for sciezka, opis in obce:
            print(f" •  {sciezka:<40} ({opis})")
    else:
        print(" •  brak — wszystko poza wykluczeniami z wykluczenia/obce.txt")
    print()
    print("Nic nie zostało zmienione. Żeby zatwierdzać pozycjami: lustro sync")
    return 0


def _wypisz_pulpit(numer):
    """Sekcja pulpitu w `status`; zwraca zaktualizowany licznik pozycji."""
    del _BLEDY_DCONF[:]
    rozne = roznice_pulpitu()

    if rozne is None:
        numer += 1
        print("PULPIT")
        print()
        print(f"{numer:2}. Lustro nie ma jeszcze zapisanych ustawień pulpitu "
              f"({PLIK_PULPITU.name} nie istnieje)")
        print("    propozycja: jednorazowy zasiew — lustro pulpit zasiew")
        print()
        return numer

    powody = powody_niepewnosci()
    if powody:
        print("PULPIT — NIE PORÓWNUJĘ, obraz ustawień jest teraz niepewny:")
        print()
        for b in powody:
            print(f"    ⚠ {b}")
        print("    Zgłoszenie rozbieżności w takiej chwili byłoby fałszywym alarmem.")
        print("    Powtórz przy odblokowanym, działającym pulpicie.")
        print()
        return numer

    uwagi = kontrola_pulpitu()

    if not rozne and not uwagi:
        print("PULPIT (0) — ustawienia zgodne z lustrem, kontrola bez zastrzeżeń")
        print()
        return numer

    if rozne:
        numer += 1
        print("PULPIT")
        print()
        print(f"{numer:2}. Ustawienia pulpitu różnią się od lustra ({len(rozne)} kluczy):")
        for klucz, a, b in rozne:
            print(f"      {klucz}")
            print(f"        tutaj:     {a if a is not None else 'brak'}")
            print(f"        w lustrze: {b if b is not None else 'brak'}")
        print("    propozycja: [o]ddać stąd do lustra / [w]grać z lustra tutaj")
        print()
    if uwagi:
        if not rozne:
            print("PULPIT")
            print()
        for u in uwagi:
            numer += 1
            print(f"{numer:2}. {u}")
        print()
    return numer


def polecenie_pulpit_status(args):
    maszyna = nazwa_maszyny()
    print(f"LUSTRO / PULPIT — {maszyna} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    sciezki = wczytaj_wzorce(PULPIT / "dconf-lustro.txt")
    tutaj = eksport_pulpitu()
    rozsz = klucze_rozszerzen()
    print(f"Ścieżek dconf objętych lustrem: {len(sciezki)}; "
          f"ustawionych kluczy na tej maszynie: {len(tutaj)}; "
          f"kluczy oddanych rozszerzeniom GNOME: {len(rozsz)}")
    print()
    _wypisz_pulpit(0)
    print("Nic nie zostało zmienione (dconf tylko odczytany).")
    return 0


def polecenie_pulpit_sprawdz(args):
    print(f"LUSTRO / PULPIT — kontrola poprawności — {nazwa_maszyny()}")
    print()
    uwagi = kontrola_pulpitu()
    if not uwagi:
        print("Bez zastrzeżeń: skróty wskazują na wożone pliki, czcionki są, "
              "tapeta jest, zakładki żyją.")
    else:
        for nr, u in enumerate(uwagi, 1):
            print(f"{nr:2}. {u}")
    print()
    print("Nic nie zostało zmienione.")
    return 0


def polecenie_pulpit_rozszerzenia(args):
    """
    Rozszerzenia GNOME Shell (spec 8.12): sprawdza, czy to, co pulpit/rozszerzenia-gnome.txt
    deklaruje jako "ma być zainstalowane", jest naprawdę na dysku tej maszyny — i, po pytaniu
    (albo bez pytania z --zatwierdzam-wszystko / w trybie bootstrapu — patrz nowa-maszyna,
    E3), doinstalowuje to, co da się pobrać z extensions.gnome.org (źródło "ego").

    Rozszerzenia źródła "lokalne" apka NIE umie zainstalować — tylko zgłasza brak.
    WŁĄCZANIE rozszerzenia to inna warstwa (dconf `enabled-extensions`, `pulpit wgraj`) —
    ta komenda jej nie dotyka, żeby nie dublować dwóch źródeł prawdy o tym, co ma być włączone.
    """
    git_pull_rebase()
    maszyna = nazwa_maszyny()
    print(f"LUSTRO / PULPIT / ROZSZERZENIA GNOME — {maszyna}")
    print()

    docelowe = wczytaj_rozszerzenia_gnome()
    print(f"W lustrze zadeklarowane jako „ma być zainstalowane”: {len(docelowe)}")

    ego_brak, inne_brak = rozszerzenia_brakujace()
    if ego_brak is None:
        print("⚠ Brak `gnome-extensions` na tej maszynie (nie ma GNOME Shell?) "
              "— nie umiem sprawdzić.")
        return 0

    if not docelowe:
        print("Plik danych jest pusty — nic do sprawdzenia.")
        return 0

    if not ego_brak and not inne_brak:
        print("Wszystkie zadeklarowane rozszerzenia są zainstalowane na tej maszynie.")
        return 0

    if inne_brak:
        print()
        print(f"Brakujące, źródła INNEGO niż extensions.gnome.org — zainstaluj ręcznie ({len(inne_brak)}):")
        for uuid, zrodlo, komentarz in inne_brak:
            print(f"   • {uuid}  (źródło: {zrodlo})" + (f"  — {komentarz}" if komentarz else ""))

    if not ego_brak:
        print()
        print("Nic, co apka umiałaby doinstalować sama (extensions.gnome.org) — koniec.")
        return 0

    print()
    print(f"Brakujące, apka umie doinstalować z extensions.gnome.org ({len(ego_brak)}):")
    for uuid, komentarz in ego_brak:
        print(f"   • {uuid}" + (f"  — {komentarz}" if komentarz else ""))

    wersja_shell = gnome_shell_wersja()
    print()
    print(f"Wersja GNOME Shell na tej maszynie: {wersja_shell or 'nieznana'}")
    if not wersja_shell:
        print("⚠ Bez wersji GNOME Shell nie umiem zapytać extensions.gnome.org o właściwą paczkę.")
        return 1

    if not getattr(args, "zatwierdzam_wszystko", False):
        if pytaj("Pobrać i zainstalować brakujące rozszerzenia z extensions.gnome.org?",
                  "Tn", "t") != "t":
            print("Nic nie instaluję.")
            return 0

    zainstalowane_teraz = []
    bledy = []
    for uuid, komentarz in ego_brak:
        print(f"   → {uuid} …", end=" ")
        ok, komunikat = pobierz_i_zainstaluj_rozszerzenie(uuid, wersja_shell)
        print(komunikat)
        if ok:
            zainstalowane_teraz.append(uuid)
        else:
            bledy.append((uuid, komunikat))

    potwierdzone = []
    if zainstalowane_teraz:
        # najpierw robimy, potem zapisujemy (spec 9.3) — sprawdzamy ponowną inwentaryzacją,
        # że instalacja naprawdę się przyjęła, zanim to trafi do dziennika.
        po = rozszerzenia_zainstalowane_lokalnie() or set()
        potwierdzone = [u for u in zainstalowane_teraz if u in po]
        for uuid in potwierdzone:
            dopisz_zdarzenie("dodano", kanal="gnome-extension", ident=uuid,
                             zrodlo="apka", notatka="zainstalowane z extensions.gnome.org "
                                                     "przez `lustro pulpit rozszerzenia`; "
                                                     "włączenie zostaje warstwie pulpitu (dconf)")
        nieprzyjete = set(zainstalowane_teraz) - set(potwierdzone)
        for uuid in nieprzyjete:
            print(f"   ⚠ {uuid}: `gnome-extensions install` zwrócił sukces, ale ponowna "
                  f"inwentaryzacja NIE widzi rozszerzenia — nie zapisuję zdarzenia")
        if potwierdzone:
            git_zapisz(f"lustra: rozszerzenia GNOME zainstalowane na {maszyna} "
                       f"({len(potwierdzone)})")

    print()
    print(f"Zainstalowane: {len(potwierdzone)} z {len(ego_brak)}. "
          f"Włączenie (jeśli potrzebne) zrobi `lustro pulpit wgraj` albo ustawienia systemowe.")
    if bledy:
        print("Błędy:")
        for uuid, komunikat in bledy:
            print(f"   • {uuid}: {komunikat}")
        return 1
    return 0


def polecenie_pulpit_zasiew(args):
    """Jednorazowy zasiew: zapisuje bieżący eksport do repozytorium.
    NIE zmienia systemu — pisze wyłącznie plik w katalogu lustra/."""
    stan = eksport_pulpitu()
    zapisz_pulpit(stan, PLIK_PULPITU)
    print(f"Zapisano {len(stan)} kluczy do {PLIK_PULPITU}")
    print("System nie został dotknięty — to zapis do repozytorium, nie do dconf.")
    return 0


def polecenie_pulpit_oddaj(args):
    """Bieżące ustawienia pulpitu TEJ maszyny → do lustra + zdarzenie (spec 8.9).

    ⚠️ Jak `wgraj`: bez terminala tylko z jawną flagą — `oddaj` nadpisuje WZORZEC
    dla wszystkich maszyn (decyzja [195]: oddawanie pulpitu to świadoma komenda)."""
    if not getattr(args, "zatwierdzam_wszystko", False) and not sys.stdin.isatty():
        print("Brak terminala (tryb nieinteraktywny): `pulpit oddaj` nadpisuje wzorzec")
        print("pulpitu dla WSZYSTKICH maszyn — bez realnego pytania ODMAWIAM.")
        print("Jawna zgoda: lustro pulpit oddaj --zatwierdzam-wszystko")
        return 1
    git_pull_rebase()
    del _BLEDY_DCONF[:]
    stan = eksport_pulpitu()
    powody = powody_niepewnosci()
    if powody:
        for b in powody:
            print(f"⚠ {b}")
        print("Obraz ustawień jest teraz niepewny — NIE nadpisuję lustra.")
        print("Powtórz przy odblokowanym, działającym pulpicie.")
        return 1

    stare = wczytaj_pulpit_z_lustra() or {}
    zmienione = sorted(k for k in set(stare) | set(stan) if stare.get(k) != stan.get(k))
    if not zmienione:
        print("Ustawienia pulpitu są już zgodne z lustrem — nie ma czego oddawać.")
        return 0

    print(f"Do oddania {len(zmienione)} kluczy:")
    for k in zmienione:
        print(f"   {k}")
        print(f"      tutaj:     {stan.get(k, 'brak')}")
        print(f"      w lustrze: {stare.get(k, 'brak')}")
    if not getattr(args, "zatwierdzam_wszystko", False):
        if pytaj("Oddać ustawienia tej maszyny do lustra?", "Tn", "t") != "t":
            print("Nic nie zmieniam.")
            return 0

    zapisz_pulpit(stan, PLIK_PULPITU)
    notatka = getattr(args, "notatka", None) or pytaj_tekst(
        "Notatka do dziennika (po co ta zmiana)", "")
    dopisz_zdarzenie("ustawienia", kanal="dconf", ident="pulpit",
                     zrodlo="apka", pliki=zmienione, notatka=notatka or None)
    print(f"Zapisano {len(stan)} kluczy do {PLIK_PULPITU.name} + zdarzenie w dzienniku.")
    git_zapisz(f"lustra: pulpit oddany z {nazwa_maszyny()} ({len(zmienione)} kluczy)")
    return 0


def polecenie_pulpit_oddaj_stan(args):
    """`lustro pulpit oddaj-stan` (kontrakt [209] 2.3.1) — migawka WŁASNEGO stanu
    gałęzi pulpitu do lustra/pulpit/stan/<maszyna>.ini.

    W odróżnieniu od `pulpit oddaj`: to jest czysta OBSERWACJA, bez skutków — plik
    nadpisuje TYLKO ten jednej, własnej maszyny, nigdy cudzy, więc (inaczej niż
    `oddaj`/`wgraj`) nie pyta o zgodę i działa bez terminala bez żadnej flagi.
    Dopiero `pulpit skladaj` (osobna komenda, czysto po stronie repo) decyduje,
    czy i które gałęzie z tej migawki trafią do wspólnego `pulpit.ini`."""
    git_pull_rebase()
    del _BLEDY_DCONF[:]
    stan = eksport_pulpitu()
    powody = powody_niepewnosci()
    if powody:
        for b in powody:
            print(f"⚠ {b}")
        print("Obraz ustawień jest teraz niepewny — NIE zapisuję migawki.")
        print("Powtórz przy odblokowanym, działającym pulpicie.")
        return 1

    PULPIT_STAN.mkdir(parents=True, exist_ok=True)
    plik = PULPIT_STAN / f"{nazwa_maszyny()}.ini"
    zapisz_pulpit(stan, plik, naglowek_linie=[
        f"# Migawka stanu pulpitu maszyny „{nazwa_maszyny()}” — plik GENEROWANY przez",
        "# `lustro pulpit oddaj-stan` (kontrakt [209] 2.3.1). Czysta obserwacja: NIE jest",
        "# wzorcem `pulpit wgraj` sama w sobie — o to, które gałęzie stąd trafiają do",
        "# wspólnego pulpit.ini, decyduje pulpit/zrodla-galezi.toml + `pulpit skladaj`.",
        "# Ścieżki wybrane w pulpit/dconf-lustro.txt; {{HOME}} = katalog domowy maszyny.",
        "",
    ])
    print(f"Migawka zapisana: {plik} ({len(stan)} kluczy).")
    print("To tylko obserwacja własnego stanu — pulpit.ini i system nie zostały ruszone.")
    git_zapisz(f"lustra: migawka pulpitu {nazwa_maszyny()} "
               f"→ pulpit/stan/{nazwa_maszyny()}.ini ({len(stan)} kluczy)")
    return 0


def polecenie_pulpit_skladaj(args):
    """`lustro pulpit skladaj` (kontrakt [209] 2.3.3) — składa `pulpit.ini` z
    przypisanych źródeł PER GAŁĄŹ (pulpit/zrodla-galezi.toml) + migawek maszyn
    (pulpit/stan/<maszyna>.ini). Gałęzie BEZ wpisu zostają z dzisiejszego
    pulpit.ini (dzień wdrożenia = plik pusty = zero zmian, kontrakt rozdz. 6).

    Czysto po stronie repo — NIE dotyka żadnej maszyny (dconf, system), tylko
    plik lustra/pulpit/pulpit.ini. Dlatego, jak `lustro lista`, nie pyta o zgodę —
    to jest przeliczenie pochodnego artefaktu ze źródeł, nie zmiana systemu.

    Brak migawki źródłowej maszyny dla którejkolwiek przypisanej gałęzi = TWARDY
    błąd (kontrakt rozdz. 8, przypadek 6) — PRZERYWA CAŁOŚĆ bez zapisu, żeby nigdy
    nie zapisać niekompletnego/milczącego złożenia (ten sam wzorzec ostrożności co
    `pulpit wgraj`, które przerywa, gdy nie umie zrobić kopii bezpieczeństwa)."""
    git_pull_rebase()
    galezie = wczytaj_zrodla_galezi()
    stare = wczytaj_pulpit_z_lustra() or {}

    if not galezie:
        print(f"{ZRODLA_GALEZI.relative_to(REPO)} nie ma żadnych wpisów [[galaz]] — "
              f"pulpit.ini zostaje BEZ ZMIAN (wszystkie gałęzie zostają ze starego pliku).")
        return 0

    nowy = dict(stare)
    zmiany_per_zrodlo = {}
    bledy = []

    for g in galezie:
        sciezka, zrodlo = g["sciezka"], g["zrodlo"]
        stan_zrodla = wczytaj_stan_maszyny(zrodlo)
        if stan_zrodla is None:
            bledy.append(f"gałąź {sciezka}: brak migawki maszyny „{zrodlo}” "
                         f"({(PULPIT_STAN / (zrodlo + '.ini')).relative_to(REPO)}) — "
                         f"uruchom tam najpierw `lustro pulpit oddaj-stan`")
            continue
        prefiks = sciezka if sciezka.endswith("/") else sciezka + "/"
        klucze_zrodla = {k: v for k, v in stan_zrodla.items()
                         if k == sciezka or k.startswith(prefiks)}
        # usuń spod tej gałęzi wszystko, co dziś jest w pulpit.ini (żeby klucze,
        # których źródło już nie ma, zniknęły), potem wstaw świeże z migawki źródła
        for k in [k for k in nowy if k == sciezka or k.startswith(prefiks)]:
            del nowy[k]
        nowy.update(klucze_zrodla)
        zmiany_per_zrodlo.setdefault(zrodlo, []).append(sciezka)

    if bledy:
        print(f"BŁĄD — {len(bledy)} gałęzi bez migawki źródła, PRZERYWAM "
              f"(nie zapisuję niekompletnego złożenia):")
        for b in bledy:
            print(f"   • {b}")
        return 1

    if nowy == stare:
        print("Złożenie nie zmienia niczego w pulpit.ini (migawki źródeł już zgodne "
              "z tym, co tam jest).")
        return 0

    zmienione_klucze = sorted(k for k in set(stare) | set(nowy) if stare.get(k) != nowy.get(k))
    zapisz_pulpit(nowy, PLIK_PULPITU)
    print(f"Złożono {PLIK_PULPITU.name} z {len(galezie)} przypisanych gałęzi "
          f"({len(zmienione_klucze)} zmienionych kluczy):")
    for zrodlo, sciezki in sorted(zmiany_per_zrodlo.items()):
        print(f"   źródło {zrodlo}: {', '.join(sciezki)}")

    for zrodlo, sciezki in zmiany_per_zrodlo.items():
        dopisz_zdarzenie(
            "ustawienia", kanal="dconf", ident="pulpit", zrodlo="sklad",
            pliki=sciezki, maszyna=zrodlo,
            notatka=f"gałęzie przejęte do wspólnego pulpit.ini przez "
                    f"`lustro pulpit skladaj` (uruchomione na {nazwa_maszyny()}); "
                    f"kontrakt [209] 2.3.3")

    git_zapisz(f"lustra: pulpit.ini złożony na {nazwa_maszyny()} "
               f"({len(galezie)} gałęzi z {len(zmiany_per_zrodlo)} źródeł)")
    return 0


def polecenie_pulpit_wgraj(args):
    """Ustawienia z lustra → na tę maszynę. ZAWSZE kopia przed nadpisaniem (8.11).

    ⚠️ Bez terminala (tryb nieinteraktywny) wgrywa TYLKO z jawną flagą
    `--zatwierdzam-wszystko` — inaczej odmawia (brak 15 z Katany, 25.08)."""
    if not getattr(args, "zatwierdzam_wszystko", False) and not sys.stdin.isatty():
        print("Brak terminala (tryb nieinteraktywny): `pulpit wgraj` ZMIENIA ustawienia,")
        print("więc bez realnego pytania ODMAWIAM. Jawna zgoda automatu:")
        print("    lustro pulpit wgraj --zatwierdzam-wszystko")
        return 1
    git_pull_rebase()          # świeży wzorzec pulpitu z GitHuba
    if wczytaj_pulpit_z_lustra() is None:
        print("Lustro nie ma jeszcze zapisanych ustawień pulpitu — nie ma czego wgrywać.")
        return 1
    del _BLEDY_DCONF[:]
    rozne = roznice_pulpitu()
    powody = powody_niepewnosci()
    if powody:
        for b in powody:
            print(f"⚠ {b}")
        print("Obraz bieżących ustawień jest niepewny — NIE wgrywam "
              "(nie byłoby czego sensownie cofać).")
        return 1
    if not rozne:
        print("Ustawienia pulpitu są już zgodne z lustrem — nie ma czego wgrywać.")
        return 0

    print(f"Do wgrania {len(rozne)} kluczy:")
    for klucz, a, b in rozne:
        print(f"   {klucz}")
        print(f"      tutaj:     {a if a is not None else 'brak'}")
        print(f"      z lustra:  {b if b is not None else 'brak'}")

    # --- OBOWIĄZKOWA kopia poprzedniego stanu (spec 8.11) ---
    KOPIE.mkdir(parents=True, exist_ok=True)
    kopia = KOPIE / f"dconf-{datetime.now():%Y-%m-%d-%H%M%S}.ini"
    kod, out = uruchom(["dconf", "dump", "/"])
    if kod != 0:
        print("⚠ Nie udało się zrobić kopii stanu dconf — PRZERYWAM. "
              "Bez kopii nie wgrywam niczego.")
        return 1
    kopia.write_text(out, encoding="utf-8")
    print(f"Kopia poprzedniego stanu: {kopia}")
    print(f"   cofnięcie: dconf load / < {kopia}")

    if not getattr(args, "zatwierdzam_wszystko", False):
        if pytaj("Wgrać ustawienia z lustra na tę maszynę?", "Tn", "t") != "t":
            print("Nic nie zmieniam (kopia zostaje, nie przeszkadza).")
            return 0

    # podmiana {{HOME}} z powrotem na katalog domowy TEJ maszyny (spec 8.4)
    tresc = PLIK_PULPITU.read_text(encoding="utf-8").replace("{{HOME}}", str(DOM))
    kod, _ = uruchom(["dconf", "load", "/"], wejscie=tresc)
    if kod != 0:
        print("⚠ `dconf load` zakończone błędem — sprawdź kopię wyżej.")
        return 1

    del _BLEDY_DCONF[:]
    po = roznice_pulpitu()
    print(f"Wgrane. Kluczy nadal różnych po wgraniu: {len(po) if po else 0} "
          f"(0 = wszystko się przyjęło).")
    dopisz_zdarzenie("ustawienia", kanal="dconf", ident="pulpit", zrodlo="apka",
                     pliki=[k for k, _, _ in rozne],
                     notatka=f"wgrane z lustra; kopia poprzedniego stanu: {kopia.name}")
    for u in kontrola_pulpitu():
        print(f"⚠ {u}")
    git_zapisz(f"lustra: pulpit wgrany na {nazwa_maszyny()} ({len(rozne)} kluczy)")
    return 0


# ---------------------------------------------------------------- polecenie: sync

def polecenie_sync_auto(args):
    """
    `lustro sync --auto` — Faza 3 planu automatu (0_Architekt/plan-automat-lustra-
    2026-08-25.md), rozszerzone w sprawie [213] („dziennik przy KAŻDEJ zmianie,
    nie tylko przez `lustro dodaj`”): stacja ma dociągać braki i księgować
    rozbieżności SAMA, bez terminala i bez pytań (wołane z timera `lustro-sync.
    service` po `chezmoi update --force`, co 60 min).

    Zakres:
      • TAK — instalacja: pakiet jest w dzienniku „dodano” gdzie indziej, a tu go
        nie ma (apt/snap/flatpak) → instalacja + wpis do dziennika (`zrodlo:
        sync`) — dokładnie ten sam kod co interaktywny `sync` (`wykonaj_pozycje`).
      • TAK [252] — kanał `skrypt` (pozycje stawiane skryptem wg skrypty.toml,
        np. AI Launcher): ta sama droga co wyżej, nieinteraktywnie. Pozycja
        z niespełnionym `wymaga` (np. katalog roboczy jeszcze nie dojechał
        Syncthingiem na nowej stacji) jest ODKŁADANA z czytelnym powodem —
        nie liczy się jako nieudana, kolejny bieg timera spróbuje ponownie.
      • TAK — brakujące zewnętrzne źródło apt z zrodla-apt.toml (klucz + wpis
        .list), niezależnie od tego, czy akurat instalujemy z niego pakiet —
        ale WYŁĄCZNIE na maszynie będącej członkiem lustra ([218b], decyzja
        usera 27.08 „serwer nie ma dostawać wszystkiego”; patrz
        `zrodla_nalezne_tej_maszynie`). Nie-członek dostaje pojedyncze źródło
        tylko przez jawny `override obecne` na pakiet z tego źródła.
      • TAK [213] — księgowanie „na maszynie jest, w dzienniku brak” (kategoria
        `niezapisane` z `zbierz_pozycje()`): dopisujemy „dodano” (zrodlo: wykryte)
        automatycznie, bez pytania. To jest SIATKA BEZPIECZEŃSTWA dla apt (gdyby
        hook dpkg z `polecenie_hak_apt` akurat zawiódł/nie był jeszcze wdrożony)
        i JEDYNA droga księgowania dla kanałów bez hooka: snap, flatpak,
        gnome-extension (te ostatnie trafiają do `niezapisane` przez inwentarz
        rozszerzeń na dysku, patrz `zbierz_pozycje()`). Bezpieczne, bo WYŁĄCZNIE
        dopisuje fakt „to tu jest” — nic nie instaluje, nic nie usuwa, nikomu
        niczego nie każe zrobić.
      • NIE — rodzaj "usun" (dziennik mówi „usunięty gdzie indziej”) — auto
        NIGDY nic nie odinstalowuje, zgodnie z zasadą nadrzędną.
      • NIE [213, decyzja pkt 3] — kategoria `usuniete_poza` („dziennik TEJ
        maszyny mówi „jest”, na maszynie już nie ma”) NADAL tylko raportowana,
        NIE księgowana automatycznie jako „usunieto”. Uzasadnienie: to jest
        WNIOSKOWANIE z różnicy inwentarza po czasie, nie zapis realnej
        transakcji — automat nie ma jak odróżnić „user świadomie usunął to
        poleceniem, którego hook nie złapał” od „coś zniknęło samo, przy okazji
        aktualizacji/autoremove”. Napisanie „usunieto” zmienia konsensus dla
        CAŁEGO lustra (spec 4.5 — nowsze zdarzenie wygrywa) i przy błędnym
        odgadnięciu wyglądałoby jak cichy rozkaz „usuńcie to wszędzie”, którego
        nikt świadomie nie wydał. `polecenie_hak_apt` (hook dpkg) NIE ma tego
        problemu — tam zdarzenie „usunieto” zapisuje się w chwili PRAWDZIWEJ,
        jednoznacznej transakcji apt, więc jest bezpieczne mimo tego samego
        wpływu na konsensus. Zgodnie z „zniknięcie z jednej maszyny-lustra to
        rozbieżność DO DOCIĄGNIĘCIA NA NIEJ, nie usunięcie wszędzie" — właściwa
        reakcja to `lustro usun` (świadomy zapis) albo ponowna instalacja, obie
        ręczne.
      • NIE: pulpit (`dconf`) — decyzja usera [195]: `pulpit oddaj` tylko ręcznie.
      • NIE: kanał `gnome-extension` INSTALACJA/USUNIĘCIE (tylko KSIĘGOWANIE
        „obecne” wyżej) — poza zakresem [194] (nie potrzebuje sudo, ale ma
        własne, nieprzetestowane w pełni zachowanie przy świeżej instalacji —
        zostaje w gestii `lustro pulpit rozszerzenia`, ręcznie).
      • Statusy `testowe`/`wyjatek` (statusy-pozycji.toml) są już odsiane w
        `zbierz_pozycje()` — auto nie musi ich znać osobno.
    """
    git_pull_rebase()          # świeży dziennik — timer i tak woła to przez `chezmoi
                                # update` wcześniej, ale `sync --auto` ma być bezpieczne
                                # też uruchomione osobno (ta sama zasada co `sync`/`dodaj`)
    dane = zbierz_pozycje()
    naglowek(dane)
    args.zatwierdzam_wszystko = True   # nigdy nie pytać — nie ma komu odpowiedzieć

    zrobione, nieudane, zaksiegowane = 0, 0, 0

    brak_zrodel = zrodla_nalezne_tej_maszynie()   # [218b] — tylko członkom lustra
    if brak_zrodel:
        print(f"ŹRÓDŁA APT DO DODANIA ({len(brak_zrodel)}):")
        for z in brak_zrodel:
            print(f"  • {z.get('nazwa')} ({z.get('url')})")
            if dodaj_zrodlo_apt(z):
                zrobione += 1
            else:
                nieudane += 1
        print()

    # [257c] — samonaprawa: zdejmij nasz wpis źródła tam, gdzie pakiet już
    # utrzymuje własny (inaczej apt przy każdym `update` ostrzega
    # „configured multiple times"). `dpkg` jest w NOPASSWD [194], więc działa
    # z timera bez hasła. Nic nie robi, gdy duplikatu nie ma.
    posprzataj_zdublowane_zrodla()

    do_instalacji = [(kanal, ident, zdarz)
                     for (kanal, ident), zdarz, rodzaj in dane["rozbieznosci"]
                     if rodzaj == "brak-tutaj" and kanal in KANALY_INSTALOWALNE]

    # [252] kanał skrypt: pozycje bez definicji albo z niespełnionym `wymaga`
    # (np. katalog roboczy jeszcze nie dojechał Syncthingiem) ODKŁADAMY z powodem —
    # to nie błąd, timer spróbuje za godzinę.
    odlozone = []
    if do_instalacji:
        skrypty = wczytaj_skrypty()
        gotowe = []
        for kanal, ident, zdarz in do_instalacji:
            if kanal == KANAL_SKRYPT:
                d = skrypty.get(ident)
                powody = ([f"brak definicji w {SKRYPTY_TOML.name}"] if d is None
                          else wymagania_niespelnione(d))
                if powody:
                    odlozone.append((ident, powody))
                    continue
            gotowe.append((kanal, ident, zdarz))
        do_instalacji = gotowe
    if odlozone:
        print(f"ODŁOŻONE — POZYCJE SKRYPT CZEKAJĄ NA WARUNKI ({len(odlozone)}):")
        for ident, powody in odlozone:
            print(f"  • {ident} (skrypt): " + "; ".join(powody))
        print("  (to nie błąd — kolejny bieg timera lustro-sync spróbuje ponownie)")
        print()

    if do_instalacji:
        print(f"PAKIETY DO DOCIĄGNIĘCIA ({len(do_instalacji)}):")
        for kanal, ident, zdarz in do_instalacji:
            print(f"  • {ident} ({kanal}) — wg dziennika {zdarz.get('maszyna')}")
        print()
        for kanal, ident, zdarz in do_instalacji:
            if kanal == "apt":
                zapewnij_zrodlo_dla(ident, args)   # sieć bezpieczeństwa — patrz wyżej
            poz = {"rodzaj": "instaluj", "kanal": kanal, "id": ident, "zdarz": zdarz}
            if wykonaj_pozycje(poz, args):
                zrobione += 1
            else:
                nieudane += 1

    # [213] — księgowanie „jest tutaj, w dzienniku brak" (patrz zakres wyżej).
    # Celowo NIEZALEŻNE od członkostwa w lustrze — to zapis faktu o TEJ maszynie,
    # nie o konsensusie fleety (działa tak samo na serwerze, `czlonek_lustra =
    # false`, bo `zbierz_pozycje()` liczy `niezapisane` poza bramką reguły 4).
    if dane["niezapisane"]:
        print(f"KSIĘGOWANIE — NA MASZYNIE JEST, W DZIENNIKU BRAK ({len(dane['niezapisane'])}):")
        for (kanal, ident), wersja in dane["niezapisane"]:
            print(f"  • {ident} ({kanal}, {wersja}) → dopisuję „dodano” (zrodlo: wykryte)")
            dopisz_zdarzenie("dodano", kanal=kanal, ident=ident, wersja=wersja,
                             zrodlo="wykryte",
                             notatka="wykryte automatycznie przez `lustro sync --auto` — "
                                     "zainstalowane poza `lustro dodaj` (kanał bez hooka "
                                     "dpkg — snap/flatpak/gnome-extension — albo siatka "
                                     "bezpieczeństwa dla apt) [213]")
            zaksiegowane += 1
        print()

    # Migawka inwentarza (27.08) — ZAWSZE, bezwarunkowo (jak `git_zapisz` niżej):
    # tania operacja (żadnej instalacji), a to jedyny mechanizm, który wypełnia
    # `lustra/inwentarz/<maszyna>.json` cyklicznie dla stacji. Pisze plik TYLKO
    # gdy treść się zmieniła (`zapisz_migawke_inwentarza`) — commit robi
    # wspólny `git_zapisz()` na końcu tego przebiegu, nie osobny.
    zmienione_inw, n_inw = zapisz_migawke_inwentarza()
    if zmienione_inw:
        print(f"Migawka inwentarza zaktualizowana ({n_inw} pozycji).")
        print()

    pominiete = len(dane["usuniete_poza"]) + (1 if roznice_pulpitu() else 0)
    if not do_instalacji and not brak_zrodel and not dane["niezapisane"] and not odlozone:
        print("Nic do automatycznego dociągnięcia/księgowania.")
    print()
    if odlozone:
        print(f"Odłożone (kanał skrypt, czekają na warunki — patrz wyżej): {len(odlozone)}.")
    if pominiete:
        print(f"Pominięte celowo (poza zakresem --auto — patrz `lustro status`): "
              f"{pominiete} pozycji (usunięcia gdzieś indziej / „dziennik mówi jest, "
              f"na maszynie brak” — kierunek „usunieto” zostaje ręczny, [213] pkt 3 / "
              f"pulpit).")
    print(f"Auto-sync: {zrobione} wykonanych, {zaksiegowane} zaksięgowanych, "
          f"{nieudane} nieudanych.")
    # Zawsze (nie tylko gdy `zrobione`) — hook dpkg (`polecenie_hak_apt`) mógł
    # dopisać zdarzenia do dziennika MIĘDZY biegami timera; `git_zapisz` i tak
    # sam sprawdza `git status --porcelain` i nic nie robi, gdy repo jest czyste,
    # więc to bezpieczne wywołać bezwarunkowo (spec „lekko i odpornie" [213]).
    czesci = []
    if zrobione:
        czesci.append(f"{zrobione} dociągniętych")
    if zaksiegowane:
        czesci.append(f"{zaksiegowane} zaksięgowanych (wykryte)")
    if zmienione_inw:
        czesci.append(f"migawka inwentarza ({n_inw} pozycji)")
    opis = ", ".join(czesci) if czesci else "porządki (hook dpkg / zaległe commity)"
    git_zapisz(f"lustra: auto-sync na {nazwa_maszyny()} — {opis} "
               f"(--auto, [194]/[213])")
    return 1 if nieudane else 0


def polecenie_sync(args):
    if getattr(args, "auto", False):
        return polecenie_sync_auto(args)

    if args.tylko_pokaz:
        print("(tryb --tylko-pokaz: niczego nie zmieniam, o nic nie pytam)")
        print()
        return polecenie_status(args)

    git_pull_rebase()
    posprzataj_zdublowane_zrodla()      # [257c] — patrz `polecenie_sync_auto`
    dane = zbierz_pozycje()
    naglowek(dane)

    pozycje = []
    for (kanal, ident), zdarz, rodzaj in dane["rozbieznosci"]:
        if rodzaj == "brak-tutaj":
            pozycje.append({
                "rodzaj": "instaluj", "kanal": kanal, "id": ident, "zdarz": zdarz,
                "tytul": f"{ident} — NIE MA tutaj, JEST na {zdarz['maszyna']}",
                "propozycja": f"zainstalować tutaj ({kanal})"})
        else:
            if args.tylko_instaluj:
                continue
            pozycje.append({
                "rodzaj": "usun", "kanal": kanal, "id": ident, "zdarz": zdarz,
                "tytul": f"{ident} — JEST tutaj, USUNIĘTY na {zdarz['maszyna']}",
                "propozycja": f"odinstalować tutaj ({kanal})"})
    for (kanal, ident), wersja in dane["niezapisane"]:
        pozycje.append({
            "rodzaj": "zapisz-dodano", "kanal": kanal, "id": ident, "wersja": wersja,
            "tytul": f"{ident} ({kanal}, {wersja}) — jest na maszynie, brak w dzienniku",
            "propozycja": "dopisać do dziennika (zrodlo: reczne)"})
    for (kanal, ident), zdarz in dane["usuniete_poza"]:
        pozycje.append({
            "rodzaj": "zapisz-usunieto", "kanal": kanal, "id": ident, "zdarz": zdarz,
            "tytul": f"{ident} ({kanal}) — dziennik mówi „jest”, na maszynie go nie ma",
            "propozycja": "dopisać do dziennika (zrodlo: reczne)"})

    del _BLEDY_DCONF[:]
    rozne = roznice_pulpitu()
    powody = powody_niepewnosci()
    if rozne and not powody:
        pozycje.append({
            "rodzaj": "pulpit", "kanal": "dconf", "id": "pulpit", "rozne": rozne,
            "tytul": f"Ustawienia pulpitu różnią się od lustra ({len(rozne)} kluczy)",
            "propozycja": "[o]ddać stąd do lustra / [w]grać z lustra tutaj"})

    # Kontrola poprawności pulpitu (skróty/czcionki/tapeta/zakładki/rozszerzenia GNOME) —
    # tylko informacyjnie, apka jej sama nie naprawia (tak jak w `status`), ale user ma to
    # zobaczyć również tutaj, a nie dopiero po osobnym `lustro pulpit sprawdz`.
    uwagi_pulpitu = [] if powody else kontrola_pulpitu()
    if uwagi_pulpitu:
        print("PULPIT — KONTROLA (informacyjnie, o zgodę pyta osobna komenda):")
        for u in uwagi_pulpitu:
            print(f"    ⚠ {u}")
        print()

    if not pozycje:
        if not uwagi_pulpitu:
            print("Nic do wyrównania — lustro i maszyna mówią to samo.")
        else:
            print("Nic do wyrównania interaktywnie — patrz uwagi wyżej.")
        return 0

    print(f"DO ROZSTRZYGNIĘCIA ({len(pozycje)})")
    print()

    zatwierdzone, hurtem = [], bool(args.zatwierdzam_wszystko)
    for nr, poz in enumerate(pozycje, 1):
        print(f"{nr:2}. {poz['tytul']}")
        if (poz.get("zdarz") or {}).get("notatka"):
            print(f"    notatka źródła: \"{poz['zdarz']['notatka']}\"")
        print(f"    propozycja: {poz['propozycja']}")

        if poz["rodzaj"] == "pulpit":
            if hurtem:
                poz["kierunek"] = "o"
                zatwierdzone.append(poz)
                print("    → oddaję stąd do lustra (hurtem)")
                print()
                continue
            odp = pytaj("Pulpit: [o]ddaj stąd / [w]graj z lustra / [n]ie ruszaj / "
                        "[s]zczegóły", "onws", "n")
            while odp == "s":
                for klucz, a, b in poz["rozne"]:
                    print(f"      {klucz}\n        tutaj:     {a}\n        w lustrze: {b}")
                odp = pytaj("Pulpit: [o]ddaj stąd / [w]graj z lustra / [n]ie ruszaj",
                            "onw", "n")
            if odp in ("o", "w"):
                poz["kierunek"] = odp
                zatwierdzone.append(poz)
            print()
            continue

        if hurtem:
            zatwierdzone.append(poz)
            print("    → zatwierdzone hurtem")
            print()
            continue

        while True:
            odp = pytaj("[T]ak / [n]ie / [p]omiń na zawsze / [s]zczegóły / "
                        "[h]urtem — T dla wszystkich pozostałych", "Tnpsh", "n")
            if odp == "s":
                pokaz_szczegoly(poz, dane)
                continue
            break
        if odp == "h":
            hurtem = True
            zatwierdzone.append(poz)
        elif odp == "t":
            zatwierdzone.append(poz)
        elif odp == "p":
            powod = pytaj_tekst("Krótko: dlaczego ta maszyna ma odstawać", "")
            dopisz_pomijane(poz["kanal"], poz["id"], powod)
            print(f"    → zapisane w {plik_pomijanych().name} — apka już o to nie zapyta")
        print()

    if not zatwierdzone:
        print("Nic nie zatwierdzono — nic nie zmieniam.")
        return 0

    print(f"DO WYKONANIA ({len(zatwierdzone)}):")
    for poz in zatwierdzone:
        print(f"   • {poz['rodzaj']}: {poz['id']} ({poz['kanal']})")
    if not args.zatwierdzam_wszystko:
        if pytaj("Wykonać?", "Tn", "t") != "t":
            print("Odwołane — nic nie zmieniam.")
            return 0
    print()

    zrobione = 0
    for poz in zatwierdzone:
        zrobione += wykonaj_pozycje(poz, args)

    print()
    print(f"Wykonane: {zrobione} z {len(zatwierdzone)} pozycji.")
    git_zapisz(f"lustra: sync na {nazwa_maszyny()} — {zrobione} pozycji")
    return 0


def polecenie_profil(args):
    """
    `lustro profil status` — co profil tej maszyny obejmuje i co na niej stoi mimo to.
    `lustro profil sprzataj` — usuwa (z pytaniem przy KAŻDEJ pozycji) programy, które
    do profilu tej maszyny nie należą. Sprawa [284].

    Świadomie osobna komenda, a nie tryb `sync --auto`: `sync --auto` chodzi z timera
    co 60 minut i z zasady NIGDY niczego nie odinstalowuje. Zawężenie profilu to
    jednorazowa decyzja człowieka o roli maszyny — ma zostać wykonana raz, na oczach
    usera, a nie „przy okazji” w tle.
    """
    dane = zbierz_pozycje()
    naglowek(dane)
    profil, wzorce = dane["profil"], dane["wzorce_profilu"]
    print(f"PROFIL TEJ MASZYNY: {profil}")
    if "*" in wzorce or not wzorce:
        print("  Bez ograniczeń — maszyna dostaje wszystko, co ma lustro.")
    else:
        print(f"  Wzorców „zostaja”: {len(wzorce)} (definicja: {PROFILE_TOML.name})")
    print()

    poza = dane.get("poza_profilem") or []
    if not poza:
        print("Nic nie stoi na tej maszynie poza profilem — nie ma czego sprzątać.")
        return 0

    do_usuniecia = [(k, w) for k, w in poza if k[0] in ("apt", "snap", "flatpak")]
    reszta = [(k, w) for k, w in poza if k[0] not in ("apt", "snap", "flatpak")]

    print(f"STOI TUTAJ, A NIE NALEŻY DO PROFILU „{profil}” ({len(poza)}):")
    for (kanal, ident), wersja in poza:
        print(f"   • {ident} ({kanal}, {wersja})")
    print()
    if reszta:
        print(f"  Z tego {len(reszta)} pozycji kanałów spoza apt/snap/flatpak "
              f"(rozszerzenia GNOME, pozycje kanału `skrypt`) sprzątanie NIE rusza — "
              f"to pliki w katalogu użytkownika, nie zainstalowane programy.")
        print()

    if args.co == "status":
        print("To był tylko podgląd. Usuwanie: lustro profil sprzataj")
        return 0

    if not do_usuniecia:
        print("Nic do odinstalowania.")
        return 0

    git_pull_rebase()
    zatwierdzone, hurtem = [], bool(args.zatwierdzam_wszystko)
    for nr, ((kanal, ident), wersja) in enumerate(do_usuniecia, 1):
        poz = {"rodzaj": "usun-profil", "kanal": kanal, "id": ident,
               "powod": f"poza profilem „{profil}” tej maszyny [284]"}
        print(f"{nr:2}. {ident} ({kanal}, {wersja}) — poza profilem „{profil}”")
        print(f"    propozycja: odinstalować tutaj")
        if hurtem:
            zatwierdzone.append(poz)
            print("    → zatwierdzone hurtem")
            print()
            continue
        odp = pytaj("[T]ak / [n]ie / [h]urtem — T dla wszystkich pozostałych", "Tnh", "n")
        if odp == "h":
            hurtem = True
            zatwierdzone.append(poz)
        elif odp == "t":
            zatwierdzone.append(poz)
        print()

    if not zatwierdzone:
        print("Nic nie zatwierdzono — nic nie zmieniam.")
        return 0
    print(f"DO WYKONANIA ({len(zatwierdzone)}):")
    for poz in zatwierdzone:
        print(f"   • usun: {poz['id']} ({poz['kanal']})")
    if not args.zatwierdzam_wszystko and pytaj("Wykonać?", "Tn", "t") != "t":
        print("Odwołane — nic nie zmieniam.")
        return 0
    print()
    zrobione = sum(wykonaj_pozycje(poz, args) for poz in zatwierdzone)
    print()
    print(f"Wykonane: {zrobione} z {len(zatwierdzone)} pozycji.")
    git_zapisz(f"lustra: profil {profil} na {nazwa_maszyny()} — "
               f"{zrobione} pozycji spoza profilu usuniętych")
    return 0


def pokaz_szczegoly(poz, dane):
    kanal, ident = poz["kanal"], poz["id"]
    print(f"    --- szczegóły: {ident} ({kanal}) ---")
    for z in dane["historia"].get((kanal, ident), []):
        print(f"      {data_ludzka(z.get('ts'))}  {z.get('maszyna')}: "
              f"{z.get('zdarzenie')} (zrodlo: {z.get('zrodlo')})"
              + (f" — {z['notatka']}" if z.get("notatka") else ""))
    if poz["rodzaj"] == "instaluj":
        print(f"      komenda: {' '.join(komenda_instalacji(kanal, ident) or ['?'])}")
    if poz["rodzaj"] == "usun":
        print(f"      komenda: {' '.join(komenda_usuniecia(kanal, ident) or ['?'])}")
        mapa = wczytaj_mape_ustawien()
        if mapa.get(ident):
            print(f"      ustawienia w lustrze: {' '.join(mapa[ident])}")


def wykonaj_pozycje(poz, args):
    """Wykonuje JEDNĄ zatwierdzoną pozycję. Zwraca 1 przy powodzeniu, 0 przy porażce.
    Kolejność ze spec 9.3: wykonaj → sprawdź inwentaryzacją → dopiero wtedy dziennik."""
    kanal, ident, rodzaj = poz["kanal"], poz["id"], poz["rodzaj"]
    zrodlowe = poz.get("zdarz") or {}
    # `ts` puste = zdarzenie SYNTETYCZNE (kontrakt [209], override bez żadnego realnego
    # zdarzenia w dzienniku nigdzie — `zbierz_pozycje` sam takie tworzy tylko do wyświetlenia
    # w `status`/`sync`). Bez tego warunku pole `za` w dzienniku dostałoby fałszywe
    # „maszyna: (brak zdarzenia — tylko override)" zamiast realnej pary maszyna+ts.
    za = ({"maszyna": zrodlowe.get("maszyna"), "ts": zrodlowe.get("ts")}
          if zrodlowe.get("maszyna") and zrodlowe.get("ts")
          and zrodlowe.get("maszyna") != nazwa_maszyny()
          else None)

    # rozszerzenia GNOME — osobna droga (nie ma komendy apt/snap/flatpak);
    # instalacja z extensions.gnome.org, usunięcie z katalogu usera, weryfikacja Z DYSKU
    if kanal == "gnome-extension" and rodzaj in ("instaluj", "usun"):
        if rodzaj == "instaluj":
            print(f"[{ident}] instaluję (gnome-extension, extensions.gnome.org)…")
            ok, komunikat = pobierz_i_zainstaluj_rozszerzenie(ident, gnome_shell_wersja())
            print(f"    {komunikat}")
            po = rozszerzenia_na_dysku(tylko_uzytkownika=True)
            if not ok or ident not in po:
                print("    ⚠ rozszerzenia nie widzę na dysku — dziennika NIE ruszam")
                return 0
            dopisz_zdarzenie("dodano", kanal=kanal, ident=ident, wersja=po.get(ident),
                             zrodlo="sync", za=za,
                             notatka="włączenie zostaje warstwie pulpitu (dconf); "
                                     "żywa powłoka zobaczy rozszerzenie po przelogowaniu")
            print("    ✓ zainstalowane, zapisane w dzienniku (włączy pulpit/relog)")
            return 1
        print(f"[{ident}] usuwam (gnome-extension)…")
        kod, out = uruchom(["gnome-extensions", "uninstall", ident])
        if ident in rozszerzenia_na_dysku(tylko_uzytkownika=True):
            # gnome-extensions bywa ślepy na świeże instalacje — katalog usera wprost
            shutil.rmtree(KATALOGI_ROZSZERZEN[0] / ident, ignore_errors=True)
        if ident in rozszerzenia_na_dysku(tylko_uzytkownika=True):
            print(f"    ⚠ rozszerzenie nadal jest na dysku (kod {kod}) — dziennika NIE ruszam")
            return 0
        dopisz_zdarzenie("usunieto", kanal=kanal, ident=ident, zrodlo="sync", za=za,
                         notatka=zrodlowe.get("notatka"))
        print("    ✓ usunięte, zapisane w dzienniku")
        return 1

    # kanał skrypt [252] — polecenia z skrypty.toml, nieinteraktywnie, weryfikacja
    # ponownym `sprawdz`; niespełnione `wymaga` = odłożone (powód), nie porażka
    if kanal == KANAL_SKRYPT and rodzaj in ("instaluj", "usun"):
        d = wczytaj_skrypty().get(ident)
        if d is None:
            print(f"[{ident}] brak definicji w {SKRYPTY_TOML.name} — nie wiem, jak "
                  f"{'postawić' if rodzaj == 'instaluj' else 'usunąć'} tę pozycję; pomijam")
            return 0
        if rodzaj == "instaluj":
            powody = wymagania_niespelnione(d)
            if powody:
                print(f"[{ident}] odłożone (skrypt): " + "; ".join(powody))
                return 0
            print(f"[{ident}] instaluję (skrypt: {d['zainstaluj']})…")
            kod = zainstaluj_skrypt(d)
            wersja = inwentarz_skrypt({ident: d}).get(ident)
            if wersja is None:
                print(f"    ⚠ po skrypcie `sprawdz` nadal nie widzi pozycji (kod {kod}) — "
                      f"dziennika NIE ruszam")
                return 0
            dopisz_zdarzenie("dodano", kanal=kanal, ident=ident, wersja=wersja,
                             zrodlo="sync", za=za)
            print(f"    ✓ zainstalowane ({wersja}), zapisane w dzienniku")
            return 1
        if not d.get("usun"):
            print(f"[{ident}] pozycja skrypt bez pola `usun` w {SKRYPTY_TOML.name} — "
                  f"usuń ręcznie; `lustro sync` potem zaproponuje wpis „usunieto”")
            return 0
        print(f"[{ident}] usuwam (skrypt: {d['usun']})…")
        kod, _ = uruchom_skrypt(d["usun"], timeout=300)
        if inwentarz_skrypt({ident: d}).get(ident) is not None:
            print(f"    ⚠ `sprawdz` nadal widzi pozycję (kod {kod}) — dziennika NIE ruszam")
            return 0
        dopisz_zdarzenie("usunieto", kanal=kanal, ident=ident, zrodlo="sync", za=za,
                         notatka=zrodlowe.get("notatka"))
        print("    ✓ usunięte, zapisane w dzienniku")
        return 1

    if rodzaj == "instaluj":
        print(f"[{ident}] instaluję ({kanal})…")
        kod = _z_tlumikiem_haka(komenda_instalacji(kanal, ident))
        wersja = sprawdz_jedna_pozycje(kanal, ident)
        if wersja is None:
            print(f"    ⚠ po instalacji programu NADAL nie widzę (kod {kod}) — "
                  f"dziennika NIE ruszam")
            return 0
        dopisz_zdarzenie("dodano", kanal=kanal, ident=ident, wersja=wersja,
                         zrodlo="sync", za=za)
        print(f"    ✓ zainstalowane ({wersja}), zapisane w dzienniku")
        return 1

    if rodzaj == "usun":
        print(f"[{ident}] usuwam ({kanal})…")
        kod = _z_tlumikiem_haka(komenda_usuniecia(kanal, ident))
        if sprawdz_jedna_pozycje(kanal, ident) is not None:
            print(f"    ⚠ program nadal jest na maszynie (kod {kod}) — "
                  f"dziennika NIE ruszam")
            return 0
        dopisz_zdarzenie("usunieto", kanal=kanal, ident=ident, zrodlo="sync", za=za,
                         notatka=zrodlowe.get("notatka"))
        print("    ✓ usunięte, zapisane w dzienniku")
        return 1

    if rodzaj == "usun-profil":
        # [284] usunięcie DLATEGO, że pozycja nie należy do profilu tej maszyny.
        # Zdarzenie ma WŁASNĄ nazwę i to jest rdzeń bezpieczeństwa całej operacji:
        # `stan_oczekiwany()` liczy konsensus wyłącznie ze zdarzeń "dodano"/"usunieto",
        # więc "usunieto-profil" NIE zmienia oczekiwań pozostałych maszyn. Gdyby zapisać
        # zwykłe "usunieto", sprzątanie Katany wyglądałoby dla Vostro i HP jak rozkaz
        # „usuńcie u siebie LibreOffice’a” — a nikt takiej decyzji nie podjął.
        if kanal not in ("apt", "snap", "flatpak"):
            # Świadome ograniczenie: rozszerzenia GNOME i pozycje kanału `skrypt`
            # to pliki i rejestracje w katalogu użytkownika, nie zainstalowane
            # programy — nic nie ważą i nic nie uruchamiają w tle. Sprzątanie
            # profilu ich nie rusza; kto chce, usuwa je `lustro usun`.
            print(f"[{ident}] kanał {kanal} — sprzątanie profilu tego nie rusza; "
                  f"w razie potrzeby: lustro usun {ident}")
            return 0
        print(f"[{ident}] usuwam — poza profilem tej maszyny ({kanal})…")
        kod = _z_tlumikiem_haka(komenda_usuniecia(kanal, ident))
        if sprawdz_jedna_pozycje(kanal, ident) is not None:
            print(f"    ⚠ program nadal jest na maszynie (kod {kod}) — dziennika NIE ruszam")
            return 0
        dopisz_zdarzenie("usunieto-profil", kanal=kanal, ident=ident, zrodlo="profil",
                         notatka=poz.get("powod"))
        print("    ✓ usunięte, zapisane w dzienniku (usunieto-profil — konsensus bez zmian)")
        return 1

    if rodzaj == "zapisz-dodano":
        dopisz_zdarzenie("dodano", kanal=kanal, ident=ident, wersja=poz.get("wersja"),
                         zrodlo="reczne",
                         notatka="dopisane przez `lustro sync` — instalacja poza apką")
        print(f"[{ident}] dopisane do dziennika (dodano, zrodlo: reczne)")
        return 1

    if rodzaj == "zapisz-usunieto":
        dopisz_zdarzenie("usunieto", kanal=kanal, ident=ident, zrodlo="reczne",
                         notatka="dopisane przez `lustro sync` — usunięcie poza apką")
        print(f"[{ident}] dopisane do dziennika (usunieto, zrodlo: reczne)")
        return 1

    if rodzaj == "pulpit":
        podargs = argparse.Namespace(zatwierdzam_wszystko=True, notatka=None)
        if poz.get("kierunek") == "o":
            return 1 if polecenie_pulpit_oddaj(podargs) == 0 else 0
        return 1 if polecenie_pulpit_wgraj(podargs) == 0 else 0

    return 0


# ---------------------------------------------------------------- dodaj / usun / ustawienia

def polecenie_dodaj(args):
    git_pull_rebase()          # świeży dziennik z GitHuba; offline nie blokuje instalacji
    nazwa = args.program
    inw = inwentaryzacja()
    juz = znajdz_zainstalowany(nazwa, inw)
    if juz:
        for kanal, ident in juz:
            print(f"„{ident}” już jest na tej maszynie ({kanal}, {inw[(kanal, ident)]}).")
        print("Jeśli brakuje go w dzienniku — `lustro sync` to zaproponuje.")
        return 0

    # [176] zewnętrzne repozytorium apt — najpierw źródło, potem dopiero szukanie pakietu
    if not zapewnij_zrodlo_dla(nazwa, args):
        return 1

    kanal = args.kanal
    if not kanal:
        kandydaci = wykryj_kanal(nazwa)
        if not kandydaci:
            print(f"Nie znalazłem „{nazwa}” ani w apt, ani w snapie, ani na Flathubie, "
                  f"ani w {SKRYPTY_TOML.name}.")
            print("Podaj kanał ręcznie: lustro dodaj <nazwa> --kanal apt|snap|flatpak|skrypt")
            return 1
        if len(kandydaci) == 1:
            kanal = kandydaci[0]
            print(f"Kanał wykryty: {kanal}")
        else:
            print(f"„{nazwa}” jest dostępny w kilku kanałach: {', '.join(kandydaci)}")
            skroty = "".join(k[0] for k in kandydaci)
            odp = pytaj("Który kanał? "
                        + " / ".join(f"[{k[0]}]{k[1:]}" for k in kandydaci),
                        skroty.capitalize(), kandydaci[0][0])
            kanal = next(k for k in kandydaci if k[0] == odp)

    # [252] kanał skrypt: pozycja musi mieć definicję (DANE) — `dodaj` niczego
    # nie zgaduje; następny skrypt to nowy blok [[skrypt]] w skrypty.toml.
    definicja_skryptu = None
    if kanal == KANAL_SKRYPT:
        definicja_skryptu = wczytaj_skrypty().get(nazwa)
        if definicja_skryptu is None:
            print(f"„{nazwa}” nie ma definicji w lustra/{SKRYPTY_TOML.name}.")
            print("Kanał skrypt to DANE: dopisz blok [[skrypt]] (id, opis, sprawdz, "
                  "zainstaluj, wymaga — wzór w nagłówku pliku), zrób commit i uruchom "
                  f"`lustro dodaj {nazwa}` jeszcze raz.")
            return 1
        powody = wymagania_niespelnione(definicja_skryptu)
        if powody:
            print("Jeszcze nie da się zainstalować: " + "; ".join(powody))
            return 1
        if definicja_skryptu.get("opis"):
            print(f"    {definicja_skryptu['opis']}")
        print(f"    polecenie: {definicja_skryptu['zainstaluj']}")

    print(f"Instaluję „{nazwa}” z kanału {kanal}.")
    if not args.zatwierdzam_wszystko:
        if pytaj("Wykonać?", "Tn", "t") != "t":
            print("Nic nie zmieniam.")
            return 0

    przed = zdjecie_katalogow()
    if definicja_skryptu is not None:
        kod = zainstaluj_skrypt(definicja_skryptu, pokaz_wszystko=True)
    else:
        kod = _z_tlumikiem_haka(komenda_instalacji(kanal, nazwa))
    wersja = sprawdz_jedna_pozycje(kanal, nazwa)
    if wersja is None:
        print(f"⚠ Po instalacji programu nie widzę (kod {kod}). Dziennika NIE ruszam.")
        return 1

    notatka = args.notatka or pytaj_tekst("Notatka do dziennika (po co ten program)", "")
    dopisz_zdarzenie("dodano", kanal=kanal, ident=nazwa, wersja=wersja,
                     zrodlo="apka", notatka=notatka or None)
    print(f"✓ Zainstalowane ({wersja}) i zapisane w dzienniku.")

    # spec 7.5 — pytanie o ustawienia
    po = zdjecie_katalogow()
    zapytaj_o_ustawienia(nazwa, kandydaci_ustawien(nazwa, przed, po))

    git_zapisz(f"lustra: dodano {nazwa} ({kanal}) na {nazwa_maszyny()}")
    return 0


def polecenie_usun(args):
    git_pull_rebase()
    nazwa = args.program
    inw = inwentaryzacja()
    trafienia = znajdz_zainstalowany(nazwa, inw)
    if not trafienia:
        print(f"„{nazwa}” nie jest zainstalowany na tej maszynie "
              f"(albo siedzi w wykluczeniach).")
        return 1
    if len(trafienia) > 1:
        print(f"„{nazwa}” pasuje do kilku pozycji: "
              + ", ".join(f"{i} ({k})" for k, i in trafienia))
        print("Podaj dokładny identyfikator.")
        return 1
    kanal, ident = trafienia[0]

    komenda = komenda_usuniecia(kanal, ident)
    if komenda is None:
        print(f"Nie umiem usunąć „{ident}” ({kanal}) automatycznie"
              + (f" — pozycja skrypt bez pola `usun` w {SKRYPTY_TOML.name}"
                 if kanal == KANAL_SKRYPT else "")
              + ". Usuń ręcznie; `lustro sync` potem zaproponuje wpis „usunieto”.")
        return 1
    print(f"Usuwam „{ident}” ({kanal}, {inw[(kanal, ident)]}).")
    if not args.zatwierdzam_wszystko:
        if pytaj("Wykonać?", "Tn", "t") != "t":
            print("Nic nie zmieniam.")
            return 0

    kod = _z_tlumikiem_haka(komenda)
    if sprawdz_jedna_pozycje(kanal, ident) is not None:
        print(f"⚠ Program nadal jest na maszynie (kod {kod}). Dziennika NIE ruszam.")
        return 1

    notatka = args.notatka or pytaj_tekst("Notatka do dziennika (dlaczego schodzi)", "")
    dopisz_zdarzenie("usunieto", kanal=kanal, ident=ident, zrodlo="apka",
                     notatka=notatka or None)
    print("✓ Usunięte i zapisane w dzienniku.")

    # --- ustawienia po programie ---
    mapa = wczytaj_mape_ustawien()
    sciezki = list(mapa.get(ident) or mapa.get(nazwa) or [])
    if kanal == "flatpak":
        kat = DOM / ".var/app" / ident
        if str(kat) not in [str(pelna_sciezka(s)) for s in sciezki]:
            sciezki.append(str(kat))

    istniejace = [s for s in sciezki if pelna_sciezka(s).exists()]
    if not istniejace:
        print("Program nie zostawił po sobie plików ustawień, które lustro zna.")
    else:
        print("Po programie zostały ustawienia:")
        for s in istniejace:
            print(f"   • {skroc_dom(pelna_sciezka(s))}")
        odp = ("t" if args.usun_ustawienia else
               pytaj("Usunąć je też? [T] zdejmij z lustra i skasuj z dysku / "
                     "[l] tylko zdejmij z lustra / [n] zostaw", "Tln", "n"))
        if odp in ("t", "l"):
            chezmoi_zapomnij(istniejace)
        if odp == "t":
            for s in istniejace:
                p = pelna_sciezka(s)
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.exists():
                    p.unlink()
                print(f"    ✓ skasowane z dysku: {skroc_dom(p)}")
            dopisz_zdarzenie("ustawienia", kanal="chezmoi", ident=ident,
                             zrodlo="apka",
                             pliki=[skroc_dom(pelna_sciezka(s)) for s in istniejace],
                             notatka="ustawienia usunięte razem z programem")

    git_zapisz(f"lustra: usunięto {ident} ({kanal}) na {nazwa_maszyny()}")
    return 0


def polecenie_ustawienia(args):
    """Oddaje bieżące ustawienia programu do lustra (chezmoi + zdarzenie)."""
    git_pull_rebase()
    program = args.program
    mapa = wczytaj_mape_ustawien()
    sciezki = list(args.pliki) if args.pliki else list(mapa.get(program, []))

    if not sciezki:
        kandydaci = kandydaci_ustawien(program, set(), zdjecie_katalogow())[:10]
        if not kandydaci:
            print(f"Nie wiem, gdzie „{program}” trzyma ustawienia.")
            print(f"Podaj ręcznie: lustro ustawienia {program} --pliki .config/x/y.conf")
            return 1
        weszly = zapytaj_o_ustawienia(program, kandydaci)
        if not weszly:
            return 0
        dopisz_zdarzenie("ustawienia", kanal="chezmoi", ident=program,
                         zrodlo="apka", pliki=weszly, notatka=args.notatka or None)
        git_zapisz(f"lustra: ustawienia {program} oddane z {nazwa_maszyny()}")
        return 0

    weszly = chezmoi_dodaj(sciezki)
    if not weszly:
        print("Nic nie weszło do lustra.")
        return 1
    if program not in mapa:
        dopisz_do_mapy(program, weszly, f"dodane przez lustro {datetime.now():%Y-%m-%d}")
    notatka = args.notatka or pytaj_tekst("Notatka do dziennika (co się zmieniło)", "")
    dopisz_zdarzenie("ustawienia", kanal="chezmoi", ident=program, zrodlo="apka",
                     pliki=weszly, notatka=notatka or None)
    print(f"✓ Ustawienia „{program}” oddane do lustra ({len(weszly)} ścieżek).")
    git_zapisz(f"lustra: ustawienia {program} oddane z {nazwa_maszyny()}")
    return 0


# ---------------------------------------------------------------- dziennik / lista

def polecenie_dziennik(args):
    zdarzenia = wczytaj_dzienniki()
    if args.maszyna:
        zdarzenia = [z for z in zdarzenia if z.get("maszyna") == args.maszyna]
    if args.od:
        zdarzenia = [z for z in zdarzenia if z.get("ts", "") >= args.od]
    if not zdarzenia:
        print("Dziennik pusty (albo filtr nic nie zwrócił).")
        return 0
    slowa = {"dodano": "dodano", "usunieto": "usunięto",
             "ustawienia": "ustawienia", "obce": "instalacja obca",
             "notatka": "notatka", "wykluczono": "wykluczono"}
    for z in zdarzenia:
        opis = slowa.get(z.get("zdarzenie"), z.get("zdarzenie", "?"))
        kanal = f" ({z['kanal']})" if z.get("kanal") else ""
        wersja = f" {z['wersja']}" if z.get("wersja") else ""
        zrodlo = f"  [{z['zrodlo']}]" if z.get("zrodlo") else ""
        print(f"{data_ludzka(z.get('ts'))}  {z.get('maszyna'):<8} "
              f"{opis} {z.get('id','')}{wersja}{kanal}{zrodlo}")
        if z.get("za"):
            print(f"{'':>18}  └─ za: {z['za'].get('maszyna')} "
                  f"{data_ludzka(z['za'].get('ts'))}")
        if z.get("notatka"):
            print(f"{'':>18}  └─ {z['notatka']}")
    print()
    print(f"Razem zdarzeń: {len(zdarzenia)}")
    return 0


# ---- parser starego programy.md: przenosimy ręczne kolumny „Do czego" i „Uwagi" ----

def _identyfikatory_z_komendy(tekst):
    """Wyciąga nazwy pakietów z komend instalacji w dowolnym miejscu komórki."""
    ident = []
    for m in re.finditer(r"(apt(?:-get)?\s+install|snap\s+install|flatpak\s+install)"
                         r"([^`|)\n]*)", tekst):
        for slowo in m.group(2).split():
            slowo = slowo.strip("`,;'\"()")
            if not slowo or slowo.startswith("-"):
                continue
            if slowo in ("flathub", "sudo", "install", "…", "..."):
                continue
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", slowo):
                ident.append(slowo)
    return ident


def _identyfikatory_z_nazwy(tekst):
    """Wiersz zbiorczy („git, curl, wget…") rozbijamy na osobne nazwy — reguła ogólna:
    komórka z przecinkami, w której każdy człon wygląda jak nazwa pakietu."""
    goly = re.sub(r"\*\*|`", "", tekst).strip()
    if not goly:
        return []
    czlony = [c.strip() for c in re.split(r"[,/]| oraz | i ", goly) if c.strip()]
    wynik = []
    for c in czlony:
        c = c.split("(")[0].strip().rstrip(":…").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{1,60}", c):
            continue
        # nazwa pakietu jest z małych liter (`xournalpp`) albo ma kropki
        # (`org.zotero.Zotero`). „LibreOffice" to nazwa dla człowieka, nie pakiet —
        # dzięki temu warunkowi tabela GENEROWANA daje się odczytać z powrotem
        # i ręczne opisy przeżywają kolejne przegenerowanie.
        if c.islower() or "." in c:
            wynik.append(c)
    return wynik


def _identyfikatory_z_pakietu(tekst):
    """„…, pakiet `google-chrome-stable`" — programy z zewnętrznych repozytoriów
    opisane bez komendy instalacji."""
    return [m.group(1) for m in
            re.finditer(r"pakiet[y]?\s+`([A-Za-z0-9][A-Za-z0-9.+_-]*)`", tekst)]


def wczytaj_reczne_kolumny(plik):
    """
    Czyta stary programy.md i zwraca {identyfikator: (do_czego, uwagi)}.

    Ogólnie, bez wiedzy o konkretnych wierszach:
    • wiersz jest NAGŁÓWKIEM tabeli tylko wtedy, gdy zaraz pod nim stoi linia
      oddzielająca `|---|---|` — dzięki temu pusta linia w środku tabeli
      (a taka jest w programy.md) nie robi z następnego wiersza nowego nagłówka;
    • kolumny rozpoznajemy po nazwach nagłówka, nie po numerze;
    • identyfikatory zbieramy z kolumny nazwy (wiersz zbiorczy „git, curl, wget…”),
      z komend instalacji ORAZ ze zwrotu „pakiet `nazwa`" (tak opisane są programy
      z zewnętrznych repozytoriów, które nie mają komendy `apt install`).
    """
    wynik = {}
    if not plik or not Path(plik).exists():
        return wynik

    linie = Path(plik).read_text(encoding="utf-8").splitlines()

    def komorki_z(linia):
        return [c.strip() for c in linia.strip().strip("|").split("|")]

    def czy_oddzielacz(linia):
        if not linia.strip().startswith("|"):
            return False
        k = komorki_z(linia)
        return bool(k) and all(c and set(c) <= set("-: ") for c in k)

    naglowki = None
    for nr, linia in enumerate(linie):
        if not linia.strip().startswith("|"):
            continue
        if czy_oddzielacz(linia):
            continue
        komorki = komorki_z(linia)
        if nr + 1 < len(linie) and czy_oddzielacz(linie[nr + 1]):
            naglowki = [c.lower() for c in komorki]     # to jest nagłówek tabeli
            continue
        if naglowki is None or len(komorki) != len(naglowki):
            continue

        def kolumna(*klucze):
            for i, n in enumerate(naglowki):
                if any(k in n for k in klucze):
                    return komorki[i] if i < len(komorki) else ""
            return ""

        nazwa = kolumna("program", "rozszerzenie", "narzędzie")
        do_czego = kolumna("do czego", "opis", "zastosowanie")
        uwagi = kolumna("uwagi", "komentarz")
        komenda = kolumna("komenda", "skąd", "instalacj")
        if not nazwa and not komenda:
            continue
        znalezione = (_identyfikatory_z_komendy(komenda)
                      + _identyfikatory_z_pakietu(komenda)
                      + _identyfikatory_z_nazwy(nazwa))
        for i in znalezione:
            if i not in wynik or not wynik[i][0]:
                wynik[i] = (do_czego, uwagi)
    return wynik


def polecenie_lista(args):
    """Generuje programy.md ORAZ .chezmoidata/packages.yaml z dzienników.

    `programy.md` (tabela dla człowieka) zostaje NIEFILTROWANA — pełny obraz
    historyczny ze wszystkich dzienników, jak dziś.

    `.chezmoidata/packages.yaml` (lista WYKONAWCZA — to ją stawia bootstrap nowej
    maszyny) stosuje kontrakt [209] rozdz. 5: „nowa maszyna bootstrapuje się
    z konsensusu lustra tak jak dziś (reguła 3)" — czyli TYLKO z dzienników
    maszyn-członków lustra, z pominięciem pozycji ograniczonych `wylacznie_na`
    (nowa maszyna z założenia nie jest jeszcze na żadnej takiej liście imiennej).
    Ewentualne `override obecne` przypisane jej kluczowi z góry dociągnie później
    `lustro sync`/`sync --auto` — to już zwykła reguła 2, nie dotyczy tego pliku.
    """
    zdarzenia = wczytaj_dzienniki()
    ostatnie, _ = stan_oczekiwany(zdarzenia)          # NIEFILTROWANE — do programy.md
    maszyny = sorted({z.get("maszyna") for z in zdarzenia if z.get("maszyna")})
    if not maszyny:
        maszyny = [nazwa_maszyny()]

    reczne = wczytaj_reczne_kolumny(args.reczne or args.do)
    statusy = wczytaj_statusy_pozycji()

    # Konsensus dla LISTY WYKONAWCZEJ (packages.yaml): tylko dzienniki członków
    # lustra, kontrakt [209] rozdz. 4-5.
    czlonkowie = wczytaj_czlonkow_lustra()
    zdarzenia_czlonkow = [z for z in zdarzenia
                          if czy_czlonek_lustra(z.get("maszyna"), czlonkowie)]
    ostatnie_wykonawcze, _ = stan_oczekiwany(zdarzenia_czlonkow)

    per_maszyna = {}
    for z in zdarzenia:
        if z.get("zdarzenie") not in ("dodano", "usunieto"):
            continue
        klucz = (z.get("kanal"), z.get("id"), z.get("maszyna"))
        if None not in klucz:
            per_maszyna[klucz] = z

    wiersze, pakiety = [], {k: [] for k in KANALY}
    for (kanal, ident) in sorted(ostatnie):
        komorki = []
        for m in maszyny:
            z = per_maszyna.get((kanal, ident, m))
            if z is None:
                komorki.append("–")
            elif z["zdarzenie"] == "dodano":
                komorki.append(f"✓ {data_ludzka(z['ts'])[:10]}")
            else:
                komorki.append(f"– {data_ludzka(z['ts'])[:10]}")
        ost = ostatnie[(kanal, ident)]
        do_czego, uwagi = reczne.get(ident, ("", ""))
        if not uwagi:
            uwagi = ost.get("notatka", "")
            # notatka z zasiewu bywa powtórzeniem opisu — nie dublujemy tekstu
            if do_czego and uwagi.startswith(do_czego):
                uwagi = uwagi[len(do_czego):].lstrip("; ").strip()
        st = statusy.get((kanal, ident))
        if st and st["status"] == "testowe" and not uwagi:
            uwagi = "⏳ testowe (kwarantanna) — nie propaguje się automatem"
        wiersze.append((ident, kanal, komorki, do_czego, uwagi))
        if kanal in pakiety:
            # Lista WYKONAWCZA (kontrakt [209] rozdz. 5): konsensus tylko z
            # dzienników członków lustra (nie z `ost`, który jest niefiltrowany —
            # ten służy tylko tabeli dla człowieka wyżej), pominięcie kwarantanny
            # (poprawka 11 — bez zmian) i pominięcie pozycji ograniczonych
            # `wylacznie_na` (nowa maszyna z bootstrapu nie jest jeszcze na
            # żadnej takiej liście imiennej, więc nie powinna jej dostać z automatu).
            ost_wyk = ostatnie_wykonawcze.get((kanal, ident))
            if ost_wyk is None or ost_wyk.get("zdarzenie") != "dodano":
                continue
            if st and st["status"] == "testowe":
                continue
            if st and st.get("wylacznie_na"):
                continue
            pakiety[kanal].append(ident)

    linie = [
        "# Programy — tabela GENEROWANA z dzienników luster",
        "",
        f"Wygenerowane: {datetime.now():%Y-%m-%d %H:%M} przez `lustro lista`.",
        "**Kolumn ✓/– nie edytować ręcznie** — źródłem prawdy jest `lustra/dziennik/*.jsonl`",
        "w repozytorium konfiguracji (chezmoi).",
        "",
        "Kolumny „Do czego” i „Uwagi” są **ręczne** — generator przenosi je ze starej",
        "wersji pliku po nazwie pakietu i **nigdy ich nie kasuje**. Wiersze zbiorcze",
        "(„git, curl, wget…”) rozbija na osobne pozycje.",
        "",
        "Legenda: ✓ = jest (data ostatniego zdarzenia), – z datą = usunięte,",
        "samo – = to lustro nigdy o tym nie słyszało.",
        "",
    ]
    linie.append("| Program | Kanał | " + " | ".join(maszyny) + " | Do czego | Uwagi |")
    linie.append("|" + "---|" * (4 + len(maszyny)))
    for ident, kanal, komorki, do_czego, uwagi in wiersze:
        linie.append(f"| {ident} | {kanal} | " + " | ".join(komorki)
                     + f" | {do_czego} | {uwagi} |")
    linie += [
        "",
        f"Razem pozycji: {len(wiersze)} (apt: {len(pakiety['apt'])}, "
        f"snap: {len(pakiety['snap'])}, flatpak: {len(pakiety['flatpak'])}, "
        f"skrypt: {sum(1 for w in wiersze if w[1] == KANAL_SKRYPT)} — "
        f"pozycje skrypt dociąga `sync --auto`, nie packages.yaml).",
        "",
        "Lista wykonawcza dla chezmoi (ta sama treść, format maszynowy):",
        "`.chezmoidata/packages.yaml` — czyta ją `run_onchange_install-packages.sh.tmpl`.",
    ]
    tresc = "\n".join(linie) + "\n"

    # Ogon ręczny: wszystko poniżej znacznika NALEŻY DO CZŁOWIEKA i generator go
    # przepisuje bez zmian. Dzięki temu opisy, sekcje „zależne od sprzętu" czy
    # „do decyzji usera" przeżywają każde przegenerowanie tabeli.
    if args.do and Path(args.do).exists():
        stare = Path(args.do).read_text(encoding="utf-8")
        if ZNACZNIK_RECZNY in stare:
            tresc += "\n" + ZNACZNIK_RECZNY + stare.split(ZNACZNIK_RECZNY, 1)[1]

    if args.do:
        Path(args.do).write_text(tresc, encoding="utf-8")
        print(f"Zapisano {len(wiersze)} pozycji do {args.do}")
    else:
        print(tresc)

    kat = REPO / ".chezmoidata"
    kat.mkdir(exist_ok=True)
    yml = [
        "# Lista programów lustra — plik GENEROWANY przez `lustro lista`.",
        "# Nie edytować ręcznie: źródłem prawdy jest lustra/dziennik/*.jsonl.",
        f"# Wygenerowane: {datetime.now():%Y-%m-%d %H:%M} na maszynie {nazwa_maszyny()}.",
        "packages:",
    ]
    for kanal in KANALY:
        if pakiety[kanal]:
            yml.append(f"  {kanal}:")
            for p in sorted(pakiety[kanal]):
                yml.append(f"    - {p}")
        else:
            yml.append(f"  {kanal}: []")
    (kat / "packages.yaml").write_text("\n".join(yml) + "\n", encoding="utf-8")
    print(f"Zapisano listę wykonawczą: {kat / 'packages.yaml'} "
          f"(apt {len(pakiety['apt'])}, snap {len(pakiety['snap'])}, "
          f"flatpak {len(pakiety['flatpak'])})")
    return 0


# ---------------------------------------------------------------- wejście

def niedostepne(nazwa):
    def f(args):
        print(f"`lustro {nazwa}` — niedostępne w E2 (wchodzi w E3, spec rozdz. 10).")
        return 2
    return f


def main():
    global TRYB_ROOT

    p = argparse.ArgumentParser(
        prog="lustro",
        description="Porównywarka domowych komputerów. ETAP E2 — zmienia system, "
                    "ale zawsze po pytaniu.")
    p.add_argument("--root", choices=["sudo", "pkexec"], default=TRYB_ROOT,
                   help="jak prosić o uprawnienia roota (domyślnie sudo; "
                        "pkexec = okienko systemowe)")
    pod = p.add_subparsers(dest="polecenie")

    def wspolne(parser, notatka=True):
        parser.add_argument("--zatwierdzam-wszystko", action="store_true",
                            dest="zatwierdzam_wszystko",
                            help="bez pytań — ŚWIADOMIE NIE domyślne (spec 9.1)")
        if notatka:
            parser.add_argument("--notatka", default=None)

    pod.add_parser("status", help="inwentaryzacja + rozbieżności (nic nie zmienia)")

    sy = pod.add_parser("sync", help="wyrównywanie z pytaniem przy każdej pozycji")
    sy.add_argument("--tylko-pokaz", action="store_true", dest="tylko_pokaz",
                    help="to samo co `status` — do powiadomienia na pulpicie")
    sy.add_argument("--tylko-instaluj", action="store_true", dest="tylko_instaluj",
                    help="nigdy nic nie usuwa — najbezpieczniejszy tryb")
    sy.add_argument("--auto", action="store_true",
                    help="tryb bez pytań i bez terminala (timer lustro-sync, Faza 3 "
                         "automatu): dociąga TYLKO brakujące pakiety apt/snap/flatpak "
                         "i pozycje kanału skrypt (skrypty.toml, [252]) "
                         "(dziennik mówi „jest”, tu brak) oraz brakujące źródła apt z "
                         "zrodla-apt.toml; księguje „jest tutaj, w dzienniku brak” "
                         "(zrodlo: wykryte, [213]). Nigdy nie usuwa, nigdy nie rusza "
                         "pulpitu ani rozszerzeń GNOME — te kategorie zostają dla "
                         "`lustro sync` ręcznego. Pozycje ze statusem `testowe` "
                         "(statusy-pozycji.toml) są pomijane jak wszędzie indziej.")
    wspolne(sy)

    dd = pod.add_parser("dodaj", help="instalacja programu + zapis do dziennika")
    dd.add_argument("program")
    dd.add_argument("--kanal", choices=list(KANALY_INSTALOWALNE), default=None,
                    help="skrypt = pozycja z lustra/skrypty.toml [252]")
    wspolne(dd)

    us = pod.add_parser("usun", help="odinstalowanie programu + zapis do dziennika")
    us.add_argument("program")
    us.add_argument("--usun-ustawienia", action="store_true", dest="usun_ustawienia",
                    help="bez pytania skasuj też ustawienia programu")
    wspolne(us)

    ut = pod.add_parser("ustawienia", help="oddanie ustawień programu do lustra")
    ut.add_argument("program")
    ut.add_argument("--pliki", nargs="*", default=None,
                    help="ścieżki względem katalogu domowego")
    wspolne(ut)

    d = pod.add_parser("dziennik", help="historia zdarzeń po ludzku")
    d.add_argument("--maszyna")
    d.add_argument("--od", help="data od, np. 2026-08-01")

    l = pod.add_parser("lista", help="programy.md + .chezmoidata/packages.yaml")
    l.add_argument("--do", help="zapisz tabelę do pliku zamiast na ekran")
    l.add_argument("--reczne", help="skąd wziąć ręczne kolumny (domyślnie: plik z --do)")

    pu = pod.add_parser("pulpit", help="warstwa GNOME (dconf)")
    pu.add_argument("co", choices=["status", "zasiew", "oddaj", "oddaj-stan", "wgraj",
                                    "sprawdz", "rozszerzenia", "skladaj"])
    wspolne(pu)

    pf = pod.add_parser("profil", help="czym jest profil TEJ maszyny i co stoi poza nim [284]")
    pf.add_argument("co", choices=["status", "sprzataj"], nargs="?", default="status")
    wspolne(pf, notatka=False)

    nm = pod.add_parser("nowa-maszyna", help="bootstrap (E3 — niedostępne)")
    nm.add_argument("reszta", nargs="*")

    iv = pod.add_parser("inwentarz", help="migawka pełnej inwentaryzacji tej maszyny "
                                          "z wersjami, do lustra/inwentarz/<maszyna>.json")
    iv.add_argument("co", choices=["eksportuj"], nargs="?", default="eksportuj")

    hk = pod.add_parser("hak-apt", help="hook dpkg — dziennik przy KAŻDEJ zmianie apt [213]")
    hk.add_argument("--zainstaluj", action="store_true",
                    help="zbuduj i zainstaluj na TEJ maszynie pakiet .deb z hookiem "
                         "dpkg (DPkg::Post-Invoke); bez tej flagi to jest wewnętrzne "
                         "wywołanie SAMEGO hooka, nie do ręcznego użycia")

    args = p.parse_args()
    TRYB_ROOT = args.root

    if args.polecenie is None:
        p.print_help()
        return 0
    if args.polecenie == "status":
        return polecenie_status(args)
    if args.polecenie == "sync":
        return polecenie_sync(args)
    if args.polecenie == "dodaj":
        return polecenie_dodaj(args)
    if args.polecenie == "usun":
        return polecenie_usun(args)
    if args.polecenie == "ustawienia":
        return polecenie_ustawienia(args)
    if args.polecenie == "dziennik":
        return polecenie_dziennik(args)
    if args.polecenie == "lista":
        return polecenie_lista(args)
    if args.polecenie == "hak-apt":
        return polecenie_hak_apt_instaluj(args) if args.zainstaluj else polecenie_hak_apt(args)
    if args.polecenie == "profil":
        return polecenie_profil(args)
    if args.polecenie == "inwentarz":
        return polecenie_inwentarz_eksportuj(args)
    if args.polecenie == "pulpit":
        return {"status": polecenie_pulpit_status,
                "zasiew": polecenie_pulpit_zasiew,
                "oddaj": polecenie_pulpit_oddaj,
                "oddaj-stan": polecenie_pulpit_oddaj_stan,
                "wgraj": polecenie_pulpit_wgraj,
                "sprawdz": polecenie_pulpit_sprawdz,
                "rozszerzenia": polecenie_pulpit_rozszerzenia,
                "skladaj": polecenie_pulpit_skladaj}[args.co](args)
    return niedostepne(args.polecenie)(args)


if __name__ == "__main__":
    sys.exit(main())
