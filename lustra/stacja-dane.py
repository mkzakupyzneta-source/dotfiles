#!/usr/bin/env python3
"""
stacja-dane.py — pomocnik `nowa-stacja.sh` i `przyjmij-maszyne.sh`: wszystko, co
wymaga czytania/pisania DANYCH mechanizmu luster (maszyny.toml, siec.toml,
syncthing.toml, klucze-publiczne/) i rozmowy z REST API Syncthinga.
Zero zależności poza Pythonem 3.11+ (tomllib, urllib). Obszar 5_Wspolna_konfiguracja,
2026-08-27, sprawa „automat nowej stacji" ([NR?]).

Podpolecenia (każde wypisuje na stdout, nic nie zmienia poza jawnie opisanymi):
  (~/.ssh/config i ~/.ssh/authorized_keys stacji SKŁADA CHEZMOI z maszyny.toml/siec.toml
   i klucze-publiczne/ — szablony obszaru 2, sprawa [222]; tu ich nie ma celowo)
  hosty            [--bez X]            → adresy maszyn domowych (do ssh-keyscan), po jednym w linii
  cele             [--bez X]            → "klucz user host profil" maszyn z kontem SSH (profil: stacja|serwer|-)
  maszyna-wpisz    --klucz X …          → ZMIENIA maszyny.toml (blok X: dopisuje/aktualizuje pola)
  karty-wpisz      --klucz X [--pokaz]  → MIERZY karty sieciowe TEJ maszyny i ZMIENIA maszyny.toml
                                          (bloki [[maszyna.karta]] bloku X + skrót `mac_lan`)
  syncthing-konfiguruj --api --klucz-api --nazwa X --dom D --pulpit P
                                        → ZMIENIA konfigurację lokalnego Syncthinga (nowa stacja)
  syncthing-przyjmij   --api --klucz-api --id ID --nazwa X [--adresy a,b]
                                        → ZMIENIA konfigurację Syncthinga (serwer/stacja): dopisuje
                                          urządzenie i dokłada je do folderów z syncthing.toml
  syncthing-urzadzenie-wpisz --klucz X --id ID --nazwa N --adresy a,b
                                        → ZMIENIA syncthing.toml (blok [[urzadzenie]])
"""
import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

TU = Path(__file__).resolve().parent
MASZYNY = TU / "maszyny.toml"
SIEC = TU / "siec.toml"
SYNCTHING = TU / "syncthing.toml"
KLUCZE = TU / "klucze-publiczne"


def wczytaj(plik):
    with open(plik, "rb") as f:
        return tomllib.load(f)


def maszyny():
    return wczytaj(MASZYNY).get("maszyna", [])


# ------------------------------------------------------------ hosty / cele

def polecenie_hosty(a):
    for m in maszyny():
        if m.get("klucz") == a.bez or not m.get("aktywna", True):
            continue
        for pole in ("host_lan", "ip_tailscale"):
            w = (m.get(pole) or "").strip()
            if w:
                print(w)


def polecenie_cele(a):
    """Maszyny, na które da się wejść po SSH z kontem (do rozniesienia kluczy)."""
    for m in maszyny():
        if m.get("klucz") == a.bez or not m.get("aktywna", True) or not m.get("user"):
            continue
        host = (m.get("host_lan") or m.get("ip_tailscale") or "").strip()
        if host:
            print(m["klucz"], m["user"], host, m.get("profil") or "-")


# ------------------------------------------------------------- maszyna-wpisz

POLA_WPISU = ("nazwa", "rola", "nazwa_hosta", "host_lan", "host_tailscale", "ip_tailscale",
              "user", "katalog_roboczy", "dostepna_jako_cel", "aktywna", "profil",
              "czlonek_lustra", "mac_lan", "system")
