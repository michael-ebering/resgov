#!/usr/bin/env python3
"""Import RGF leads from lead_collector DB into Listmonk + create drip campaign drafts.

Uses subprocess curl for API calls (avoids cookie parsing issues).
"""
import json, subprocess, sys, os, tempfile

LISTMONK_URL = "http://127.0.0.1:9000"
LISTMONK_USER = "listmonk"
LISTMONK_PASS = "hermes1234"
COOKIE_FILE = "/tmp/lmk-session"

def get_session():
    """Login and store session cookie."""
    os.system(f"rm -f {COOKIE_FILE}")
    result = subprocess.run(
        ["curl", "-s", "-c", COOKIE_FILE, f"{LISTMONK_URL}/admin/login"],
        capture_output=True, text=True
    )
    nonce = ""
    for line in result.stdout.split("\n"):
        if 'name="nonce" value="' in line:
            nonce = line.split('name="nonce" value="')[1].split('"')[0]
            break
    if not nonce:
        print("ERROR: Could not extract nonce from login page")
        return False

    subprocess.run([
        "curl", "-s", "-L", "-c", COOKIE_FILE, "-b", COOKIE_FILE,
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-d", f"nonce={nonce}&next=/admin&username={LISTMONK_USER}&password={LISTMONK_PASS}",
        f"{LISTMONK_URL}/admin/login"
    ], capture_output=True)

    # Verify session works
    check = subprocess.run(
        ["curl", "-s", "-b", COOKIE_FILE, "-o", "/dev/null", "-w", "%{http_code}",
         f"{LISTMONK_URL}/api/lists"],
        capture_output=True, text=True
    )
    if check.stdout.strip() == "200":
        print("Session OK")
        return True
    else:
        print(f"Session FAILED (HTTP {check.stdout.strip()})")
        return False

def api(method, path, data=None):
    """Make API call via curl with session cookie. Returns parsed JSON or None."""
    url = f"{LISTMONK_URL}/api/{path.lstrip('/')}"

    body_file = None
    if data:
        # Write JSON body to temp file to avoid shell escaping issues
        body_str = json.dumps(data)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(body_str)
            body_file = f.name

        cmd = ["curl", "-s", "-b", COOKIE_FILE,
               "-H", "Content-Type: application/json",
               "-X", method,
               "-d", f"@{body_file}",
               url]
    else:
        cmd = ["curl", "-s", "-b", COOKIE_FILE,
               "-H", "Content-Type: application/json",
               "-X", method,
               url]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if body_file:
        os.unlink(body_file)

    if not result.stdout.strip():
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  JSON parse error: {result.stdout[:200]}")
        return None

