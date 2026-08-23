#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zasiew-e1 — JEDNORAZOWE zasianie dziennika lustra (etap E1).

Buduje `dziennik/<maszyna>.jsonl` z tego, co na maszynie JEST DZISIAJ, doklejając
daty z przeszłości:
  • apt      → /var/log/apt/history.log (wpisy `Install:` bez adnotacji `automatic`)
  • flatpak  → data katalogu /var/lib/flatpak/app/<id>
  • snap     → data dowiązania /snap/<nazwa>/current
Gdzie daty nie da się ustalić — wpis dostaje datę 2026-08-22 i notatkę "zasiew".

Opisy "Do czego" doklejane z tabel `programy.md` (dopasowanie po nazwie pakietu
wyciągniętej z kolumny "Skąd / komenda instalacji").

TYLKO ODCZYT SYSTEMU. Skrypt pisze wyłącznie plik dziennika w repozytorium.
Uruchomienie drugi raz nadpisze dziennik — po E1 zdarzenia dopisuje już apka.
"""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lustro  # noqa: E402

DATA_ZASIEWU = "2026-08-22T12:00:00+02:00"
STREFA = "+02:00"


def daty_apt():
    """{pakiet: 'YYYY-MM-DDTHH:MM:SS+02:00'} — ostatnia RĘCZNA instalacja z history.log."""
    plik = Path("/var/log/apt/history.log")
    if not plik.exists():
        return {}
    tresc = plik.read_text(encoding="utf-8", errors="replace")
    daty = {}
    for blok in tresc.split("\n\n"):
        m = re.search(r"^Start-Date:\s+(\S+)\s+(\S+)", blok, re.M)
        if not m:
            continue
        ts = f"{m.group(1)}T{m.group(2)}{STREFA}"
        inst = re.search(r"^Install:\s*(.*?)(?=^\w+-?\w*:|\Z)", blok, re.M | re.S)
        if not inst:
            continue
        for kawalek in re.findall(r"([\w.+-]+):\w+\s+\(([^)]*)\)", inst.group(1)):
            nazwa, szczegoly = kawalek
            if "automatic" in szczegoly:
                continue                    # zależność, nie świadoma instalacja
            daty[nazwa] = ts                # późniejszy blok nadpisuje wcześniejszy
    return daty


def daty_flatpak():
    daty = {}
    katalog = Path("/var/lib/flatpak/app")
    if not katalog.is_dir():
        return daty
    for p in katalog.iterdir():
        try:
            d = datetime.fromtimestamp(p.stat().st_mtime).astimezone()
            daty[p.name] = d.replace(microsecond=0).isoformat()
        except OSError:
            pass
    return daty


def daty_snap():
    daty = {}
    katalog = Path("/snap")
    if not katalog.is_dir():
        return daty
    for p in katalog.iterdir():
        link = p / "current"
        if not link.is_symlink():
            continue
        try:
            d = datetime.fromtimestamp(link.lstat().st_mtime).astimezone()
            daty[p.name] = d.replace(microsecond=0).isoformat()
        except OSError:
            pass
    return daty


def opisy_z_programy_md(sciezka):
    """{nazwa_pakietu: 'do czego'} — z tabel programy.md."""
    plik = Path(sciezka)
    if not plik.exists():
        return {}
    opisy = {}
    for linia in plik.read_text(encoding="utf-8").splitlines():
        if not linia.startswith("|"):
            continue
        pola = [c.strip() for c in linia.strip("|").split("|")]
        if len(pola) < 3 or pola[0] in ("Program", "Rozszerzenie") or set(pola[0]) <= {"-"}:
            continue
        do_czego, komenda = pola[1], pola[2]
        for m in re.finditer(r"(?:apt install|snap install)\s+([\w.+\- ]+)", komenda):
            for nazwa in m.group(1).split():
                opisy.setdefault(nazwa, do_czego)
        for m in re.finditer(r"flatpak install\s+\S+\s+([\w.]+)", komenda):
            opisy.setdefault(m.group(1), do_czego)
        for m in re.finditer(r"pakiet `([\w.+-]+)`", komenda):
            opisy.setdefault(m.group(1), do_czego)
    return opisy


def main():
    maszyna = lustro.nazwa_maszyny()
    programy_md = (Path(__file__).resolve().parents[3]
                   / "AI-katalog-roboczy/10_Siec_domowa/5_Wspolna_konfiguracja/programy.md")
    if len(sys.argv) > 1:
        programy_md = Path(sys.argv[1])
    opisy = opisy_z_programy_md(programy_md)

    zrodla_dat = {"apt": daty_apt(), "flatpak": daty_flatpak(), "snap": daty_snap()}
    inw = lustro.inwentaryzacja()

    zdarzenia = []
    bez_daty = []
    for (kanal, ident), wersja in sorted(inw.items()):
        ts = zrodla_dat.get(kanal, {}).get(ident)
        notatki = []
        if opisy.get(ident):
            notatki.append(opisy[ident])
        if ts is None:
            ts = DATA_ZASIEWU
            notatki.append("zasiew — daty instalacji nie dało się ustalić")
            bez_daty.append(f"{kanal}:{ident}")
        else:
            notatki.append("zasiew E1 — data z historii systemu")
        zdarzenia.append({
            "ts": ts,
            "maszyna": maszyna,
            "zdarzenie": "dodano",
            "kanal": kanal,
            "id": ident,
            "wersja": wersja,
            "zrodlo": "reczne",
            "notatka": "; ".join(notatki),
        })

    zdarzenia.sort(key=lambda z: z["ts"])
    zdarzenia.append({
        "ts": lustro.teraz_iso(),
        "maszyna": maszyna,
        "zdarzenie": "notatka",
        "zrodlo": "apka",
        "id": "zasiew-e1",
        "notatka": (f"Dziennik zasiany {len(zdarzenia)} pozycjami z inwentaryzacji "
                    f"maszyny (apt/snap/flatpak po odsianiu wykluczeń). "
                    f"Daty z /var/log/apt/history.log, /var/lib/flatpak/app "
                    f"i /snap/*/current. Etap E1."),
    })

    lustro.DZIENNIKI.mkdir(parents=True, exist_ok=True)
    plik = lustro.DZIENNIKI / f"{maszyna}.jsonl"
    with plik.open("w", encoding="utf-8") as f:
        for z in zdarzenia:
            f.write(json.dumps(z, ensure_ascii=False) + "\n")

    print(f"Zapisano {len(zdarzenia)} zdarzeń do {plik}")
    print(f"  apt: {sum(1 for z in zdarzenia if z.get('kanal') == 'apt')}, "
          f"snap: {sum(1 for z in zdarzenia if z.get('kanal') == 'snap')}, "
          f"flatpak: {sum(1 for z in zdarzenia if z.get('kanal') == 'flatpak')}")
    if bez_daty:
        print(f"  bez ustalonej daty (data zasiewu {DATA_ZASIEWU[:10]}): "
              f"{', '.join(bez_daty)}")
    print(f"  opisów doklejonych z programy.md: "
          f"{sum(1 for z in zdarzenia if z.get('id') in opisy)}")


if __name__ == "__main__":
    main()