# Pola USERA (opis człowieka): przy AKTUALIZACJI istniejącego bloku NIE są nadpisywane,
# jeśli już mają niepustą wartość — automat daje je tylko nowemu blokowi. Wniosek z HP
# 29.08 ([252] uzup. 3): K5 wpisywał `--rola "Stacja robocza"` przy każdym biegu, a nazwę
# „HP (Windows)" zostawił — system operacyjny to DANA (pole `system`, z PRETTY_NAME
# /etc/os-release, odświeżane przy każdym biegu), nie część nazwy.
POLA_USERA = ("nazwa", "rola")


def _toml_wartosc(w):
    if isinstance(w, bool):
        return "true" if w else "false"
    return '"' + str(w).replace("\\", "\\\\").replace('"', '\\"') + '"'


def polecenie_maszyna_wpisz(a):
    """Blok [[maszyna]] o danym `klucz`: istnieje → pola podmienione (tylko podane),
    nie istnieje → nowy blok na końcu. Edycja tekstowa (tomllib nie pisze), potem
    kontrola: plik musi się dać wczytać i blok musi mieć wpisane wartości."""
    tekst = MASZYNY.read_text(encoding="utf-8")
    kopia = tekst
    nowe = {}
    for pole in POLA_WPISU:
        w = getattr(a, pole.replace("-", "_"), None)
        if w is None:
            continue
        if pole in ("dostepna_jako_cel", "aktywna", "czlonek_lustra"):
            w = w.lower() in ("1", "true", "tak", "yes")
        nowe[pole] = w

    linie = tekst.split("\n")
    # granice bloków [[maszyna]] (bez [[maszyna.konto]])
    starty = [i for i, l in enumerate(linie) if l.strip() == "[[maszyna]]"]
    granice = []
    for n, s in enumerate(starty):
        koniec = starty[n + 1] if n + 1 < len(starty) else len(linie)
        granice.append((s, koniec))
    wzor_klucz = re.compile(r'^\s*klucz\s*=\s*"([^"]*)"')
    cel = None
    for s, k in granice:
        for i in range(s, k):
            m = wzor_klucz.match(linie[i])
            if m and m.group(1) == a.klucz:
                cel = (s, k)
                break
        if cel:
            break

    if cel:
        s, k = cel
        # Nie ruszamy nic od `uwagi = """` w dół ani od PIERWSZEJ pod-tabeli bloku.
        # ⚠️ Warunek jest CELOWO ogólny (`[[maszyna.` — każda pod-tabela), nie listą
        # znanych nazw: pola płaskie wstawiamy pod `stop`, więc gdyby pisarz nie znał
        # jakiejś pod-tabeli, wstawiłby `system = "..."` do JEJ ŚRODKA i po cichu
        # zepsuł dane. Do 30.08 znał tylko `[[maszyna.konto]]`; wtedy doszły
        # `[[maszyna.karta]]` ([285]) i następne dojdą bez zmian w tym kodzie.
        stop = k
        for i in range(s, k):
            l = linie[i].strip()
            if l.startswith("uwagi") or l.startswith("[[maszyna."):
                stop = i
                break
        pominiete = []
        for pole, w in list(nowe.items()):
            wz = re.compile(r"^(\s*)" + re.escape(pole) + r"\s*=.*$")
            for i in range(s, stop):
                m = wz.match(linie[i])
                if m:
                    if pole in POLA_USERA and re.search(r'=\s*"[^"]+"', linie[i]):
                        pominiete.append(pole)      # pole usera z wartością — zostaje
                        del nowe[pole]
                        break
                    linie[i] = f"{m.group(1)}{pole} = {_toml_wartosc(w)}"
                    break
            else:
                linie.insert(stop, f"{pole} = {_toml_wartosc(w)}")
                stop += 1
        if pominiete:
            print(f"maszyna-wpisz: pola usera zostawione bez zmian: {', '.join(pominiete)}")
        tekst = "\n".join(linie)
    else:
        blok = [
            "",
            f"# ── {a.klucz} — dopisane automatycznie przez nowa-stacja.sh ({date.today().isoformat()}) ──",
            "[[maszyna]]",
            f'klucz = "{a.klucz}"',
        ]
        if "nazwa" not in nowe:
            nowe["nazwa"] = a.klucz.capitalize()
        for pole in POLA_WPISU:
            if pole in nowe:
                blok.append(f"{pole} = {_toml_wartosc(nowe[pole])}")
        blok.append('uwagi = """')
        blok.append(f"Stacja postawiona automatem nowa-stacja.sh ({date.today().isoformat()}).")
        blok.append('"""')
        tekst = tekst.rstrip("\n") + "\n" + "\n".join(blok) + "\n"

    MASZYNY.write_text(tekst, encoding="utf-8")
    try:
        dane = wczytaj(MASZYNY)
        blok = next(m for m in dane["maszyna"] if m.get("klucz") == a.klucz)
        for pole, w in nowe.items():
            if blok.get(pole) != w:
                raise ValueError(f"pole {pole}: jest {blok.get(pole)!r}, miało być {w!r}")
    except Exception as e:  # noqa: BLE001
        MASZYNY.write_text(kopia, encoding="utf-8")
        print(f"maszyna-wpisz: BŁĄD kontroli po edycji ({e}) — plik przywrócony", file=sys.stderr)
        return 1
    print(f"maszyna-wpisz: blok [[maszyna]] klucz={a.klucz!r} "
          + ("zaktualizowany" if cel else "dopisany") + f": {nowe}")
    return 0


