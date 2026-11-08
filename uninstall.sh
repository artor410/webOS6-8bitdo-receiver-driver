#!/bin/sh
# Remove pad8bitdo from the TV. Run on the TV as root:
#   curl -fsSL https://raw.githubusercontent.com/artor410/webOS6-8bitdo-receiver-driver/main/uninstall.sh | sh
if [ -f /tmp/pad8bitdo.pid ] && kill -0 "$(cat /tmp/pad8bitdo.pid)" 2>/dev/null; then
    kill "$(cat /tmp/pad8bitdo.pid)"
fi
rm -f /var/lib/webosbrew/init.d/60-pad8bitdo
rm -rf /home/root/pad8bitdo
rm -f /tmp/pad8bitdo.log /tmp/pad8bitdo.log.1 /tmp/pad8bitdo.err /tmp/pad8bitdo.pid
echo "pad8bitdo removed. Unplug and replug the receiver (or restart the TV) to return it to the stock drivers."
