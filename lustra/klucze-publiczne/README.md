# klucze-publiczne/ — klucze PUBLICZNE maszyn domowych (DANE, nie sekrety)

Założone 2026-08-27 przez obszar `2_Stacje_lustra` (sprawa [222], decyzja usera:
„lustra mają być tak samo ustawione"). Klucz publiczny wolno kopiować i pokazywać;
**klucz prywatny nigdy nie trafia do repozytorium** (`wykluczenia/tozsamosc.txt`, `~/.ssh/id_*`).

## Po co
Z tych plików chezmoi **składa `~/.ssh/authorized_keys` każdej stacji-lustra**
(`private_dot_ssh/private_authorized_keys.tmpl`): kto ma klucz w tym katalogu, wchodzi
na każdą stację. Nowa stacja dostaje komplet automatem przy pierwszym `chezmoi apply`.
Maszyny spoza lustra (serwer, Asus, Wyse) **nie** czytają tego katalogu — tam klucze
dopisuje się ręcznie / przez panel HA (stan z 27.08: wszystkie mają komplet).

## Konwencja nazw
`<klucz maszyny z maszyny.toml>-<rola>.pub`, jedna linia, komentarz klucza `<user>@<maszyna>-<rola>`:

| Plik | Rola (7_Bezpieczenstwo, etap S) | Uwagi |
|---|---|---|
| `vostro-dom.pub`, `katana-dom.pub` | **domowy** `~/.ssh/id_ed25519_dom` — bez frazy, tylko maszyny domowe | wygenerowane 27.08 lokalnie na każdej stacji |
| `vostro-osobisty.pub`, `katana-osobisty.pub` | **osobisty** `~/.ssh/id_ed25519` | były już w `authorized_keys` przed 27.08 — zostawione, do decyzji obszaru 7, czy wycofać z maszyn domowych (po wdrożeniu `~/.ssh/config` stacje używają w domu wyłącznie klucza domowego) |
| `serwer-glowny.pub` | jedyny klucz serwera (RSA, `~/.ssh/id_rsa`, bez frazy) | serwer nie ma profilu stacji — ma jeden klucz do wszystkiego |
| `hp-windows.pub` | HP pod Windows (`micha@PC-domowy`) | **do usunięcia po formacie HP** i zastąpienia przez `hp-dom.pub` |
| `wyse-ha.pub` | Home Assistant na Wyse (`root@core-ssh`) | dom (automatyzacje) wchodzi na stacje |

## Nowa stacja — co zrobić
1. na stacji: `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_dom -N "" -C "mk@<maszyna>-dom"`
2. skopiować `~/.ssh/id_ed25519_dom.pub` tutaj jako `<maszyna>-dom.pub`, commit + push
3. dopisać ten sam klucz ręcznie na maszynach spoza lustra: serwer, Asus (`kiosk`), Wyse (dodatek SSH w HA)
4. **test wykonany, nie odczytany:** `ssh -o BatchMode=yes <cel> hostname` z nowej stacji na każdą maszynę.

## Wycofanie maszyny (kradzież, sprzedaż)
Skasować jej plik tutaj → następny `chezmoi apply` na stacjach usuwa ją z `authorized_keys`;
ręcznie: serwer, Asus, Wyse. Reszta kluczy zostaje (osobny klucz per stacja — decyzja L2, 27.08).
