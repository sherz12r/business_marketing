# cPanel deployment

This project now includes a responsive web dashboard, but full browser automation requires a VPS or a cPanel account whose provider explicitly permits headless Chromium. Shared cPanel can normally run the email worker; it may not support Selenium or WhatsApp Web.

## Application Manager

1. Upload the project outside `public_html`, for example `/home/USERNAME/business_marketing`.
2. In **Setup Python App** or **Application Manager**, select Python 3.11 or newer and set the application root to that folder.
3. Set the startup file to `passenger_wsgi.py` and the callable to `application`.
4. Install `requirements.txt` in the application virtual environment.
5. Add `DASHBOARD_USERNAME` and a long random `DASHBOARD_PASSWORD` as environment variables.
6. Move `SMTP_PASSWORD` and `OPENAI_API_KEY` to environment variables. Do not keep secrets in `config.json`.
7. Restart the application and use HTTPS for the assigned domain or subdomain.

## Daily cron jobs

Replace the example paths with those shown by cPanel's Python application page.

```cron
0 9 * * * cd /home/USERNAME/business_marketing && /home/USERNAME/virtualenv/business_marketing/3.11/bin/python -u main.py --pending-email >> data/runtime/cron-email.log 2>&1
```

For WhatsApp, prefer the official WhatsApp Business API. Only schedule the Selenium worker if the hosting provider permits Chrome and you have successfully created a persistent logged-in profile:

```cron
30 9 * * * cd /home/USERNAME/business_marketing && /home/USERNAME/virtualenv/business_marketing/3.11/bin/python -u main.py --pending-whatsapp >> data/runtime/cron-whatsapp.log 2>&1
```

Do not schedule a second run before the first has enough time to finish.
