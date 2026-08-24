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
KOPIE = DOM / ".local/share/lustro/kopie"

EXTENSIONS_GNOME_ORG = "https://extensions.gnome.org"

KANALY = ("apt", "snap", "flatpak")

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
    """Nazwa lustra. Priorytet: plik lustra/maszyna.txt, potem nazwa hosta."""
    plik = KATALOG / "maszyna.txt"
    if plik.exists():
        n = plik.read_text(encoding="utf-8").strip()
        if n:
            return n
    kod, out = uruchom(["hostname"])
    return out.strip().lower() or "nieznana"


def chezmoi_sciezka():
    return shutil.which("chezmoi") or str(DOM / ".local/bin/chezmoi")


# ---------------------------------------------------------------- pytania do usera

def pytaj(tresc, opcje="Tnps", domyslna="n"):
    """
    Zadaje JEDNO pytanie i zwraca małą literę odpowiedzi.
    `opcje` to litery dozwolonych odpowiedzi; wielka litera = wartość domyślna.
    Gdy nie ma z kim rozmawiać (brak stdin) — zwraca wartość domyślną i mówi o tym głośno.
    """
    litery = [o.lower() for o in opcje]
    podpowiedz = "/".join(opcje)
    while True:
        try:
            odp = input(f"    {tresc} [{podpowiedz}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"    (brak odpowiedzi z terminala — przyjmuję „{domyslna}”)")
            return domyslna
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

def inwentarz_apt():
    """Pakiety oznaczone jako zainstalowane RĘCZNIE (bez zależności), po odsianiu."""
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
    return {p: wersje.get(p, "?") for p in reczne if not pasuje(p, wykl)}


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


def inwentarz_flatpak():
    """Programy flatpak. '--app' sam odsiewa biblioteki uruchomieniowe i dodatki."""
    if not czy_jest("flatpak"):
        return {}
    _, out = uruchom(["flatpak", "list", "--app",
                      "--columns=application,version"])
    wykl = wczytaj_wzorce(WYKLUCZENIA / "flatpak.txt")
    wynik = {}
    for linia in out.splitlines():
        if not linia.strip():
            continue
        pola = linia.split("\t")
        nazwa = pola[0].strip()
        wersja = pola[1].strip() if len(pola) > 1 else "?"
        if nazwa and not pasuje(nazwa, wykl):
            wynik[nazwa] = wersja
    return wynik


def inwentaryzacja():
    """Zwraca {(kanal, id): wersja} — to, co na maszynie FAKTYCZNIE jest."""
    stan = {}
    for k, f in (("apt", inwentarz_apt), ("snap", inwentarz_snap),
                 ("flatpak", inwentarz_flatpak)):
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
                     zrodlo="apka", za=None, pliki=None, notatka=None):
    """
    Dopisuje JEDNĄ linię do dziennika tej maszyny (append-only, spec 4.1).
    Kolejność pól jak w spec 4.2 — żeby dziennik czytało się okiem.
    """
    z = {"ts": teraz_iso(), "maszyna": nazwa_maszyny(), "zdarzenie": zdarzenie}
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
    plik = DZIENNIKI / f"{nazwa_maszyny()}.jsonl"
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


def rozszerzenia_zainstalowane_lokalnie():
    """
    Zbiór UUID rozszerzeń GNOME Shell zainstalowanych na TEJ maszynie
    (`gnome-extensions list` — wszystkie, nie tylko włączone).
    None = nie umiem sprawdzić (brak `gnome-extensions`, np. maszyna bez GNOME/bez pulpitu).
    """
    if not czy_jest("gnome-extensions"):
        return None
    kod, out = uruchom(["gnome-extensions", "list"])
    if kod != 0:
        return None
    return {l.strip() for l in out.splitlines() if l.strip()}


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


