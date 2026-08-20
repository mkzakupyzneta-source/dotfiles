#!/bin/bash
# Wlacza automatyczne logowanie uzytkownika mk w GDM (Ubuntu 24.04).
# Wymaga uprawnien roota. Odwracanie: uruchom z argumentem "off".
set -e
C=/etc/gdm3/custom.conf
if [ "$1" = "off" ]; then
    sed -i '/^AutomaticLoginEnable=true$/d; /^AutomaticLogin=mk$/d' "$C"
    echo "Autologowanie WYLACZONE. Kopia sprzed zmiany: $C.bak"
else
    cp -n "$C" "$C.bak"
    grep -q "^AutomaticLoginEnable=true" "$C" || sed -i '/^\[daemon\]/a AutomaticLoginEnable=true\nAutomaticLogin=mk' "$C"
    echo "Autologowanie WLACZONE dla uzytkownika mk. Kopia sprzed zmiany: $C.bak"
fi
echo "--- sekcja [daemon] po zmianie ---"
sed -n '/\[daemon\]/,/^\[/p' "$C" | grep -v "^#" | grep -v "^$"