# -------------------------------------------------------------- karty-wpisz

# Interfejsy, których NIE opisujemy jako kart maszyny: pętla zwrotna i sieci wirtualne
# zakładane przez programy (Tailscale, Docker, libvirt, mosty KVM). To nie jest sprzęt
# maszyny i ich adresy nie są adresami w domowej sieci.
KARTY_POMIJANE = ("lo", "tailscale", "docker", "veth", "virbr", "br-", "vnet", "wg", "tun", "tap")


def zmierz_karty():
    """Karty sieciowe TEJ maszyny prosto z /sys i `ip` → lista słowników
    {nazwa, rodzaj, mac, adres}. Rodzaj jest MIERZONY, nie zgadywany z nazwy:
    katalog `wireless` w /sys → wifi; ścieżka urządzenia przez USB → usb-eth
    (tym samym wygląda port w doku — czy to dok, wie tylko człowiek, dlatego
    `rodzaj` istniejącej karty nigdy nie jest nadpisywany); reszta → kabel."""
    korzen = Path("/sys/class/net")
    if not korzen.is_dir():
        return []
    adresy = {}
    try:
        import subprocess
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"],
                             capture_output=True, text=True, timeout=10).stdout
        for l in out.splitlines():
            cz = l.split()
            if len(cz) >= 4:
                adresy.setdefault(cz[1], cz[3].split("/")[0])
    except Exception:                                   # noqa: BLE001
        pass
    wynik = []
    for kat in sorted(korzen.iterdir()):
        nazwa = kat.name
        if any(nazwa.startswith(w) for w in KARTY_POMIJANE):
            continue
        try:
            mac = (kat / "address").read_text().strip()
        except OSError:
            mac = ""
        if not mac or mac == "00:00:00:00:00:00":
            continue
        if (kat / "wireless").is_dir():
            rodzaj = "wifi"
        else:
            try:
                dev = os.path.realpath(kat / "device")
            except OSError:
                dev = ""
            rodzaj = "usb-eth" if "/usb" in dev else "kabel"
        wynik.append({"nazwa": nazwa, "rodzaj": rodzaj, "mac": mac,
                      "adres": adresy.get(nazwa, "")})
    return wynik


