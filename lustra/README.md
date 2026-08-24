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
| `dziennik [--maszyna X] [--od DATA]` | historia po ludzku |
| `lista [--do PLIK]` | generuje `programy.md` **i** `.chezmoidata/packages.yaml` |
| `nowa-maszyna` | bootstrap — dopiero E3 |

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
| `zasiew-e1.py` | **jednorazowy** skrypt, który zasiał dziennik z historii systemu (E1) |
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
