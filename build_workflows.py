"""Writes the n8n workflow files in workflows/ (import them into any n8n 1.x/2.x instance).

The JavaScript inside the Code nodes lives here as plain strings so it can be read and diffed;
run this after changing it.
"""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).parent / "workflows"
CLINIC = "Northside Physio"
FROM = "Northside Physio <enquiries@northsidephysio.example>"
FRONT_DESK = "frontdesk@northsidephysio.example"
MANAGER = "practice.manager@northsidephysio.example"
SMTP = {"smtp": {"id": "npSmtpLocal00001", "name": "Clinic SMTP"}}
ALERT_SMTP = {"smtp": {"id": "npSmtpAlerts0001", "name": "Alerts SMTP"}}
ADMIN_KEY = {"httpHeaderAuth": {"id": "npAdminHeader001", "name": "Automation admin key"}}
TABLE = {"__rl": True, "mode": "name", "value": "enquiries"}
IDS = {"setup": "NPsetup000000001", "intake": "NPintake00000001", "digest": "NPdigest00000001", "errors": "NPerrors00000001"}
SETTINGS = {"executionOrder": "v1", "timezone": "Australia/Melbourne", "saveManualExecutions": True,
            "errorWorkflow": IDS["errors"], "callerPolicy": "workflowsFromSameOwner"}

VALIDATE_JS = r"""// One website enquiry in, one cleaned-up lead (or the reasons it can't be accepted) out.
const b = $json.body ?? {};
const clean = s => String(s ?? '').trim().replace(/\s+/g, ' ');

// A hidden field people never see. Bots fill it in; they get a normal "thanks" and nothing is stored.
if (clean(b.website)) return { json: { outcome: 'spam' } };

const errors = [];
const name = clean(b.name);
const email = clean(b.email).toLowerCase();
const service = clean(b.service).toLowerCase();
const message = String(b.message ?? '').trim().slice(0, 2000);

if (name.length < 2) errors.push('Please tell us your name.');
if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(email)) errors.push("That email address doesn't look right.");

// Australian numbers in any common format: 0412 345 678, +61 412 345 678, (03) 9387 1234.
let phone = String(b.phone ?? '').replace(/[^\d+]/g, '');
if (phone.startsWith('+61')) phone = '0' + phone.slice(3);
else if (phone.startsWith('61') && phone.length === 11) phone = '0' + phone.slice(2);
if (phone && !/^0[2-478]\d{8}$/.test(phone)) errors.push('Please give an Australian phone number, like 0412 345 678.');
if (!phone) errors.push('Please give a phone number so we can call you back.');

const SERVICES = { 'physiotherapy': 'Physiotherapy', 'sports injury': 'Sports injury', 'clinical pilates': 'Clinical Pilates',
                   'remedial massage': 'Remedial massage', 'ndis': 'NDIS physiotherapy' };
if (!SERVICES[service]) errors.push('Please choose a service.');
if (b.consent !== true && b.consent !== 'true' && b.consent !== 'on') errors.push('Please agree to us contacting you about this enquiry.');

// Words that mean a person should call back today rather than in the normal queue.
const urgent = /\b(urgent|severe|can'?t (walk|move|sleep|bend)|numb(ness)?|swollen|swelling|fell|fall)\b/i.test(message);

if (errors.length) return { json: { outcome: 'invalid', errors } };
return { json: { outcome: 'ok', lead: {
  name, email,
  phone: phone.replace(/^(04\d{2})(\d{3})(\d{3})$/, '$1 $2 $3').replace(/^(0[2378])(\d{4})(\d{4})$/, '($1) $2 $3'),
  phone_e164: '+61' + phone.slice(1),
  service: SERVICES[service],
  message,
  preferred_time: clean(b.preferred_time) || 'Any time',
  priority: urgent ? 'urgent' : 'normal',
} } };"""

REPEAT_JS = r"""// Has this person enquired before? Earlier rows come from the data table lookup (none = one empty item).
const lead = $('Validate and tidy').first().json.lead;
const earlier = $input.all().map(i => i.json).filter(r => r.email);
const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
const recent = earlier.filter(r => new Date(r.received_at ?? r.createdAt).getTime() > weekAgo);
const now = new Date();
const today = now.toLocaleDateString('en-CA', { timeZone: 'Australia/Melbourne' });     // 2026-10-28, the clinic's date
const reference = 'NP-' + today.slice(2).replace(/-/g, '') + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
return [{ json: { reference, received_at: now.toISOString(), ...lead,
                  repeat: recent.length > 0, previous_enquiries: earlier.length, status: 'new' } }];"""

