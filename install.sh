#!/usr/bin/env bash
# One command. Brings up Nearby on this computer: the finder and page on :8765, and AdGuard Home as the phone book on :53 (its own controls answer on this computer only).
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n%s\n' "$*"; }

command -v docker >/dev/null || { say "Docker is not installed. https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { say "Docker Compose is missing. Install the docker-compose-plugin package."; exit 1; }
docker ps >/dev/null 2>&1 || { say "Docker needs permission. Run:  sudo usermod -aG docker $USER  then log out and back in (or run: newgrp docker) and try again."; exit 1; }

[ -f .env ] || cp .env.example .env
LAN_IP="$(grep -E '^LAN_IP=' .env | cut -d= -f2)"
if [ -z "$LAN_IP" ]; then
  LAN_IP="$(ip -4 route show default | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)"
  [ -n "$LAN_IP" ] || { say "Could not work out this computer's address. Put it in .env as LAN_IP=..."; exit 1; }
  sed -i "s/^LAN_IP=.*/LAN_IP=$LAN_IP/" .env
fi

mkdir -p adguard/conf adguard/work data
chmod 600 .env    # the door's password lives here
chmod 700 data    # the home's data: this user and the app only
if [ ! -f adguard/conf/AdGuardHome.yaml ]; then
  sed "s/__LAN_IP__/$LAN_IP/" adguard/AdGuardHome.template.yaml > adguard/conf/AdGuardHome.yaml
fi

docker compose up -d --build

say "Nearby is up."
echo "  The page:          http://$LAN_IP:8765"
echo "  Open the page now and choose a password. The first person to open a fresh box claims it."
echo "  Your house's phone book now lives at $LAN_IP. Point a device's DNS there to see what it asks for."
echo "  Samsung TV: Settings > General > Network > Network Status > IP Settings > DNS Setting > Enter manually > $LAN_IP"
if command -v ufw >/dev/null && systemctl is-active --quiet ufw 2>/dev/null; then
  NET="$(ip -4 route show dev "$(ip -4 route show default | awk '{print $5}' | head -1)" | awk '/proto kernel/ {print $1}' | head -1)"
  say "This computer's firewall (ufw) is on. Other devices can't reach Nearby until you open two doors to your home network only:"
  echo "  sudo ufw allow from ${NET:-192.168.0.0/24} to any port 8765 proto tcp comment 'Nearby page'"
  echo "  sudo ufw allow from ${NET:-192.168.0.0/24} to any port 53 comment 'Nearby phone book'"
fi
say "To stop: docker compose down.   To undo a TV: set its DNS back to automatic."
