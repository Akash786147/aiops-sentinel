# Sentinel platform runbook (Ubuntu server)

Server: Ubuntu 22.04 or 24.04, 2+ vCPU, 4+ GB RAM, about 10 GB free disk. Everything runs in Docker; the only published
port is 80 (Traefik).

## 1. Install

```bash
git clone <your repo url> aiops-sentinel && cd aiops-sentinel
sudo bash deploy/install.sh
```

The script installs Docker Engine and the compose plugin if missing, creates `/srv/sentinel` (all state: the SQLite database,
each service's git repo, build snapshots), validates the compose file, starts the stack and enables start on boot.

Optional LLM diagnosis: put `OPENAI_API_KEY=...` (or `GROQ_API_KEY=...`) in `.env`, then `make up`. Without a key the
platform still deploys, detects, rolls back and ranks suspect code; only the LLM re-rank and LLM patch are skipped.

| URL | What |
| --- | --- |
| `http://<server-ip>/` | Sentinel console |
| `http://<server-ip>/svc/orders/health` | a monitored service through Traefik |
| `http://<server-ip>/grafana/` | dashboards (anonymous viewer; admin password is `GRAFANA_ADMIN_PASSWORD`) |
| `http://<server-ip>/prometheus/`, `/alertmanager/` | metrics and alerts |

## 2. Check it works (5 minutes)

```bash
docker compose -f deploy/docker-compose.yml ps          # 9 containers healthy
docker ps --filter label=sentinel.monitor=true          # orders, inventory, payments
curl -s localhost/api/health ; curl -s localhost/api/overview
```

In the console: **Overview** shows three healthy services with live charts (sample traffic is on by default).

## 3. Demo: break a service on purpose

1. Open **Test lab**, choose `inventory`, fault `oom_leak`, **Apply** (this only edits the service's working copy, like a developer's uncommitted change), then **Restart now** (this builds and deploys the edited code).
2. Within about a minute: an *oom* incident appears, Sentinel **rolls back to the last good version** (a new deployment, no
   history rewritten), then the incident page shows the diagnosis: suspect function, the diff, the confirming tests and the
   proposed patch.
3. `orders` + `F01` (slow query) is the other path: it does not crash, so there is no auto-rollback; a latency-regression
   incident is raised about 60 s after the restart and you decide on the proposed patch (**Approve** applies it and deploys).
4. **Reset to last good** in the lab returns the working copy to the last good version.

## 4. Day to day

```bash
make logs            # follow the control plane
make ps              # stack status
make down / make up  # stop / start the platform (monitored services keep running)
make backup          # tar of /srv/sentinel
make clean-services  # remove every container Sentinel started for monitored services
make test            # run the test-suite (needs the Python requirements)
```

Restart a service: **Service > Restart** (builds the working copy, health-gates, swaps). Add your own service: **Add service**,
paste a git URL and branch; the repo needs a Dockerfile, an HTTP port and a health path (defaults: 8000, `/health`). For
metrics, expose Prometheus text on `/metrics`; without it you still get lifecycle and resource monitoring.

## 5. Limits and safety

* Each monitored container is capped (default 256 MB, 0.5 CPU; change per service in Settings), so one bad service cannot
  take the server down.
* Auto-rollback: only to the last healthy version, once per incident, only for crash loops, OOM kills, failed health checks and
  memory exhaustion. Latency or error regressions are *proposed*, never applied automatically.
* Sentinel has the Docker socket, which is root-equivalent on the host. Keep the server private, put it behind a VPN or
  firewall, and do not expose port 80 publicly without auth in front of it.
* Everything is in the audit page and `audit` table of `/srv/sentinel/sentinel.db`.

## 6. Troubleshooting

| Symptom | Check |
| --- | --- |
| `docker compose config` fails | `make config` prints the line; the images are pinned, check typos in `.env` |
| Console loads, services stay "starting" | `docker logs <svc-container>`; the health gate waits `SENTINEL_HEALTH_TIMEOUT_S` (30 s) |
| No metrics for a service | Prometheus > Status > Targets; the container needs labels `sentinel.monitor=true` and the `sentinel` network |
| No logs in Grafana | `docker logs sentinel-promtail-1`; promtail reads the Docker socket |
| Out of disk | `docker image prune -f`, `make clean-services` for stale containers, old builds in `/srv/sentinel/builds` |
| Reset everything | `make down && sudo rm -rf /srv/sentinel && make up` (deletes all service history) |

## 7. Uninstall

```bash
make clean-services && make down
sudo systemctl disable sentinel-stack && sudo rm /etc/systemd/system/sentinel-stack.service
sudo rm -rf /srv/sentinel
docker volume rm sentinel_prometheus-data sentinel_loki-data sentinel_grafana-data
```
