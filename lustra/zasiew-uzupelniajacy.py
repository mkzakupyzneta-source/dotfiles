#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zasiew-uzupelniajacy — dopisuje do dziennika TEJ maszyny zdarzenia `dodano` dla
wszystkiego, co na niej FAKTYCZNIE jest, a czego dziennik jeszcze nie widział.

Różnica względem `zasiew-e1.py` (jednorazowy, z 22.08 — patrz jego nagłówek):
  • **APPEND-ONLY.** Nigdy nie kasuje ani nie nadpisuje istniejących linii —
    dopisuje przez `lustro.dopisz_zdarzenie` (ta sama funkcja, której używa cała
    reszta apki). Bezpiecznie odpalić na dzienniku, który już ma zawartość.
  • **IDEMPOTENTNY.** Uruchomiony drugi raz na niezmienionym systemie NIC nie
    dopisuje (porównuje z ostatnim zdarzeniem tej maszyny dla każdej pozycji —
    `lustro.stan_wg_tej_maszyny`).
  • **Kanały identyczne jak `lustro status`/`sync`** — `lustro.inwentaryzacja()`
    (apt oznaczone jako ręczne, snap, flatpak, po odsianiu `wykluczenia/*.txt`)
    plus rozszerzenia GNOME Shell użytkownika, jeśli powłoka działa. Dzięki temu
    to narzędzie i `status`/`sync` zawsze widzą to samo — nie ma dwóch definicji
    „co się liczy".
  • **Nic nie instaluje i nic nie usuwa** — tylko czyta system i dopisuje do
    dziennika. `--tylko-pokaz` nawet tego nie robi, tylko wypisuje, co by dopisał.

## Po co powstał (2026-08-26)

Katana miała w dzienniku 32 zdarzenia, ale dziesiątki fizycznie zainstalowanych
programów (btop, build-essential, bitwarden, BambuStudio…) z okresu stawiania
maszyny 25.08 nigdy do dziennika nie trafiły — maszyna była postawiona „drogą
obejściową" (bez startera), a etap E1 (`zasiew-e1.py`) na niej nigdy nie
zadziałał. Panel menadżera konfiguracji liczy rozbieżności Z DZIENNIKÓW, więc
pokazywał dziesiątki fałszywych braków, mimo że `lustro status` (który liczy
z żywej inwentaryzacji) na Katanie pokazywał 0 rozbieżności. Decyzja usera
26.08: **każda maszyna musi mieć dziennik** zgodny z tym, co na niej naprawdę
jest — stąd to narzędzie jako trwały, powtarzalny sposób łatania takiej dziury
(zamiast jednorazowego skryptu dla jednej maszyny).

