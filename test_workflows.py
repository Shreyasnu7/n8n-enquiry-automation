import json
import shutil
import subprocess
from pathlib import Path

import pytest

import build_workflows as bw

HERE = Path(__file__).parent
WF = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (HERE / "workflows").glob("*.json")}
CRED_IDS = {"npSmtpLocal00001", "npSmtpAlerts0001", "npAdminHeader001"}


def test_files_match_the_builder():
    for name, wf in bw.workflows().items():
        assert WF[name] == json.loads(json.dumps(wf)), f"workflows/{name}.json is stale: run python build_workflows.py"


@pytest.mark.parametrize("name", sorted(WF))
def test_connections_point_at_real_nodes(name):
    wf = WF[name]
    names = {n["name"] for n in wf["nodes"]}
    for src, outs in wf["connections"].items():
        assert src in names
        for branch in outs["main"]:
            for link in branch:
                assert link["node"] in names


def test_credentials_are_references_only():
    for wf in WF.values():
        for n in wf["nodes"]:
            for ref in n.get("credentials", {}).values():
                assert ref["id"] in CRED_IDS
    text = (HERE / "credentials" / "clinic_smtp.json").read_text() + "".join(json.dumps(w) for w in WF.values())
    assert "password\": \"\"" in text and "X-Automation-Key" not in json.dumps(WF)       # the admin key is generated per instance


def test_failures_reach_the_error_workflow_and_admin_hooks_need_the_key():
    for name in ("1_enquiry_intake", "2_morning_digest"):
        assert WF[name]["settings"]["errorWorkflow"] == bw.IDS["errors"]
    hooks = [n for w in WF.values() for n in w["nodes"] if n["type"].endswith("webhook")]
    assert {n["parameters"]["path"]: n["parameters"].get("authentication", "none") for n in hooks} == \
        {"enquiry": "none", "setup-tables": "headerAuth", "digest-now": "headerAuth"}


def test_switch_converts_types():
    """Imported Switch nodes with strict type checks silently route nothing (a real n8n gotcha)."""
    sw = next(n for n in WF["1_enquiry_intake"]["nodes"] if n["type"].endswith("switch"))
    assert sw["parameters"]["looseTypeValidation"] is True
    assert [r["outputKey"] for r in sw["parameters"]["rules"]["values"]] == ["ok", "invalid", "spam"]


def test_reply_does_not_wait_for_email():
    c = WF["1_enquiry_intake"]["connections"]
    assert c["Save enquiry"]["main"][0][0]["node"] == "Reply: received"


# ---- the Code node JavaScript, run in Node with n8n's $json / $input shapes ------------------

NODE = shutil.which("node")


def run_js(code, json_in=None, items=None, refs=None):
    harness = f"""
const $json = {json.dumps(json_in or {})};
const __items = {json.dumps(items or [])};
const __refs = {json.dumps(refs or {})};
const $input = {{ all: () => __items.map(j => ({{ json: j }})) }};
const $ = name => ({{ first: () => ({{ json: __refs[name] }}) }});
const out = (() => {{ {code} }})();
console.log(JSON.stringify(out));"""
    r = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")
GOOD = {"name": " Priya  Nair ", "email": "Priya.Nair@Gmail.com", "phone": "0412 345 678", "service": "Physiotherapy",
        "message": "Sore lower back.", "consent": True}


@needs_node
@pytest.mark.parametrize("phone,shown,e164", [
    ("0412 345 678", "0412 345 678", "+61412345678"),
    ("+61 412 345 678", "0412 345 678", "+61412345678"),
    ("61412345678", "0412 345 678", "+61412345678"),
    ("(03) 9387 5521", "(03) 9387 5521", "+61393875521"),
])
def test_phone_numbers(phone, shown, e164):
    lead = run_js(bw.VALIDATE_JS, {"body": {**GOOD, "phone": phone}})["json"]["lead"]
    assert (lead["phone"], lead["phone_e164"]) == (shown, e164)


@needs_node
def test_valid_enquiry_is_tidied():
    lead = run_js(bw.VALIDATE_JS, {"body": GOOD})["json"]["lead"]
    assert lead["name"] == "Priya Nair" and lead["email"] == "priya.nair@gmail.com" and lead["service"] == "Physiotherapy"
    assert lead["priority"] == "normal" and lead["preferred_time"] == "Any time"


@needs_node
@pytest.mark.parametrize("change,error", [
    ({"phone": "555 1234"}, "Australian phone"), ({"email": "priya@"}, "email"), ({"service": "yoga"}, "choose a service"),
    ({"consent": False}, "agree"), ({"name": ""}, "name"), ({"phone": ""}, "phone number")])
