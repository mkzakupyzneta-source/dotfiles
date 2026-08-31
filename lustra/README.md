# lustra/ — dane i apka mechanizmu luster

Ten katalog **zostaje w repozytorium chezmoi** i NIE jest rozwijany do katalogu domowego
(pilnuje tego wpis `lustra` w `.chezmoiignore` w korzeniu repozytorium — patrz „Pułapka" niżej).

Specyfikacja całości: `10_Siec_domowa/5_Wspolna_konfiguracja/mechanizm-luster-spec.md`.

## Etap E2 — apka umie już ZMIENIAĆ system (stan 2026-08-23)

Zasada nadrzędna: **najpierw robimy, potem zapisujemy.** Zdarzenie trafia do dziennika
dopiero po ponownej inwentaryzacji potwierdzającej, że operacja naprawdę się udała.
Nic nie dzieje się bez pytania — jedyny wyjątek to jawny przełącznik
`--zatwierdzam-wszystko`, który **domyślnie jest wyłączony**.

| Polecenie | Co robi |
|---|---|
| `status` | tylko czyta: inwentaryzacja, rozbieżności, pulpit, instalacje obce |
| `sync` | to samo, ale przy każdej pozycji pyta i wykonuje to, co zatwierdzone |
| `dodaj <program>` | instaluje (kanał wykryty albo zapytany), zapisuje zdarzenie, pyta o ustawienia |
| `usun <program>` | odinstalowuje, zapisuje zdarzenie, pyta, czy usunąć też ustawienia |
| `ustawienia <program>` | oddaje pliki ustawień programu do lustra (`chezmoi add` + zdarzenie) |
| `pulpit status\|zasiew\|oddaj\|wgraj\|sprawdz` | warstwa GNOME (dconf) |
| `pulpit rozszerzenia` | rozszerzenia GNOME Shell — sprawdza, czy to, co ma być zainstalowane, jest na dysku; dla źródła `ego` (extensions.gnome.org) umie po pytaniu doinstalować |
| `pulpit oddaj-stan` | (kontrakt [209], 26.08) migawka WŁASNEGO stanu gałęzi do `pulpit/stan/<maszyna>.ini` — czysta obserwacja, nie pyta o zgodę |
| `pulpit skladaj` | (kontrakt [209], 26.08) składa `pulpit.ini` z `pulpit/zrodla-galezi.toml` + migawek maszyn — źródło KAŻDEJ gałęzi dowolne, nie jedna wspólna maszyna |
| `dziennik [--maszyna X] [--od DATA]` | historia po ludzku |
| `lista [--do PLIK]` | generuje `programy.md` **i** `.chezmoidata/packages.yaml` |
| `nowa-maszyna` | zaślepka (E3) — bootstrap robi **`nowa-stacja.sh`** (niżej), nie apka |

Przełączniki `sync`: `--tylko-pokaz` (jak `status`, do powiadomienia na pulpicie),
`--tylko-instaluj` (nigdy nic nie usuwa — najbezpieczniejszy tryb automatyczny),
`--zatwierdzam-wszystko` (bez pytań — świadomie NIE domyślne).

Pytania w `sync`: `[T]ak / [n]ie / [p]omiń na zawsze / [s]zczegóły /
[h]urtem` (= „T dla wszystkich pozostałych"). Na koniec jeszcze jedno podsumowanie
„do wykonania — wykonać?". `[p]omiń na zawsze` **nie jest zdarzeniem instalacji** —
ląduje w lokalnym pliku `pomijane-<maszyna>.txt`, żeby jedna maszyna mogła świadomie
odstawać bez zaśmiecania historii.

## Uprawnienia roota

Domyślnie `sudo` — bo docelowo apkę uruchamia user w terminalu.
Gdy terminala nie ma (sesja automatyczna, agent), przełącznik `--root pkexec`
każe prosić o hasło **okienkiem systemowym**:

```bash
lustro --root pkexec usun jakis-program
LUSTRO_ROOT=pkexec lustro dodaj vlc     # to samo przez zmienną środowiskową
```

## Jak uruchomić

```bash
python3 ~/.local/share/chezmoi/lustra/lustro.py status
python3 ~/.local/share/chezmoi/lustra/lustro.py sync --tylko-pokaz
python3 ~/.local/share/chezmoi/lustra/lustro.py dziennik --od 2026-08-20
python3 ~/.local/share/chezmoi/lustra/lustro.py lista --do /tmp/programy-nowe.md
```

**Wygodniej — alias `lustro`.** Propozycja do dopisania w `dot_bashrc` w repozytorium
chezmoi (⚠️ NIE zastosowane — wymaga `chezmoi apply`, czyli zgody usera):

```bash
# mechanizm luster (5_Wspolna_konfiguracja)
alias lustro='python3 "$HOME/.local/share/chezmoi/lustra/lustro.py"'
```

## Co tu leży

| Plik / katalog | Do czego |
|---|---|
| `lustro.py` | apka: inwentaryzacja, porównanie, wyrównywanie, warstwa pulpitu |
| `nowa-stacja.sh` | **automat nowej stacji (27.08)**: jedna linia na świeżym Ubuntu 24.04 → stacja-lustro (K0–K16: apt-minimum, repo z serwera, sudoers [194], 3 klucze SSH, maszyny.toml, chezmoi apply, zasiew, `sync --auto`, Node/Claude/bw, hook dpkg, timer, pulpit, ufw, Tailscale, Syncthing, VPN, raport). Linia: `curl -fsSL http://192.168.1.49:8100/nowa-stacja.sh -o /tmp/nowa-stacja.sh && bash /tmp/nowa-stacja.sh` |
| `przyjmij-maszyne.sh` | **na serwerze**, po `nowa-stacja.sh`: klucz domowy nowej maszyny → `klucze-publiczne/<nazwa>-dom.pub`, `authorized_keys` serwera/Asusa wprost (stacje przez chezmoi), known_hosts, git (pull z nowej maszyny, push GitHub, `updateInstead`), Syncthing (urządzenie + foldery na serwerze i stacjach) |
| `gsconnect-paruj.sh` | **telefon ↔ komputer ([299], 31.08)**: doprowadza GSConnecta na TEJ maszynie do parowania z telefonem i zostawia userowi jedno dotknięcie ekranu telefonu (30-sekundowe okno protokołu KDE Connect). Ustawienia wtyczek jeżdżą lustrem (gałąź `…/gsconnect/device/<id telefonu>/plugin/` w `pulpit/pulpit.ini`); parowania i tożsamości maszyny (`~/.config/gsconnect/`, `certificate-pem`, `paired`) lustrem przenieść NIE WOLNO. Nowa stacja: uruchomić raz, po `chezmoi apply` i `pulpit wgraj`. |
| `stacja-dane.py` | pomocnik obu skryptów: `hosty`, `cele` (z maszyny.toml), `maszyna-wpisz` (edycja bloku `[[maszyna]]` z kontrolą tomllib), `syncthing-konfiguruj` / `syncthing-przyjmij` (REST) / `syncthing-urzadzenie-wpisz` |
| `syncthing.toml` | DANE Syncthinga: urządzenia (ID, adresy) i wspólne foldery (id, ścieżka, wersjonowanie, .stignore) — czytane przez oba skrypty |
| `zasiew-e1.py` | **jednorazowy** skrypt, który zasiał dziennik z historii systemu (E1) |
| `zasiew-uzupelniajacy.py` | **wielokrotnego użytku**, append-only, idempotentny — dopisuje `dodano` dla tego, co fizycznie jest, a czego w dzienniku tej maszyny brak (naprawa dziury z 26.08, patrz `mechanizm-luster-spec.md` rozdz. 17). Odsiewa pakiety z obrazu instalatora, jeśli maszyna ma `/var/log/installer/initial-status.gz` (np. Linux Mint na serwerze). Wołany automatycznie na końcu `run_onchange_install-packages.sh.tmpl` przy nowej maszynie. |
| `dziennik/<maszyna>.jsonl` | historia zdarzeń jednej maszyny; **tylko ta maszyna tu dopisuje** |
| `pomijane-<maszyna>.txt` | pozycje, w których ta maszyna świadomie odstaje (lokalne) |
| `wykluczenia/apt.txt`, `snap.txt`, `flatpak.txt` | czego nie liczyć jako warsztat |
| `wykluczenia/obce.txt` | znane instalacje spoza apt/snap/flatpak |
| `wykluczenia/ustawienia.txt` | pliki stanu i cache — nie wozimy |
| `wykluczenia/tozsamosc.txt` | ⛔ tożsamość maszyny — **nigdy** nie lustrzyć (spec 7.6) |
| `pulpit/dconf-lustro.txt` | które ścieżki GNOME są w lustrze |
| `pulpit/dconf-poza-lustrem.txt` | które celowo nie są, z uzasadnieniem |
| `pulpit/dconf-pomijane-klucze.txt` | pojedyncze klucze do pominięcia |
| `pulpit/dconf-wyjatki.txt` | klucze wożone mimo pominiętej ścieżki |
| `pulpit/dconf-rozszerzenia.txt` | **generowany** — klucze przejęte przez rozszerzenia GNOME |
| `pulpit/rozszerzenia-gnome.txt` | które rozszerzenia GNOME Shell mają być **zainstalowane** (nie: włączone) na każdej maszynie, i skąd (`ego` = extensions.gnome.org, `lokalne` = zgłoszenie bez instalacji) |
| `pulpit/pulpit.ini` | eksport ustawień pulpitu — **plik generowany**, `{{HOME}}` zamiast `/home/mk` |
| `ustawienia-map.txt` | program → jego pliki ustawień |
| `skrypty.toml` | pozycje kanału **`skrypt`** — programy stawiane skryptem, nie menedżerem pakietów (AI Launcher): `sprawdz`/`zainstaluj`/`wymaga` jako **dane** ([252], 29.08 — sekcja niżej) |
| `zrodla-apt.toml` | zewnętrzne repozytoria apt (Fortinet, Tailscale…): skąd klucz, jaka linia `deb`, które pakiety — **dane**, apka je czyta w `status` i `dodaj` (od 25.08, [176]) |

Poza tym katalogiem, ale należy do mechanizmu:
`../.chezmoidata/packages.yaml` (generowana lista programów) i
`../run_onchange_install-packages.sh.tmpl` (instaluje ją **tylko na nowej maszynie**).

**Wykluczenia są DANYMI, nie kodem.** Żeby coś przestało się pokazywać, dopisuje się wzorzec
do pliku tekstowego — bez ruszania `lustro.py`.

## Rozszerzenia GNOME Shell — instalacja z extensions.gnome.org (24.08)

Lustro wozi listę **włączonych** rozszerzeń (`enabled-extensions`, w `pulpit.ini`), ale to nie
wystarcza na nowej maszynie: rozszerzenie może być „włączone" w ustawieniach, a fizycznie nie
zainstalowane na dysku — GNOME Shell po cichu je pomija, bez błędu. `pulpit/rozszerzenia-gnome.txt`
odpowiada za tę drugą warstwę: co ma być **zainstalowane**.

- `lustro status` / `lustro sync` / `lustro pulpit sprawdz` **wykrywają** brak jako uwagę
  (kontrola poprawności pulpitu) — nic nie instalują sami.
- `lustro pulpit rozszerzenia` **instaluje** to, co da się (źródło `ego` = extensions.gnome.org),
  po pytaniu (albo bez pytania z `--zatwierdzam-wszystko`): pobiera paczkę przez API
  `extension-info/?uuid=<uuid>&shell_version=<wersja>` (pole `download_url`) i woła
  `gnome-extensions install --force <zip>`. Idempotentne — już zainstalowane pomija.
- Rozszerzenia źródła `lokalne` (spoza extensions.gnome.org) apka tylko zgłasza — instalacja
  ręczna.
- **Włączanie zostaje przy `pulpit wgraj`/dconf** — ta komenda go nie dotyka, żeby nie było
  dwóch miejsc decydujących, co ma być włączone.

Zweryfikowane na żywo 24.08.2026 (Vitals@CoreCoding.com, GNOME Shell 46.0): API odpowiada
HTTP 200 z `download_url`, plik pod tym adresem jest prawidłowym zip-em rozszerzenia,
`gnome-extensions install --help` potwierdza składnię. **Sama instalacja `gnome-extensions
install` nie została odpalona na żywo** — na Vostro nie było czego instalować (Vitals już jest);
do sprawdzenia przy najbliższej okazji, gdy na jakiejś maszynie faktycznie czegoś brakuje
(kandydat: poligon, E3). Pełny opis → spec, rozdz. 8.12.

## Zewnętrzne repozytoria apt — `zrodla-apt.toml` (25.08, sprawa [176])

Część programów nie leży w Ubuntu, tylko u producenta (FortiClient → `repo.fortinet.com`,
Tailscale → `pkgs.tailscale.com`). Na nowej maszynie `apt install <program>` nic wtedy nie
znajdzie. `zrodla-apt.toml` opisuje takie źródła jako **dane** (blok `[[zrodlo]]`: adres,
skąd klucz i w jakim formacie, dokąd keyring, jaka linia `deb`, które pakiety z niego
pochodzą; opis pól w nagłówku pliku). Zastępnik `{codename}` = nazwa wydania z `/etc/os-release`.

- `lustro status` — sekcja „ZEWNĘTRZNE ŹRÓDŁA APT, KTÓRYCH TU NIE MA": źródło uznane za
  obecne, gdy jego `url` stoi w którymś pliku `.list`/`.sources` w `/etc/apt/sources.list.d/`
  **i** plik `keyring` istnieje. Nic nie zmienia.
- `lustro dodaj <pakiet>` — jeśli pakiet stoi w polu `pakiety` jakiegoś źródła, a źródła nie ma:
  mówi to jasno, pyta `[T/n]` i dodaje **jednym skryptem `sh` pod jednym sudo/pkexec**
  (klucz pobrany i `gpg --dearmor` bez roota; pod rootem tylko `install` keyringu, zapis
  listy, `apt-get update`). Dopiero potem szuka pakietu w apt i instaluje jak dotąd.
  Idempotentne. Przy odmowie — nie instaluje pakietu (bez źródła i tak by się nie udało).
- Nie ma jeszcze: osobnej komendy „dodaj samo źródło", uwzględnienia źródeł w
  `run_onchange_install-packages.sh.tmpl` (bootstrap nowej maszyny — E3), wpisów dla
  Chrome / VS Code / OneDrive (zainstalowane ręcznie przed powstaniem pliku).

Zweryfikowane na żywo 25.08 na Vostro: źródło Fortinet dodane przez `dodaj` (pkexec),
`apt-cache policy forticlient` → kandydat `7.4.8.1904` z `repo.fortinet.com … ubuntu22 stable/non-free`,
instalacja i wpis w dzienniku tą samą komendą. Tailscale (dodany wcześniej skryptem obszaru 6)
rozpoznany jako obecny bez żadnej zmiany.

## Kanał `skrypt` — programy stawiane skryptem, nie menedżerem pakietów (29.08, [252])

Nie wszystko da się postawić z apt/snap/flatpak: AI Launcher ma własny `install.sh` (kopiuje
pliki do `~/.local/share`). Do 29.08 lustro takich rzeczy nie umiało — widziało je najwyżej
w migawce jako `poza`, więc na nowym HP launcher nie stanął. Decyzja usera [252]: „nawet jak
ręcznie, to miało do lustra trafiać". Rozwiązane o poziom ogólniej — STRUKTURA na dane, nie
wyjątek na launcher:

- **`skrypty.toml`** — dane: jeden blok `[[skrypt]]` na program. `sprawdz` (polecenie; kod 0 =
  pozycja jest — ma sprawdzać wszystko, co instalacja zostawia, także ikonę), `zainstaluj`
  (polecenie), opcjonalnie `wersja`, `usun`, `wymaga` (warunki: `katalog-roboczy` albo ścieżka,
  która musi istnieć — bo źródło leży w `~/AI-katalog-roboczy` i na nowej stacji musi najpierw
  dojechać Syncthingiem). Ścieżki z `~`. Nowy program = nowy blok, kodu nikt nie rusza.
- **Dalej wszystko jak dla apt:** `status`/`sync` pokazują rozbieżność, `sync --auto` (timer
  co 60 min, K8 nowej stacji) dociąga brak — nieinteraktywnie (stdin z /dev/null, limit 15 min),
  pełne wyjście w `~/.local/share/lustro/skrypty/<id>.log`; niespełnione `wymaga` = pozycja
  **ODŁOŻONA** z powodem (nie błąd), następny bieg spróbuje znowu. Dziennik i migawka
  inwentarza dostają kanał `skrypt` (nie `poza`). `sync --auto` księguje też „jest tutaj, w
  dzienniku brak" (wykryte) — jak dla snapa.
- **`lustro dodaj <id>`** — kanał wykrywany z `skrypty.toml` (albo `--kanal skrypt`); bez
  definicji apka odsyła do pliku, niczego nie zgaduje. `lustro usun` tylko, gdy blok ma `usun`.
- Tylko członkowie lustra (stacje), jak apt; wyjątki per maszyna → `statusy-pozycji.toml`
  (`kanal = "skrypt"`). Bootstrap nowej stacji NIE wpisuje ich do `packages.yaml` — dociąga
  je `sync --auto`, bo szablon chezmoi nie umie czekać na Syncthing.
- Pierwsza pozycja: **`ailauncher`** (`install.sh` z `12_Narzedzia-AI/AILauncher_V2/linux/`;
  od 29.08 razem z ikoną `ailauncher.png`). `python3-tk`, którego skrypt by dostawiał, jest
  osobną pozycją **apt** lustra — skrypt zastaje go na miejscu; gdyby go nie było, hook dpkg
  zaksięguje instalację jako apt (nie tłumimy go, bo to prawdziwa transakcja apt).
- Migawka `poza` widzi też od 29.08 pliki `~/.local/share/applications/*.desktop` usera
  (id = nazwa pliku) — to, co user postawi ręką z ikoną w menu, nie ginie w panelu;
  wyciszanie wzorcem w `wykluczenia/obce.txt`.

Zweryfikowane 29.08 na Katanie: na kopii repo (bez śladu w prawdziwym dzienniku) `sync --auto`
zainstalował pozycję testową, zapisał zdarzenie `kanal: skrypt`, dał migawkę z kanałem `skrypt`
i ODŁOŻYŁ pozycję z niespełnionym `wymaga`. Realne dociągnięcie na Vostro/HP przez timer —
do obejrzenia w dziennikach po ich najbliższym biegu.

## ⚠️ Pułapka sprawdzona 2026-08-23: chezmoi rozwijał `lustra/`

Specyfikacja zakładała (hipoteza 1, rozdz. 14), że chezmoi zostawi katalog `lustra/`
w repozytorium, bo nie ma przedrostka `dot_`. **To nieprawda.** Bez `.chezmoiignore`
`chezmoi managed` pokazuje `lustra`, `lustra/dziennik`, … — czyli `chezmoi apply`
utworzyłby katalog `~/lustra`. Dlatego w korzeniu repozytorium leży `.chezmoiignore`
z jedną linią `lustra`. **Nie kasować jej.**

## ⚠️ Pułapka sprawdzona 2026-08-23: fałszywy alarm pulpitu od rozszerzeń GNOME

`lustro status` o 16:40 pokazał trzy klucze mutter (`edge-tiling`,
`toggle-tiled-left`, `toggle-tiled-right`) jako rozbieżne — „tutaj: brak,
w lustrze: false", cztery minuty po eksporcie z tej samej maszyny.

**Przyczyna:** te klucze nie należą do usera, tylko do rozszerzenia
**Ubuntu Tiling Assistant**. Rozszerzenie przy włączeniu zapisuje w nich swoje
wartości, a przy wyłączeniu je **kasuje** (`Gio.Settings.reset`). Wyłączenie dzieje
się samo — na ekranie blokady, przy restarcie powłoki, chwilę po zalogowaniu.
W tym oknie czasowym `dconf dump` ich nie widzi, a lustro widzi „rozbieżność".
Potwierdzone o 17:45: `gnome-extensions info tiling-assistant@ubuntu.com` →
`Enabled: Yes`, `State: INACTIVE`, a klucze zniknęły.

**Naprawione dwoma ogólnymi regułami** (nie wpisem pod te trzy klucze):

1. **Klucze przejęte przez rozszerzenia są poza lustrem.** Rozszerzenia prowadzą
   listę przejętych kluczy we własnym kluczu `overridden-settings` (wzorzec
   `SettingsOverrider`). Apka czyta go u **wszystkich** rozszerzeń i zapisuje wynik
   w `pulpit/dconf-rozszerzenia.txt` — bo sam znacznik znika razem z rozszerzeniem.
   Na nowej maszynie te klucze ustawi sobie samo rozszerzenie; lustro wozi listę
   włączonych rozszerzeń, a nie skutki ich działania.
2. **Dopóki jakiekolwiek włączone rozszerzenie nie wstało** (`State: INACTIVE`),
   warstwy pulpitu w ogóle **nie porównujemy** — apka mówi, dlaczego, i każe powtórzyć
   przy działającym pulpicie. Ta reguła łapie też rozszerzenia, które znacznika nie
   prowadzą. Tą samą drogą blokowany jest nieudany odczyt `dconf`.

## Nazwa maszyny

Domyślnie nazwa hosta (`hostname`), tutaj `vostro`. Można ją nadpisać plikiem
`lustra/maszyna.txt` — ale wtedy plik dotyczyłby wszystkich maszyn (repozytorium jest
wspólne), więc **na razie nie używać**.

## Ustawienia zasilania stacji — `zasilanie-stacja.sh` ([267c] 29.08, [279] 30.08)

Jeden skrypt, trzy ustawienia, każde sterowane **osobnym polem** w `maszyny.toml` — w skrypcie
nie ma ani jednej nazwy maszyny:

| pole w `maszyny.toml` | co ustawia | gdzie ląduje |
|---|---|---|
| `wolno_wylaczac` | zgoda na `sudo systemctl poweroff` bez hasła (przycisk „wyłącz" w panelu) | `/etc/sudoers.d/91-lustro-zasilanie` |
| `klapa_zamkniecie` | czy zamknięcie klapy usypia (`usyp` / `ekran-gasnie` / `ignoruj`) | `/etc/systemd/logind.conf.d/50-lustro-klapa.conf` |
| `klapa_otwarcie_budzi` | czy otwarcie klapy budzi uśpioną maszynę | `/proc/acpi/wakeup` + `lustro-klapa-wakeup.service` |

```
sh lustra/zasilanie-stacja.sh                    # podgląd, bez roota, nic nie zmienia
sudo sh lustra/zasilanie-stacja.sh --wykonaj     # wykonanie
sudo sh lustra/zasilanie-stacja.sh --wykonaj --przeladuj-logind   # + bez restartu maszyny
```

Ostatnia linia podglądu to `# jest-co-robic` albo `# nic-do-zrobienia` — po tym poznaje
krok **K3b** automatu `nowa-stacja.sh`, czy w ogóle wołać skrypt (żeby maszyna bez żadnego
z tych ustawień nie dostała niepotrzebnego pytania o hasło sudo).

**Strażnik klapy** (`~/bin/klapa-straznik.sh` + `klapa-straznik.service`, oba wozi chezmoi)
dokłada zachowanie `ekran-gasnie`: przy zamknięciu klapy gasi ekran od ręki, a usypia dopiero
po `klapa_usyp_po_min` minutach; otwarcie klapy albo podłączenie monitora zewnętrznego odwołuje
odliczanie. Włącza go i wyłącza `run_onchange_after_wlacz-klapa-straznik.sh.tmpl` — też z danych.
Dziennik: `journalctl --user -t klapa-straznik`. Testowanie na sucho (atrapy zamiast `xset`
i `systemctl suspend`) — opis w nagłówku samego skryptu.

## Profile maszyn — `profile.toml`: co w ogóle DOTYCZY tej maszyny ([284], 30.08)

Nie każda maszyna ma być pełnym lustrem. Katana od 30.08 jest **„mocą obliczeniową na
żądanie"**: user włącza ją na czas cięższego zadania, pracuje na niej przez sieć
(SSH, tmux, podgląd pulpitu przez VNC) i wyłącza po zadaniu. Nie ma tam OneDrive'a,
przeglądarki z zalogowanymi kontami, pakietu biurowego ani komunikatorów.

Rola maszyny to **jedna dana** — pole `profil` w `maszyny.toml` — o dwóch skutkach,
opisanych w dwóch plikach, bo czytają je dwa różne programy:

| Plik | Kto czyta | Co mówi |
|---|---|---|
| `.chezmoidata/maszyny.yaml` | chezmoi (`.chezmoiignore.tmpl`) | **które pliki konfiguracyjne** maszyna dostaje |
| `lustra/profile.toml` | `lustro.py` | **które programy** jej dotyczą (lista `zostaja`) |

Profil w `maszyny.yaml` opisuje się listą `tylko` (dozwolone ścieżki) **albo** `oprocz`
(wykluczone) — tym, która jest krótsza. Profil w `profile.toml` mówi, co **zostaje**,
a nie co wypada: dzięki temu nowy program dołożony gdziekolwiek we flocie domyślnie
**nie** trafia na maszynę o zawężonym profilu i nikt nie musi o tym pamiętać.

Komendy:

```
lustro profil status     # jaki profil, ile wzorców, co stoi tu mimo że nie należy
lustro profil sprzataj   # usuwa te pozycje — z pytaniem przy KAŻDEJ
```

Trzy rzeczy, o które łatwo się potknąć:

- **`[[pozycja.override]]` wygrywa z profilem** (kontrakt [209], reguła 2). Jednorazowy
  wyjątek „ta jedna rzecz jednak ma tu być" to nadal jeden wpis w `statusy-pozycji.toml`.
- **Profil sam z siebie niczego nie usuwa.** Pozycja spoza profilu jest po prostu
  niesprawdzana; `sync --auto` (timer, co 60 min) nigdy jej nie odinstaluje. Usuwa
  wyłącznie świadome `lustro profil sprzataj`, uruchomione ręcznie przez człowieka.
- **Usunięcie zapisuje zdarzenie `usunieto-profil`, nie `usunieto`.** To rdzeń
  bezpieczeństwa: `stan_oczekiwany()` liczy konsensus tylko ze zdarzeń `dodano`/`usunieto`,
  więc sprzątanie Katany **nie** wygląda dla Vostro i HP jak rozkaz „usuńcie u siebie
  LibreOffice'a". Sprzątanie obejmuje kanały `apt`/`snap`/`flatpak`; rozszerzenia GNOME
  i pozycje kanału `skrypt` zostają (to pliki w katalogu użytkownika, nie programy).

## OneDrive wg danych — `run_onchange_after_onedrive-wg-danych.sh.tmpl` ([279a], 30.08)

Pakiet apt `onedrive` w `postinst` zakłada
`/etc/systemd/user/default.target.wants/onedrive.service`, czyli **włącza usługę
wszystkim użytkownikom** maszyny. Na maszynie bez zalogowanego konta klient przy każdym
starcie sesji otwiera przeglądarkę na stronie logowania Microsoftu (na Katanie wywracało
to przy okazji Chrome). Zachowanie ma wynikać z **danych maszyny**, nie z tego, co pakiet
zrobił sam sobie przy instalacji — stąd pole `onedrive` w `maszyny.toml`:

- `"brak"` → skrypt maskuje usługę (`systemctl --user mask`, **bez roota** — to symlink
  `~/.config/systemd/user/onedrive.service` → `/dev/null`),
- inna wartość (np. `"konto-osobiste"`) → maska zdejmowana, jeśli wcześniej stała,
- brak pola → nic nie ruszamy (nie wiemy, więc nie zgadujemy).

Nowy sposób używania OneDrive'a = nowa **wartość** pola, bez zmian w skrypcie.
