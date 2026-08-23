#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lustro — porównywarka domowych komputerów ("luster").

ETAP E1 (2026-08-23): TYLKO ODCZYT SYSTEMU.
Apka nic nie instaluje, nic nie usuwa, nie dotyka dconf i nie woła `chezmoi apply`.
Polecenia zmieniające cokolwiek (`sync`, `dodaj`, `usun`, `ustawienia`,
`pulpit oddaj|wgraj`) odpowiadają "niedostępne w E1".

Specyfikacja: 10_Siec_domowa/5_Wspolna_konfiguracja/mechanizm-luster-spec.md
Biblioteka standardowa Pythona 3, bez zależności zewnętrznych.
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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

KANALY = ("apt", "snap", "flatpak")


# ---------------------------------------------------------------- narzędzia

def uruchom(cmd, wejscie=None):
    """Uruchamia polecenie i zwraca (kod, stdout). Nigdy nie rzuca wyjątkiem."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=wejscie,
                           timeout=120)
        return p.returncode, p.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


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
        skrot = s.replace(str(DOM), "~", 1)
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
                pakiet = _nalezy_do_pakietu(p)
                if pakiet:
                    continue                     # to jednak pakiet apt
                if pusty_katalog(p):
                    continue                     # pusty katalog = nic nie zainstalowano
                dodaj(p, opis)

    if Path("/opt").is_dir():
        for p in sorted(Path("/opt").iterdir()):
            pakiet = _nalezy_do_pakietu(p)
            if pakiet:
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


def stan_oczekiwany(zdarzenia):
    """
    Liczy stan oczekiwany z historii WSZYSTKICH luster (spec 4.4).
    Nigdy nie jest zapisywany do pliku — zawsze liczony na świeżo.
    Zwraca {(kanal, id): zdarzenie_ostatnie} oraz {(kanal,id): [wszystkie zdarzenia]}.
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


# ---------------------------------------------------------------- pulpit (dconf)

def _dconf_dump(sciezka):
    """
    Zwraca {pelny_klucz: wartosc} dla jednej ścieżki dconf.
    `dconf dump` wypisuje TYLKO to, co user zmienił wobec ustawień fabrycznych.
    """
    if not czy_jest("dconf"):
        return {}
    kod, out = uruchom(["dconf", "dump", sciezka])
    if kod != 0:
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


def eksport_pulpitu():
    """
    Eksportuje wybrane ścieżki dconf (spec 8.3) z podmianą katalogu domowego
    na znacznik {{HOME}} (spec 8.4). Zwraca {pelny_klucz: wartosc}.
    """
    sciezki = wczytaj_wzorce(PULPIT / "dconf-lustro.txt")
    pomijane = set(wczytaj_wzorce(PULPIT / "dconf-pomijane-klucze.txt"))
    wyjatki = wczytaj_wzorce(PULPIT / "dconf-wyjatki.txt")

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

    # pojedyncze klucze do pominięcia + ścieżki spoza lustra
    poza = wczytaj_wzorce(PULPIT / "dconf-poza-lustrem.txt")
    stan = {k: v for k, v in stan.items()
            if k not in pomijane and not any(k.startswith(p) for p in poza)}

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
        "# Format zgodny z `dconf dump /` — do wczytania: `dconf load /` (dopiero w E2,",
        "# zawsze po zrobieniu kopii poprzedniego stanu — spec 8.11).",
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


