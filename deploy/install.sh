#!/usr/bin/env bash
# Install AIOps Sentinel on a fresh Ubuntu 22.04/24.04 server.  Run from the repo root:  sudo bash deploy/install.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE=/srv/sentinel

if [[ $EUID -ne 0 ]]; then
  echo "run as root: sudo bash deploy/install.sh" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "==> installing Docker Engine and the compose plugin"
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi

echo "==> state directory ${STATE}"
mkdir -p "${STATE}"

if [[ ! -f "${REPO}/.env" ]]; then
  cp "${REPO}/.env.example" "${REPO}/.env"
  echo "==> created ${REPO}/.env  (add OPENAI_API_KEY or GROQ_API_KEY there for LLM diagnosis; the platform works without)"
fi

echo "==> validating the stack"
cd "${REPO}"
docker compose -f deploy/docker-compose.yml config -q

echo "==> starting the stack"
docker compose -f deploy/docker-compose.yml up -d --build

echo "==> installing the systemd unit (start on boot)"
sed "s#__REPO__#${REPO}#g" deploy/sentinel-stack.service > /etc/systemd/system/sentinel-stack.service
systemctl daemon-reload
systemctl enable sentinel-stack.service

echo
echo "Sentinel is up:  http://<server-ip>/        Grafana: /grafana/   Prometheus: /prometheus/"
