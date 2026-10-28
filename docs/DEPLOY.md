# Deploying the web workspace on a Linux server

This guide serves the workspace from a subdirectory of an existing website, e.g.
`https://example.org/idbd/`, with user accounts you administer and a read-only demo
for visitors.

```
browser ──https──▶ your web server (nginx or Apache, already serving your site)
                      │  /          → your website, unchanged
                      │  /idbd/...  → forwarded to ↓
                      ▼
                  IDBD workspace (Python, listening only on 127.0.0.1:8765),
                  kept running by systemd
```

The web server keeps handling HTTPS and your site; it forwards only `/idbd/`
requests to the app, which is never exposed to the internet directly.

## What you need

- A Linux server where you have `sudo`, already serving your site over **HTTPS**
  with nginx or Apache. (Logins use secure cookies, so HTTPS is required.)
- About 1 GB of disk for the app plus whatever users upload (default quota:
  1 GB per user).
- `git` and `curl` (`sudo apt install git curl` on Ubuntu). Python itself is
  **not** needed: `uv` installs its own.

The steps are written for **Ubuntu with Apache 2.4** (tested configuration: Ubuntu
26.04 LTS, Apache 2.4.66). nginx and other distributions differ only in step 6.

Commands below assume the defaults: app in `/opt/idbd`, data in `/var/lib/idbd`,
settings in `/etc/idbd/idbd.env`, prefix `/idbd`, port `8765`. If you change one,
change it everywhere it appears.

## 1. Install uv and create a service account

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
sudo useradd --system --home /var/lib/idbd --create-home --shell /usr/sbin/nologin idbd
```

The `idbd` account runs the app and owns its data; it cannot log in.

## 2. Get the code and install it

```bash
sudo mkdir -p /opt/idbd && sudo chown idbd:idbd /opt/idbd
sudo -u idbd git clone https://github.com/brianfox5/idbd_toolkit.git /opt/idbd
cd /opt/idbd
sudo -u idbd env UV_PYTHON_INSTALL_DIR=/opt/idbd/.python uv sync --extra web --locked
```

This creates `/opt/idbd/.venv` with Python and every dependency inside `/opt/idbd`;
nothing else on the server is touched.

## 3. Settings

```bash
sudo mkdir -p /etc/idbd
sudo cp deploy/idbd.env.example /etc/idbd/idbd.env
sudo chown root:idbd /etc/idbd/idbd.env && sudo chmod 640 /etc/idbd/idbd.env
sudo nano /etc/idbd/idbd.env        # check IDBD_ROOT_PATH matches your chosen prefix
```

## 4. Create the first administrator

```bash
sudo -u idbd env IDBD_DATA_DIR=/var/lib/idbd /opt/idbd/.venv/bin/idbd-admin \
     create-user brianfox --role admin --name "Brian Fox"
