"""Runs the workflows in a real, throwaway n8n instance and records what they did.

    python harness.py            fresh instance, the sample enquiries, the digest, a mail outage -> results/run.json

Nothing touches your normal n8n: the instance lives in .n8n-demo/ on port 5680, and mail goes to two local
SMTP sinks (the clinic's mail on 2525, the alerts account on 2526) that save every message.
"""
import email
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from email import policy
from pathlib import Path

import httpx
import psutil
from aiosmtpd.controller import Controller

HERE = Path(__file__).parent
FOLDER = HERE / ".n8n-demo"
PORT = 5680
BROKER_PORT = 5681         # n8n's task runner broker; its default (5679) is easy to collide with
BASE = f"http://127.0.0.1:{PORT}"
IDS = {"setup": "NPsetup000000001", "intake": "NPintake00000001", "digest": "NPdigest00000001", "errors": "NPerrors00000001"}


class Sink:
    """A local SMTP server that keeps every message it receives."""

    def __init__(self, port):
        self.port, self.messages, self.controller = port, [], None

    async def handle_DATA(self, server, session, envelope):
        m = email.message_from_bytes(envelope.content, policy=policy.default)
        body = m.get_body(("html", "plain"))
        self.messages.append({"to": envelope.rcpt_tos, "from": m["From"], "subject": str(m["Subject"]),
                              "html": body.get_content() if body else ""})
        return "250 OK"

    def start(self):
        self.controller = Controller(self, hostname="127.0.0.1", port=self.port)
        self.controller.start()
        return self

    def stop(self):
        if self.controller:
            self.controller.stop()
            self.controller = None


def wait_for(sink, count, timeout=30):
    """The reply goes out before the emails, so give them time to arrive (and the next step a quiet mail server)."""
    end = time.time() + timeout
    while len(sink.messages) < count and time.time() < end:
        time.sleep(0.2)
    time.sleep(0.5)
    return len(sink.messages) >= count


def env():
    return {**os.environ, "N8N_USER_FOLDER": str(FOLDER), "N8N_PORT": str(PORT), "N8N_RUNNERS_BROKER_PORT": str(BROKER_PORT), "N8N_LISTEN_ADDRESS": "127.0.0.1",
            "GENERIC_TIMEZONE": "Australia/Melbourne", "N8N_DIAGNOSTICS_ENABLED": "false", "N8N_PERSONALIZATION_ENABLED": "false",
            "N8N_VERSION_NOTIFICATIONS_ENABLED": "false", "N8N_SECURE_COOKIE": "false", "WEBHOOK_URL": BASE + "/",
            "N8N_EDITOR_BASE_URL": BASE + "/"}


def cli(*args):
    exe = shutil.which("n8n") or shutil.which("n8n.cmd")
    r = subprocess.run([exe, *args], env=env(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode:
        raise RuntimeError(f"n8n {' '.join(args)} failed:\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r.stdout


def fresh_instance():
    """New database, credentials with a generated admin key, the four workflows, all published."""
    shutil.rmtree(FOLDER, ignore_errors=True)
    FOLDER.mkdir()
    key = secrets.token_urlsafe(24)
    creds = json.loads((HERE / "credentials" / "clinic_smtp.json").read_text())
    creds += [{"id": "npSmtpAlerts0001", "name": "Alerts SMTP", "type": "smtp",
               "data": {**creds[0]["data"], "port": 2526}},
              {"id": "npAdminHeader001", "name": "Automation admin key", "type": "httpHeaderAuth",
               "data": {"name": "X-Automation-Key", "value": key}}]
    (FOLDER / "credentials.json").write_text(json.dumps(creds))
    cli("import:credentials", f"--input={FOLDER / 'credentials.json'}")
    (FOLDER / "credentials.json").unlink()
    cli("import:workflow", "--separate", f"--input={HERE / 'workflows'}")
    for wf in ("setup", "intake", "digest", "errors"):     # 2.x runs only published versions, error workflows included
        cli("publish:workflow", f"--id={IDS[wf]}")
    (FOLDER / "admin_key.txt").write_text(key)
    return key


def body(r):
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}


def up():
    """/healthz answers before the routes exist; the settings endpoint only once n8n is really serving."""
    try:
        return httpx.get(BASE + "/rest/settings", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@contextmanager
def running():
    exe = shutil.which("n8n") or shutil.which("n8n.cmd")
    log = open(FOLDER / "n8n.log", "w", encoding="utf-8")
    proc = subprocess.Popen([exe, "start"], env=env(), stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            if up():
                break
            if proc.poll() is not None:
                raise RuntimeError("n8n exited:\n" + (FOLDER / "n8n.log").read_text()[-2000:])
            time.sleep(0.5)
        else:
            raise RuntimeError("n8n did not start in 2 minutes")
        time.sleep(2)                      # let it finish registering the published webhooks
        yield
    finally:
        try:
            procs = psutil.Process(proc.pid).children(recursive=True) + [psutil.Process(proc.pid)]
        except psutil.NoSuchProcess:
            procs = []
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        log.close()


def run_scenario():
    clinic, alerts = Sink(2525).start(), Sink(2526).start()
    key = fresh_instance()
    out = {"enquiries": [], "digest": None, "outage": None}
    try:
        with running():
            admin = {"X-Automation-Key": key}
            r = httpx.post(BASE + "/webhook/setup-tables", headers=admin, timeout=60)
            out["setup"] = {"status": r.status_code, "body": body(r)}
            out["setup_without_key"] = httpx.post(BASE + "/webhook/setup-tables", timeout=30).status_code

            for e in json.loads((HERE / "samples" / "enquiries.json").read_text(encoding="utf-8")):
                before = len(clinic.messages)
                r = httpx.post(BASE + "/webhook/enquiry", json=e["form"], timeout=60)
                wait_for(clinic, before + (2 if body(r).get("reference") else 0), timeout=30 if body(r).get("reference") else 2)
                out["enquiries"].append({"label": e["label"], "status": r.status_code, "response": body(r),
                                         "emails": clinic.messages[before:]})

            before = len(clinic.messages)
            r = httpx.post(BASE + "/webhook/digest-now", headers=admin, timeout=60)
            wait_for(clinic, before + 1)
            out["digest"] = {"status": r.status_code, "emails": clinic.messages[before:]}

            clinic.stop()                                    # the clinic's mail server goes down
            r = httpx.post(BASE + "/webhook/enquiry", timeout=60, json={
                "name": "Grace Liu", "email": "grace.liu@outlook.com", "phone": "0433 812 400", "service": "clinical pilates",
                "message": "Interested in a pilates assessment after my knee reconstruction.", "consent": True})
            wait_for(alerts, 1)
            out["outage"] = {"status": r.status_code, "response": body(r), "alerts": alerts.messages}
    finally:
        clinic.stop()
        alerts.stop()
    return out


if __name__ == "__main__":
    res = run_scenario()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "run.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for e in res["enquiries"]:
        print(f"{e['status']}  {e['label']:<38} {json.dumps(e['response'])[:80]}  emails: {len(e['emails'])}")
    print("digest:", res["digest"]["status"], [m["subject"] for m in res["digest"]["emails"]])
    print("outage:", res["outage"]["status"], [m["subject"] for m in res["outage"]["alerts"]])
    sys.exit(0)
