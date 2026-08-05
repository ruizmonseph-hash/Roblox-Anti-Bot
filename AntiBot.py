### THIS IS A @CGKSIFSYD PROJECT
import os
import re
import json
import time
import logging
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

# ----------------------------------------------------------------
# LOGGING
# ----------------------------------------------------------------
log_buffer = []
LOG_LOCK = threading.Lock()


class BufferHandler(logging.Handler):
    def emit(self, record):
        entry = self.format(record)
        with LOG_LOCK:
            log_buffer.append(entry)
            if len(log_buffer) > 500:
                log_buffer.pop(0)


_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

_buf = BufferHandler()
_buf.setFormatter(_fmt)
app.logger.addHandler(_buf)
app.logger.setLevel(logging.INFO)

_out = logging.StreamHandler()
_out.setFormatter(_fmt)
app.logger.addHandler(_out)


def add_log(msg, level="INFO"):
    getattr(app.logger, level.lower(), app.logger.info)(msg)


# ----------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------
SEED_USERNAMES = [
    "SunnyMisty202487", "Sugar_SandyCookie83", "Grace_PandaGamer2020",
    "Green_Meteor42", "TDRi_Wild2006",
]

NAME_PATTERN = re.compile(r"^[A-Za-z]+_[A-Za-z]+\d{2,4}$")
BIO_KEYWORDS = ["check my desc", "check my profile", "check my bio"]
BASE_DELAY = 2.0

USE_LLM = True
LLM_KEY = os.environ.get("OPENCODE-API", "")
LLM_URL = "https://opencode.ai/zen/v1"
LLM_MODEL = os.environ.get("OPENCODE_ZEN_MODEL", "deepseek-v4-flash")

HDR = {"Content-Type": "application/json"}

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


# ----------------------------------------------------------------
# ROBLOX API WITH BACKOFF
# ----------------------------------------------------------------
def rbx_req(method, url, retries=5, **kw):
    kw.setdefault("timeout", 15)
    for i in range(retries):
        try:
            r = requests.get(url, headers=HDR, **kw) if method == "GET" \
                else requests.post(url, headers=HDR, **kw)
            if r.status_code == 429:
                w = BASE_DELAY * (2 ** i)
                add_log(f"429 on {url.split('/')[-1]}, wait {w:.0f}s", "WARNING")
                time.sleep(w); continue
            r.raise_for_status(); return r
        except Exception as e:
            if i == retries - 1:
                add_log(f"Failed after {retries} tries: {e}", "ERROR"); return None
            time.sleep(BASE_DELAY * (2 ** i))
    return None


def resolve(names):
    add_log(f"Resolving {len(names)} seeds...")
    r = rbx_req("POST", "https://users.roblox.com/v1/usernames/users",
                json={"usernames": names, "excludeBannedUsers": False})
    return r.json().get("data", []) if r and r.status_code == 200 else []


def user_details(uid):
    r = rbx_req("GET", f"https://users.roblox.com/v1/users/{uid}")
    return r.json() if r and r.status_code == 200 else None


def search_users(keyword, limit=50):
    """Search Roblox users by keyword (public, no auth needed)."""
    add_log(f"Searching Roblox for '{keyword}'...")
    r = rbx_req("GET", "https://users.roblox.com/v1/users/search",
                params={"keyword": keyword, "limit": limit})
    if r and r.status_code == 200:
        data = r.json().get("data", [])
        add_log(f"  Found {len(data)} user(s) for '{keyword}'")
        return data
    return []


# ----------------------------------------------------------------
# AI SEARCH TERM GENERATOR
# ----------------------------------------------------------------
def ai_generate_search_terms(topic):
    """Ask the LLM to generate Roblox username search terms likely to find spam bots."""
    if not USE_LLM or not LLM_KEY:
        # Fallback: just use the topic itself
        return [topic]

    prompt = (
        "You are helping find Roblox spam/bot accounts. "
        "Spam bots often have usernames like 'Word_Word1234' and bios saying "
        "'check my description' or 'check my profile'.\n\n"
        f"The user wants to search for: {topic}\n\n"
        "Generate 5 short search keywords (1-2 words each) that would help "
        "find spam bot accounts on Roblox related to this topic. "
        "Focus on partial username patterns that bots commonly use.\n\n"
        "Respond with strict JSON only: "
        '{"keywords": ["term1", "term2", "term3", "term4", "term5"]}'
    )

    try:
        r = requests.post(f"{LLM_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.7, "max_tokens": 200}, timeout=20)
        r.raise_for_status()
        c = r.json()["choices"][0]["message"]["content"].strip()
        c = c.removeprefix("```json").removesuffix("```").strip()
        p = json.loads(c)
        keywords = p.get("keywords", [topic])
        add_log(f"🤖 AI generated search terms: {keywords}")
        return keywords
    except Exception as e:
        add_log(f"AI search term generation failed: {e}", "ERROR")
        return [topic]


# ----------------------------------------------------------------
# ANALYSIS
# ----------------------------------------------------------------
def age_days(iso):
    try:
        c = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - c).days
    except Exception:
        return None


