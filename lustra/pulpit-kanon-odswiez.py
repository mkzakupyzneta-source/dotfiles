#!/usr/bin/env python3
"""ZRZUĆ PULPIT TEJ MASZYNY DO KANONU — gałąź `ubuntu-2604`, sprawa [423] (2026-09-14).

Po co osobny skrypt, skoro jest `lustro pulpit oddaj`: kanon tej gałęzi ma TRZY świadome
odstępstwa od surowego zrzutu, których `oddaj` nie zna i przy każdym uruchomieniu by je
zjadł. Ten skrypt robi to samo co `oddaj`, a potem nakłada te trzy poprawki z powrotem.

    python3 ~/.local/share/chezmoi/lustra/pulpit-kanon-odswiez.py

Trzy poprawki (każda uzasadniona, każda idempotentna):
  1. TAPETA — kanon wskazuje WŁASNĄ KOPIĘ pliku (`~/.local/share/tapety/…`, wożoną przez
     chezmoi), a nie plik z pakietu `ubuntu-wallpapers`: inne wydanie Ubuntu ma inną tapetę
     w /usr/share/backgrounds (spec 8.6 — „tapeta to plik, nie tylko ustawienie").
  2. SKRÓT `custom2` (Super+Shift+H → ~/bin/dane-logowania) — skrypt opierał się na xdotool
     (X11) i wypadł z kanonu tej gałęzi. Same klucze `custom2` odsiewa już
     `pulpit/dconf-pomijane-klucze.txt`; tutaj trzeba jeszcze wyjąć jego ścieżkę z LISTY
     `custom-keybindings`, bo bez tego GNOME szukałby skrótu, którego nie ma.
  3. `disabled-extensions` — dokładnie cztery pozycje profilu [418]; bez zaszłości
     `forge@jmmaranan.com`, która wisi w dconf HP po rozszerzeniu, którego już nie ma.

Skrypt NICZEGO nie zmienia na maszynie (czyta dconf) i NIE robi commitu — na końcu wypisuje
gotowe komendy gita. Po odświeżeniu warto zerknąć `git diff` na pulpit.ini: to jest miejsce,
w którym widać, co user naprawdę przestawił.
"""
import importlib.util
import pathlib
import sys

KAT = pathlib.Path(__file__).resolve().parent

TAPETA_STARA = "file:///usr/share/backgrounds/ubuntu-wallpaper-d.png"
TAPETA_NOWA = "file://{{HOME}}/.local/share/tapety/ubuntu-wallpaper-d.png"
CUSTOM2 = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom2/"
WYLACZONE = ("disabled-extensions=['ubuntu-dock@ubuntu.com', 'tiling-assistant@ubuntu.com', "
             "'ubuntu-appindicators@ubuntu.com', 'gTile@vibou']")

NAGLOWEK_DODATEK = """#
# ⚠️ GAŁĄŹ `ubuntu-2604`, sprawa [423]: pełne lustro pulpitu (wygląd, skróty, ustawienia
# rozszerzeń, lista włączonych i wyłączonych). Odświeżanie: `pulpit-kanon-odswiez.py`
# w tym samym katalogu — NIE samo `lustro pulpit oddaj` (zjadłoby trzy świadome poprawki
# opisane w nagłówku tamtego skryptu: tapeta jako własny plik, wycięty skrót custom2,
# lista disabled-extensions bez zaszłości).
"""