def get_leads():
    """Get leads from lead_collector container."""
    result = subprocess.run(
        ["docker", "exec", "leadcollector", "python3", "-c",
         "import sqlite3,json; conn=sqlite3.connect('/data/leads.db'); "
         "rows=conn.execute('SELECT email, created_at FROM leads ORDER BY id').fetchall(); "
         "print(json.dumps([{'email':r[0],'created_at':r[1]} for r in rows])); conn.close()"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR getting leads: {result.stderr}")
        return []
    return json.loads(result.stdout.strip())

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "all"

    print("=== AUTHENTICATING ===")
    if not get_session():
        print("FATAL: Cannot authenticate")
        return

    if action in ("import", "all"):
        print("\n=== IMPORTING LEADS ===")
        leads = get_leads()
        print(f"Found {len(leads)} leads in collector DB")

        # Find or create RGF Waitlist
        lists_resp = api("GET", "/lists")
        list_id = None
        if lists_resp and "data" in lists_resp:
            for l in lists_resp["data"]["results"]:
                if l["name"] == "RGF Waitlist":
                    list_id = l["id"]
                    print(f"Found 'RGF Waitlist' (id={list_id})")
                    break

        if not list_id:
            result = api("POST", "/lists", {
                "name": "RGF Waitlist", "type": "public", "tags": ["rfg", "waitlist"]
            })
            if result and "data" in result:
                list_id = result["data"]["id"]
                print(f"Created 'RGF Waitlist' (id={list_id})")

        if list_id and leads:
            imported = skipped = 0
            for lead in leads:
                email = lead["email"]
                r = api("POST", "/subscribers", {
                    "email": email,
                    "name": email.split("@")[0],
                    "status": "enabled",
                    "lists": [list_id],
                    "attribs": {"source": "rfg-landing-page"}
                })
                if r and "data" in r:
                    imported += 1
                    print(f"  + {email}")
                elif r and "message" in r and "duplicate" in r.get("message", "").lower():
                    skipped += 1
                    print(f"  SKIP (duplicate): {email}")
                else:
                    print(f"  FAILED: {email} -> {r}")
            print(f"\nImported: {imported}, Skipped (dupes): {skipped}")

    if action in ("campaigns", "all"):
        print("\n=== CREATING DRIP CAMPAIGNS ===")

        # Find list ID
        lists_resp = api("GET", "/lists")
        list_id = None
        if lists_resp and "data" in lists_resp:
            for l in lists_resp["data"]["results"]:
                if l["name"] == "RGF Waitlist":
                    list_id = l["id"]
        if not list_id:
            list_id = 3  # Aronia fallback
            print(f"Using fallback list id={list_id}")

        list_ids = [list_id]

        campaigns = [
            {
                "name": "RGF-01-Welcome",
                "subject": "RGF -- your early access is confirmed",
                "body": """<html><body style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;color:#e0e0e0;background:#0a0a1a">
<div style="text-align:center;margin-bottom:30px"><h1 style="color:#fff;font-size:24px;margin:0">Welcome, Builder.</h1><p style="color:#a1a1aa;font-size:14px;margin-top:8px">You joined the RGF early access list. Here is what is next.</p></div>
<div style="background:#12122a;border:1px solid #2a2a4a;border-radius:12px;padding:24px;margin:20px 0">
<p style="font-size:15px;line-height:1.7;color:#e0e0e0"><strong style="color:#F97316">RGF (Resource Governance Framework)</strong> is the open-source governance layer for multi-agent AI systems. You can self-host it right now -- no credit card, no strings attached.</p>
<h3 style="color:#F97316;margin-top:24px;font-size:13px;letter-spacing:1.5px">Get started in 30 seconds</h3>
<pre style="background:#0a0a1a;border:1px solid #2a2a4a;border-radius:8px;padding:16px;font-size:13px;color:#4ADE80;overflow-x:auto">git clone https://github.com/michael-ebering/resgov.git
cd resgov &amp;&amp; docker compose up</pre>
<p style="font-size:13px;color:#a1a1aa;margin-top:12px"><a href="https://api.resgov.silentops.cloud/docs" style="color:#B99BFF;text-decoration:none">API Docs</a> &middot; <a href="https://github.com/michael-ebering/resgov" style="color:#B99BFF;text-decoration:none">GitHub</a></p>
</div>
<div style="text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #2a2a4a"><p style="font-size:12px;color:#717171">RGF v0.4.0 &middot; Resource Governance Framework &middot; <a href="https://silentops.cloud" style="color:#717171">SilentOps</a></p></div>
</body></html>"""
            },
            {
                "name": "RGF-02-SelfHost",
                "subject": "Self-hosted RGF: what builders are doing",
                "body": """<html><body style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;color:#e0e0e0;background:#0a0a1a">
<h1 style="color:#fff;font-size:22px">How builders are running RGF today</h1>
<p style="color:#a1a1aa;font-size:14px;line-height:1.7;margin-top:8px">You signed up for RGF. Here is what early adopters are doing:</p>
<div style="background:#12122a;border:1px solid #2a2a4a;border-radius:12px;padding:24px;margin:20px 0">
<ul style="font-size:14px;line-height:2.2;color:#e0e0e0;padding-left:20px;margin:0">
<li><strong style="color:#F97316">Budget Prediction</strong> &mdash; AI agents that forecast costs and stop before limits</li>
<li><strong style="color:#F97316">Governance as Code</strong> &mdash; Resource rules in <code style="background:#0a0a1a;padding:2px 6px;border-radius:4px;color:#4ADE80">.rgf</code> files, version-controlled</li>
<li><strong style="color:#F97316">Multi-Agent Isolation</strong> &mdash; Tenant-scoped resource quotas per team</li>
<li><strong style="color:#F97316">Crash Recovery</strong> &mdash; State recovered after restarts, windows preserved</li>
</ul></div>
<p style="font-size:13px;line-height:1.7;color:#a1a1aa">Already running RGF? Hit reply and tell me what you are building. I read and reply to every message.</p>
<div style="text-align:center;margin:30px 0"><a href="https://github.com/michael-ebering/resgov" style="display:inline-block;background:#F97316;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-size:14px;font-weight:600">Star on GitHub</a></div>
<div style="text-align:center;padding-top:20px;border-top:1px solid #2a2a4a"><p style="font-size:12px;color:#717171">RGF v0.4.0 &middot; Resource Governance Framework &middot; <a href="https://silentops.cloud" style="color:#717171">SilentOps</a></p></div>
</body></html>"""
            },
            {
                "name": "RGF-03-CloudLaunch",
                "subject": "Managed RGF Cloud: early access now open",
                "body": """<html><body style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;color:#e0e0e0;background:#0a0a1a">
<h1 style="color:#fff;font-size:22px">RGF Managed Cloud &rarr; early access</h1>
<p style="color:#a1a1aa;font-size:14px;line-height:1.7;margin-top:8px">You asked for managed cloud access to RGF. We are now onboarding the first builders.</p>
<div style="background:#12122a;border:1px solid #2a2a4a;border-radius:12px;padding:24px;margin:20px 0;text-align:center">
<p style="font-size:16px;color:#fff;margin:0 0 8px;font-weight:600">What you get:</p>
<p style="font-size:13px;color:#a1a1aa;line-height:2;margin:0">Zero-config hosting &middot; Built-in monitoring<br>Auto-scaling budgets &middot; Webhook integrations<br>Priority support &middot; BSL 1.1 licensed core</p>
<div style="margin-top:24px"><a href="mailto:michael@silentops.cloud?subject=RGF Cloud Early Access" style="display:inline-block;background:#F97316;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-size:14px;font-weight:600">Request your invite</a></div>
<p style="font-size:11px;color:#52525b;margin-top:12px">Limited to the first 50 builders. No credit card required.</p>
</div>
<p style="font-size:13px;color:#a1a1aa;text-align:center">If you just want to self-host, <a href="https://github.com/michael-ebering/resgov" style="color:#B99BFF">RGF remains free and open source</a>.</p>
<div style="text-align:center;padding-top:20px;border-top:1px solid #2a2a4a"><p style="font-size:12px;color:#717171">RGF v0.4.0 &middot; Resource Governance Framework &middot; <a href="https://silentops.cloud" style="color:#717171">SilentOps</a></p></div>
</body></html>"""
            },
        ]

        for camp in campaigns:
            r = api("POST", "/campaigns", {
                "name": camp["name"],
                "subject": camp["subject"],
                "body": camp["body"],
                "lists": list_ids,
                "type": "regular",
                "content_type": "html",
                "tags": ["rfg", "waitlist", "drip"]
            })
            if r and "data" in r:
                print(f"  CREATED: {camp['name']} (id={r['data']['id']})")
            else:
                print(f"  FAILED: {camp['name']} -> {r}")

    if action == "status":
        print("\n=== SUBSCRIBERS ===")
        subs = api("GET", "/subscribers?per_page=50")
        if subs and "data" in subs:
            for s in subs["data"]["results"]:
                print(f"  {s['id']:>3} | {s['email']:<35} | {s['status']}")
        print("\n=== CAMPAIGNS ===")
        camps = api("GET", "/campaigns")
        if camps and "data" in camps:
            for c in camps["data"]["results"]:
                print(f"  {c['id']:>3} | {c['name']:<30} | {c['status']}")

    print("\nDone.")

if __name__ == "__main__":
    main()
