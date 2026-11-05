# n8n: website enquiries for a physio clinic

Real n8n workflows (n8n 2.x, importable into 1.x too) that take a clinic's website enquiry form from "someone hits Send" to "the right person knows and the patient has a reference". The clinic, Northside Physio in Brunswick, is fictional.

**1. Website enquiry intake** (`POST /webhook/enquiry`)
- Cleans and checks the form: name, email, an Australian phone number in any common format (stored as shown and as +61), a known service, and consent. Mistakes come back as HTTP 422 with plain-English reasons the form can show.
- A hidden honeypot field catches bots: they get a normal "thanks" and nothing is stored or sent.
- Flags urgent wording ("can't walk", "swollen", "numbness", "fell") so the front desk calls back today.
- Looks up earlier enquiries from the same email in an n8n Data Table and marks repeats within the last week.
- Saves the enquiry, replies to the website with a reference straight away (so the reply never depends on email), then emails the front desk (with an [URGENT] subject when needed) and sends the patient a confirmation with a safety note.

**2. Morning enquiry digest:** weekdays at 8:00 Melbourne time (Monday covers the weekend), a summary for the practice manager by service, with urgent ones highlighted. It can also be run on demand through a key-protected webhook.

**3. Alert when a workflow fails:** the error workflow for both. It emails which workflow and step failed, why, and a link to the failed run, through a separate mail account so a clinic mail outage can still be reported.

**0. Setup** creates the `enquiries` Data Table (key-protected, safe to run twice).

## Run it

Import `workflows/*.json` into n8n, create an SMTP credential named "Clinic SMTP" (and "Alerts SMTP") and a Header Auth credential named "Automation admin key", publish the workflows, then call `/webhook/setup-tables` once with the key.

`build_workflows.py` writes the workflow files; the JavaScript in the Code nodes lives there as readable strings.

## Tested in a real n8n

`python harness.py` starts a throwaway n8n instance (its own data folder and port, so it never touches an existing n8n) with two local mail servers that capture every email. It then runs the sample enquiries, the digest and a mail outage. `results/run.json` and `results/emails.html` are from a real run.

`python -m pytest -q`: 29 tests. They check the workflow files (wiring, credentials as references only, error workflow set, the Switch node's type conversion, reply-before-email order). They run the Code-node JavaScript in Node with n8n's `$json` and `$input` shapes (phone formats, every validation message, urgent words, honeypot, repeat window, digest, error text). The last test is the whole scenario in real n8n, about 2 minutes.
