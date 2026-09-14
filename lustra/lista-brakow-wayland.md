# Lista braków — co wypadło z kanonu na gałęzi `ubuntu-2604` i czym to zastąpić

Sprawa **[423]**, 2026-09-14, obszar `5_Wspolna_konfiguracja`.
Werdykty usera z tabeli `5_Wspolna_konfiguracja/ubuntu-2604/tabela-weryfikacyjna-2026-09-14.html`
(sprawy [419]/[420]).

**Zasada tej listy: nic z niej NIE JEST instalowane przez automat.** To jest spis
„czego świadomie nie ma i co wziąć, gdy się okaże potrzebne" — zamienniki dociągamy
na żądanie, jedną komendą, wtedy gdy user faktycznie czegoś zabraknie.

Dlaczego w ogóle wypadły: stary Vostro i Katana chodziły na wymuszonej sesji **X11**
(`WaylandEnable=false` w GDM — krok K12b automatu). Od tego wisiała cała rodzina narzędzi,
które działają tylko na X11. Nowe Ubuntu 26.04 zostaje na **Wayland** (sesja domyślna),
więc rodzina odpada w komplecie, a razem z nią powód, dla którego X11 był wymuszany.

---

## 1. Rodzina X11 — to jest sedno

| Co wypadło | Do czego służyło | Kandydat na zamiennik | Status |
|---|---|---|---|
| **`x11vnc`** + usługa `zdalny-pulpit.service` + `~/bin/zdalny-pulpit.sh` | podgląd ŻYWEJ sesji graficznej tej maszyny z innego komputera (VNC na 127.0.0.1:5900, przez tunel SSH) | **wbudowane „Udostępnianie ekranu" GNOME** (`gnome-remote-desktop`, protokół RDP) — Ustawienia → System → Udostępnianie → Udostępnianie ekranu | **PRIORYTET.** Jedyna pozycja z tej listy, której brak user zauważy od razu |
| `xdotool` | wpisywanie tekstu i klikanie „za usera" w aktywnym oknie (automaty, dyktowanie) | **`ydotool`** (`sudo apt install ydotool`) — działa przez `/dev/uinput`, niezależnie od X11/Wayland; wymaga usługi `ydotoold` i uprawnień do `/dev/uinput` | niesprawdzone na 26.04 |
| `xclip` | kopiowanie do schowka z wiersza poleceń (używał tego `~/bin/ocr-zrzut.sh`) | **`wl-clipboard`** (`wl-copy` / `wl-paste`), `sudo apt install wl-clipboard` | `ocr-zrzut.sh` na tej gałęzi **sam wykrywa**, co ma pod ręką (`wl-copy`, potem `xclip`), a gdy nie ma nic — mówi to powiadomieniem zamiast milczeć |
| `xvfb` | „ekran w pamięci" do testów bez monitora (zasada 16 kontraktu: testy nie mogą wychodzić na usera) | na Wayland: `gnome-kiosk --headless` albo dalej `xvfb` przez Xwayland (`sudo apt install xvfb`) | do rozstrzygnięcia przy pierwszym teście, który tego potrzebuje |
| `openbox` | zapasowy menedżer okien dla sesji X11 / x11vnc | nie ma odpowiednika i nie jest potrzebny — sesja GNOME/Wayland ma własny kompozytor (Mutter) | zamknięte |
| `autorandr` | zapamiętywanie układu monitorów per zestaw ekranów (X11) | **prawdopodobnie zbędny**: GNOME na Wayland sam zapamiętuje układ ekranów w `~/.config/monitors.xml` i przywraca go po podłączeniu tego samego zestawu | sprawdzić dopiero, gdy układ monitorów zacznie „uciekać" |
| `~/bin/dane-logowania` (skrót **Super+Shift+H**) | wpisywał login/hasło z pęku kluczy do okna, które nie przyjmuje wklejania — stał na `xdotool` | przepis niżej (`ydotool`) | skrót usunięty z kanonu pulpitu, klawisz wolny |
| krok **K12b** automatu (`WaylandEnable=false`) | wymuszał sesję X11 w GDM | usunięty — nowy system zostaje na Wayland | zamknięte |