def nazwa_z_hosta(m):
    """Klucz TEJ maszyny wyprowadzony WYŁĄCZNIE z nazwy hosta i `lustra/maszyny.toml`
    (czyli tak, jak robi to `lustro.py`, ale z pominięciem pliku `maszyna.txt`)."""
    import socket
    import tomllib
    host = socket.gethostname().strip().lower()
    try:
        dane = tomllib.loads((KAT / "maszyny.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return host or None
    for wpis in dane.get("maszyna", []):
        if (wpis.get("nazwa_hosta") or "").strip().lower() == host:
            return (wpis.get("klucz") or host).strip() or host
    return host or None


def main():
    spec = importlib.util.spec_from_file_location("lustro_kanon", KAT / "lustro.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["lustro_kanon"] = m
    spec.loader.exec_module(m)

    # ⚠️ TOŻSAMOŚĆ MASZYNY WZORCOWEJ, a nie nazwa wymuszona plikiem `lustra/maszyna.txt`.
    # Na tej gałęzi `maszyna.txt` mówi „vostro-temp" — tak ma się nazywać NOWA maszyna — ale
    # zrzut robimy na maszynie WZORCOWEJ (HP) i to JEJ tożsamością trzeba zwijać znaczniki
    # maszynowe [291]. Bez tego nazwa czujnika temperatury procesora HP
    # (`_temperature_k10temp_tctl_`, AMD) wpadłaby do kanonu DOSŁOWNIE zamiast zwinąć się do
    # `{{TEMP_CPU}}` — i pojechała na maszynę z innym procesorem jako martwa pozycja Vitals.
    wzorcowa = nazwa_z_hosta(m)
    if wzorcowa and wzorcowa != m.nazwa_maszyny():
        print(f"maszyna wzorcowa (po nazwie hosta): {wzorcowa} — `maszyna.txt` "
              f"(„{m.nazwa_maszyny()}”) dotyczy NOWEJ maszyny, nie tego zrzutu")
        m.nazwa_maszyny = lambda _n=wzorcowa: _n

    powody = m.powody_niepewnosci()
    if powody:
        for p in powody:
            print(f"⚠ {p}")
        print("Obraz pulpitu jest niepewny — NIE zapisuję kanonu. Powtórz przy odblokowanym, "
              "działającym pulpicie (rozszerzenia muszą być wstałe).")
        return 1

    stan = m.eksport_pulpitu()
    if not stan:
        print("⚠ Eksport pulpitu jest pusty — nie nadpisuję kanonu.")
        return 1
    m.zapisz_pulpit(stan, m.PLIK_PULPITU)

    tekst = m.PLIK_PULPITU.read_text(encoding="utf-8")
    uwagi = []

    # 1. tapeta
    if TAPETA_STARA in tekst:
        tekst = tekst.replace(TAPETA_STARA, TAPETA_NOWA)
    elif TAPETA_NOWA not in tekst:
        uwagi.append("tapeta: nie rozpoznałem ani starej, ani nowej ścieżki — sprawdź "
                     "sekcję [org/gnome/desktop/background] ręcznie")

    # 2. skrót custom2 poza listą
    linie = []
    for linia in tekst.splitlines():
        if linia.startswith("custom-keybindings=") and CUSTOM2 in linia:
            czesci = [c for c in linia.split("'") if c.startswith("/org/")]
            zostaja = [c for c in czesci if c != CUSTOM2]
            linia = "custom-keybindings=[" + ", ".join(f"'{c}'" for c in zostaja) + "]"
        linie.append(linia)
    tekst = "\n".join(linie) + "\n"

    # 3. disabled-extensions
    linie = []
    zmieniono_wyl = False
    for linia in tekst.splitlines():
        if linia.startswith("disabled-extensions="):
            if linia != WYLACZONE:
                linia = WYLACZONE
                zmieniono_wyl = True
        linie.append(linia)
    tekst = "\n".join(linie) + "\n"
    if not any(l.startswith("disabled-extensions=") for l in linie):
        uwagi.append("w eksporcie nie ma klucza `disabled-extensions` — sprawdź, czy "
                     "pulpit/dconf-wyjatki.txt nadal go wymienia")

    # nagłówek gałęzi (dopisywany raz)
    if "GAŁĄŹ `ubuntu-2604`" not in tekst:
        znacznik = "# (robi kopię poprzedniego stanu przed nadpisaniem — spec 8.11).\n"
        tekst = tekst.replace(znacznik, znacznik + NAGLOWEK_DODATEK, 1)

    m.PLIK_PULPITU.write_text(tekst, encoding="utf-8")

    print(f"Kanon pulpitu odświeżony z maszyny „{m.nazwa_maszyny()}”: "
          f"{len(stan)} kluczy → {m.PLIK_PULPITU}")
    print(f"   poprawki gałęzi: tapeta ✓, skrót custom2 wycięty ✓, "
          f"disabled-extensions {'poprawione ✓' if zmieniono_wyl else 'już zgodne ✓'}")
    for u in uwagi:
        print(f"   ⚠ {u}")
    print()
    print("Co dalej (commit zostaje CZŁOWIEKOWI — najpierw zobacz, co się zmieniło):")
    print("   git -C ~/.local/share/chezmoi diff -- lustra/pulpit/pulpit.ini")
    print("   git -C ~/.local/share/chezmoi add lustra/pulpit/pulpit.ini && \\")
    print("     git -C ~/.local/share/chezmoi commit -m 'lustra: pulpit — odświeżony kanon gałęzi ubuntu-2604'")
    print("   git -C ~/.local/share/chezmoi push origin ubuntu-2604")
    return 0


if __name__ == "__main__":
    sys.exit(main())
