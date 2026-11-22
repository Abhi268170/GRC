"""End-to-end smoke test of a running stack, through the public API only (standard library only).

It signs in as the super admin, creates and publishes one control and one assessment, signs up
two companies, takes one of them through a whole run (intake, evidence, guided chat with
streaming, ratings, results, approval, reports) and checks that the other company can't see any
of it. It makes real AI calls (a few cents) and leaves its test data behind, so point it at a
throwaway stack, not at one with real data:

    docker compose -p grcverify --env-file .env.verify -f docker-compose.yml up -d --build backend worker ai-service
    BASE_URL=http://localhost:18000 SUPER_ADMIN_EMAIL=... SUPER_ADMIN_PASSWORD=... python3 scripts/e2e_smoke.py
    docker compose -p grcverify --env-file .env.verify -f docker-compose.yml down -v
"""
import json, os, sys, time, urllib.error, urllib.request, uuid

BASE = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
STAMP = uuid.uuid4().hex[:6]


class Client:
    """Keeps the session token from the login cookie and sends it as a bearer token, so the
    test also works over plain HTTP against a stack that sets Secure cookies."""

    def __init__(self, name):
        self.name, self.token = name, None

    def _request(self, method, path, body=None, files=None):
        headers, data = {}, None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if files:
            boundary = uuid.uuid4().hex
            fname, content, ctype = files
            data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\n"
                    f"Content-Type: {ctype}\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        return urllib.request.Request(BASE + path, data=data, method=method, headers=headers)

    def _remember(self, headers):
        for value in headers.get_all("Set-Cookie") or []:
            if value.startswith("grc_session="):
                self.token = value.split(";", 1)[0].split("=", 1)[1] or None

    def call(self, method, path, body=None, expect=None, raw=False, files=None):
        try:
            with urllib.request.urlopen(self._request(method, path, body, files), timeout=300) as r:
                code, payload = r.status, r.read()
                self._remember(r.headers)
        except urllib.error.HTTPError as e:
            code, payload = e.code, e.read()
        if expect is not None and code != expect:
            raise SystemExit(f"FAIL [{self.name}] {method} {path}: got {code}, expected {expect}: {payload[:400]!r}")
        if raw:
            return code, payload
        return code, (json.loads(payload) if payload else None)

    def stream(self, path, body):
        """POST and read Server-Sent Events; returns the list of event types."""
        types = []
        with urllib.request.urlopen(self._request("POST", path, body), timeout=300) as r:
            for line in r:
                line = line.decode().strip()
                if line.startswith("data: "):
                    types.append(json.loads(line[6:])["type"])
        return types


def ok(msg):
    print("ok  ", msg, flush=True)


