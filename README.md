# Business Marketing Automation

This application collects business leads, prepares outreach messages, sends or reviews email and WhatsApp outreach, and exposes progress through a responsive web dashboard.

## Can it run online and on iOS?

Yes, with one important distinction:

- The web dashboard can be opened in Safari on an iPhone or iPad and added to the Home Screen like an app.
- Python, SQLite, Chrome/Selenium, and the outreach workers run on the server—not on iOS.
- Closing Safari does not stop a job. The server continues running and the dashboard can be reopened later.
- A Linux VPS is recommended for the complete Google/website/WhatsApp workflow.
- Ordinary shared cPanel hosting is generally suitable only for the dashboard and email queue unless the provider explicitly supports long-running processes and headless Chromium.

## Deployment choices

| Hosting option | Dashboard | Email worker | Google/website automation | WhatsApp Web automation |
| --- | --- | --- | --- | --- |
| Linux VPS | Yes | Yes | Yes | Yes, after linking a persistent browser profile |
| cPanel with permitted Chromium | Yes | Yes | Provider-dependent | Provider-dependent |
| Ordinary shared cPanel | Yes | Usually | Usually no | Usually no |
| iPhone/iPad alone | Dashboard only | No | No | No |

## Before deployment

1. Use Python 3.11 or newer.
2. Copy the project to the server.
3. Keep these paths writable by the application user:
   - `data/`
   - `logs/`
   - `chrome_profile/`
   - `config.json`
4. Set `headless` to `true` in `config.json` for normal server operation.
5. Store passwords and API keys in `.env` or the hosting provider's environment-variable manager. Do not commit `.env`, `config.json`, the SQLite database, or the Chrome profile.

Create `.env` from `.env.example` and provide at least:

```dotenv
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=replace-with-a-long-unique-password
OPENAI_API_KEY=
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=
```

`DASHBOARD_PASSWORD` is mandatory for remote access. The application deliberately refuses remote access when it is missing.

## Recommended production setup: Ubuntu VPS

The commands below assume the application will live at `/opt/business_marketing` and run as a non-root user named `marketing`. Adjust names and paths for your server.

Create that service user if it does not already exist, then give it ownership of the application directory:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin marketing
sudo chown -R marketing:marketing /opt/business_marketing
```

If your provider created a normal deployment user for you, use that account instead and update the systemd `User` and `Group` values below.

### 1. Install system packages

Install Python, Nginx, and a Chrome/Chromium browser supported by Selenium. Package names vary by Linux distribution and hosting provider.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
```

After installing Chrome or Chromium, verify that the application user can start it:

```bash
google-chrome --version
# or
chromium --version
```

### 2. Install the application

