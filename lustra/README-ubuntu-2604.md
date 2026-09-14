# Gałąź `ubuntu-2604` — kanon pod czyste Ubuntu 26.04 na Vostro

Sprawa **[423]**, 2026-09-14, obszar `5_Wspolna_konfiguracja`, zbudowane na maszynie HP.
Werdykty usera: tabela `5_Wspolna_konfiguracja/ubuntu-2604/tabela-weryfikacyjna-2026-09-14.html`
(sprawy [419]/[420]).

> ## ⛔ TEJ GAŁĘZI NIE WOLNO SCALIĆ DO `main`
> To **kopia** kanonu, a nie jego nowa wersja. Istniejące maszyny (HP, Vostro-24.04, Katana,
> serwer) jadą dalej po `main` i nic się u nich nie zmienia. Gałąź zawiera rzeczy prawdziwe
> tylko dla JEDNEJ maszyny — przede wszystkim plik `lustra/maszyna.txt`, który **każdej**
> maszynie każe nazywać się `vostro-temp`. Scalenie do `main` wywróciłoby dzienniki całej floty.
> Kiedy nowy system się sprawdzi, decyzję „co z tego przenieść na `main`" podejmuje user,
> pozycja po pozycji, a nie `git merge`.

---

## 1. Co jest na tej gałęzi inaczej niż na `main` — skrót