CLINIC_EMAIL_HTML = r"""={{ (() => {
  const l = $('Check for earlier enquiries').first().json;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const flag = l.priority === 'urgent' ? '<p style="background:#fbe3dc;color:#8f2410;padding:8px 10px;border-radius:4px"><b>Urgent:</b> the message mentions symptoms that need a call back today.</p>' : '';
  const rep = l.repeat ? `<p style="background:#f6ecd4;color:#7a5200;padding:8px 10px;border-radius:4px">Has enquired ${l.previous_enquiries} time(s) before, at least once in the last week.</p>` : '';
  return `<div style="font:14px/1.5 Arial,sans-serif;color:#222;max-width:560px">${flag}${rep}
  <table style="border-collapse:collapse">
  <tr><td style="color:#666;padding:3px 12px 3px 0">Reference</td><td><b>${esc(l.reference)}</b></td></tr>
  <tr><td style="color:#666;padding:3px 12px 3px 0">Name</td><td>${esc(l.name)}</td></tr>
  <tr><td style="color:#666;padding:3px 12px 3px 0">Phone</td><td><a href="tel:${esc(l.phone_e164)}">${esc(l.phone)}</a></td></tr>
  <tr><td style="color:#666;padding:3px 12px 3px 0">Email</td><td>${esc(l.email)}</td></tr>
  <tr><td style="color:#666;padding:3px 12px 3px 0">Service</td><td>${esc(l.service)}</td></tr>
  <tr><td style="color:#666;padding:3px 12px 3px 0">Best time</td><td>${esc(l.preferred_time)}</td></tr></table>
  <p style="white-space:pre-wrap;border-left:3px solid #ccc;padding-left:10px">${esc(l.message)}</p></div>`;
})() }}"""

PATIENT_EMAIL_HTML = r"""={{ (() => {
  const l = $('Check for earlier enquiries').first().json;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const when = l.priority === 'urgent' ? 'today' : 'within one business day';
  return `<div style="font:15px/1.6 Arial,sans-serif;color:#222;max-width:520px">
  <p>Hi ${esc(l.name.split(' ')[0])},</p>
  <p>Thanks for getting in touch about ${esc(l.service.toLowerCase())}. One of our team will call you on ${esc(l.phone)} ${when}.</p>
  <p>Your reference is <b>${esc(l.reference)}</b>.</p>
  <p>If your pain gets much worse, or you have new numbness or weakness, please see your GP or call 000 in an emergency.</p>
  <p>Northside Physio<br>212 Sydney Rd, Brunswick VIC 3056 &middot; (03) 9387 1234</p></div>`;
})() }}"""

DIGEST_JS = r"""// Enquiries since the start of the previous business day, grouped for the morning huddle.
const rows = $input.all().map(i => i.json).filter(r => r.reference);
const now = new Date();
const since = new Date(now);
since.setDate(now.getDate() - (now.getDay() === 1 ? 3 : 1));   // Monday's digest covers the weekend
since.setHours(8, 0, 0, 0);
const fresh = rows.filter(r => new Date(r.received_at) >= since).sort((a, b) => a.received_at < b.received_at ? -1 : 1);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const byService = {};
for (const r of fresh) byService[r.service] = (byService[r.service] ?? 0) + 1;
const urgent = fresh.filter(r => r.priority === 'urgent');
const time = d => new Date(d).toLocaleString('en-AU', { timeZone: 'Australia/Melbourne', weekday: 'short', hour: 'numeric', minute: '2-digit' });
const rowsHtml = fresh.map(r => `<tr${r.priority === 'urgent' ? ' style="background:#fbe3dc"' : ''}>
  <td style="padding:4px 8px">${time(r.received_at)}</td><td style="padding:4px 8px">${esc(r.name)}${r.repeat ? ' (repeat)' : ''}</td>
  <td style="padding:4px 8px">${esc(r.phone)}</td><td style="padding:4px 8px">${esc(r.service)}</td>
  <td style="padding:4px 8px">${r.priority === 'urgent' ? '<b>urgent</b>' : ''}</td></tr>`).join('');
const html = `<div style="font:14px/1.5 Arial,sans-serif;color:#222">
  <p><b>${fresh.length}</b> new enquiries since ${time(since)}${urgent.length ? `, <b style="color:#8f2410">${urgent.length} urgent</b>` : ''}.</p>
  <p>${Object.entries(byService).map(([s, n]) => `${esc(s)}: ${n}`).join(' &middot; ') || 'No enquiries.'}</p>
  ${fresh.length ? `<table style="border-collapse:collapse;border:1px solid #ddd"><tr style="background:#f3f3f3"><th style="padding:4px 8px;text-align:left">Received</th><th style="padding:4px 8px;text-align:left">Name</th><th style="padding:4px 8px;text-align:left">Phone</th><th style="padding:4px 8px;text-align:left">Service</th><th></th></tr>${rowsHtml}</table>` : ''}</div>`;
return [{ json: { count: fresh.length, urgent: urgent.length, html,
                  subject: `${fresh.length} new enquiries${urgent.length ? ` (${urgent.length} urgent)` : ''}: ${now.toLocaleDateString('en-AU', { timeZone: 'Australia/Melbourne', weekday: 'long', day: 'numeric', month: 'long' })}` } }];"""