```bash
cd /opt/business_marketing
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Copy `.env.example` to `.env`, enter the production credentials, and configure `config.json`. For a server, the important settings are:

```json
{
  "headless": true,
  "data_dir": "data",
  "chrome_profile_dir": "chrome_profile"
}
```

Do not replace the entire existing `config.json` with this short example; update only these values and retain the other sections.

### 3. Test locally on the server

```bash
source /opt/business_marketing/venv/bin/activate
cd /opt/business_marketing
gunicorn --workers 1 --bind 127.0.0.1:8000 web_app:app
```

Keep Gunicorn bound to `127.0.0.1` when using Nginx so port 8000 is not exposed publicly. Flask's built-in `python web_app.py` server is for local development only, not production.

### 4. Run it with systemd

Create `/etc/systemd/system/business-marketing.service`:

```ini
[Unit]
Description=Business Marketing Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=marketing
Group=marketing
WorkingDirectory=/opt/business_marketing
EnvironmentFile=/opt/business_marketing/.env
ExecStart=/opt/business_marketing/venv/bin/gunicorn --workers 1 --bind 127.0.0.1:8000 web_app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and inspect it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now business-marketing
sudo systemctl status business-marketing
sudo journalctl -u business-marketing -f
```

One Gunicorn worker is intentional: the dashboard coordinates a single automation process and uses local SQLite/state files.

### 5. Put Nginx and HTTPS in front of it

Create an Nginx server block for your domain:

```nginx
server {
    listen 80;
    server_name marketing.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
```

Enable the site, validate Nginx, and reload it. Point the domain's DNS record to the VPS, then enable an HTTPS certificate using the VPS provider's certificate tool or Let's Encrypt. Do not use the dashboard over plain HTTP on the public internet because its login and lead data are sensitive.

Allow only SSH, HTTP, and HTTPS through the server firewall. Do not publicly expose SQLite, `.env`, `chrome_profile/`, or port 8000.

## One-time WhatsApp Web setup

WhatsApp automation needs a persistent linked WhatsApp Web session in `chrome_profile/`.

1. Temporarily access the VPS through a trusted graphical console or VNC session.
2. Set `headless` to `false`.
3. Start a WhatsApp job so the server browser opens WhatsApp Web.
4. On the primary iPhone, open WhatsApp, go to **Settings → Linked Devices**, and link the server browser using the QR code or phone-linking flow shown by WhatsApp.
5. Confirm that a chat can open from the server browser.
6. Stop the worker, set `headless` back to `true`, and restart the service.
7. Preserve and back up `chrome_profile/` securely. Anyone with access to that profile may be able to access the linked WhatsApp session.

Review linked devices regularly and remove any server or session you no longer recognize. WhatsApp may log out inactive linked devices, so occasional relinking can be necessary.

WhatsApp Web UI automation can break when WhatsApp changes its interface. For high-volume or business-critical delivery, use the official WhatsApp Business Platform instead of browser automation.

## cPanel deployment

See [CPANEL_DEPLOYMENT.md](CPANEL_DEPLOYMENT.md) for the Passenger setup and cron examples. Before choosing cPanel, ask the provider whether the account supports:

- Python 3.11+
- long-running child processes
- headless Chrome/Chromium
- persistent writable browser profiles
- sufficient memory for Chrome

If any of those are unavailable, host the dashboard/email worker on cPanel and run browser automation on a separate VPS or computer.

## Use it from iPhone or iPad

1. Open `https://marketing.example.com` in Safari.
2. Enter the dashboard username and password.
3. Review leads, delivery status, saved messages, and logs, or start an automation job.
4. To install it like an app, use Safari's **Share** menu, choose **Add to Home Screen**, enable **Open as Web App** when offered, and tap **Add**.

The phone is only controlling the server. Keep the VPS online while jobs run. If a WhatsApp login, CAPTCHA, or manual-review screen is required, connect to the server's graphical session; that browser screen is not streamed into the mobile dashboard.

## LinkedIn campaign workflow

The desktop dashboard includes a human-reviewed LinkedIn channel. **Run LinkedIn Bot** opens a LinkedIn people search in a new tab of the shared Chrome window using the same persistent `chrome_profile_dir` as WhatsApp; if that Chrome profile is not already open, Chrome creates its first window. LinkedIn requests sign-in in its own page when required. The default search is `Co Founder and CEO`, configurable under **Settings → LinkedIn → People Search Keywords**. Select a lead and choose **LinkedIn Details** to add the founder/owner name, role, business type, and LinkedIn profile URL. The dashboard creates a short draft from the lead's saved business and website analysis and uses the same sender company, contact name, email, phone, and website configured on the **Company** settings tab. Review the draft, open LinkedIn, copy it, send it manually, and then choose **Mark LinkedIn Sent**.

The application does not request or store LinkedIn credentials and does not scrape profiles or automate sending. Sign in directly on LinkedIn. If no profile URL is saved, **Open LinkedIn** opens a people search for the selected business so you can choose the appropriate person yourself.

## Updating the server

Back up the database and configuration before deploying an update:

```bash
sudo systemctl stop business-marketing
cp data/outreach.sqlite3 data/outreach.sqlite3.backup
# Upload or pull the new application files here.
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl start business-marketing
```

Never replace these production files/directories during a normal code update:

- `.env`
- `config.json`
- `data/`
- `chrome_profile/`

## Troubleshooting

- **Remote access says a password is required:** set `DASHBOARD_PASSWORD` and restart Gunicorn/Passenger.
- **Dashboard loads but automation does not start:** inspect the live dashboard log and `journalctl -u business-marketing`.
- **Chrome fails on the VPS:** confirm that Chrome/Chromium is installed, `headless` is enabled, and the service user owns `chrome_profile/`.
- **WhatsApp asks for login repeatedly:** relink the persistent server browser and confirm `chrome_profile_dir` has not changed.
- **Email fails:** verify the SMTP environment variables, port, TLS/SSL settings, and the hosting provider's outbound-mail policy.
- **SQLite reports locking:** run one dashboard worker and only one automation job at a time.

## Official references

- [Flask production deployment](https://flask.palletsprojects.com/en/stable/deploying/)
- [Flask Gunicorn deployment](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)
- [Apple: add a website to the iPhone Home Screen](https://support.apple.com/guide/iphone/iphea86e5236/ios)
- [WhatsApp: review linked devices](https://faq.whatsapp.com/1428782138011916/)
