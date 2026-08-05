# Roblox Spam Scanner

**Made By @Cgksifsyd**

A small Flask app that scans Roblox accounts for spam/bot patterns using
heuristics (username pattern, bio keywords, account age) plus an optional
AI (LLM) triage pass, and can post flagged accounts straight to a Discord
channel via webhook.

## Features

- **Seed Scan** — checks a hardcoded list of known usernames.
- **AI Search** — give it a topic/keyword, an LLM generates related search
  terms, then every matching Roblox account is checked.
- **Heuristic detection** — flags accounts based on:
  - Username matching the common bot pattern `Word_Word1234`
  - Bio containing phrases like "check my desc/profile/bio"
  - Account created less than 30 days ago
- **AI verdict on every account** — even accounts that pass the heuristics
  get an explicit "not a bot" verdict with a short reason from the LLM (when
  an API key is configured).
- **Discord webhook alerts** — flagged accounts are automatically posted to
  a Discord channel if you set up a webhook.
- **Live log + results panel** in the browser, no page reloads needed.

## Requirements

- Python 3.10+
- Dependencies: `flask`, `requests`, `gunicorn` (for production)

Install them with:

```bash
pip install flask requests gunicorn
```

## Running locally

```bash
python AntiBot.py
```

The app serves on `http://localhost:5000`.

For production, use a real WSGI server instead of Flask's dev server:

```bash
gunicorn --bind=0.0.0.0:5000 --reuse-port AntiBot:app
```

## Configuration

All configuration is done through environment variables (never hardcode
secrets in the source file).

| Variable | Required | Description |
| --- | --- | --- |
| `OPENCODE-API` | Optional but recommended | API key for the LLM used to generate AI search terms and triage accounts. Without it, AI search falls back to using your raw search topic, and per-account AI verdicts are skipped. |
| `OPENCODE_ZEN_MODEL` | Optional | Overrides the LLM model (default: `deepseek-v4-flash`). |
| `DISCORD_WEBHOOK_URL` | Optional | Default Discord webhook URL to post flagged accounts to. Can also be set/changed from the app's UI without restarting. |

### Getting an API key

This project talks to an OpenAI-compatible chat completions endpoint at
`https://opencode.ai/zen/v1/chat/completions`. Get an API key from your LLM
provider of choice that's compatible with this endpoint (or point
`LLM_URL` in `AntiBot.py` at any OpenAI-compatible API you have a key for),
then set it as the `OPENCODE-API` environment variable.

**On Replit:**
1. Open the **Secrets** tool (lock icon in the sidebar).
2. Add a new secret named `OPENCODE-API` with your key as the value.
3. Restart the app so it picks up the new secret.

**Elsewhere (local/self-hosted):**

```bash
export OPENCODE-API="your-key-here"
python AntiBot.py
```

(Note: some shells don't allow hyphens in exported variable names via
`export VAR-NAME=...` — if that's an issue for you, rename the variable in
`AntiBot.py` to something shell-friendly like `OPENCODE_API_KEY` and update
the `os.environ.get(...)` call accordingly.)

### Setting up the Discord webhook

1. In Discord, go to your server → the channel you want alerts in →
   **Edit Channel → Integrations → Webhooks → New Webhook**.
2. Copy the webhook URL.
3. Either:
   - Paste it into the **Discord Webhook** field in the app's sidebar and
     click **Save Webhook** (stored in memory only, no restart needed), or
   - Set it as the `DISCORD_WEBHOOK_URL` environment variable before
     starting the app.

Once configured, every account that gets flagged is automatically posted
to that channel as an embed with the username, profile link, and the
reasons it was flagged.

## Running without an API key

The app works fine with no LLM key configured — it just relies purely on
the heuristic checks (username pattern, bio keywords, account age) and
skips the AI search-term generation and per-account AI verdict step.

## Project structure

- `AntiBot.py` — the entire app: Flask server, scanning logic, and the
  frontend (inlined HTML/CSS/JS via `render_template_string`).

## Disclaimer

This tool only uses Roblox's public, unauthenticated APIs (`users.roblox.com`)
to look up and search for accounts. It does not take any action against
accounts (ban, report, etc.) — it only flags accounts for a human to review.
Respect Roblox's Terms of Service and API rate limits when using this tool.

## License

MIT License

Copyright (c) 2026 ruizmonseph-hash

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
