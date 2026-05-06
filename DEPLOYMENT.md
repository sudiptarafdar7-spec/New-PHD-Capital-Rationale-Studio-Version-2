# Deployment — PHD Capital Rationale Studio (new.researchrationale.in)

This app is designed to run **alongside** your existing app on the same VPS,
in its own directory, with its own database, systemd service, and Nginx vhost.

---

## 1.  Point DNS at your VPS

In your DNS provider, add an **A record**:

| Host                       | Type | Value (your VPS IP) |
|----------------------------|------|---------------------|
| `new.researchrationale.in` | A    | `<your-vps-ip>`     |

Wait a minute or two for it to propagate.

---

## 2.  One-line install / upgrade

SSH into the VPS as `root` and run:

```bash
curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/deploy.sh | sudo bash
```

That single command auto-detects whether this is a **fresh install** or an
**upgrade** of an existing install:

| Step | Fresh install                                              | Upgrade                          |
|------|------------------------------------------------------------|----------------------------------|
| 1    | Install system packages (Python 3.11, Node 20, PostgreSQL, Nginx, ffmpeg, certbot) | skipped |
| 2    | Create OS user `phdnew`                                    | skipped                          |
| 3    | Create database `phd_new_db` + user `phd_new_user`         | skipped                          |
| 4    | Write `/etc/phd-new.env` with auto-generated secrets       | skipped (your env stays)         |
| 5    | Clone repo to `/var/www/new-rationale-studio`              | `git pull`                       |
| 6    | Install pip + npm deps, `vite build` the frontend          | same                             |
| 7    | Create all DB tables + seed default **admin user**         | only re-run schema (idempotent)  |
| 8    | Install `phd-new.service` systemd unit on port `8100`      | restart it                       |
| 9    | Install Nginx vhost for `new.researchrationale.in`         | same                             |
| 10   | Get SSL cert via Let's Encrypt + auto-renew                | skipped if cert exists           |

**Re-run the same command** any time to deploy updates — your data, env,
SSL cert, and uploaded files are preserved.

> **Faster updates** (after the first install): use `update.sh` instead of
> re-running the full installer. It skips system packages and only pulls code,
> rebuilds the frontend, syncs DB schema, and restarts the service (~30 sec):
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/update.sh | sudo bash
> ```

---

## 3.  First-time login

Visit **https://new.researchrationale.in** and log in:

```
Email     :  admin@phdcapital.in
Password  :  Admin@123
```

> Change the password immediately after first login (top-right profile menu).

To use a **different** initial admin email/password, set them before running the installer:

```bash
ADMIN_EMAIL="you@example.com" ADMIN_PASSWORD="MyStrongPass!" \
  bash <(curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/deploy.sh)
```

---

## 4.  Where everything lives

| Thing                    | Path                                      |
|--------------------------|-------------------------------------------|
| App code                 | `/var/www/new-rationale-studio`           |
| Python venv              | `/var/www/new-rationale-studio/venv`      |
| Built frontend           | `/var/www/new-rationale-studio/build`     |
| Job files / uploads      | `/var/www/new-rationale-studio/backend/{job_files,uploaded_files,channel_logos,generated_charts}` |
| Env vars + secrets       | `/etc/phd-new.env` (chmod 600)            |
| systemd unit             | `/etc/systemd/system/phd-new.service`     |
| Nginx vhost              | `/etc/nginx/sites-available/phd-new.conf` |
| Backend logs             | `/var/log/phd-new.log`, `/var/log/phd-new.err.log` |
| PostgreSQL DB            | `phd_new_db` (user `phd_new_user`)        |

---

## 5.  Common ops

```bash
# Live logs
journalctl -u phd-new -f
tail -f /var/log/phd-new.err.log

# Restart backend
systemctl restart phd-new

# Edit env vars (e.g. add an API key)
nano /etc/phd-new.env
systemctl restart phd-new

# DB backup
sudo -u postgres pg_dump phd_new_db > backup_$(date +%F).sql

# Renew SSL (auto runs via certbot timer — manual trigger:)
certbot renew
```

---

## 6.  API keys

You can either:

- Put them in `/etc/phd-new.env` (recommended for `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `ASSEMBLYAI_API_KEY`, `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`),
  then `systemctl restart phd-new`, **or**
- Save them through the UI → **Admin → API Keys** (stored in the `api_keys` table).

The backend prefers env vars and falls back to the DB.

---

## 7.  Coexistence with the existing app

This deployment is fully isolated from any previous install:

| Resource     | Existing app                       | This app                          |
|--------------|------------------------------------|-----------------------------------|
| Directory    | `/var/www/rationale-studio`        | `/var/www/new-rationale-studio`   |
| OS user      | `phd`                              | `phdnew`                          |
| Database     | `phd_rationale_db`                 | `phd_new_db`                      |
| Service      | `phd-capital-backend.service`      | `phd-new.service`                 |
| Backend port | `8000`                             | `8100`                            |
| Domain       | `researchrationale.in`             | `new.researchrationale.in`        |

Nothing on the existing app is touched.