def heuristic(d):
    if not d: return False, []
    f = []
    n = d.get("name", "")
    b = (d.get("description") or "").lower()
    if NAME_PATTERN.match(n): f.append("Name matches spam pattern")
    if any(k in b for k in BIO_KEYWORDS): f.append("Bio has 'check my desc/profile' text")
    a = age_days(d.get("created", ""))
    if a is not None and a < 30: f.append(f"Account only {a} days old")
    return bool(f), f


def llm_check(d):
    if not USE_LLM or not LLM_KEY: return None, ""
    prompt = ("Triage this Roblox account for spam. JSON only: "
              '{"is_spam":bool,"reason":"str"}\n\n'
              "If the account looks legitimate, set is_spam to false and give a short "
              "reason explaining why it looks like a real, non-bot account.\n\n"
              f"User: {d.get('name','')}\nBio: {d.get('description') or '(none)'}")
    try:
        r = requests.post(f"{LLM_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "max_tokens": 150}, timeout=20)
        r.raise_for_status()
        c = r.json()["choices"][0]["message"]["content"].strip()
        c = c.removeprefix("```json").removesuffix("```").strip()
        p = json.loads(c)
        is_spam = bool(p.get("is_spam"))
        reason = p.get("reason", "")
        if not is_spam and not reason:
            reason = "Not a bot — account looks legitimate."
        return is_spam, reason
    except Exception as e:
        add_log(f"LLM failed: {e}", "ERROR"); return None, str(e)


def send_discord_alert(entry):
    """Post a flagged-account alert to the configured Discord webhook."""
    if not DISCORD_WEBHOOK_URL:
        return
    embed = {
        "title": f"🚩 Flagged: @{entry['username']}",
        "url": entry["profile_url"],
        "color": 0xf85149,
        "description": "\n".join(f"• {f}" for f in entry["flags"]) or "No details",
        "fields": [{"name": "Profile", "value": entry["profile_url"], "inline": False}],
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
        if r.status_code >= 300:
            add_log(f"Discord webhook returned {r.status_code}: {r.text[:200]}", "WARNING")
        else:
            add_log(f"📨 Sent Discord alert for @{entry['username']}")
    except Exception as e:
        add_log(f"Discord webhook failed: {e}", "ERROR")


# ----------------------------------------------------------------
# SCAN WORKER
# ----------------------------------------------------------------
results = []
running = False


def check_candidate(uid, name, cands_checked):
    """Check a single candidate. Returns True if flagged."""
    if uid in cands_checked:
        return False
    cands_checked.add(uid)

    add_log(f"Checking @{name} ({uid})...")
    d = user_details(uid)
    time.sleep(BASE_DELAY)
    if not d:
        add_log(f"  ⚠ No details for @{name}", "WARNING")
        return False

    h_flag, flags = heuristic(d)
    if h_flag:
        add_log(f"  🚩 Heuristic: {', '.join(flags)}")

    l_spam, l_reason = llm_check(d)
    time.sleep(BASE_DELAY)

    if l_reason:
        flags.append(f"LLM: {l_reason}")
        if l_spam:
            add_log(f"  🤖 LLM: SPAM — {l_reason}")
        else:
            add_log(f"  🤖 LLM: not a bot — {l_reason}")
    elif l_spam is None and not h_flag:
        add_log(f"  🤖 not a bot")

    if h_flag or l_spam is True:
        entry = {"id": uid, "username": name,
                 "profile_url": f"https://www.roblox.com/users/{uid}",
                 "flags": flags}
        results.append(entry)
        add_log(f"  ✅ FLAGGED @{name} → https://www.roblox.com/users/{uid}")
        send_discord_alert(entry)
        return True

    return False


def scan_seeds():
    """Scan the hardcoded seed usernames."""
    global results, running
    running = True
    results = []
    add_log("=== Seed scan started ===")

    res = resolve(SEED_USERNAMES)
    cands = {e["id"]: e["name"] for e in res}
    add_log(f"Resolved {len(cands)} seed(s)")

    checked = set()
    for uid, name in cands.items():
        check_candidate(uid, name, checked)

    add_log(f"=== Seed scan done. {len(results)} flagged ===")
    running = False


def scan_search(topic):
    """Use AI to generate search terms, search Roblox, then scan each result."""
    global results, running
    running = True
    results = []
    add_log(f"=== AI Search started for '{topic}' ===")

    # Step 1: AI generates search keywords
    keywords = ai_generate_search_terms(topic)
    time.sleep(BASE_DELAY)

    # Step 2: Search Roblox for each keyword
    all_candidates = {}
    for kw in keywords:
        found = search_users(kw)
        for u in found:
            all_candidates[u["id"]] = u.get("name", u.get("displayName", "unknown"))
        time.sleep(BASE_DELAY)

    add_log(f"Total unique candidates from search: {len(all_candidates)}")

    # Step 3: Check each candidate
    checked = set()
    for uid, name in all_candidates.items():
        check_candidate(uid, name, checked)

    add_log(f"=== AI Search done. {len(results)} flagged ===")
    running = False


# ----------------------------------------------------------------
# TEMPLATE
# ----------------------------------------------------------------
HTML = """<!DOCTYPE html><html><head><title>Roblox Spam Scanner</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#0d1117;color:#c9d1d9;display:flex;height:100vh;overflow:hidden}
.sb{width:440px;min-width:320px;background:#161b22;border-right:1px solid #30363d;display:flex;flex-direction:column;padding:1rem;overflow-y:auto}
.mn{flex:1;display:flex;flex-direction:column;padding:1rem;overflow:hidden}
h1{font-size:1.1rem;margin-bottom:.75rem;color:#58a6ff}
h2{font-size:.95rem;margin-bottom:.5rem;color:#58a6ff;margin-top:1rem}
button{padding:10px 20px;font-size:14px;cursor:pointer;background:#238636;border:none;color:#fff;border-radius:6px;margin-bottom:.5rem;width:100%}
button:disabled{opacity:.4;cursor:not-allowed}
button.search-btn{background:#1f6feb}
input[type=text]{width:100%;padding:10px;font-size:14px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:6px;margin-bottom:.5rem;font-family:inherit}
input[type=text]:focus{outline:none;border-color:#58a6ff}
.card{background:#1c2333;padding:.75rem;border-radius:6px;margin-bottom:.5rem;border-left:3px solid #f85149;font-size:.85rem}
.card a{color:#58a6ff;text-decoration:none;word-break:break-all;font-size:.9rem}
.fl{color:#d29922;margin-top:4px;font-size:.8rem;line-height:1.4}
.empty{color:#484f58;font-style:italic;padding:1rem 0}
.lp{flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow-y:auto;padding:.75rem;font-size:.78rem;line-height:1.7}
.ll{white-space:pre-wrap;word-break:break-all;margin-bottom:2px}
.lW{color:#d29922}.lE{color:#f85149}.lI{color:#8b949e}
.bg{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.7rem;margin-left:6px;vertical-align:middle}
.bgR{background:#1f6feb;color:#fff}.bgI{background:#30363d;color:#8b949e}
.divider{border:none;border-top:1px solid #30363d;margin:.75rem 0}
</style></head><body>
<div class="sb">
<h1>🚩 Flagged <span id="bg" class="bg bgI">IDLE</span></h1>
<div style="color:#8b949e;font-size:.75rem;margin-bottom:.5rem">Made By @Cgksifsyd</div>

<h2>🔍 AI Search</h2>
<input type="text" id="searchInput" placeholder="e.g. free robux, check my bio, spam wave..." />
<button class="search-btn" id="searchBtn" onclick="goSearch()"> AI Search & Scan</button>

<hr class="divider">

<h2>📋 Seed Scan</h2>
<button id="btn" onclick="goSeeds()">▶ Scan Seed Usernames</button>

<hr class="divider">

<h2>🔔 Discord Webhook</h2>
<input type="text" id="webhookInput" placeholder="https://discord.com/api/webhooks/..." />
<button id="webhookBtn" onclick="saveWebhook()">Save Webhook</button>
<div id="webhookStatus" class="fl"></div>

<div id="res"><div class="empty">No results yet.</div></div>
</div>
<div class="mn">
<h1>📋 Live Log</h1>
<div class="lp" id="lp"><div class="ll lI">Ready. Use AI Search or Seed Scan to start.</div></div>
</div>
<div style="position:fixed;bottom:8px;right:12px;color:#484f58;font-size:.7rem">Made By @Cgksifsyd</div>
<script>
let pt=null;
function rr(r){const e=document.getElementById('res');if(!r.length){e.innerHTML='<div class="empty">'+(document.getElementById('bg').textContent==='RUNNING'?'Scanning...':'No flagged accounts.')+'</div>';return;}e.innerHTML=r.map(a=>'<div class="card"><strong>@'+a.username+'</strong> <small>('+a.id+')</small><br><a href="'+a.profile_url+'" target="_blank">roblox.com/users/'+a.id+'</a><div class="fl">'+a.flags.map(f=>'• '+f).join('<br>')+'</div></div>').join('');}
function rl(l){const e=document.getElementById('lp');if(!l.length)return;e.innerHTML=l.map(x=>'<div class="ll '+(x.level==='WARNING'?'lW':x.level==='ERROR'?'lE':'lI')+'">'+x.text+'</div>').join('');e.scrollTop=e.scrollHeight;}
function disableAll(v){document.getElementById('btn').disabled=v;document.getElementById('searchBtn').disabled=v;}
async function saveWebhook(){const u=document.getElementById('webhookInput').value.trim();const s=document.getElementById('webhookStatus');if(!u){alert('Paste a Discord webhook URL first.');return;}const r=await fetch('/api/config/webhook',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:u})});const d=await r.json();s.textContent=d.success?'✅ Webhook saved. Flagged accounts will be posted there.':'❌ '+(d.error||'Failed to save');}
async function loadWebhookStatus(){try{const d=await(await fetch('/api/config/webhook')).json();const s=document.getElementById('webhookStatus');if(d.configured){s.textContent='✅ Webhook configured';document.getElementById('webhookInput').placeholder='Webhook is set (hidden)';}}catch(e){}}
async function goSeeds(){disableAll(true);const b=document.getElementById('bg');b.textContent='RUNNING';b.className='bg bgR';document.getElementById('res').innerHTML='<div class="empty">Scanning seeds...</div>';await fetch('/api/scan/seeds',{method:'POST'});pt=setInterval(poll,1000);}
async function goSearch(){const q=document.getElementById('searchInput').value.trim();if(!q){alert('Enter a search topic first.');return;}disableAll(true);const b=document.getElementById('bg');b.textContent='RUNNING';b.className='bg bgR';document.getElementById('res').innerHTML='<div class="empty">AI searching...</div>';await fetch('/api/scan/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:q})});pt=setInterval(poll,1000);}
async function poll(){try{const d=await(await fetch('/api/status')).json();rl(d.logs||[]);rr(d.results||[]);if(!d.running){clearInterval(pt);pt=null;disableAll(false);document.getElementById('bg').textContent='DONE';document.getElementById('bg').className='bg bgI';}}catch(e){console.error(e);}}
fetch('/api/status').then(r=>r.json()).then(d=>{rl(d.logs||[]);rr(d.results||[]);}).catch(()=>{});
loadWebhookStatus();
</script></body></html>"""


# ----------------------------------------------------------------
# ROUTES
# ----------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/scan/seeds", methods=["POST"])
def api_seeds():
    global running
    if running:
        return jsonify({"error": "Already running"}), 409
    threading.Thread(target=scan_seeds, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/scan/search", methods=["POST"])
def api_search():
    global running
    if running:
        return jsonify({"error": "Already running"}), 409
    data = request.get_json(force=True)
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "No topic provided"}), 400
    threading.Thread(target=scan_search, args=(topic,), daemon=True).start()
    return jsonify({"status": "started", "topic": topic})


@app.route("/api/config/webhook", methods=["GET", "POST"])
def api_webhook_config():
    global DISCORD_WEBHOOK_URL
    if request.method == "POST":
        data = request.get_json(force=True)
        url = (data.get("url") or "").strip()
        if not url.startswith("https://discord.com/api/webhooks/") and \
           not url.startswith("https://discordapp.com/api/webhooks/"):
            return jsonify({"error": "That doesn't look like a Discord webhook URL"}), 400
        DISCORD_WEBHOOK_URL = url
        add_log("🔔 Discord webhook configured")
        return jsonify({"success": True})
    return jsonify({"configured": bool(DISCORD_WEBHOOK_URL)})


@app.route("/api/status")
def status():
    with LOG_LOCK:
        logs = [{"text": l.split("] ", 1)[-1] if "] " in l else l,
                 "level": "WARNING" if "[WARNING]" in l else "ERROR" if "[ERROR]" in l else "INFO"}
                for l in log_buffer]
    return jsonify({"running": running, "results": results, "logs": logs})


# ----------------------------------------------------------------
# LOCAL RUN
# ----------------------------------------------------------------
if __name__ == "__main__":
    print("Starting scanner on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