ERROR_JS = r"""// Turns n8n's error report into a short message someone can act on.
const e = $json.execution ?? {};
const wf = $json.workflow ?? {};
return [{ json: {
  subject: `n8n: "${wf.name ?? 'a workflow'}" failed at "${e.lastNodeExecuted ?? 'unknown step'}"`,
  html: `<div style="font:14px/1.5 Arial,sans-serif">
    <p>The workflow <b>${wf.name}</b> stopped at <b>${e.lastNodeExecuted ?? '?'}</b>.</p>
    <p style="background:#f6f6f6;padding:8px;font-family:monospace">${String(e.error?.message ?? 'no message').replace(/</g, '&lt;')}</p>
    <p>${e.url ? `<a href="${e.url}">Open the failed execution</a>` : `Execution ${e.id ?? ''}`} &middot; mode: ${e.mode ?? ''}</p></div>` } }];"""


def node(name, type_, version, pos, params, **extra):
    return {"parameters": params, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"northside/{name}")),
            "name": name, "type": f"n8n-nodes-base.{type_}", "typeVersion": version, "position": pos, **extra}


def cond(value, out):
    return {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": [{"id": f"rule-{out}", "leftValue": "={{ $json.outcome }}", "rightValue": value,
                                           "operator": {"type": "string", "operation": "equals"}}], "combinator": "and"},
            "renameOutput": True, "outputKey": out}


def links(*pairs):
    """("A", "B") or ("A", 2, "B") -> n8n connections."""
    c = {}
    for p in pairs:
        src, idx, dst = (p[0], 0, p[1]) if len(p) == 2 else p
        outs = c.setdefault(src, {"main": []})["main"]
        while len(outs) <= idx:
            outs.append([])
        outs[idx].append({"node": dst, "type": "main", "index": 0})
    return c


def respond(name, pos, body, code=200):
    return node(name, "respondToWebhook", 1.5, pos, {"respondWith": "json", "responseBody": body,
                                                    "options": {"responseCode": code}})


def email(name, pos, to, subject, html):
    return node(name, "emailSend", 2.1, pos, {"fromEmail": FROM, "toEmail": to, "subject": subject, "emailFormat": "html",
                                             "html": html, "options": {"appendAttribution": False}}, credentials=SMTP)