### Przepis: „wpisz dane logowania" na Wayland (odtworzenie `dane-logowania` przez `ydotool`)

Nie instalujemy tego z automatu. Kolejność, gdy user tego zażąda:

1. `sudo apt install ydotool` (pakiet zawiera też demona `ydotoold`).
2. Włączyć demona: `sudo systemctl enable --now ydotoold` — bez niego `ydotool` nie ma
   z czym gadać. (Wariant per-user wymaga dostępu do `/dev/uinput`, czyli reguły udev
   i grupy — to decyzja obszaru `7_Bezpieczenstwo`, bo daje programowi prawo pisania
   po klawiaturze całego systemu.)
3. Skrypt: to samo co stary `dane-logowania`, z podmianą jednej linii —
   `xdotool type --delay 12 "$TEKST"` → `ydotool type --key-delay 12 "$TEKST"`.
   Źródło hasła **zostaje w sejfie** (Bitwarden przez `bw`), zgodnie z zasadą 14
   kontraktu globalnego — do pliku nie trafia żadna wartość, tylko nazwa pozycji w sejfie.
4. Skrót klawiszowy: Ustawienia → Klawiatura → Skróty własne → `Super+Shift+H`.
   Kanon pulpitu tej gałęzi celowo tego skrótu **nie zawiera** (wpis `custom2` wycięty),
   więc nic się nie pobije.

Stary skrypt jest w historii gita: `git show main:bin/executable_dane-logowania`.

---

## 2. Monitorowanie zasobów — jedno rozszerzenie zamiast czterech programów

| Co wypadło | Do czego służyło | Czym zastąpione |
|---|---|---|
| `btop`, `htop` | podgląd procesów i obciążenia w terminalu | **rozszerzenie GNOME „Vitals"** (jest w kanonie, wersja pobierana automatycznie) + systemowy `top`, który jest w każdym Ubuntu |
| `nvtop` | obciążenie karty graficznej | Vitals (`show-gpu=true` w kanonie pulpitu) |
| `psensor` | temperatury i wentylatory w osobnym oknie | Vitals |
| `lm-sensors` **ZOSTAJE** | to nie jest program z oknem, tylko **źródło odczytów czujników** — Vitals bez niego nie ma skąd wziąć temperatur | — |

