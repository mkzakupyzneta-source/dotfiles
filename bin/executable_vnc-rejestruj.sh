#!/bin/bash
# vnc-rejestruj.sh — rejestruje ~/.local/share/applications/vnc-otworz.desktop jako program
# otwierajacy odsylacze `vnc://`. Sprawa [258b].
#
# Od [258f] (2026-08-29) to tylko NAKLADKA na ogolny ~/bin/schemat-rejestruj.sh — cala logika
# (xdg-mime + zapasowy wpis w ~/.config/mimeapps.list) jest tam jeden raz, wspolna z `ssh://`.
# Plik zostaje pod stara nazwa, bo pozycja `vnc-handler` w lustra/skrypty.toml wymienia go
# w polu `wymaga` i moze byc juz zainstalowana na maszynach, ktore jeszcze nie wzialy zmiany.
set -u
exec "$HOME/bin/schemat-rejestruj.sh" x-scheme-handler/vnc vnc-otworz.desktop "$@"
