#!/usr/bin/env bash
# Connect the UNO Q to a WPA2-Enterprise network (NUwave / eduroam) over adb.
# The password is typed here and sent straight to the board; it is not printed.
#   bash tools/board-wifi.sh            # connect (asks for network, username, password)
#   bash tools/board-wifi.sh --forget   # remove the saved campus login from the board
set -euo pipefail
ADB=${ADB:-adb}

q() { printf "'%s'" "$(printf %s "$1" | sed "s/'/'\\\\''/g")"; }  # quote for the board's shell

if [ "${1:-}" = "--forget" ]; then
  for name in NUwave eduroam; do
    "$ADB" shell "nmcli connection delete $(q "$name") 2>/dev/null && echo removed $name" || true
  done
  exit 0
fi

read -rp "Network [NUwave]: " SSID; SSID=${SSID:-NUwave}
read -rp "Username (NUwave: your Northeastern username; eduroam: user@northeastern.edu): " USERNAME
read -rsp "Password (hidden): " PASSWORD; echo

"$ADB" shell "nmcli radio wifi on; nmcli connection delete $(q "$SSID") >/dev/null 2>&1; \
nmcli connection add type wifi ifname wlan0 con-name $(q "$SSID") ssid $(q "$SSID") \
  wifi-sec.key-mgmt wpa-eap 802-1x.eap peap 802-1x.phase2-auth mschapv2 \
  802-1x.identity $(q "$USERNAME") 802-1x.password $(q "$PASSWORD") >/dev/null && \
nmcli connection up $(q "$SSID")"
unset PASSWORD

echo "Checking internet from the board..."
"$ADB" shell 'sleep 3; ip -br addr show wlan0; timeout 8 curl -s -o /dev/null -w "downloads.arduino.cc -> HTTP %{http_code}\n" https://downloads.arduino.cc/ || echo "no internet yet"'