def wait(fn, what, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(2)
    raise SystemExit(f"FAIL timed out waiting for {what}")


admin = Client("super admin")
admin.call("POST", "/auth/login", {"email": os.environ["SUPER_ADMIN_EMAIL"], "password": os.environ["SUPER_ADMIN_PASSWORD"]}, 200)
_, me = admin.call("GET", "/auth/me", expect=200)
assert me["tenant"] is None and me["user"]["platform_role"] == "super_admin"
ok("super admin signs in on the control database")
admin.call("GET", "/runs", expect=403)
ok("super admin can't call company endpoints (403)")

# ---- library content for the test
_, domains = admin.call("GET", "/library/domains", expect=200)
domain = domains[0]
_, areas = admin.call("GET", "/master-data?category=area", expect=200)
_, roles = admin.call("GET", "/master-data/organisational-roles", expect=200)
_, ctypes = admin.call("GET", "/master-data?category=control_type", expect=200)
multi = {}
for cat, field in (("protection_domain", "protection_domains"), ("security_capability", "security_capabilities"),
                   ("protection_objective", "protection_objectives"), ("use_case", "use_cases")):
    multi[field] = [admin.call("GET", f"/master-data?category={cat}", expect=200)[1][0]["id"]]
_, clauses = admin.call("GET", "/frameworks/clauses/search?q=access", expect=200)
clause_ids = [c["id"] for c in clauses[:2]] if clauses else []
_, control = admin.call("POST", "/library/controls", {
    "domain_id": domain["id"], "title": f"E2E access review {STAMP}", "area_id": areas[0]["id"],
    "responsible_role_id": roles[0]["id"], "control_types": [ctypes[0]["id"]], **multi,
    "company_risk_exposure_id": admin.call("GET", "/master-data?category=company_risk_exposure", expect=200)[1][0]["id"],
    "short_description": "Keeps access current.", "key_requirement": "Access is reviewed regularly.", "risk_exposure": "Stale access.",
    "requirements": [
        {"statement": "User access rights are reviewed at least every six months.", "guidance": "Keep a record of each review.",
         "evidence": ["Access review record"], "clause_ids": clause_ids,
         "action_templates": [{"title": "Schedule access reviews", "description": "Set a six-monthly access review."}],
         "risk_templates": [{"title": "Excess access", "description": "Leavers keep access."}]},
        {"statement": "Privileged accounts are approved by a manager.", "guidance": "Approval is documented."},
    ]}, 201)
control_id = control["id"]
admin.call("POST", f"/library/controls/{control_id}/publish", expect=200)
_, av = admin.call("POST", "/assessments", {"title": f"E2E assessment {STAMP}", "description": "test", "control_ids": [control_id]}, 201)
version_id = av["id"]
assessment_id = av["assessment_id"] if "assessment_id" in av else None
avd_id = av["domains"][0]["id"]
req_ids = [r["id"] for r in av["domains"][0]["requirements"]] if "requirements" in av["domains"][0] else None
if req_ids is None:
    req_ids = [r["id"] for c in av["domains"][0]["controls"] for r in c["requirements"]]
av = wait(lambda: (lambda d: d if d["generation_status"] in ("done", "failed", "none") else None)(admin.call("GET", f"/assessments/versions/{version_id}", expect=200)[1]), "question generation")
print("    question generation:", av["generation_status"], "uncovered:", len(av["coverage"]["uncovered"]))
if av["coverage"]["uncovered"]:
    _, av = admin.call("POST", f"/assessments/versions/{version_id}/questions", {"assessment_version_domain_id": avd_id, "text": "How do you review user access?"}, 201)
    q = [q for d in av["domains"] for q in d["questions"]][-1]
    admin.call("PUT", f"/assessments/questions/{q['id']}/requirements", {"requirement_version_ids": req_ids}, 200)
admin.call("POST", f"/assessments/versions/{version_id}/publish", expect=200)
ok("control and assessment created and published (control database)")

# ---- two companies
def signup(label):
    c = Client(label)
    email = f"e2e-{label.lower()}-{STAMP}@example.com"
    t0 = time.time()
    _, me = c.call("POST", "/auth/signup", {"company_name": f"E2E {label} {STAMP}", "industry": "Software / SaaS", "employee_count": "11-50",
                                           "full_name": f"{label} Admin", "email": email, "password": "correct-horse-battery"}, 201)
    ok(f"company {label} signed up in {time.time() - t0:.1f}s, tenant {me['tenant']['id']}")
    c.email, c.tenant_id, c.user_id = email, me["tenant"]["id"], me["user"]["id"]
    return c

a, b = signup("A"), signup("B")
Client("dup").call("POST", "/auth/signup", {"company_name": "Dup", "industry": "Software / SaaS", "employee_count": "11-50",
                                            "full_name": "Dup Admin", "email": a.email, "password": "correct-horse-battery"}, 409)
ok("signing up with an email that is already used is refused (409)")
a2 = Client("A again")
a2.call("POST", "/auth/login", {"email": a.email, "password": "wrong-password-here"}, 401)
_, me = a2.call("POST", "/auth/login", {"email": a.email.upper(), "password": "correct-horse-battery"}, 200)
assert me["tenant"]["id"] == a.tenant_id
ok("login finds the right company database through the directory")
a.call("GET", "/assessments", expect=403)

# ---- run in company A
_, catalog = a.call("GET", "/assessments/catalog/published", expect=200)
assert any(c["version_id"] == version_id for c in catalog)
_, run = a.call("POST", "/runs", {"assessment_version_id": version_id}, 201)
run_id = run["id"]
ok("company A started a run (assessment copied into its database)")
detail = wait(lambda: (lambda d: d if d["intake_job"] in ("done", "failed") else None)(a.call("GET", f"/runs/{run_id}", expect=200)[1]), "intake job")
ok(f"intake job finished in the worker: {detail['intake_job']}, run status {detail['status']}, intake {str(detail['intake'])[:80]}")
if detail["status"] == "intake":
    _, detail = a.call("POST", f"/runs/{run_id}/intake/skip", expect=200)
rd_id = detail["domains"][0]["id"]
_, ws = a.call("GET", f"/runs/{run_id}/domains/{rd_id}", expect=200)
_, ev = a.call("POST", f"/runs/{run_id}/evidence", files=("access-review.txt", b"Access review 2026-10: 42 accounts reviewed, 3 removed. Signed by IT manager.", "text/plain"), expect=201)
ev = wait(lambda: next((e for e in a.call("GET", f"/runs/{run_id}/domains/{rd_id}", expect=200)[1]["evidence"] if e["id"] == ev["id"] and e["processing_status"] in ("ready", "done", "failed")), None), "evidence processing")
ok(f"evidence processed by the worker: {ev['processing_status']}")
code, blob = a.call("GET", f"/runs/{run_id}/evidence/{ev['id']}/file", raw=True)
assert code == 200 and b"42 accounts" in blob
code, ws2 = a.call("POST", f"/runs/{run_id}/domains/{rd_id}/messages", {"content": "We review all user access every six months and keep a signed record; managers approve admin accounts by ticket.", "evidence_ids": [ev["id"]]})
ok(f"guided chat turn: HTTP {code}")
for rid in req_ids:
    a.call("PUT", f"/runs/{run_id}/requirements/{rid}", {"answer": "Reviewed twice a year, recorded.", "rating": 3}, 200)
time.sleep(1)
def complete():
    code, d = a.call("POST", f"/runs/{run_id}/domains/{rd_id}/complete")
    if code == 200:
        return d
    # cross-analysis may still be suggesting ratings: confirm them
    _, w = a.call("GET", f"/runs/{run_id}/domains/{rd_id}", expect=200)
    for rid in req_ids:
        a.call("PUT", f"/runs/{run_id}/requirements/{rid}", {"answer": "Reviewed twice a year, recorded.", "rating": 3})
    return None
wait(complete, "domain completion", 120)
a.call("POST", f"/runs/{run_id}/submit", expect=200)
detail = wait(lambda: (lambda d: d if d["outputs_job_status"] in ("done", "failed") else None)(a.call("GET", f"/runs/{run_id}", expect=200)[1]), "outputs job", 420)
assert detail["outputs_job_status"] == "done", detail["outputs_job_error"]
ok(f"results generated by the worker; run status {detail['status']}, score {detail['score']}")
a.call("POST", f"/runs/{run_id}/approve", expect=200)
_, res = a.call("GET", f"/runs/{run_id}/results", expect=200)
ok(f"results: {len(res.get('actions', res.get('action_items', [])))} action(s), {len(res.get('risks', []))} risk(s)")
for fmt in ("pdf", "docx"):
    code, blob = a.call("GET", f"/runs/{run_id}/report.{fmt}", raw=True)
    print("    report", fmt, code, len(blob))
_, notes = a.call("GET", "/notifications", expect=200)
ok(f"company A notifications: {[n['type'] for n in notes]}")
_, acts = a.call("GET", "/action-items", expect=200)
_, risks = a.call("GET", "/risks", expect=200)
ok(f"registers: {len(acts)} action item(s), {len(risks)} risk(s)")

# ---- isolation
_, runs_b = b.call("GET", "/runs", expect=200)
assert runs_b == []
b.call("GET", f"/runs/{run_id}", expect=404)
b.call("GET", f"/runs/{run_id}/domains/{rd_id}", expect=404)
b.call("GET", f"/runs/{run_id}/evidence/{ev['id']}/file", expect=404)
b.call("GET", f"/runs/{run_id}/results", expect=404)
assert b.call("GET", "/action-items", expect=200)[1] == [] and b.call("GET", "/risks", expect=200)[1] == []
_, users_b = b.call("GET", "/users", expect=200)
assert [u["id"] for u in users_b] == [b.user_id]
ok("company B sees none of company A's runs, evidence, results, registers or users (404 / empty)")
_, run_b = b.call("POST", "/runs", {"assessment_version_id": version_id}, 201)
ok("company B started its own run")

# ---- users
_, created = a.call("POST", "/users", {"email": f"e2e-user-{STAMP}@example.com", "full_name": "Member One", "organisational_role_id": roles[1]["id"]}, 201)
b.call("POST", "/users", {"email": f"e2e-user-{STAMP}@example.com", "full_name": "Clash"}, 409)
m = Client("A member")
_, me = m.call("POST", "/auth/login", {"email": f"e2e-user-{STAMP}@example.com", "password": created["temporary_password"]}, 200)
assert me["tenant"]["id"] == a.tenant_id and me["user"]["must_change_password"]
m.call("GET", "/runs", expect=403)
m.call("POST", "/auth/change-password", {"current_password": created["temporary_password"], "new_password": "another-long-password"}, 204)
assert len(m.call("GET", "/runs", expect=200)[1]) == 1
ok("new user: email unique across companies, temporary password, signs in to company A")

# ---- cross-company: run counts, deprecation, master data
_, assessments = admin.call("GET", "/assessments", expect=200)
mine = next(x for x in assessments if x["published"] and x["published"]["id"] == version_id)
assert mine["run_count"] == 2, mine["run_count"]
ok("super admin sees run count 2 across both company databases")
_, draft = admin.call("POST", f"/assessments/{mine['id']}/draft", expect=201)
admin.call("POST", f"/assessments/versions/{draft['id']}/publish", expect=200)
def deprecated():
    _, d = a.call("GET", f"/runs/{run_id}", expect=200)
    _, n = a.call("GET", "/notifications", expect=200)
    return d["version_deprecated"] and any(x["type"] == "assessment_deprecated" for x in n)
wait(deprecated, "deprecation fan-out", 60)
assert wait(lambda: b.call("GET", f"/runs/{run_b['id']}", expect=200)[1]["version_deprecated"], "deprecation in B", 30)
ok("publishing version 2 marked both companies' copies as deprecated and notified them")
_, run_a2 = a.call("POST", "/runs", {"assessment_version_id": draft["id"]}, 201)
assert run_a2["version"] == 2 and not run_a2["version_deprecated"]
ok("company A started a run on version 2 (second copy alongside the first)")
detail2 = wait(lambda: (lambda d: d if d["intake_job"] in ("done", "failed") else None)(a.call("GET", f"/runs/{run_a2['id']}", expect=200)[1]), "intake job of the second run")
if detail2["status"] == "intake":
    _, detail2 = a.call("POST", f"/runs/{run_a2['id']}/intake/skip", expect=200)
rd2 = detail2["domains"][0]["id"]
a.call("GET", f"/runs/{run_a2['id']}/domains/{rd2}", expect=200)
events = a.stream(f"/runs/{run_a2['id']}/domains/{rd2}/messages/stream", {"content": "We review access twice a year and record it."})
assert events and events[-1] == "done" and "text" in events, events
ok(f"streaming chat turn: {len(events)} events, ended with done")
print("ALL PASSED")