⚠️ **Czujnik temperatury procesora nazywa się inaczej na AMD i na Intelu.** Kanon wozi tę
nazwę jako znacznik `{{TEMP_CPU}}` (`lustra/pulpit/znaczniki-maszyn.toml`), a wartości dla
`vostro-temp` **nie ma** — więc `lustro pulpit wgraj` świadomie POMINIE klucz `hot-sensors`
i Vitals stanie na swoich domyślnych czujnikach. To zachowanie zamierzone („lepiej nie ruszyć
niż wpisać bzdurę"). Uzupełnienie to jedna linia w tym pliku po zmierzeniu na maszynie:
`for f in /sys/class/hwmon/*/name; do echo "$f $(cat $f)"; done`.

---

## 3. Terminale

| Co wypadło | Czym zastąpione |
|---|---|
| `kitty` (+ `.config/kitty/kitty.conf`) | **GNOME Terminal** — jego ustawienia (czarny profil, paleta) jadą w kanonie pulpitu, gałąź `/org/gnome/terminal/legacy/` |
| `wezterm` (+ `.config/wezterm/wezterm.lua` + zewnętrzne źródło apt `apt.fury.io/wez`) | j.w. Werdykt usera: „nie używa" |

---

## 4. Reszta cięć (poza rodziną X11)

| Co wypadło | Do czego służyło | Uwaga |
|---|---|---|
| `ddcutil` | sterowanie jasnością **monitora zewnętrznego** przez magistralę DDC/CI | doinstalować na żądanie; wymaga grupy `i2c` |
| `brightnessctl` | sterowanie podświetleniem ekranu laptopa z wiersza poleceń | GNOME ma własny suwak jasności |
| `cryptsetup`, `dislocker` | otwieranie woluminów LUKS / BitLocker z wiersza poleceń | `cryptsetup` doinstalować, gdy trzeba ręcznie otworzyć dysk; szyfrowanie systemowe robi instalator |
| `meson`, `ninja-build`, `libdrm-dev`, `libegl-dev`, `libva-dev`, `libgstreamer-plugins-bad1.0-dev` | biblioteki i narzędzia do **kompilowania** cudzego kodu | wchodzą same jako zależności, gdy coś naprawdę będzie budowane |
| `ibus-table-cangjie*`, `libchewing3*`, `libpinyin*`, `m17n-db`, `libm17n-0`, `libmarisa0`, `libopencc*`, `libotf1` | metody wpisywania pisma chińskiego/japońskiego — **wjechały z obrazu instalatora**, nikt ich nie wybierał | gdyby wróciły same na nowym systemie (są w obrazie 26.04), mechanizm potraktuje je jak pakiety bazowe instalatora i nie doda do kanonu — ale warto zerknąć na `lustro status` po tygodniu |
| `hp-pilnuj-snu-po-klapie` | łatka **wyłącznie dla HP** (pilnowanie uśpienia po zamknięciu klapy), wciągnięta do kanonu przypadkiem przez hook dpkg 12.09 | nie dotyczy Vostro |
| snap `teams-for-linux` | nieoficjalny klient Teams | wersja przeglądarkowa albo Ferdium (jest w kanonie jako flatpak) |
| rozszerzenie `gTile@vibou` | siatka i układy okien | **Tiling Shell** (jest w kanonie) — to samo miejsce, user wybrał Tiling Shell |
| źródło apt `fortinet` | repozytorium producenta dla `forticlient` | **uwaga: to NIE dotyczy uczelnianego VPN-a.** Profil ITLiMS (krok K15) stoi na `network-manager-fortisslvpn-gnome` — zwykłym pakiecie Ubuntu, który w kanonie ZOSTAJE |

---

## 5. Czego ta lista NIE rozstrzyga — rzeczy do sprawdzenia na żywym 26.04

Wszystko poniżej jest **niezweryfikowane** (nie mam Ubuntu 26.04 i nic tam nie sprawdzałem):

1. **Flameshot na Wayland.** `flameshot` ZOSTAJE w kanonie (skrót Super+Shift+S, zrzuty do
   wspólnego schowka), ale program jest z rodziny X11 i na Wayland bywa kapryśny. Jeśli nie
   zadziała: GNOME ma własne narzędzie zrzutów pod klawiszem **Print** (ten skrót też jest
   w kanonie: `/org/gnome/shell/keybindings/show-screenshot-ui`).
2. **Wersje rozszerzeń GNOME.** Ubuntu 26.04 ma nowszego GNOME Shella niż 46. Instalator
   rozszerzeń pyta extensions.gnome.org o paczkę dla wersji WYKRYTEJ na maszynie, więc dobierze
   właściwą sam. Rozszerzenie bez paczki pod nową wersję zostanie tylko zgłoszone
   (największe ryzyko: **Tailscale QS**, mały projekt jednego autora). Wtedy: albo poczekać na
   aktualizację u autora, albo używać `tailscale status` z terminala / panelu sieci.
3. **Nazwy pakietów.** Nie sprawdzałem, czy wszystkie 73 pakiety apt z listy istnieją pod tymi
   samymi nazwami w 26.04. Pakiet, którego nie ma, zgłosi się jako nieudana pozycja w `lustro
   sync --auto` — to komunikat, nie awaria bootstrapu.
4. **Sterownik NVIDIA.** Poza mechanizmem luster z definicji (`wykluczenia/apt.txt`: `nvidia-*`).
   Instaluje się ręcznie przez „Dodatkowe sterowniki" po pierwszym uruchomieniu.
