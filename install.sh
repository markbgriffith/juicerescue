#!/bin/zsh
# Install the JuiceBox services (DNS override, JuicePassProxy, web page) as launchd agents.
#   ./install.sh <this Mac's LAN IP> <JuiceBox ID> [upstream DNS, default 1.1.1.1]
set -euo pipefail
[[ $# -ge 2 ]] || { echo "usage: $0 <mac-ip> <juicebox-id> [upstream-dns]"; exit 1; }
DIR=${0:A:h}; MAC_IP=$1; JB_ID=$2; UPSTREAM=${3:-1.1.1.1}
LA=~/Library/LaunchAgents; mkdir -p "$LA" "$DIR/log" "$DIR/config"
for s in dns proxy web; do
  dest="$LA/com.juicerescue.$s.plist"
  sed -e "s#__DIR__#$DIR#g" -e "s#__MAC_IP__#$MAC_IP#g" -e "s#__JUICEBOX_ID__#$JB_ID#g" \
      -e "s#__UPSTREAM_DNS__#$UPSTREAM#g" "$DIR/launchd/com.juicerescue.$s.plist" > "$dest"
  plutil -lint -s "$dest"
  launchctl bootout "gui/$(id -u)/com.juicerescue.$s" 2>/dev/null || true
  for try in 1 2 3 4 5; do  # bootout finishes asynchronously
    launchctl bootstrap "gui/$(id -u)" "$dest" 2>/dev/null && break
    sleep 2
  done
done
launchctl list | grep com.juicerescue