def kontrola_pulpitu():
    """
    Kontroler poprawności (spec 8.5, 8.7, 8.6) — sam odczyt:
    czy skróty wskazują na pliki wożone przez lustro, czy czcionki są, czy tapeta jest.
    """
    uwagi = []

    # 1. skróty własne → skrypty w ~/bin muszą być wożone przez chezmoi
    wozone = set()
    if czy_jest("chezmoi") or (DOM / ".local/bin/chezmoi").exists():
        chez = shutil.which("chezmoi") or str(DOM / ".local/bin/chezmoi")
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
                    f"skrót wskazuje na {plik.replace(str(DOM), '~')}, "
                    f"którego lustro nie wozi\n"
                    f"    propozycja: dołożyć skrypt do lustra "
                    f"(chezmoi add {plik.replace(str(DOM), '~')})")

    # 2. czcionki nazwane w ustawieniach muszą być zainstalowane
    if czy_jest("fc-list"):
        interfejs = _dconf_dump("/org/gnome/desktop/interface/")
        for klucz in ("font-name", "document-font-name", "monospace-font-name"):
            wartosc = interfejs.get("/org/gnome/desktop/interface/" + klucz)
            if not wartosc:
                continue
            rodzina = re.sub(r"\s+\d+$", "", wartosc.strip("'\"")).strip()
            kod, out = uruchom(["fc-list", "-q", rodzina])
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
    return uwagi


# ---------------------------------------------------------------- polecenia

def polecenie_status(args):
    maszyna = nazwa_maszyny()
    zdarzenia = wczytaj_dzienniki()
    inw = inwentaryzacja()
    ostatnie, historia = stan_oczekiwany(zdarzenia)
    moje = stan_wg_tej_maszyny(zdarzenia, maszyna)

    inne = sorted({z.get("maszyna") for z in zdarzenia} - {maszyna})
    opis_luster = []
    for m in inne:
        ost = max((z["ts"] for z in zdarzenia if z.get("maszyna") == m), default="?")
        opis_luster.append(f"{m} (dziennik do {data_ludzka(ost)})")
    if not opis_luster:
        opis_luster = ["brak innych luster — jedyne lustro w dziennikach to ta maszyna"]

    print(f"LUSTRO — {maszyna} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Porównanie z: {', '.join(opis_luster)}")
    print()

    numer = 0
    rozbieznosci, niezapisane, usuniete_poza = [], [], []

    for klucz, zdarz in sorted(ostatnie.items()):
        kanal, ident = klucz
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

    # w inwentarzu, ale bez ŻADNEGO zdarzenia w dzienniku tej maszyny
    for klucz, wersja in sorted(inw.items()):
        if klucz not in moje and klucz not in ostatnie:
            niezapisane.append((klucz, wersja))

    if rozbieznosci:
        print(f"ROZBIEŻNOŚCI ({len(rozbieznosci)})")
        print()
        for (kanal, ident), zdarz, rodzaj in rozbieznosci:
            numer += 1
            if rodzaj == "brak-tutaj":
                print(f"{numer:2}. {ident} — NIE MA tutaj, JEST na {zdarz['maszyna']}")
                print(f"    źródło: {zdarz['maszyna']} dodał {data_ludzka(zdarz['ts'])} "
                      f"({kanal}, {ident})")
                print(f"    propozycja: zainstalować tutaj")
            else:
                print(f"{numer:2}. {ident} — JEST tutaj, USUNIĘTY na {zdarz['maszyna']}")
                print(f"    źródło: {zdarz['maszyna']} usunął {data_ludzka(zdarz['ts'])} ({kanal})")
                if zdarz.get("notatka"):
                    print(f"            notatka: \"{zdarz['notatka']}\"")
                print(f"    propozycja: odinstalować tutaj")
            print()
    else:
        print("ROZBIEŻNOŚCI (0) — nic")
        print()

    if niezapisane:
        print(f"ZAINSTALOWANE POZA APKĄ, JESZCZE NIEZAPISANE W DZIENNIKU ({len(niezapisane)})")
        print()
        for (kanal, ident), wersja in niezapisane:
            numer += 1
            print(f"{numer:2}. {ident} ({kanal}, {wersja}) — jest na maszynie, "
                  f"brak zdarzenia w dzienniku")
            print(f"    propozycja: dopisać do dziennika jako \"dodano … zrodlo: reczne\"")
            print()

    if usuniete_poza:
        print(f"USUNIĘTE POZA APKĄ, JESZCZE NIEZAPISANE W DZIENNIKU ({len(usuniete_poza)})")
        print()
        for (kanal, ident), zdarz in usuniete_poza:
            numer += 1
            print(f"{numer:2}. {ident} ({kanal}) — dziennik mówi \"jest\" "
                  f"(od {data_ludzka(zdarz['ts'])}), na maszynie go nie ma")
            print(f"    propozycja: dopisać do dziennika \"usunieto … zrodlo: reczne\"")
            print()

    # --- warstwa pulpitu ---
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
    print("Nic nie zostało zmienione. Etap E1 — apka umie wyłącznie czytać.")
    return 0


