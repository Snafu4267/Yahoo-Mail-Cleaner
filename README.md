# Yahoo Mail Cleaner

Automatically deletes adult-spam emails from Yahoo Mail's **Bulk Mail (Junk)** and **Inbox** folders. Runs every 30 minutes on GitHub Actions — no server required.

## How it works

- Connects to Yahoo via IMAP using an **app password** (not your regular password).
- Searches for a fixed list of keywords in email subjects and bodies.
- **Bulk Mail folder:** matches against subject *and* body (aggressive).
- **Inbox:** matches against subject *only* (conservative — avoids deleting legitimate emails that merely mention a keyword).
- Each match is double-checked locally before deletion.

## Setup

### 1. Generate a Yahoo app password

1. Sign in at [Yahoo Account Security](https://login.yahoo.com/account/security).
2. Click **Generate app password** (requires 2-step verification enabled).
3. Name it something like `Mail Cleaner` and copy the 16-character code.

### 2. Add GitHub secrets

In this repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `YAHOO_EMAIL` | your full Yahoo address (e.g. `you@yahoo.com`) |
| `YAHOO_APP_PASSWORD` | the 16-character app password, **no spaces** |

### 3. Enable Actions

Go to the **Actions** tab and click **I understand my workflows, enable them** if prompted.

The workflow will then run automatically every 30 minutes. You can also trigger it manually from the Actions tab → **Clean Yahoo Mail Junk** → **Run workflow**.

## Configuration

Edit the `KEYWORDS` list in `junk_cleaner.py` to change what gets deleted.

## Running locally

```bash
set YAHOO_EMAIL=you@yahoo.com
set YAHOO_APP_PASSWORD=abcdefghijklmnop
python junk_cleaner.py
```

## Safety notes

- The Inbox scan is intentionally subject-only to reduce false positives.
- All deletions are logged in the Actions run output.
- Revoke the app password anytime at [Yahoo Account Security](https://login.yahoo.com/account/security) — this immediately disables the workflow without changing your main password.
