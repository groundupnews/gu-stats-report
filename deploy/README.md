# Deploying the web interface

The report's web interface runs on the same server as the counter, at
https://counter.groundup.org.za/report/, behind the same nginx basic auth as
`/stats/`. gunicorn serves `web.py` on 127.0.0.1:5001 and nginx forwards
`/report/` to it.

On the server the code is in `/home/groundup/statsreport`, the service runs
as `groundup`, and it's called `gunicorn_statsreport`.

## First installation

1. **Check port 5001 is free** (no output means free):

       ss -ltnp | grep :5001

   If it's taken, pick another port and change it in both
   `gunicorn_statsreport.service` and `nginx-report.conf`.

2. **Get the code and install the libraries**, logged in as `groundup` (not
   with sudo, so the files belong to `groundup`). Create the virtualenv
   here; one copied from another machine won't run:

       git clone git@github.com:groundupnews/gu-stats-report.git /home/groundup/statsreport
       cd /home/groundup/statsreport
       python3 -m venv env
       env/bin/pip install -r requirements.txt

3. **Copy your settings** from your laptop, then make them readable only by
   the service's user (the file holds the Matomo token and passwords):

       scp local_settings.py server:/tmp/
       sudo mv /tmp/local_settings.py /home/groundup/statsreport/
       sudo chown groundup:www-data /home/groundup/statsreport/local_settings.py
       sudo chmod 600 /home/groundup/statsreport/local_settings.py

4. **Check a report works from the command line**, as `groundup`:

       env/bin/python report.py 202610 --output /tmp/test-report.html

5. **Install and start the service:**

       sudo cp deploy/gunicorn_statsreport.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now gunicorn_statsreport
       systemctl status gunicorn_statsreport
       curl -s http://127.0.0.1:5001/report/ | head -5

6. **Add the nginx block.** Paste `deploy/nginx-report.conf` into
   `/etc/nginx/sites-available/counter` after the `location /stats/` block,
   then check and reload:

       sudo nginx -t
       sudo systemctl reload nginx

7. **Open** https://counter.groundup.org.za/report/ and log in with a
   `/stats/` user.

## Updating

As `groundup`:

    cd /home/groundup/statsreport
    git pull
    env/bin/pip install -r requirements.txt
    sudo systemctl restart gunicorn_statsreport

## When something goes wrong

- Report errors and warnings (e.g. "Videos could not be analysed"):
  `journalctl -u gunicorn_statsreport -e`
- nginx errors: `/var/log/nginx/counter_error.log`
- "502 Bad Gateway": the service isn't running
  (`systemctl status gunicorn_statsreport`).
- `status=203/EXEC` in `systemctl status`: systemd couldn't run
  `env/bin/gunicorn` at all, so it's missing (libraries not installed) or the
  virtualenv was copied from another machine (its scripts point to a Python
  that doesn't exist here). Recreate it on the server, as `groundup`:

      cd /home/groundup/statsreport
      rm -rf env
      python3 -m venv env
      env/bin/pip install -r requirements.txt
      sudo systemctl reset-failed gunicorn_statsreport
      sudo systemctl restart gunicorn_statsreport

  `reset-failed` clears systemd's "Start request repeated too quickly".