def test_invalid_fields(change, error):
    out = run_js(bw.VALIDATE_JS, {"body": {**GOOD, **change}})["json"]
    assert out["outcome"] == "invalid" and any(error in e for e in out["errors"])


@needs_node
@pytest.mark.parametrize("message,priority", [
    ("Rolled my ankle, it's very swollen and I can't walk", "urgent"), ("New numbness in my left hand", "urgent"),
    ("Looking for a pilates class on Saturdays", "normal"), ("Had a fall at work yesterday", "urgent")])
def test_urgent_words(message, priority):
    assert run_js(bw.VALIDATE_JS, {"body": {**GOOD, "message": message}})["json"]["lead"]["priority"] == priority


@needs_node
def test_honeypot_is_spam():
    assert run_js(bw.VALIDATE_JS, {"body": {**GOOD, "website": "http://x.example"}})["json"]["outcome"] == "spam"


@needs_node
def test_repeat_only_counts_the_last_week():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    lead = run_js(bw.VALIDATE_JS, {"body": GOOD})["json"]["lead"]
    old = [{"email": lead["email"], "received_at": (now - timedelta(days=30)).isoformat()}]
    r = run_js(bw.REPEAT_JS, items=old, refs={"Validate and tidy": {"lead": lead}})[0]["json"]
    assert r["repeat"] is False and r["previous_enquiries"] == 1 and r["reference"].startswith("NP-")
    r = run_js(bw.REPEAT_JS, items=old + [{"email": lead["email"], "received_at": now.isoformat()}],
               refs={"Validate and tidy": {"lead": lead}})[0]["json"]
    assert r["repeat"] is True
    assert run_js(bw.REPEAT_JS, items=[{}], refs={"Validate and tidy": {"lead": lead}})[0]["json"]["previous_enquiries"] == 0


@needs_node
def test_digest_counts_and_flags_urgent():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rows = [{"reference": "NP-1", "received_at": now, "name": "A", "phone": "0412 345 678", "service": "Physiotherapy", "priority": "urgent"},
            {"reference": "NP-2", "received_at": now, "name": "B <script>", "phone": "0412 000 111", "service": "Physiotherapy", "priority": "normal"},
            {"reference": "NP-3", "received_at": "2020-01-01T00:00:00Z", "name": "Old", "phone": "", "service": "NDIS physiotherapy"}]
    d = run_js(bw.DIGEST_JS, items=rows + [{}])[0]["json"]
    assert d["count"] == 2 and d["urgent"] == 1 and d["subject"].startswith("2 new enquiries (1 urgent)")
    assert "&lt;script&gt;" in d["html"] and "Old" not in d["html"]


@needs_node
def test_error_message_is_readable():
    e = run_js(bw.ERROR_JS, {"workflow": {"name": "1. Website enquiry intake"},
                             "execution": {"lastNodeExecuted": "Email the front desk", "error": {"message": "refused <x>"},
                                           "url": "http://n8n/x/1", "mode": "webhook"}})[0]["json"]
    assert e["subject"] == 'n8n: "1. Website enquiry intake" failed at "Email the front desk"' and "&lt;x>" in e["html"]


# ---- the real thing: a throwaway n8n instance ---------------------------------------------

@pytest.fixture(scope="module")
def run():
    if not (shutil.which("n8n") or shutil.which("n8n.cmd")):
        pytest.skip("n8n is not installed")
    import harness
    return harness.run_scenario()


@pytest.mark.integration
def test_end_to_end_in_n8n(run):
    assert run["setup"]["status"] == 200 and run["setup_without_key"] == 403
    by = {e["label"]: e for e in run["enquiries"]}
    assert [e["status"] for e in run["enquiries"]] == [200, 200, 422, 200, 200, 200]
    assert len(by["form filled in wrong"]["response"]["errors"]) == 5
    assert by["bot (hidden field filled)"]["response"] == {"ok": True} and by["bot (hidden field filled)"]["emails"] == []
    urgent = by["sports injury, urgent words"]["emails"]
    assert urgent[0]["subject"].startswith("[URGENT]") and "call you on +61" not in urgent[1]["html"] and "today" in urgent[1]["html"]
    assert {m["to"][0] for m in urgent} == {bw.FRONT_DESK, "tom.obrien@outlook.com"}
    assert "Has enquired 1 time(s) before" in by["same patient asks again"]["emails"][0]["html"]
    assert run["digest"]["emails"][0]["subject"].startswith("4 new enquiries (1 urgent)")
    assert run["outage"]["response"]["ok"] is True                                    # the patient still gets a reference
    assert run["outage"]["alerts"][0]["subject"].endswith('failed at "Email the front desk"')