| Obszar | Zmiana |
|---|---|
| **Lista programów** (`.chezmoidata/packages.yaml`) | **85 pozycji** zamiast 122: apt 73 (było 109), snap 2 (było 3), flatpak 10 (bez zmian). Wycięte 36 pakietów apt + snap `teams-for-linux` + rozszerzenie `gTile` |
| **Jak wycięte** | mechanizmem, nie ręką: nowy dziennik `lustra/dziennik/vostro-temp.jsonl` z 38 zdarzeniami `usunieto` (`zrodlo: reczne`, notatka „werdykt usera [420], tabela 2026-09-14"), potem przegenerowana lista (`lustro lista`). Dzienniki pozostałych maszyn **nietknięte** — historia jest append-only |
| **Nowa maszyna** | blok `[[maszyna]] klucz = "vostro-temp"` w `lustra/maszyny.toml` (wpis `vostro` nietknięty). OneDrive **zamaskowany** (`onedrive = "brak"`), bez zdalnego pulpitu, Syncthing i Tailscale dostają nową tożsamość przy bootstrapie |
| **Pulpit** | `lustra/pulpit/pulpit.ini` to ŚWIEŻY zrzut żywego HP z 14.09 wieczorem — **pełne lustro**: wygląd, skróty, ustawienia rozszerzeń (Dash to Panel, Tiling Shell, Vitals, Caffeine, Desktop Cube, DING), lista włączonych i wyłączonych rozszerzeń. Zastępuje stary wzorzec (Dash to Dock, Vostro sprzed miesiąca) |
| **Pulpit — automat** | nowy `run_onchange_after_pulpit-z-lustra.sh.tmpl`: po każdej zmianie kanonu pulpitu maszyna sama instaluje brakujące rozszerzenia i wgrywa dconf. Koniec zasady [195] („pulpit tylko ręcznie") — decyzja usera 14.09 |
| **Bootstrap** | `lustra/nowa-stacja.sh`: przyjmuje 26.04, **usunięty krok K12b** (wymuszanie X11 — nowy system jedzie na Wayland), K11 najpierw instaluje rozszerzenia a potem wgrywa dconf, `--galaz X` bierze gałąź ze zdalnego repozytorium |
| **Zdjęte z wożenia** | `.config/kitty/kitty.conf`, `.config/wezterm/wezterm.lua`, `.config/zrzuty/gnome-dconf.ini`, usługa+skrypt `wygaszanie-ekranow`, `bin/wlacz-autologowanie.sh`, `bin/zdalny-pulpit.sh` + `zdalny-pulpit.service` + jego `run_onchange`, `bin/dane-logowania` |
| **Dołożone do wożenia** | `~/.config/autostart/transkryptor-wskaznik.desktop` (treść z HP, ścieżka domowa liczona przez chezmoi) oraz **plik tapety** `~/.local/share/tapety/ubuntu-wallpaper-d.png` (bo `/usr/share/backgrounds/…` w nowym wydaniu Ubuntu wygląda inaczej) |
| **Źródła apt** | usunięte `wezterm` (apt.fury.io) i `fortinet` (martwe). Zostają: tailscale, google-chrome, vscode, onedrive |
| **Nowe dokumenty** | `lustra/lista-brakow-wayland.md` (co wypadło z rodziny X11 i czym to zastąpić) oraz ten plik |

Pełna lista braków i zamienników: **`lustra/lista-brakow-wayland.md`**.

---

## 2. JUTRO, KROK PO KROKU — świeży Ubuntu 26.04 na Vostro

### Krok 0 (w instalatorze Ubuntu) — nazwa komputera

W instalatorze, przy zakładaniu konta:

- **Nazwa użytkownika:** `mk`
- **Nazwa komputera:** `vostro-temp` ← **to jest ważne**

Dlaczego: mechanizm rozpoznaje maszynę **po nazwie hosta**. Gdyby nowy system też nazywał się
`vostro`, byłby dla mechanizmu tą samą maszyną co stare Ubuntu 24.04 i pisałby do jej dziennika.

Gdyby nazwa umknęła w instalatorze — do naprawienia po pierwszym uruchomieniu, w terminalu:

```bash
sudo hostnamectl set-hostname vostro-temp
```

(potem wylogowanie i zalogowanie albo restart)

### Krok 1 — sieć i terminal

Podłączyć Wi-Fi albo kabel. Otworzyć terminal: **Ctrl+Alt+T**.

### Krok 2 — pobranie kanonu Z TEJ GAŁĘZI

```bash
sudo apt update && sudo apt install -y git
mkdir -p ~/.local/share
git clone --branch ubuntu-2604 mk@192.168.1.49:.local/share/chezmoi ~/.local/share/chezmoi
```

- Pierwsze pytanie (`Are you sure you want to continue connecting?`) → wpisać `yes`.
- Drugie: **hasło konta `mk` na serwerze** (OptiPlex). To jedyne miejsce, gdzie tu potrzebne.

Sprawdzenie, że przyszła właściwa gałąź (ma pokazać `ubuntu-2604`):

```bash
git -C ~/.local/share/chezmoi branch --show-current
```

**Gdyby serwer nie odpowiadał** — to samo z HP (musi być włączony i w tej samej sieci;
adres `192.168.1.65`, hasło konta na HP):

```bash
git clone --branch ubuntu-2604 mk@192.168.1.65:.local/share/chezmoi ~/.local/share/chezmoi
```

> Świadomie **nie** używamy tu jednolinijkowca `wget … nowa-stacja.sh` z serwera: plik na
> serwerowym HTTP pochodzi z gałęzi `main` i przyniósłby stary kanon (z wymuszaniem X11).

### Krok 3 — automat

```bash
bash ~/.local/share/chezmoi/lustra/nowa-stacja.sh --nazwa vostro-temp --galaz ubuntu-2604
```

Automat zapyta o pięć rzeczy i **nic więcej**:

1. hasło sudo tej maszyny (raz, na początku),
2. **frazę do klucza osobistego** `id_ed25519` (ssh-keygen pyta dwa razy — to nowy klucz tej
   instalacji; frazę zapisać potem w sejfie jako `SSH — vostro-temp (id_ed25519)`),
3. hasło konta na serwerze (raz, krok K4b — `ssh-copy-id`),
4. logowanie do **Tailscale** w przeglądarce (skrypt wypisze adres i poczeka),
5. wklejenie klucza `id_ed25519_github.pub` na koncie GitHub (krok K16b, przy klawiaturze).

Trwa długo (`texlive-full` sam waży kilka GB). Pełny log: `~/nowa-stacja.log`.
Na końcu automat wypisze RAPORT: co się udało, co wymaga ręki, klucze publiczne i ID Syncthinga.

### Krok 4 — na SERWERZE: przyjęcie maszyny

Z dowolnej maszyny (albo z nowego Vostro):

```bash
ssh mk@192.168.1.49
~/.local/share/chezmoi/lustra/przyjmij-maszyne.sh vostro-temp <adres-LAN-z-raportu> --galaz ubuntu-2604
```

**Przełącznika `--galaz ubuntu-2604` nie pomijać.** Skrypt sam rozpoznaje po nim maszynę
pracującą na osobnej gałęzi: pobiera jej gałąź do repozytorium serwera i **nie commituje jej
klucza do `main`** (klucz zostaje zapisany lokalnie na serwerze). Bez tego przełącznika skrypt
dopisałby klucz nowej maszyny do gałęzi `main` i wypchnął na GitHuba — czyli tknąłby kanon
istniejących maszyn.

Co ten krok daje: serwer i Asus wpuszczają nową maszynę kluczem, `known_hosts` po obu stronach
się uzupełnia, a przede wszystkim **Syncthing dostaje jej ID i oba foldery** — bez tego
`~/AI-katalog-roboczy` nigdy nie dojedzie.

> **Świadome ograniczenie:** nowa maszyna będzie mogła wejść po SSH na **serwer** (i odwrotnie),
> ale **nie na HP ani Katanę** — ich `authorized_keys` składa chezmoi z `lustra/klucze-publiczne/`
> na gałęzi `main`, a tam klucza `vostro-temp` celowo nie ma. Gdyby to zaczęło przeszkadzać, jest
> to JEDNA świadoma decyzja usera: dopisać `vostro-temp-dom.pub` do `main`. Kierunek odwrotny
> (z HP na nowego Vostro) działa od razu — nowa maszyna ma u siebie komplet cudzych kluczy.

### Krok 5 — wylogowanie i zalogowanie

Dopiero po ponownym zalogowaniu wstają rozszerzenia GNOME: pasek Dash to Panel na dole,
kafelkowanie Tiling Shell, czujniki Vitals, ikony na pulpicie.

---

## 3. Co zostaje RĘCZNIE (automat tego nie zrobi)

1. **Sterownik NVIDIA** — „Dodatkowe sterowniki" (Additional Drivers) w Ustawieniach systemu.
   Sterowniki są poza mechanizmem luster z definicji (`wykluczenia/apt.txt`: `nvidia-*`).
2. **Grubość paska Dash to Panel.** Ustawienia paska zależne od MONITORÓW nie jeżdżą lustrem
   (rozszerzenie trzyma je pod nazwami konkretnych ekranów). Jeśli pasek jest grubszy niż na HP:
   Menedżer rozszerzeń → Dash to Panel → *Position* → wysokość **32 px**.
3. **Logowania:** Chrome (synchronizacja konta + Zotero Connector), Zotero (+ Better BibTeX),
   Bitwarden, Claude Code ×2 konta (pierwsze uruchomienie `claude` w `~/AI-katalog-roboczy` —
   zatwierdzić MCP), Ferdium/Teams.
4. **Sejf (Bitwarden):** `bw login`, potem `sekrety-odswiez`. Do sejfu dwie pozycje:
   wpis maszyny `vostro-temp` (folder `Siec_domowa`) i `SSH — vostro-temp (id_ed25519)`
   (tylko klucz osobisty, ten z frazą). Kluczy `_dom` i `_github` do sejfu **nie** wkładamy —
   automat generuje je od nowa przy każdej instalacji.
5. **Transkryptor:** instalator workera z `~/AI-katalog-roboczy/12_Narzedzia-AI/Transkryptor/`
   (usługi użytkownika i wskaźnik nagrywania wozi już lustro, ale `venv` zakłada instalator).
6. **OneDrive: NIE WŁĄCZAĆ.** Usługa jest celowo zamaskowana (`onedrive = "brak"`) — archiwum
   prowadzi stary system na Ubuntu 24.04. Dwa klienty na jednym koncie = konflikty.
7. **Zdalny pulpit** — jeśli będzie potrzebny: Ustawienia → System → Udostępnianie →
   *Udostępnianie ekranu* (wbudowane w GNOME). Starego `x11vnc` już nie ma.
8. **Sprzęt maszyny** (monitory, budzenie przez sieć, zasilanie, szyfrowanie dysku) — to obszar
   `2_Stacje_lustra`, nie ten.

---

## 4. Jak to cofnąć

- **Nic nie trzeba cofać na `main`** — ta gałąź jej nie dotknęła ani jednym commitem.
- Rezygnacja z całości: `git push origin --delete ubuntu-2604` (i to samo na zdalnym `serwer`);
  nowa maszyna po prostu przechodzi wtedy na `main` (`git checkout main` w `~/.local/share/chezmoi`) —
  ale wtedy wracają wszystkie cięte pozycje i stary wzorzec pulpitu.
- Cofnięcie samych cięć programów, **bez** kasowania gałęzi: dziennik jest append-only, więc
  pomyłkę naprawia się **nowym zdarzeniem**, nie kasowaniem starego — `lustro dodaj <pakiet>`
  na nowej maszynie zapisze `dodano` z nowszą datą i pozycja wróci do konsensusu.
- Cofnięcie wgranego pulpitu na maszynie: `lustro pulpit wgraj` **przed każdą zmianą** zapisuje
  pełną kopię dconf i wypisuje komendę powrotu (`dconf load / < ~/.local/share/lustro/kopie/…`).

---

## 5. Czego NIE zweryfikowano (uczciwie)

- Niczego nie sprawdzano na żywym Ubuntu 26.04 — nie ma tu takiej maszyny. Nazwy pakietów,
  wersje rozszerzeń GNOME i zachowanie Waylanda to **założenia**, nie pomiary.
- `chezmoi apply` z tej gałęzi **nie był uruchamiany** (zakaz zmian na HP). Sprawdzono
  wyłącznie, że chezmoi poprawnie czyta źródło i widzi spójny zestaw plików (`chezmoi managed`
  na kopii źródła, bez `apply`).
- Kanon pulpitu to zrzut żywego HP z wieczora 14.09. User w tym czasie **pracował na maszynie
  i zmieniał ustawienia** (między dwoma odczytami zmieniły się m.in. ustawienia Caffeine
  i procent baterii na pasku). Jeśli tego wieczoru dopieszcza jeszcze pulpit, kanon warto
  odświeżyć jedną komendą **na HP, na tej gałęzi**:
  `python3 ~/.local/share/chezmoi/lustra/pulpit-kanon-odswiez.py`
  (kanon z tego commita został tak odświeżony o 23:3x — po odświeżeniu różnice wobec żywego HP
  to dokładnie trzy świadome odstępstwa kanonu i nic więcej, sprawdzone).
- Automatyczne ZBIERANIE zmian pulpitu z HP do kanonu (kierunek odwrotny) **nie jest zrobione** —
  działa kierunek kanon → maszyny. Ręczna komenda „zrzuć pulpit do kanonu":
  **`python3 ~/.local/share/chezmoi/lustra/pulpit-kanon-odswiez.py`** (na maszynie
  wzorcowej, przy działającym pulpicie). To jest komenda „zrzuć pulpit do kanonu" dla tej gałęzi:
  robi to samo co `lustro pulpit oddaj`, ale nakłada z powrotem trzy świadome odstępstwa kanonu
  (tapeta jako własny plik, wycięty skrót `custom2`, `disabled-extensions` bez zaszłości) — samo
  `lustro pulpit oddaj` by je zjadło. Nie commituje; wypisuje gotowe komendy gita.