def polecenie_karty_wpisz(a):
    """Bloki [[maszyna.karta]] dla maszyny `--klucz`: kartę znaną (po nazwie albo po MAC)
    AKTUALIZUJE w miejscu, nieznaną DOPISUJE. Niczego nie kasuje — karta chwilowo
    niewidoczna (odpięty dok, wyjęta przejściówka) to nie jest karta nieistniejąca.
    `rodzaj` i `budzenie` istniejącej karty zostają bez zmian: pierwsze bywa decyzją
    człowieka (dok kontra zwykły USB), drugie jest nią zawsze.
    Na koniec pilnuje skrótu `mac_lan` — ma stać w nim MAC karty z `budzenie = true`."""
    zmierzone = zmierz_karty()
    if not zmierzone:
        print("karty-wpisz: nie zmierzyłem żadnej karty (brak /sys/class/net?) — nic nie robię",
              file=sys.stderr)
        return 1
    print("karty-wpisz: zmierzone karty tej maszyny:")
    for k in zmierzone:
        print(f"    {k['nazwa']:16} {k['rodzaj']:8} {k['mac']}  {k['adres'] or '(bez adresu)'}")

    tekst = MASZYNY.read_text(encoding="utf-8")
    kopia = tekst
    linie = tekst.split("\n")
    starty = [i for i, l in enumerate(linie) if l.strip() == "[[maszyna]]"]
    granice = [(s, starty[n + 1] if n + 1 < len(starty) else len(linie))
               for n, s in enumerate(starty)]
    wzor_klucz = re.compile(r'^\s*klucz\s*=\s*"([^"]*)"')
    cel = None
    for s, k in granice:
        if any((m := wzor_klucz.match(linie[i])) and m.group(1) == a.klucz
               for i in range(s, k)):
            cel = (s, k)
            break
    if cel is None:
        print(f"karty-wpisz: nie ma bloku [[maszyna]] o klucz={a.klucz!r}", file=sys.stderr)
        return 1
    s, k = cel

    # granice istniejących pod-bloków [[maszyna.karta]] wewnątrz bloku maszyny
    karty_od = [i for i in range(s, k) if linie[i].strip() == "[[maszyna.karta]]"]

    def pole_w_bloku(i0, pole):
        """Numer linii z danym polem wewnątrz pod-bloku zaczynającego się w i0."""
        for i in range(i0 + 1, k):
            l = linie[i].strip()
            if l.startswith("[["):
                return None
            m = re.match(r"^(\s*)" + re.escape(pole) + r"\s*=", linie[i])
            if m:
                return i
        return None

    def wartosc(i0, pole):
        i = pole_w_bloku(i0, pole)
        if i is None:
            return None
        m = re.search(r'=\s*"([^"]*)"', linie[i])
        return m.group(1) if m else linie[i].split("=", 1)[1].strip()

    zmiany, dopisane = [], []
    for karta in zmierzone:
        trafiony = None
        for i0 in karty_od:
            if (wartosc(i0, "nazwa") or "") == karta["nazwa"] or \
               ((wartosc(i0, "mac") or "").lower() == karta["mac"].lower() and karta["mac"]):
                trafiony = i0
                break
        if trafiony is None:
            dopisane.append(karta)
            continue
        for pole in ("nazwa", "mac", "adres"):
            i = pole_w_bloku(trafiony, pole)
            nowa = karta[pole]
            if i is None:
                continue
            stara = wartosc(trafiony, pole)
            if stara == nowa or (pole == "adres" and not nowa):
                continue          # brak adresu w pomiarze nie kasuje zapisanego
            wc = re.match(r"^(\s*)(\w+)(\s*)=", linie[i])
            linie[i] = f'{wc.group(1)}{pole}{wc.group(3)}= "{nowa}"'
            zmiany.append(f"{karta['nazwa']}.{pole}: {stara!r} → {nowa!r}")

    if dopisane:
        # wstawiamy PO ostatnim istniejącym [[maszyna.karta]], a gdy nie ma żadnego —
        # po polu `uwagi` (czyli za wszystkimi polami płaskimi bloku)
        if karty_od:
            wst = karty_od[-1] + 1
            while wst < k and not linie[wst].strip().startswith("[["):
                wst += 1
        else:
            wst = k
            for i in range(s, k):
                if linie[i].startswith('uwagi = """'):
                    wst = next((j + 1 for j in range(i + 1, k)
                                if linie[j].rstrip().endswith('"""')), k)
                    break
                if linie[i].strip().startswith("[[maszyna."):
                    wst = i
                    break
        blok = []
        for karta in dopisane:
            blok += ["", "  [[maszyna.karta]]",
                     f'  # dopisane automatycznie (karty-wpisz, {date.today().isoformat()})',
                     f'  nazwa    = "{karta["nazwa"]}"',
                     f'  rodzaj   = "{karta["rodzaj"]}"',
                     f'  mac      = "{karta["mac"]}"',
                     f'  adres    = "{karta["adres"]}"',
                     "  budzenie = false"]
        linie[wst:wst] = blok

    tekst = "\n".join(linie)

    if a.pokaz:
        for z in zmiany:
            print("    zmiana: " + z)
        for d in dopisane:
            print(f"    dopisanie: {d['nazwa']} ({d['rodzaj']}, {d['mac']})")
        if not zmiany and not dopisane:
            print("    nic do zmiany")
        print("karty-wpisz: --pokaz — pliku NIE zapisuję")
        return 0

    MASZYNY.write_text(tekst, encoding="utf-8")
    try:
        dane = wczytaj(MASZYNY)
        blok_m = next(m for m in dane["maszyna"] if m.get("klucz") == a.klucz)
        karty = blok_m.get("karta", [])
        if not karty:
            raise ValueError("po zapisie blok nie ma ani jednej [[maszyna.karta]]")
    except Exception as e:                                # noqa: BLE001
        MASZYNY.write_text(kopia, encoding="utf-8")
        print(f"karty-wpisz: BŁĄD kontroli po edycji ({e}) — plik przywrócony", file=sys.stderr)
        return 1

    for z in zmiany:
        print("    zmiana: " + z)
    for d in dopisane:
        print(f"    dopisane: {d['nazwa']} ({d['rodzaj']}, {d['mac']})")
    if not zmiany and not dopisane:
        print("    nic do zmiany — dane kart były aktualne")

    # skrót `mac_lan` — kontrola, nie zgadywanie: poprawiamy tylko wtedy, gdy DOKŁADNIE
    # jedna karta ma `budzenie = true` (inaczej to decyzja człowieka, nie automatu)
    budzace = [c for c in karty if c.get("budzenie")]
    if len(budzace) == 1 and blok_m.get("mac_lan", "").lower() != budzace[0]["mac"].lower():
        print(f"    ⚠ `mac_lan` = {blok_m.get('mac_lan')!r}, a kartą do budzenia jest "
              f"{budzace[0]['nazwa']} ({budzace[0]['mac']}) — popraw `mac_lan` "
              f"(`maszyna-wpisz --klucz {a.klucz} --mac-lan {budzace[0]['mac']}`)")
    elif not budzace:
        print("    ⚠ żadna karta nie ma `budzenie = true` — budzenie przez sieć nie zadziała; "
              "ustaw je na karcie KABLOWEJ")
    return 0