```

You'll be asked for a password (at least 10 characters). Further accounts can be
added in the browser under **Administration**.



## 5. Run it as a service

```bash
sudo cp deploy/idbd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now idbd
sudo systemctl status idbd           # should say "active (running)"
curl -s http://127.0.0.1:8765/api/me # {"mode":"server","user":null,...}
```

systemd starts the app at boot and restarts it if it ever stops, so it keeps running
after you log out.

## 6. Connect Apache

Enable the proxy modules (once):

```bash
sudo a2enmod proxy proxy_http headers
```

Find the configuration file for your site's **HTTPS** virtual host:

```bash
grep -l "443" /etc/apache2/sites-enabled/*.conf
```

On a site secured with Let's Encrypt this is usually
`/etc/apache2/sites-enabled/<your-site>-le-ssl.conf` (or `000-default-le-ssl.conf`).
Open it (`sudo nano <that file>`) and paste the contents of
`deploy/apache-idbd.conf` just before the closing `</VirtualHost>`. Then check and
reload:

```bash
sudo apachectl configtest        # should print "Syntax OK"
sudo systemctl reload apache2
```

If the site isn't on HTTPS yet: `sudo apt install certbot python3-certbot-apache`
then `sudo certbot --apache` sets it up and creates the `-le-ssl.conf` file.

The pasted block raises two limits the defaults would hit: the **response timeout**
(an agent draft can take a minute or more) and the **upload size** (PDFs, up to
100 MB).

*Using nginx instead?* Paste the blocks from `deploy/nginx-idbd.conf` into the
`server { }` block for your HTTPS site, then `sudo nginx -t && sudo systemctl reload nginx`.

Open `https://<your-site>/idbd/` — you should see the worked example and a *Log in*
button.

## Using it

- **Visitors** see the worked example, read-only.
- **Researchers** (accounts you create) each get a private workspace: their projects
  are invisible to others.
- **Administrators** can also add accounts, change roles, disable accounts and reset
  passwords (*Administration* in the header). Disabling an account or resetting its
  password signs that person out everywhere.
- **Draft with agent:** each user enters their own provider, model and API key under
  *⚙ Agent*. Keys stay in their browser and are sent only with draft requests; the
  server never stores them. (To let the server's own key serve everyone instead, set
  `IDBD_SERVER_KEYS=1` and a key in `idbd.env` — every user's drafts would then be
  billed to you.)

Command-line account management (on the server):

```bash
sudo -u idbd env IDBD_DATA_DIR=/var/lib/idbd /opt/idbd/.venv/bin/idbd-admin list
#   … create-user NAME [--role admin] | set-password NAME | disable NAME | enable NAME

sudo -u idbd env IDBD_DATA_DIR=/var/lib/idbd /opt/idbd/.venv/bin/idbd-admin \
create-user guest --role admin 

```

## Updating

```bash
sudo /opt/idbd/deploy/update.sh --check   # optional: see what's coming, change nothing
sudo /opt/idbd/deploy/update.sh
```

The script lists the incoming changes, pulls them, reinstalls dependencies exactly as
pinned in `uv.lock`, restarts the service and confirms the app is answering. Data in
`/var/lib/idbd`, the settings in `/etc/idbd/idbd.env`, the installed service file and
your Apache configuration are never modified. It stops or warns when an update needs
you:

- **Files edited in `/opt/idbd` on the server** — it stops before changing anything
  (server settings belong in `/etc/idbd/idbd.env`).
- **Dependencies changed but `uv.lock` wasn't updated** — it puts the previous version
  back, leaving the site as it was; run `uv lock` on your development machine,
  commit `uv.lock`, push, and update again.
- **The Apache block, settings template or service file changed** — it shows exactly
  what changed and the command to apply it.
- **The app doesn't come back after the restart** — it shows the recent log and the
  commands to return to the previous version.

Afterwards, ask anyone with the site open to reload the page.

## Backups

Everything users create is in `/var/lib/idbd`: `users.json` (accounts),
`secret.key` (signs login cookies), and `workspaces/<user>/` (projects and uploads).
Back that directory up; restoring it restores the site.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| **502 Bad Gateway** | the app isn't running — `sudo systemctl status idbd`, `sudo journalctl -u idbd -n 50` |
| **504 Gateway Timeout** on *Draft with agent* | the web server's timeout wasn't raised (step 6) |
| **413** when uploading a PDF | the web server's upload limit wasn't raised (step 6) |
| Page loads but looks unstyled or buttons do nothing | `IDBD_ROOT_PATH` doesn't match the prefix in the web server config |
| Login seems to succeed but you stay logged out | the site isn't on HTTPS (secure cookies are dropped); for a quick plain-HTTP test only, set `IDBD_COOKIE_SECURE=0` |
| Apache error `Invalid command 'RequestHeader'` or `'ProxyPass'` | a module isn't enabled: `sudo a2enmod proxy proxy_http headers` |
| Apache logs | `sudo tail -f /var/log/apache2/error.log` |
| Apache on RHEL/Alma/Rocky/Amazon Linux returns 503 | SELinux blocks the proxy: `sudo setsebool -P httpd_can_network_connect 1` |
| *OpenAI-compatible* endpoint at `localhost` unreachable | `localhost` means the **server**, not the user's laptop; local models must run on the server or be reachable from it |

## Configuration reference

Set in `/etc/idbd/idbd.env`:

| Variable | Default | Meaning |
|---|---|---|
| `IDBD_MODE` | `local` | `server` enables accounts, per-user workspaces and the demo |
| `IDBD_DATA_DIR` | `./var` | accounts, signing key and workspaces |
| `IDBD_EXAMPLE_DIR` | `./examples/data` | the worked example shown read-only |
| `IDBD_ROOT_PATH` | *(none)* | URL prefix, e.g. `/idbd` |
| `IDBD_HOST` / `IDBD_PORT` | `127.0.0.1` / `8000` | where the app listens |
| `IDBD_COOKIE_SECURE` | `1` | `0` allows login over plain HTTP (testing only) |
| `IDBD_SECRET_KEY` | *(generated)* | cookie-signing key; by default generated into the data directory |
| `IDBD_MAX_PROJECTS` | `50` | projects per user |
| `IDBD_QUOTA_MB` | `1000` | storage per user |
| `IDBD_SERVER_KEYS` | `0` in server mode | `1` lets keys in the environment serve as a fallback |
