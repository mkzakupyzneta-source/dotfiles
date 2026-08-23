# lustra/ — dane i apka mechanizmu luster

Ten katalog **zostaje w repozytorium chezmoi** i NIE jest rozwijany do katalogu domowego
(pilnuje tego wpis `lustra` w `.chezmoiignore` w korzeniu repozytorium — patrz „Pułapka" niżej).

Specyfikacja całości: `10_Siec_domowa/5_Wspolna_konfiguracja/mechanizm-luster-spec.md`.

## Etap E1 — TYLKO ODCZYT (stan 2026-08-23)

Apka umie wyłącznie **patrzeć**. Nic nie instaluje, nic nie usuwa, nie dotyka `dconf`
i nie woła `chezmoi apply`. Polecenia zmieniające cokolwiek odpowiadają
„niedostępne w E1" i kończą się kodem 2.

| Działa dziś | Wchodzi w E2/E3 |
|---|---|
| `status`, `pulpit status`, `dziennik`, `lista`, `pulpit zasiew` | `sync`, `dodaj`, `usun`, `ustawienia`, `pulpit oddaj`, `pulpit wgraj`, `pulpit sprawdz`, `nowa-maszyna` |

## Jak uruchomić

```bash
python3 ~/.local/share/chezmoi/lustra/lustro.py status
python3 ~/.local/share/chezmoi/lustra/lustro.py pulpit status
python3 ~/.local/share/chezmoi/lustra/lustro.py dziennik --od 2026-08-20
python3 ~/.local/share/chezmoi/lustra/lustro.py lista            # tabela na ekran
python3 ~/.local/share/chezmoi/lustra/lustro.py lista --do /tmp/programy-nowe.md
```

**Wygodniej — alias `lustro`.** Propozycja do dopisania w `dot_bashrc` w repozytorium
chezmoi (⚠️ NIE zastosowane — wymaga `chezmoi apply`, czyli zgody usera):

```bash
# mechanizm luster (5_Wspolna_konfiguracja)
alias lustro='python3 "$HOME/.local/share/chezmoi/lustra/lustro.py"'
```

Po dopisaniu i `chezmoi apply` wystarczy `lustro status`.

## Co tu leży

| Plik / katalog | Do czego |
|---|---|
| `lustro.py` | apka: inwentaryzacja, porównanie z dziennikami, wykrywanie instalacji obcych, warstwa pulpitu |
| `zasiew-e1.py` | **jednorazowy** skrypt, który zasiał dziennik z historii systemu (E1) |
| `dziennik/<maszyna>.jsonl` | historia zdarzeń jednej maszyny; **tylko ta maszyna tu dopisuje** (dlatego scalanie w gicie jest bezkonfliktowe) |
| `wykluczenia/apt.txt`, `snap.txt`, `flatpak.txt` | czego nie liczyć jako warsztat (jądro, sterowniki, szkielet Ubuntu) |
| `wykluczenia/obce.txt` | znane i zaakceptowane instalacje spoza apt/snap/flatpak |
| `wykluczenia/ustawienia.txt` | pliki stanu i cache — nie wozimy |
| `wykluczenia/tozsamosc.txt` | ⛔ tożsamość maszyny — **nigdy** nie lustrzyć (spec 7.6) |
| `pulpit/dconf-lustro.txt` | które ścieżki GNOME są w lustrze |
| `pulpit/dconf-poza-lustrem.txt` | które celowo nie są, z uzasadnieniem |
| `pulpit/dconf-pomijane-klucze.txt` | pojedyncze klucze do pominięcia wewnątrz tych ścieżek |
| `pulpit/dconf-wyjatki.txt` | pojedyncze klucze wożone mimo pominiętej ścieżki (`favorite-apps`, `enabled-extensions`) |
| `pulpit/pulpit.ini` | eksport ustawień pulpitu — **plik generowany**, `{{HOME}}` zamiast `/home/mk` |
| `ustawienia-map.txt` | program → jego pliki ustawień |

**Wykluczenia są DANYMI, nie kodem.** Żeby coś przestało się pokazywać, dopisuje się wzorzec
do pliku tekstowego — bez ruszania `lustro.py`.

## ⚠️ Pułapka sprawdzona 2026-08-23 na Vostro

Specyfikacja zakładała (hipoteza 1, rozdz. 14), że chezmoi zostawi katalog `lustra/`
w repozytorium, bo nie ma przedrostka `dot_`. **To nieprawda.** Bez `.chezmoiignore`
`chezmoi managed` pokazuje `lustra`, `lustra/dziennik`, … — czyli `chezmoi apply`
utworzyłby katalog `~/lustra`. Dlatego w korzeniu repozytorium leży `.chezmoiignore`
z jedną linią `lustra`. **Nie kasować jej.**

## Nazwa maszyny

Domyślnie nazwa hosta (`hostname`), tutaj `vostro`. Można ją nadpisać plikiem
`lustra/maszyna.txt` — ale wtedy plik dotyczyłby wszystkich maszyn (repozytorium jest
wspólne), więc **na razie nie używać**; to furtka na wypadek maszyny o nazwie hosta
niepasującej do nazwy lustra.