# ------------------------------------------------------------ Syncthing REST

def _rest(api, klucz, sciezka, metoda="GET", dane=None):
    req = urllib.request.Request(api.rstrip("/") + sciezka, method=metoda,
                                 headers={"X-API-Key": klucz, "Content-Type": "application/json"},
                                 data=None if dane is None else json.dumps(dane).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        tresc = r.read().decode() or "null"
        return json.loads(tresc)


def _sciezka_folderu(wzor, dom, pulpit):
    return wzor.replace("$PULPIT", pulpit).replace("~", dom, 1) if wzor.startswith("~") \
        else wzor.replace("$PULPIT", pulpit)


def _dodaj_urzadzenie(api, klucz, ident, nazwa, adresy):
    obecne = {d["deviceID"]: d for d in _rest(api, klucz, "/rest/config/devices")}
    if ident in obecne:
        print(f"   urządzenie {nazwa} ({ident[:7]}…) już jest — pomijam")
        return
    wzor = _rest(api, klucz, "/rest/config/defaults/device")
    wzor.update({"deviceID": ident, "name": nazwa, "addresses": adresy or ["dynamic"]})
    _rest(api, klucz, "/rest/config/devices", "POST", wzor)
    print(f"   + urządzenie {nazwa} ({ident[:7]}…) adresy {adresy}")


def _dolacz_do_folderu(api, klucz, folder_id, ident):
    try:
        f = _rest(api, klucz, f"/rest/config/folders/{folder_id}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"   folder {folder_id}: nie ma go w tej instancji — pomijam")
            return False
        raise
    if any(d["deviceID"] == ident for d in f.get("devices", [])):
        print(f"   folder {folder_id}: {ident[:7]}… już jest uczestnikiem")
        return True
    f["devices"].append({"deviceID": ident, "introducedBy": "", "encryptionPassword": ""})
    _rest(api, klucz, f"/rest/config/folders/{folder_id}", "PUT", f)
    print(f"   + folder {folder_id}: dodany uczestnik {ident[:7]}…")
    return True


def polecenie_syncthing_konfiguruj(a):
    """NOWA stacja: wszystkie urządzenia z syncthing.toml + oba foldery (uczestnicy =
    wszystkie urządzenia z pliku + ja). Idempotentne."""
    dane = wczytaj(SYNCTHING)
    moje_id = _rest(a.api, a.klucz_api, "/rest/system/status")["myID"]
    print(f"Syncthing lokalny: ID {moje_id}")
    urzadzenia = dane.get("urzadzenie", [])
    for u in urzadzenia:
        if u["id"] == moje_id:
            continue
        _dodaj_urzadzenie(a.api, a.klucz_api, u["id"], u["nazwa"], u.get("adresy"))
    obecne_foldery = {f["id"] for f in _rest(a.api, a.klucz_api, "/rest/config/folders")}
    for f in dane.get("folder", []):
        sciezka = _sciezka_folderu(f["sciezka"], a.dom, a.pulpit)
        Path(sciezka).mkdir(parents=True, exist_ok=True)
        st = Path(sciezka) / ".stignore"
        if f.get("stignore") and not st.exists():
            st.write_text("\n".join(f["stignore"]) + "\n", encoding="utf-8")
        if f["id"] in obecne_foldery:
            print(f"   folder {f['id']} już skonfigurowany — dokładam tylko uczestników")
            for u in urzadzenia:
                if u["id"] != moje_id:
                    _dolacz_do_folderu(a.api, a.klucz_api, f["id"], u["id"])
            continue
        wzor = _rest(a.api, a.klucz_api, "/rest/config/defaults/folder")
        wzor.update({
            "id": f["id"], "label": f.get("etykieta", f["id"]), "path": sciezka,
            "type": "sendreceive",
            "devices": [{"deviceID": u["id"], "introducedBy": "", "encryptionPassword": ""}
                        for u in urzadzenia if u["id"] != moje_id]
                       + [{"deviceID": moje_id, "introducedBy": "", "encryptionPassword": ""}],
        })
        if f.get("wersjonowanie"):
            wzor["versioning"] = dict(wzor.get("versioning", {}),
                                      type=f["wersjonowanie"],
                                      params={k: str(v) for k, v in f.get("parametry", {}).items()})
        _rest(a.api, a.klucz_api, "/rest/config/folders", "POST", wzor)
        print(f"   + folder {f['id']} → {sciezka} ({f.get('wersjonowanie', 'bez wersjonowania')})")
    print("MOJE_ID=" + moje_id)
    return 0


def polecenie_syncthing_przyjmij(a):
    """Serwer/stacja: dopisz urządzenie nowej stacji i dołóż je do folderów z syncthing.toml."""
    adresy = [x for x in (a.adresy or "").split(",") if x] or ["dynamic"]
    _dodaj_urzadzenie(a.api, a.klucz_api, a.id, a.nazwa, adresy)
    for f in wczytaj(SYNCTHING).get("folder", []):
        _dolacz_do_folderu(a.api, a.klucz_api, f["id"], a.id)
    return 0


def polecenie_syncthing_urzadzenie_wpisz(a):
    tekst = SYNCTHING.read_text(encoding="utf-8")
    if re.search(r'^klucz\s*=\s*"' + re.escape(a.klucz) + '"', tekst, re.M):
        # podmiana id/adresów istniejącego bloku — najprościej: usuń blok i dopisz na nowo
        tekst = re.sub(r'\n\[\[urzadzenie\]\]\nklucz = "' + re.escape(a.klucz) + r'"\n(?:[^\[\n][^\n]*\n)*',
                       "\n", tekst)
    adresy = [x for x in a.adresy.split(",") if x]
    blok = (f'\n[[urzadzenie]]\nklucz = "{a.klucz}"\nid = "{a.id}"\nnazwa = "{a.nazwa}"\n'
            f'adresy = [{", ".join(_toml_wartosc(x) for x in adresy)}]\n')
    # wstaw przed pierwszym [[folder]]
    poz = tekst.find("\n[[folder]]")
    tekst = tekst[:poz] + blok + tekst[poz:] if poz >= 0 else tekst + blok
    SYNCTHING.write_text(tekst, encoding="utf-8")
    wczytaj(SYNCTHING)  # kontrola składni
    print(f"syncthing.toml: urządzenie {a.klucz} = {a.id[:7]}… zapisane")
    return 0


# ------------------------------------------------------------------ main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    pod = p.add_subparsers(dest="co", required=True)

    s = pod.add_parser("hosty"); s.add_argument("--bez")
    s = pod.add_parser("cele"); s.add_argument("--bez")

    s = pod.add_parser("maszyna-wpisz")
    s.add_argument("--klucz", required=True)
    for pole in POLA_WPISU:
        s.add_argument("--" + pole.replace("_", "-"), dest=pole)

    for nazwa in ("syncthing-konfiguruj", "syncthing-przyjmij"):
        s = pod.add_parser(nazwa)
        s.add_argument("--api", default="http://127.0.0.1:8384")
        s.add_argument("--klucz-api", required=True, dest="klucz_api")
        if nazwa == "syncthing-konfiguruj":
            s.add_argument("--dom", default=str(Path.home()))
            s.add_argument("--pulpit", default=str(Path.home() / "Desktop"))
        else:
            s.add_argument("--id", required=True)
            s.add_argument("--nazwa", required=True)
            s.add_argument("--adresy", default="")

    s = pod.add_parser("karty-wpisz")
    s.add_argument("--klucz", required=True)
    s.add_argument("--pokaz", action="store_true",
                   help="tylko pokaż, co by zmienił — pliku nie zapisuje")

    s = pod.add_parser("syncthing-urzadzenie-wpisz")
    s.add_argument("--klucz", required=True); s.add_argument("--id", required=True)
    s.add_argument("--nazwa", required=True); s.add_argument("--adresy", default="dynamic")

    a = p.parse_args()
    return {
        "hosty": polecenie_hosty,
        "cele": polecenie_cele,
        "maszyna-wpisz": polecenie_maszyna_wpisz,
        "karty-wpisz": polecenie_karty_wpisz,
        "syncthing-konfiguruj": polecenie_syncthing_konfiguruj,
        "syncthing-przyjmij": polecenie_syncthing_przyjmij,
        "syncthing-urzadzenie-wpisz": polecenie_syncthing_urzadzenie_wpisz,
    }[a.co](a) or 0


if __name__ == "__main__":
    sys.exit(main())
