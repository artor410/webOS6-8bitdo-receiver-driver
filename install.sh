#!/bin/sh
# Install pad8bitdo on a rooted LG webOS TV. Run on the TV as root:
#   curl -fsSL https://raw.githubusercontent.com/artor410/webOS6-8bitdo-receiver-driver/main/install.sh | sh
set -e
BASE="https://raw.githubusercontent.com/artor410/webOS6-8bitdo-receiver-driver/main"
DIR=/home/root/pad8bitdo
HOOK=/var/lib/webosbrew/init.d/60-pad8bitdo

[ "$(id -u)" = "0" ] || { echo "Run this as root (rooted TV, SSH as root)."; exit 1; }
command -v python >/dev/null || { echo "This TV has no 'python' (Python 2.7). Not supported, sorry."; exit 1; }
[ -d /var/lib/webosbrew ] || { echo "Homebrew Channel not found (/var/lib/webosbrew missing)."; exit 1; }

echo "Downloading driver..."
mkdir -p "$DIR"
curl -fsSL "$BASE/pad8bitdo.py" -o "$DIR/pad8bitdo.py.new"
mv "$DIR/pad8bitdo.py.new" "$DIR/pad8bitdo.py"
chmod 755 "$DIR/pad8bitdo.py"

echo "Installing boot hook..."
mkdir -p /var/lib/webosbrew/init.d
curl -fsSL "$BASE/init.d/60-pad8bitdo" -o "$HOOK"
chmod 755 "$HOOK"

echo "Starting driver..."
if [ -f /tmp/pad8bitdo.pid ] && kill -0 "$(cat /tmp/pad8bitdo.pid)" 2>/dev/null; then
    kill "$(cat /tmp/pad8bitdo.pid)"; sleep 2
fi
sh "$HOOK"
sleep 3
tail -n 3 /tmp/pad8bitdo.log 2>/dev/null || true
echo
echo "Done. Plug in the receiver, turn the controller on, then (re)open your app."
echo "Log: /tmp/pad8bitdo.log"