def workflows():
    setup = {"id": IDS["setup"], "name": "0. Setup: create the enquiries table", "active": False, "settings": {"executionOrder": "v1"},
             "nodes": [node("Run once", "webhook", 2.1, [0, 0], {"httpMethod": "POST", "path": "setup-tables", "authentication": "headerAuth",
                                                                   "responseMode": "lastNode", "responseData": "firstEntryJson", "options": {}},
                            credentials=ADMIN_KEY, webhookId="7f0c2a55-1b9e-4d31-8c0a-2f6d9e4b1a01"),
                       node("Create enquiries table", "dataTable", 1.1, [240, 0], {
                           "resource": "table", "operation": "create", "tableName": "enquiries",
                           "columns": {"column": [{"name": n, "type": t} for n, t in (
                               ("reference", "string"), ("received_at", "date"), ("name", "string"), ("email", "string"),
                               ("phone", "string"), ("phone_e164", "string"), ("service", "string"), ("message", "string"),
                               ("preferred_time", "string"), ("priority", "string"), ("repeat", "boolean"),
                               ("previous_enquiries", "number"), ("status", "string"))]},
                           "options": {"createIfNotExists": True}})],
             "connections": links(("Run once", "Create enquiries table"))}

    intake_nodes = [
        node("Website form", "webhook", 2.1, [0, 200], {"httpMethod": "POST", "path": "enquiry", "responseMode": "responseNode",
                                                       "options": {"allowedOrigins": "https://northsidephysio.example"}},
             webhookId="b1d6c0de-4e7a-4c2e-9a3e-5a1f0e2d7c11"),
        node("Validate and tidy", "code", 2, [220, 200], {"mode": "runOnceForEachItem", "jsCode": VALIDATE_JS}),
        node("Route", "switch", 3.2, [440, 200], {"rules": {"values": [cond("ok", "ok"), cond("invalid", "invalid"), cond("spam", "spam")]},
                                                  "looseTypeValidation": True, "options": {}}),
        node("Earlier enquiries from this email", "dataTable", 1.1, [680, 60], {
            "resource": "row", "operation": "get", "dataTableId": TABLE, "matchType": "allConditions",
            "filters": {"conditions": [{"keyName": "email", "condition": "eq", "keyValue": "={{ $json.lead.email }}"}]},
            "returnAll": True}, alwaysOutputData=True),
        node("Check for earlier enquiries", "code", 2, [900, 60], {"mode": "runOnceForAllItems", "jsCode": REPEAT_JS}),
        node("Save enquiry", "dataTable", 1.1, [1120, 60], {
            "resource": "row", "operation": "insert", "dataTableId": TABLE,
            "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": [], "schema": []}, "options": {}}),
        email("Email the front desk", [1560, 60], FRONT_DESK,
              "={{ ($('Check for earlier enquiries').first().json.priority === 'urgent' ? '[URGENT] ' : '') + 'New enquiry: ' + $('Check for earlier enquiries').first().json.name + ', ' + $('Check for earlier enquiries').first().json.service }}",
              CLINIC_EMAIL_HTML),
        email("Email the patient", [1780, 60], "={{ $('Check for earlier enquiries').first().json.email }}",
              "={{ 'We got your enquiry (' + $('Check for earlier enquiries').first().json.reference + ')' }}", PATIENT_EMAIL_HTML),
        respond("Reply: received", [1340, 60], "={{ JSON.stringify({ ok: true, reference: $('Check for earlier enquiries').first().json.reference }) }}"),
        respond("Reply: fix these", [680, 240], "={{ JSON.stringify({ ok: false, errors: $json.errors }) }}", 422),
        respond("Reply: thanks (spam, not stored)", [680, 400], '={{ JSON.stringify({ ok: true }) }}'),
    ]
    intake = {"id": IDS["intake"], "name": "1. Website enquiry intake", "active": False, "settings": SETTINGS, "nodes": intake_nodes,
              "connections": links(("Website form", "Validate and tidy"), ("Validate and tidy", "Route"),
                                   ("Route", 0, "Earlier enquiries from this email"), ("Route", 1, "Reply: fix these"),
                                   ("Route", 2, "Reply: thanks (spam, not stored)"),
                                   ("Earlier enquiries from this email", "Check for earlier enquiries"),
                                   ("Check for earlier enquiries", "Save enquiry"),
                                   # Reply as soon as the enquiry is stored: the website's answer shouldn't depend on email.
                                   ("Save enquiry", "Reply: received"), ("Reply: received", "Email the front desk"),
                                   ("Email the front desk", "Email the patient"))}

    digest = {"id": IDS["digest"], "name": "2. Morning enquiry digest", "active": False, "settings": SETTINGS,
              "nodes": [node("Weekdays 8:00", "scheduleTrigger", 1.2, [0, 0],
                             {"rule": {"interval": [{"field": "cronExpression", "expression": "0 8 * * 1-5"}]}}),
                        node("Run now", "webhook", 2.1, [0, 180], {"httpMethod": "POST", "path": "digest-now", "authentication": "headerAuth",
                                                                   "responseMode": "lastNode", "responseData": "firstEntryJson", "options": {}},
                             credentials=ADMIN_KEY, webhookId="3c9e7d12-6a40-4f5b-b2d8-91e0c4a7f302"),
                        node("All enquiries", "dataTable", 1.1, [240, 80], {"resource": "row", "operation": "get", "dataTableId": TABLE,
                                                                            "returnAll": True}, alwaysOutputData=True),
                        node("Build digest", "code", 2, [460, 80], {"mode": "runOnceForAllItems", "jsCode": DIGEST_JS}),
                        email("Email the practice manager", [680, 80], MANAGER, "={{ $json.subject }}", "={{ $json.html }}")],
              "connections": links(("Weekdays 8:00", "All enquiries"), ("Run now", "All enquiries"),
                                   ("All enquiries", "Build digest"), ("Build digest", "Email the practice manager"))}

    errors = {"id": IDS["errors"], "name": "3. Alert when a workflow fails", "active": False, "settings": {"executionOrder": "v1"},
              "nodes": [node("When any workflow fails", "errorTrigger", 1, [0, 0], {}),
                        node("Describe the failure", "code", 2, [220, 0], {"mode": "runOnceForAllItems", "jsCode": ERROR_JS}),
                        # Sent through a different mail account, so an outage of the clinic's mail can still be reported.
                        {**email("Email the developer", [440, 0], "automation-alerts@northsidephysio.example", "={{ $json.subject }}", "={{ $json.html }}"),
                         "credentials": ALERT_SMTP}],
              "connections": links(("When any workflow fails", "Describe the failure"), ("Describe the failure", "Email the developer"))}
    return {"0_setup": setup, "1_enquiry_intake": intake, "2_morning_digest": digest, "3_error_alert": errors}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for fname, wf in workflows().items():
        (OUT / f"{fname}.json").write_text(json.dumps(wf, indent=2), encoding="utf-8")
        print("wrote", OUT / f"{fname}.json")
