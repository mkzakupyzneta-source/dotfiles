#!/bin/bash
# Wznawia sesje Claude Code po restarcie systemu - JEDNORAZOWO.
#   (bez argumentu)  - uruchamiane przez autostart: kasuje wpis i otwiera terminal
#   uzbroj           - zaklada wpis autostartu na nastepny restart
#   rozbroj          - usuwa wpis
#
# Dlaczego skrypt, a nie polecenie wprost w pliku .desktop:
# format .desktop ma wlasne zasady cytowania i nie dopuszcza sekwencji \" w Exec=.
# Poprzednia wersja z tego powodu nigdy sie nie uruchomila.
DESKTOP="$HOME/.config/autostart/claude-code-resume.desktop"
SELF="$HOME/bin/wznow-sesje-claude.sh"
KATALOG="/home/mk/_LINUX_START"

case "$1" in
  uzbroj)
    mkdir -p "$HOME/.config/autostart"
    cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Code - wznowienie sesji
Comment=Jednorazowe wznowienie rozmowy po restarcie
Exec=$SELF
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=10
EOF
    echo "UZBROJONE. Po najblizszym starcie otworzy sie terminal z wznowiona sesja."
    echo "Wpis skasuje sie sam po jednym uruchomieniu."
    ;;
  rozbroj)
    rm -f "$DESKTOP"; echo "ROZBROJONE - wpis usuniety." ;;
  *)
    rm -f "$DESKTOP"                       # jednorazowo, zeby nie wracalo co start
    sleep 10                               # niech pulpit zdazy wstac
    gnome-terminal --working-directory="$KATALOG" -- bash -lc 'claude --continue; exec bash'
    ;;
esac