def zapisz_pulpit(stan, plik):
    """Zapisuje eksport w formacie zgodnym z `dconf dump /` (sekcje bez wiodącego /)."""
    grupy = {}
    for klucz, wartosc in stan.items():
        sekcja, nazwa = klucz.rsplit("/", 1)
        grupy.setdefault(sekcja.strip("/"), {})[nazwa] = wartosc
    linie = [
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


def wczytaj_pulpit_z_lustra():
    if not PLIK_PULPITU.exists():
        return None
    stan, sekcja = {}, ""
    for linia in PLIK_PULPITU.read_text(encoding="utf-8").splitlines():
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


def git_zapisz(wiadomosc):
    """Jeden commit na koniec przebiegu + push, jeśli repozytorium ma remote (spec 9.3)."""
    kod, out = uruchom(["git", "-C", str(REPO), "status", "--porcelain"])
    if kod != 0:
        print("⚠ Nie umiem sprawdzić stanu repozytorium — pomijam commit.")
        return
    if not out.strip():
        print("Repozytorium bez zmian — nie ma czego zapisywać.")
        return
    uruchom(["git", "-C", str(REPO), "add", "-A"])
    uruchom(["git", "-C", str(REPO), "commit", "-m", wiadomosc])
    print(f"Commit w repozytorium konfiguracji: {wiadomosc}")
    if git_ma_remote():
        kod, _ = uruchom(["git", "-C", str(REPO), "push"], timeout=180)
        print("Wysłane na serwer (git push)." if kod == 0
              else "⚠ `git push` się nie udał — commit został lokalnie.")
    else:
        print("Repozytorium nie ma jeszcze serwera (remote) — commit został lokalnie.")


def chezmoi_dodaj(sciezki):
    """`chezmoi add` na liście ścieżek. Zwraca listę tych, które weszły."""
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
    return weszly


def chezmoi_zapomnij(sciezki):
    zapomniane = []
    for s in sciezki:
        pelna = pelna_sciezka(s)
        kod, _ = uruchom([chezmoi_sciezka(), "forget", "--force", str(pelna)])
        if kod == 0:
            zapomniane.append(str(pelna).replace(str(DOM) + "/", ""))
            print(f"    ✓ zdjęte z lustra: {skroc_dom(pelna)}")
    return zapomniane


# ---------------------------------------------------------------- kanały: instalacja

def czy_flatpak_systemowy(ident):
    """Flatpak zainstalowany systemowo wymaga roota; --user nie wymaga."""
    kod, out = uruchom(["flatpak", "list", "--app",
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
    return None


def wykryj_kanal(nazwa):
    """
    Zwraca listę kanałów, w których program da się zainstalować.
    Kolejność ma znaczenie: apt przed snapem przed flatpakiem.
    """
    kandydaci = []
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
    """Wspólny rdzeń `status` i `sync`."""
    maszyna = nazwa_maszyny()
    zdarzenia = wczytaj_dzienniki()
    inw = inwentaryzacja()
    ostatnie, historia = stan_oczekiwany(zdarzenia)
    moje = stan_wg_tej_maszyny(zdarzenia, maszyna)
    pomijane = wczytaj_pomijane()

    rozbieznosci, niezapisane, usuniete_poza = [], [], []

    for klucz, zdarz in sorted(ostatnie.items()):
        if klucz in pomijane:
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

    return {"maszyna": maszyna, "zdarzenia": zdarzenia, "inwentarz": inw,
            "rozbieznosci": rozbieznosci, "niezapisane": niezapisane,
            "usuniete_poza": usuniete_poza, "pomijane": pomijane,
            "historia": historia}


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
    """Bieżące ustawienia pulpitu TEJ maszyny → do lustra + zdarzenie (spec 8.9)."""
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


def polecenie_pulpit_wgraj(args):
    """Ustawienia z lustra → na tę maszynę. ZAWSZE kopia przed nadpisaniem (8.11)."""
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

def polecenie_sync(args):
    if args.tylko_pokaz:
        print("(tryb --tylko-pokaz: niczego nie zmieniam, o nic nie pytam)")
        print()
        return polecenie_status(args)

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
    za = ({"maszyna": zrodlowe.get("maszyna"), "ts": zrodlowe.get("ts")}
          if zrodlowe.get("maszyna") and zrodlowe.get("maszyna") != nazwa_maszyny()
          else None)

    if rodzaj == "instaluj":
        print(f"[{ident}] instaluję ({kanal})…")
        kod = uruchom_widoczne(komenda_instalacji(kanal, ident))
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
        kod = uruchom_widoczne(komenda_usuniecia(kanal, ident))
        if sprawdz_jedna_pozycje(kanal, ident) is not None:
            print(f"    ⚠ program nadal jest na maszynie (kod {kod}) — "
                  f"dziennika NIE ruszam")
            return 0
        dopisz_zdarzenie("usunieto", kanal=kanal, ident=ident, zrodlo="sync", za=za,
                         notatka=zrodlowe.get("notatka"))
        print("    ✓ usunięte, zapisane w dzienniku")
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
    nazwa = args.program
    inw = inwentaryzacja()
    juz = znajdz_zainstalowany(nazwa, inw)
    if juz:
        for kanal, ident in juz:
            print(f"„{ident}” już jest na tej maszynie ({kanal}, {inw[(kanal, ident)]}).")
        print("Jeśli brakuje go w dzienniku — `lustro sync` to zaproponuje.")
        return 0

    kanal = args.kanal
    if not kanal:
        kandydaci = wykryj_kanal(nazwa)
        if not kandydaci:
            print(f"Nie znalazłem „{nazwa}” ani w apt, ani w snapie, ani na Flathubie.")
            print("Podaj kanał ręcznie: lustro dodaj <nazwa> --kanal apt|snap|flatpak")
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

    print(f"Instaluję „{nazwa}” z kanału {kanal}.")
    if not args.zatwierdzam_wszystko:
        if pytaj("Wykonać?", "Tn", "t") != "t":
            print("Nic nie zmieniam.")
            return 0

    przed = zdjecie_katalogow()
    kod = uruchom_widoczne(komenda_instalacji(kanal, nazwa))
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

    print(f"Usuwam „{ident}” ({kanal}, {inw[(kanal, ident)]}).")
    if not args.zatwierdzam_wszystko:
        if pytaj("Wykonać?", "Tn", "t") != "t":
            print("Nic nie zmieniam.")
            return 0

    kod = uruchom_widoczne(komenda_usuniecia(kanal, ident))
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
    """Generuje programy.md ORAZ .chezmoidata/packages.yaml z dzienników."""
    zdarzenia = wczytaj_dzienniki()
    ostatnie, _ = stan_oczekiwany(zdarzenia)
    maszyny = sorted({z.get("maszyna") for z in zdarzenia if z.get("maszyna")})
    if not maszyny:
        maszyny = [nazwa_maszyny()]

    reczne = wczytaj_reczne_kolumny(args.reczne or args.do)

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
        wiersze.append((ident, kanal, komorki, do_czego, uwagi))
        if ost.get("zdarzenie") == "dodano" and kanal in pakiety:
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
        f"snap: {len(pakiety['snap'])}, flatpak: {len(pakiety['flatpak'])}).",
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
    wspolne(sy)

    dd = pod.add_parser("dodaj", help="instalacja programu + zapis do dziennika")
    dd.add_argument("program")
    dd.add_argument("--kanal", choices=list(KANALY), default=None)
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
    pu.add_argument("co", choices=["status", "zasiew", "oddaj", "wgraj", "sprawdz",
                                    "rozszerzenia"])
    wspolne(pu)

    nm = pod.add_parser("nowa-maszyna", help="bootstrap (E3 — niedostępne)")
    nm.add_argument("reszta", nargs="*")

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
    if args.polecenie == "pulpit":
        return {"status": polecenie_pulpit_status,
                "zasiew": polecenie_pulpit_zasiew,
                "oddaj": polecenie_pulpit_oddaj,
                "wgraj": polecenie_pulpit_wgraj,
                "sprawdz": polecenie_pulpit_sprawdz,
                "rozszerzenia": polecenie_pulpit_rozszerzenia}[args.co](args)
    return niedostepne(args.polecenie)(args)


if __name__ == "__main__":
    sys.exit(main())
