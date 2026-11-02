# Running ATLAS in the cloud

ATLAS runs on one small Linux server so your own PC does not have to stay on. It is protected by a password and HTTPS. Research and paper trading only: live trading stays disabled, and IBKR is not used in the cloud (stocks come from Yahoo, delayed).

**Cost:** a VPS with 2 GB RAM, roughly $6-12 per month (Hetzner, DigitalOcean, Vultr and similar). You need no domain: a free `<ip-with-dashes>.sslip.io` name works.

## One-time setup

1. **Rent a server.** Ubuntu 24.04, 2 GB RAM. Note its IP address, for example `203.0.113.5`.
2. **Pick the web address.**
   - Free: your IP with dashes plus `.sslip.io`, e.g. `203-0-113-5.sslip.io`.
   - Or your own domain: add an `A` record pointing to the IP.
3. **Log in to the server** (from PowerShell on Windows): `ssh root@203.0.113.5`
4. **Install Docker and the firewall:**
   ```bash
   curl -fsSL https://get.docker.com | sh
   ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
   ```
5. **Get ATLAS:**
   ```bash
   git clone https://github.com/SushiWarriorX/atlastradingterminal.git
   cd atlastradingterminal
   git checkout feature/cloud-deploy      # until this branch is merged
   ```
6. **Create your settings file:**
   ```bash
   cp deploy/env.example .env
   chmod 600 .env
   nano .env
   ```
   Set `ATLAS_DOMAIN` (your address from step 2) and `ATLAS_AUTH_PASSWORD` (at least 12 characters; `openssl rand -base64 18` makes a good one). Optionally add `ANTHROPIC_API_KEY`. Save with Ctrl+O, Enter, Ctrl+X.
7. **Start it:**
   ```bash
   docker compose up -d --build
   ```
   The first build takes a few minutes.
8. **Open** `https://<your address>` and log in. The HTTPS certificate is obtained automatically (give it a minute on first start).

## Everyday commands (run in the `atlastradingterminal` folder on the server)

| Task | Command |
|---|---|
| See logs | `docker compose logs -f atlas` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` (your data stays) |
| Update to new code | `git pull` then `docker compose up -d --build` |
| Back up the database | `docker compose exec atlas python -c "import sqlite3;s=sqlite3.connect('/data/atlas.db');d=sqlite3.connect('/data/backup.db');s.backup(d)"` then `docker compose cp atlas:/data/backup.db ./atlas-backup.db` |
| Change the password | edit `.env`, then `docker compose up -d` (everyone is logged out) |

Copy `atlas-backup.db` off the server now and then (`scp root@203.0.113.5:atlastradingterminal/atlas-backup.db .`). The database holds your journal, notes and saved runs.

## Moving your existing local data (optional)

Stop the app on the server, then from your PC copy your `atlas.db` up and into the data volume:
```bash
scp atlas.db root@203.0.113.5:atlastradingterminal/atlas.db
docker compose down
docker compose run --rm --no-deps -v "$PWD/atlas.db:/in.db:ro" atlas cp /in.db /data/atlas.db
docker compose up -d
```

## What is protected, and what is not

- Everything under `/api` and `/ws` needs a login cookie (HttpOnly, SameSite=Strict, Secure over HTTPS, 7 days). Five wrong passwords from one address lock that address out for five minutes. Requests from other websites are refused.
- The app container publishes no port; only Caddy (HTTPS) is reachable. ATLAS refuses to start on a public address without `ATLAS_AUTH_PASSWORD`.
- Secrets live only in `.env` on the server. Keep SSH keys-only (`PasswordAuthentication no`) and enable automatic security updates (`apt install unattended-upgrades`).
- There is one password and one user. This is not multi-user software. Anyone with the password can use the research tools and the paper-trading engine (no UI exposes it, and live orders always return 403).
- Not verified: the Docker image build and the HTTPS setup were prepared without a Docker daemon or a real server. Check the first start with `docker compose logs`.

## Going back to your PC

Nothing about the local Windows setup changed: without `ATLAS_AUTH_PASSWORD` the app behaves exactly as before and listens only on `127.0.0.1`.