def _wypisz_pulpit(numer):
    """Sekcja pulpitu w `status`; zwraca zaktualizowany licznik pozycji."""
    tutaj = eksport_pulpitu()
    w_lustrze = wczytaj_pulpit_z_lustra()

    if w_lustrze is None:
        numer += 1
        print("PULPIT")
        print()
        print(f"{numer:2}. Lustro nie ma jeszcze zapisanych ustawień pulpitu "
              f"({PLIK_PULPITU.name} nie istnieje)")
        print(f"    propozycja: jednorazowy zasiew — lustro pulpit zasiew")
        print()
        return numer

    rozne = []
    for klucz in sorted(set(tutaj) | set(w_lustrze)):
        a, b = tutaj.get(klucz), w_lustrze.get(klucz)
        if a != b:
            rozne.append((klucz, a, b))

    uwagi = kontrola_pulpitu()

    if not rozne and not uwagi:
        print("PULPIT (0) — ustawienia zgodne z lustrem, kontrola bez zastrzeżeń")
        print()
        return numer

    if rozne:
        numer += 1
        print(f"PULPIT")
        print()
        print(f"{numer:2}. Ustawienia pulpitu różnią się od lustra ({len(rozne)} kluczy):")
        for klucz, a, b in rozne:
            print(f"      {klucz}")
            print(f"        tutaj:     {a if a is not None else 'brak'}")
            print(f"        w lustrze: {b if b is not None else 'brak'}")
        print(f"    propozycja: [o]ddać stąd do lustra / [w]grać z lustra tutaj "
              f"(oba dopiero w E2)")
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
    print(f"Ścieżek dconf objętych lustrem: {len(sciezki)}; "
          f"ustawionych kluczy na tej maszynie: {len(tutaj)}")
    print()
    _wypisz_pulpit(0)
    print("Nic nie zostało zmienione (dconf tylko odczytany).")
    return 0


def polecenie_pulpit_zasiew(args):
    """Jednorazowy zasiew E1: zapisuje bieżący eksport do repozytorium.
    NIE zmienia systemu — pisze wyłącznie plik w katalogu lustra/."""
    stan = eksport_pulpitu()
    zapisz_pulpit(stan, PLIK_PULPITU)
    print(f"Zapisano {len(stan)} kluczy do {PLIK_PULPITU}")
    print("System nie został dotknięty — to zapis do repozytorium, nie do dconf.")
    return 0


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
        print(f"{data_ludzka(z.get('ts'))}  {z.get('maszyna'):<8} "
              f"{opis} {z.get('id','')}{wersja}{kanal}")
        if z.get("notatka"):
            print(f"{'':>18}  └─ {z['notatka']}")
    print()
    print(f"Razem zdarzeń: {len(zdarzenia)}")
    return 0


