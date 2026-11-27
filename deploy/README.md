# Stable VPS deployment

This guide assumes an **Ubuntu 24.04 LTS** VPS with root SSH access.

The app runs with **gunicorn** on `127.0.0.1:8000`, and **Caddy** provides the
public HTTPS URL and automatic certificates.

Use a domain name if possible. If you do not have one, you can test with a
free `sslip.io` hostname such as `203.0.113.10.sslip.io`, which resolves to
that IP address.

---

## 1. Create the server

Recommended: a small KVM VPS with 1–2 GB RAM, Ubuntu 24.04.

After it starts, note:

- the public IPv4 address,
- the Ubuntu root login.

For a custom domain, add an **A record** pointing the domain to the VPS IPv4
address before starting Caddy.

---

## 2. Install system packages

SSH into the VPS:

```bash
ssh root@YOUR_SERVER_IP
```

Then:

```bash
apt update
apt upgrade -y
apt install -y python3 python3-venv python3-pip curl ufw
```

Create the application user and folders:

```bash
adduser --disabled-password --gecos "" abroad
mkdir -p /srv/abroad/data /srv/abroad/data/uploads
chown -R abroad:abroad /srv/abroad
```

---

## 3. Upload the project

On your Windows PC, from the project folder (Git Bash):

```bash
tar \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='instance/cloudflared.exe' \
  --exclude='instance/tunnel.log' \
  --exclude='flask.log' \
  -czf abroad-release.tar.gz .
```

Upload it:

```bash
scp abroad-release.tar.gz root@YOUR_SERVER_IP:/tmp/
```

On the VPS:

```bash
tar -xzf /tmp/abroad-release.tar.gz -C /srv/abroad
chown -R abroad:abroad /srv/abroad
```

The archive includes `instance/abroad.sqlite` and `instance/uploads`.
Copy the existing data into the persistent data directory:

```bash
cp /srv/abroad/instance/abroad.sqlite /srv/abroad/data/abroad.sqlite
cp -a /srv/abroad/instance/uploads/. /srv/abroad/data/uploads/
chown -R abroad:abroad /srv/abroad/data
```

If you want a fresh demo database instead, do not copy the SQLite file. The
app will create and seed it on first start.

---

## 4. Create the Python environment

```bash
cd /srv/abroad
sudo -u abroad python3 -m venv .venv
sudo -u abroad .venv/bin/pip install --upgrade pip
sudo -u abroad .venv/bin/pip install -r requirements.txt
```

`requirements.txt` now includes `gunicorn` for production.

---

## 5. Create the production environment file

Generate a strong Flask secret:

```bash
SECRET=$(openssl rand -hex 32)
```

Create `/srv/abroad/.env`:

```bash
cat > /srv/abroad/.env <<EOF
SECRET_KEY=$SECRET
DATABASE_PATH=/srv/abroad/data/abroad.sqlite
UPLOAD_FOLDER=/srv/abroad/data/uploads
START_REFUND_SWEEPER=1
REFUND_SWEEP_SECONDS=60
ALLOW_DEMO_ADMIN=0
TZ=Africa/Tunis
PYTHONUNBUFFERED=1
EOF
chown abroad:abroad /srv/abroad/.env
chmod 600 /srv/abroad/.env
```

`ALLOW_DEMO_ADMIN=0` hides and disables the one-click admin demo login.
Buyer, seller, traveler and pro demo buttons remain available.

---

## 6. Set a private admin password

The public deployment must not keep the demo admin password.

```bash
sudo -u abroad bash -c 'cd /srv/abroad && set -a && . ./.env && set +a && .venv/bin/flask --app app set-password admin@abroad.tn'
```

Choose a strong password. You can use the same command later to rotate it.

The command is defined in `app.py`; it updates the password hash in SQLite
without putting the password in shell history.

---

## 7. Install and start the app service

```bash
cp /srv/abroad/deploy/abroad.service /etc/systemd/system/abroad.service
systemctl daemon-reload
systemctl enable --now abroad
systemctl status abroad --no-pager
```

Check the application locally:

```bash
curl -I http://127.0.0.1:8000/login
```

The expected status is `200 OK`.

If it is not running:

```bash
journalctl -u abroad -n 80 --no-pager
```

---

## 8. Install Caddy for HTTPS

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install -y caddy
```

Choose the public hostname:

```bash
# With a real domain:
DOMAIN=your-domain.com

# Or, with no domain:
DOMAIN=YOUR_SERVER_IP.sslip.io
```

Put the Caddy config in place:

```bash
cp /srv/abroad/deploy/Caddyfile /etc/caddy/Caddyfile
mkdir -p /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/override.conf <<EOF
[Service]
Environment=DOMAIN=$DOMAIN
EOF
systemctl daemon-reload
systemctl restart caddy
```

If using a real domain, make sure its A record already points to the VPS.
Caddy will obtain a Let's Encrypt certificate automatically.

Allow web traffic:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

---

## 9. Verify the public link

```bash
curl -I https://$DOMAIN/login
```

Then open the same address on your phone. The final stable link is:

```text
https://YOUR_DOMAIN
```

The app is now reachable without your PC being on.

---

## 10. Updating the application later

Build a new archive locally, upload it, and extract it **without deleting
`/srv/abroad/data`**:

```bash
scp abroad-release.tar.gz root@YOUR_SERVER_IP:/tmp/
ssh root@YOUR_SERVER_IP
tar -xzf /tmp/abroad-release.tar.gz -C /srv/abroad
chown -R abroad:abroad /srv/abroad
sudo -u abroad bash -c 'cd /srv/abroad && .venv/bin/pip install -r requirements.txt'
systemctl restart abroad
```

Never extract over `/srv/abroad/data`; that directory contains the live
database and uploads.

---

## Troubleshooting

### App service fails

```bash
journalctl -u abroad -n 100 --no-pager
```

Common causes:

- `.env` is missing or has a typo.
- `DATABASE_PATH` points to a directory that `abroad` cannot write.
- `gunicorn` was not installed in `.venv`.

### HTTPS certificate fails

- Confirm the domain's A record points to the VPS.
- Confirm ports 80 and 443 are open.
- Check Caddy logs:

```bash
journalctl -u caddy -n 100 --no-pager
```

### Database permissions

```bash
chown -R abroad:abroad /srv/abroad/data
```

### Backups

Stop the service before copying the SQLite file, or use SQLite's backup
command:

```bash
systemctl stop abroad
cp /srv/abroad/data/abroad.sqlite /root/abroad-$(date +%F).sqlite
tar -czf /root/abroad-uploads-$(date +%F).tar.gz -C /srv/abroad/data uploads
systemctl start abroad
```