## Kiedy uruchamiać

  • ręcznie, na dowolnej maszynie z podejrzeniem dziury w dzienniku;
  • na końcu bootstrapu nowej maszyny — patrz krok w
    `run_onchange_install-packages.sh.tmpl` (gałąź „nowa maszyna") i
    `procedura-nowej-stacji.md`, Etap 2 — żeby żadna przyszła maszyna nie
    zaczynała pracy z pustym albo niepełnym dziennikiem.

## Użycie

    python3 zasiew-uzupelniajacy.py                    # dopisuje brakujące, nota domyślna
    python3 zasiew-uzupelniajacy.py --tylko-pokaz       # tylko pokazuje, nic nie zapisuje
    python3 zasiew-uzupelniajacy.py --notatka "tekst"   # własna notatka zamiast domyślnej
"""

import argparse
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lustro  # noqa: E402

# Debian/Ubuntu/Mint zapisują przy stawianiu systemu, co dokładnie zainstalował
# instalator (`/var/log/installer/initial-status.gz`, format `dpkg --get-selections`
# rozszerzony o pola Package/Status/…). Odkryte 26.08 na serwerze (OptiPlex, Linux
# Mint): tam `apt-mark showmanual` zwraca ~2000 pozycji, bo instalator Mint
# oznacza PRAWIE CAŁY zestaw pulpitu jako "ręczny" — inaczej niż na Vostro/Katanie
# (Ubuntu, stawiane przez lustro), gdzie manualne są tylko świadome instalacje.
# Bez tego pliku zasiew zalałby dziennik serwera prawie dwoma tysiącami pozycji
# systemowych, które nie są niczyim świadomym wyborem (definicja "warsztatu",
# spec rozdz. 2) — zweryfikowane: 1886 z 1984 pozycji `apt-mark showmanual` na
# serwerze pokrywa się dokładnie z tym plikiem, zostaje 99 realnych instalacji.
# Gdzie pliku nie ma (Vostro, Katana — sprawdzone 26.08, oba bez tego logu)
# zachowanie jest DOKŁADNIE jak dotychczas (zbiór pusty, nic nie odsiane) — to
# jest uzupełnienie na brakujący sygnał, nie zmiana reguły dla maszyn, które go
# nie mają.
PLIK_INSTALATORA = Path("/var/log/installer/initial-status.gz")


def pakiety_bazowe_instalatora():
    """Zbiór nazw pakietów apt, które przyjechały z obrazem systemu (nie są
    świadomą instalacją) — z initial-status.gz, jeśli plik istnieje na tej
    maszynie. Pusty zbiór = brak filtra (dotychczasowe zachowanie)."""
    if not PLIK_INSTALATORA.exists():
        return set()
    try:
        with gzip.open(PLIK_INSTALATORA, "rt", encoding="utf-8", errors="replace") as f:
            return {linia.split(":", 1)[1].strip()
                    for linia in f if linia.startswith("Package:")}
    except OSError as e:
        print(f"  (nie udało się odczytać {PLIK_INSTALATORA}: {e} — filtr pomijam)",
              file=sys.stderr)
        return set()


NOTATKA_DOMYSLNA = (
    "zasiew uzupełniający — pozycja fizycznie obecna na maszynie, brak jej "
    "dotąd w dzienniku (data instalacji nieznana, zapisana data uruchomienia "
    "zasiewu)"
)


def brakujace_wpisy(maszyna):
    """Zwraca listę ((kanal, id), wersja) do dopisania — w inwentarzu, ale
    ostatnie zdarzenie tej maszyny dla tej pozycji to NIE 'dodano' (albo go
    nie ma wcale)."""
    inw = lustro.inwentaryzacja()

    # Rozszerzenia GNOME Shell użytkownika — ta sama reguła co w zbierz_pozycje():
    # tylko gdy powłoka faktycznie działa / katalogi rozszerzeń istnieją, inaczej
    # `gnome-extensions list` bywa niewiarygodne (spec, "wieczny fałszywy alarm").
    try:
        if any(k.is_dir() for k in lustro.KATALOGI_ROZSZERZEN) or lustro.czy_jest("gnome-shell"):
            for uuid, wersja in lustro.rozszerzenia_na_dysku(tylko_uzytkownika=True).items():
                inw[("gnome-extension", uuid)] = wersja
    except Exception as e:  # maszyna bez pulpitu (np. serwer) — nie blokuje reszty
        print(f"  (rozszerzenia GNOME pominięte: {e})", file=sys.stderr)

    zdarzenia = lustro.wczytaj_dzienniki()
    moje = lustro.stan_wg_tej_maszyny(zdarzenia, maszyna)
    bazowe = pakiety_bazowe_instalatora()

    brakujace, pominieto_bazowe = [], 0
    for klucz, wersja in sorted(inw.items()):
        kanal, ident = klucz
        if kanal == "apt" and ident in bazowe:
            pominieto_bazowe += 1
            continue
        ostatnie = moje.get(klucz)
        if ostatnie is None or ostatnie.get("zdarzenie") != "dodano":
            brakujace.append((klucz, wersja))
    if pominieto_bazowe:
        print(f"  ({pominieto_bazowe} pakietów apt pominiętych — z obrazu systemu, "
              f"{PLIK_INSTALATORA})", file=sys.stderr)
    return brakujace


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tylko-pokaz", action="store_true",
                     help="nic nie zapisuje, tylko pokazuje co by dopisał")
    ap.add_argument("--notatka", default=NOTATKA_DOMYSLNA,
                     help="notatka dopisywana do każdego zdarzenia zasiewu")
    ap.add_argument("--maszyna", default=None,
                     help="nadpisanie nazwy maszyny (domyślnie lustro.nazwa_maszyny())")
    args = ap.parse_args()

    maszyna = args.maszyna or lustro.nazwa_maszyny()
    brakujace = brakujace_wpisy(maszyna)

    if not brakujace:
        print(f"{maszyna}: dziennik już zgadza się z inwentaryzacją — nic do dopisania.")
        return

    by_kanal = {}
    for (kanal, ident), wersja in brakujace:
        by_kanal.setdefault(kanal, []).append((ident, wersja))

    tryb = "POKAŻĘ (nic nie zapisuję)" if args.tylko_pokaz else "DOPISUJĘ"
    print(f"{maszyna}: {tryb} {len(brakujace)} brakujących zdarzeń 'dodano':")
    for kanal, poz in sorted(by_kanal.items()):
        print(f"  {kanal}: {len(poz)}")
        for ident, wersja in poz:
            print(f"    {ident} {wersja}")

    if args.tylko_pokaz:
        return

    for (kanal, ident), wersja in brakujace:
        lustro.dopisz_zdarzenie("dodano", kanal=kanal, ident=ident, wersja=wersja,
                                 zrodlo="zasiew", notatka=args.notatka, maszyna=maszyna)

    print(f"\n{maszyna}: dopisano {len(brakujace)} zdarzeń do "
          f"{lustro.DZIENNIKI / (maszyna + '.jsonl')}")


if __name__ == "__main__":
    main()
