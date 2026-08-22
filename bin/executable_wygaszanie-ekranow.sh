#!/bin/bash
# Domyka wygaszanie ekranow w GNOME na X11.
#
# PROBLEM: GNOME 46 po uplywie `org.gnome.desktop.session idle-delay` zaciemnia ekran,
# ale NIE wysyla monitorom polecenia DPMS off — podswietlenie zostaje wlaczone.
# Ustawianie wlasnych licznikow przez `xset dpms <czasy>` nie dziala trwale,
# bo GNOME nadpisuje je przy kazdej zmianie stanu bezczynnosci.
#
# ROZWIAZANIE: nie liczymy czasu sami — pytamy GNOME, czy JUZ uznal sesje za bezczynna
# (org.gnome.ScreenSaver.GetActive). Dzieki temu automatycznie respektujemy blokady
# bezczynnosci: podczas filmu albo dlugiego zadania GNOME nie zglasza bezczynnosci,
# wiec i my nie gasimy.
#
# Wybudzenie dzieje sie samo — dowolne wcisniecie klawisza lub ruch myszy.
# Wylaczenie: systemctl --user disable --now wygaszanie-ekranow.service

set -uo pipefail
INTERWAL="${INTERWAL:-10}"   # co ile sekund pytamy

[ -z "${DISPLAY:-}" ] && export DISPLAY=:1

czy_bezczynna() {
  local o
  o=$(gdbus call --session \
        --dest org.gnome.ScreenSaver \
        --object-path /org/gnome/ScreenSaver \
        --method org.gnome.ScreenSaver.GetActive 2>/dev/null) || return 1
  [[ "$o" == *"true"* ]]
}

monitor_swieci() {
  xset q 2>/dev/null | grep -q "Monitor is On"
}

while true; do
  if czy_bezczynna && monitor_swieci; then
    xset dpms force off 2>/dev/null
    logger -t wygaszanie-ekranow "sesja bezczynna — wygaszono monitory"
  fi
  sleep "$INTERWAL"
done
