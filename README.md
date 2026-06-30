# Digest

A FastAPI app that connects Linear and Slack via OAuth 2.0. Hit one endpoint and it pulls open issues from a Linear team, builds an unassigned + assignment summary digest, and posts it to a Slack channel.

---

## What it does

- Authenticates with Linear and Slack using OAuth 2.0 + PKCE — no hardcoded tokens
- Exposes `POST /api/workflows/linear-slack-digest` which reads from Linear and writes to Slack
- Lets you configure everything through a web UI — no redeployment needed to connect a new workspace

---

## Tech stack

| Area | Choice |
|---|---|
| Framework | FastAPI (Python 3.14)|
| Database | SQLite|
| Encryption | Fernet (cryptography)|
| HTTP client | httpx |
| UI | Jinja2 + plain CSS |
| Container | Docker|

---

## Quick start (local)

**Prerequisites:** Docker and Docker Compose installed.

```bash
# 1. Clone the repo
git clone https://github.com/patelanuj21/digest
cd digest

# 2. Create your .env file
cp .env.example .env

# 3. Generate a Fernet key and add it to .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste the output as APP_SECRET_KEY in .env

# 4. Start the app
docker compose up --build

# To run in the background, add -d
docker compose up --build -d

# 5. Open http://localhost:8000
```

The SQLite database is stored at `./data/app.db` on your machine. Delete it to reset all state.

---

## Setting up integrations

The app uses a bring-your-own-credentials model. You create OAuth apps in Linear and Slack, paste the credentials into the app's Settings page, and the app generates the exact redirect URLs you need to register. No static config, no redeployment.

### Step 1 — Set your Base URL in Settings

Open **Settings** (`http://localhost:8000/settings`) and set your Base URL:

- Local: `http://localhost:8000`
- Custom domain: `https://your-domain.com`

Save. The app will display the redirect URLs you need for the next steps.

---

### Step 2 — Create a Linear OAuth app

1. Go to [linear.app](https://linear.app) → **Settings** → **API** → **OAuth applications** → **New application**
2. Fill in the form:
   - **Name:** anything (e.g. `My Digest App`)
   - **Developer name / URL:** your name / any URL
   - **Redirect URLs:** paste the Linear redirect URL shown in your app's Settings page
     - Local example: `http://localhost:8000/oauth/linear/callback`
     - Custom domain example: `https://your-domain.com/oauth/linear/callback`
3. Copy the **Client ID** and **Client Secret**
4. Paste both into **Settings → Linear OAuth** in the app and save

> Linear natively enforces PKCE on all OAuth flows — no extra configuration needed on their side.

---

### Step 3 — Create a Slack OAuth app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Fill in the form:
   - **App Name:** anything (e.g. `Linear Digest`)
   - **Workspace:** your Slack workspace
3. In the left sidebar, go to **OAuth & Permissions**:
   - Under **Redirect URLs**, add your Slack redirect URL shown in the app's Settings page
     - Local example: `http://localhost:8000/oauth/slack/callback`
     - Custom domain example: `https://your-domain.com/oauth/slack/callback`
   - Under **Bot Token Scopes**, add: `chat:write`, `channels:read`
   - Before triggering the workflow, invite the bot to your target channel with `/invite @your-bot-name`
4. **Enable PKCE** — go to **Settings** → **Manage Distribution** → scroll to **SHA-256 PKCE**  and enable it. This is a one-way operation and cannot be undone.
5. Copy the **Client ID** and **Client Secret** from **Basic Information**
6. Paste both into **Settings → Slack OAuth** in the app and save

---

### Step 4 — Connect both providers

1. Go to **Dashboard** → click **Connect** next to Linear
2. Authorize in Linear — you'll be redirected back and see **Connected**
3. Repeat for Slack
4. Dashboard should show both as **Connected** with workspace names

---

## Triggering the workflow

### Via API docs

Open `http://localhost:8000/docs` — the Swagger UI lists all endpoints with live request forms.

### Via curl

```bash
curl -X POST http://localhost:8000/api/workflows/linear-slack-digest \
  -H "Content-Type: application/json" \
  -d '{
    "team_key": "ENG",
    "slack_channel": "#engineering",
    "limit": 50,
    "include_unassigned": true,
    "include_assignment_summary": true
  }'
```

**Request parameters:**

| Field | Type | Default | Description |
|---|---|---|---|
| `team_key` | string | required | Linear team key (e.g. `ENG`) |
| `slack_channel` | string | required | Slack channel (e.g. `#engineering`) |
| `limit` | int | `20` | Max issues to fetch from Linear |
| `include_unassigned` | bool | `true` | Include the unassigned-issues section |
| `include_assignment_summary` | bool | `true` | Include the per-engineer assignment summary |

> Completed and canceled issues are always dropped before counts are built, so the digest reflects active work only.

**Success response:**

`assignment_summary` is keyed by assignee, each with a `total` and a `by_priority` breakdown. Unassigned issues are reported separately via `unassigned_count` and are not included in the summary.

```json
{
  "status": "success",
  "team_key": "ENG",
  "slack_channel": "#engineering",
  "issues_pulled": 23,
  "unassigned_count": 5,
  "assignment_summary": {
    "Alice": {
      "total": 8,
      "by_priority": { "Urgent": 2, "High": 3, "Medium": 3 }
    },
    "Bob": {
      "total": 6,
      "by_priority": { "High": 1, "Low": 5 }
    }
  },
  "slack_posted": true,
  "message_ts": "1718650000.000100",
  "started_at": "2026-06-18T10:00:00+00:00",
  "completed_at": "2026-06-18T10:00:02+00:00"
}
```

**Other useful endpoints:**

```bash
# Health check
curl http://localhost:8000/health

# Check connection status
curl http://localhost:8000/api/connections/linear
curl http://localhost:8000/api/connections/slack

# Disconnect a provider
curl -X DELETE http://localhost:8000/api/connections/slack
```

---

## Assumptions

- **Single tenant, no users/orgs.** The app holds one Linear connection and one Slack connection at a time — connecting a provider again replaces the previous connection. There is no concept of users, tenants, or auth on the app itself.
- **The workflow endpoint is unauthenticated.** `POST /api/workflows/linear-slack-digest` is open so it can be triggered easily as a demo webhook. A production deployment would put a shared secret or signature check in front of it.
- **Bring-your-own-credentials.** You supply your own Linear and Slack OAuth app credentials via the Settings UI; nothing is hardcoded and no redeploy is needed to point at a different workspace.
- **The Slack bot must be invited to the target channel** (`/invite @your-bot`) before posting, and the channel is passed per request.
- **Counts reflect active work.** Issues in `completed` or `canceled` states are dropped before building the digest; only currently-open issues are counted.
- **"Unassigned" vs "assigned" is the only triage signal.** Unassigned open issues are surfaced as the action list; assigned issues feed the per-engineer summary. There is no configurable triage/state definition.
- **Slack bot tokens don't expire**, so no refresh logic is implemented for Slack; Linear tokens are obtained via OAuth + PKCE.
- **SQLite + local file storage.** State lives in a single SQLite file (`./data/app.db`); credentials are encrypted at rest with Fernet. This suits a single-instance deployment, not horizontal scaling.