def polecenie_lista(args):
    """Generuje tabelę programów z dzienników — w formacie programy.md."""
    zdarzenia = wczytaj_dzienniki()
    ostatnie, _ = stan_oczekiwany(zdarzenia)
    maszyny = sorted({z.get("maszyna") for z in zdarzenia if z.get("maszyna")})
    if not maszyny:
        maszyny = [nazwa_maszyny()]

    # ostatnie zdarzenie per (kanal, id, maszyna)
    per_maszyna = {}
    for z in zdarzenia:
        if z.get("zdarzenie") not in ("dodano", "usunieto"):
            continue
        klucz = (z.get("kanal"), z.get("id"), z.get("maszyna"))
        if None not in klucz:
            per_maszyna[klucz] = z

    # "Do czego" i "Uwagi" przenoszone z dziennika (pole notatka) — spec 10.4
    wiersze = []
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
        wiersze.append((ident, kanal, komorki, ost.get("notatka", "")))

    linie = []
    linie.append("# Programy — tabela GENEROWANA z dzienników luster")
    linie.append("")
    linie.append(f"Wygenerowane: {datetime.now().strftime('%Y-%m-%d %H:%M')} "
                 f"przez `lustro lista`. Nie edytować ręcznie — źródłem prawdy "
                 f"jest `lustra/dziennik/*.jsonl`.")
    linie.append("")
    naglowek = "| Program | Kanał | " + " | ".join(maszyny) + " | Uwagi |"
    linie.append(naglowek)
    linie.append("|" + "---|" * (3 + len(maszyny)))
    for ident, kanal, komorki, notatka in wiersze:
        linie.append(f"| {ident} | {kanal} | " + " | ".join(komorki) +
                     f" | {notatka} |")
    linie.append("")
    linie.append(f"Razem pozycji: {len(wiersze)}")
    tresc = "\n".join(linie)

    if args.do:
        Path(args.do).write_text(tresc + "\n", encoding="utf-8")
        print(f"Zapisano {len(wiersze)} pozycji do {args.do}")
    else:
        print(tresc)
    return 0


def niedostepne(nazwa):
    def f(args):
        print(f"`lustro {nazwa}` — niedostępne w E1.")
        print("Etap E1 umie wyłącznie czytać: `status`, `pulpit status`, "
              "`dziennik`, `lista`.")
        print("Zmienianie systemu (instalacja, usuwanie, wgrywanie ustawień) "
              "wchodzi w etapie E2 — spec rozdz. 12.")
        return 2
    return f


# ---------------------------------------------------------------- wejście

def main():
    p = argparse.ArgumentParser(
        prog="lustro",
        description="Porównywarka domowych komputerów. ETAP E1 — TYLKO ODCZYT.")
    pod = p.add_subparsers(dest="polecenie")

    pod.add_parser("status", help="inwentaryzacja + rozbieżności (nic nie zmienia)")

    d = pod.add_parser("dziennik", help="historia zdarzeń po ludzku")
    d.add_argument("--maszyna")
    d.add_argument("--od", help="data od, np. 2026-08-01")

    l = pod.add_parser("lista", help="tabela programów w formacie programy.md")
    l.add_argument("--do", help="zapisz do pliku zamiast na ekran")

    pu = pod.add_parser("pulpit", help="warstwa GNOME (dconf)")
    pu.add_argument("co", choices=["status", "zasiew", "oddaj", "wgraj", "sprawdz"])

    for nazwa, pomoc in (("sync", "wyrównywanie z pytaniem"),
                         ("dodaj", "instalacja programu"),
                         ("usun", "odinstalowanie programu"),
                         ("ustawienia", "oddanie ustawień programu do lustra"),
                         ("nowa-maszyna", "bootstrap")):
        s = pod.add_parser(nazwa, help=pomoc + " (E2/E3 — niedostępne)")
        s.add_argument("reszta", nargs="*")

    args = p.parse_args()

    if args.polecenie is None:
        p.print_help()
        return 0
    if args.polecenie == "status":
        return polecenie_status(args)
    if args.polecenie == "dziennik":
        return polecenie_dziennik(args)
    if args.polecenie == "lista":
        return polecenie_lista(args)
    if args.polecenie == "pulpit":
        if args.co == "status":
            return polecenie_pulpit_status(args)
        if args.co == "zasiew":
            return polecenie_pulpit_zasiew(args)
        return niedostepne("pulpit " + args.co)(args)
    return niedostepne(args.polecenie)(args)


if __name__ == "__main__":
    sys.exit(main())
