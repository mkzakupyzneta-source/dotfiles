#!/usr/bin/env python3
"""Sklada PNG 256x256 z pliku SVG lezacego obok — zrodlo ikon pozycji lustra.

Po co osobny skrypt: ikona ma byc ODTWARZALNA (regula „dane, nie kod" —
zrodlem jest SVG w repozytorium, PNG to wynik), a nie plikiem sciagnietym
z internetu, o ktorym za pol roku nikt nie wie, skad sie wzial.

Uzycie:  python3 zrob-png.py panel-sieci.svg ../../dot_local/share/panel-sieci/panel-sieci.png
Wymaga:  python3-cairosvg (na HP jest; na innej maszynie: sudo apt install python3-cairosvg).
Sprawa [262], 2026-08-29, obszar 5.
"""
import sys
from pathlib import Path

import cairosvg

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(2)
zrodlo, cel = Path(sys.argv[1]), Path(sys.argv[2])
cel.parent.mkdir(parents=True, exist_ok=True)
cairosvg.svg2png(url=str(zrodlo), write_to=str(cel), output_width=256, output_height=256)
print(f"{cel} — {cel.stat().st_size} B")
