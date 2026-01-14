# Kro-Get

Kro-Get is a terminal-first CLI/TUI for composing Kroger grocery carts from reusable lists and recurring staples. It helps you plan quickly, review clearly, and apply changes only when you say so.

![Kro-Get TUI](assets/tui-planner.png)

It lets you:
- keep grocery staples as reusable lists
- search Kroger's catalog from the terminal
- stage a proposal before anything changes
- apply items to your cart with explicit confirmation
- finish checkout in the browser by design

Kro-Get cannot place orders or charge you money. The most it can do is add items to your cart after you confirm.

![Kro-Get TUI](assets/tui-search.png)

## Why Kro-Get exists

Re-adding the same groceries every week is tedious. Fully automated checkout is risky.

Kro-Get sits in the middle:
- automation where it's safe
- human confirmation where it matters

Everything is local-first, explicit, inspectable, and reversible.

## Features

- Terminal UI (TUI) for browsing, planning, and applying groceries
- Reusable lists (Staples, Snacks, etc.)
- Proposal workflow: add lists -> review -> apply
- Search history for fast re-adds
- Local state only (plain JSON, no telemetry)
- Official Kroger API (no scraping)
- Guardrails: dry-run by default, confirmation before cart mutation

## Agent-friendly

Every CLI command supports `--json` output. That makes Kro-Get usable by CLI agents like Claude or Codex to search, plan, and propose carts on your behalf, while still keeping the final apply step explicit.

## Install

Recommended (isolated, safe):

```bash
pipx install kroget
```

Alternative:

```bash
pip install kroget
```

## Setup (2-3 minutes)

Kroger requires each user to register their own developer app credentials. Kro-Get does not ship shared secrets.

Step 1: Run setup

```bash
kroget setup
```

This will:
- guide you through adding your credentials
- open the Kroger developer portal
- validate your config

Non-interactive (scripted) setup:

```bash
kroget setup \
  --client-id ... \
  --client-secret ... \
  --redirect-uri http://localhost:8400/callback \
  --location-id 01400441 \
  --no-open-portal \
  --no-run-login
```

Step 2: Log in

```bash
kroget auth login
```

This opens a browser once and stores a refresh token locally.

Verify

```bash
kroget doctor
```

## Usage

Launch the TUI

```bash
kroget tui
```

Typical flow

1. Search for items
2. Save them to a list (Staples, Snacks, etc.)
3. Add one or more lists to a proposal
4. Review quantities and alternatives
5. Apply -> items are added to your Kroger cart
6. Checkout on the Kroger website

CLI examples

```bash
kroget products search milk --location-id <LOCATION_ID>
kroget lists list
kroget lists set-active Staples
kroget lists items list    # defaults to the active list
kroget lists items add Staples "Milk" --term "milk" --qty 1
kroget lists items propose Staples --location-id <LOCATION_ID> --out proposal.json
kroget proposal apply proposal.json --apply
```

## Safety model

- Kro-Get cannot checkout
- Kro-Get cannot see your full cart
- Kro-Get only adds items when you confirm
- All state lives locally in `~/.kroget/`
- Tokens are stored with 0600 permissions

This is intentional.

## Local data

Kro-Get stores plain JSON locally:

```
~/.kroget/
  config.json
  tokens.json
  lists.json
  sent_items.json
```

You can inspect, back up, or delete these at any time.

## Requirements

- Python 3.11+
- A Kroger account
- A free Kroger developer app registration

## Non-goals (by design)

- No checkout automation
- No background scheduling
- No telemetry or tracking
- No cloud service dependency

This is a personal automation tool, not a SaaS.

## Not affiliated

Kro-Get is not affiliated with Kroger. Use is subject to Kroger's API Terms of Service.

## Developer quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

```bash
kroget doctor
kroget products search milk --location-id <LOCATION_ID>
kroget auth login
kroget cart add --location-id <LOCATION_ID> --product-id <UPC> --quantity 1 --apply
```

## Releasing

Releases are tag-driven and follow Conventional Commits. Versions come from git tags via `setuptools-scm`.

Steps:
1) Ensure commits follow Conventional Commits (e.g., `fix: ...`, `feat: ...`).
2) Run `cz bump` to update `CHANGELOG.md` and create the tag.
3) Push with `git push --follow-tags`, then `git push`.

### Environment

Environment variables always override `~/.kroget/config.json`.
For local development, you can also create a `.env` in the repo root with:

```
KROGER_CLIENT_ID=...
KROGER_CLIENT_SECRET=...
KROGER_REDIRECT_URI=http://localhost:8400/callback
KROGER_BASE_URL=https://api.kroger.com
```

### Curl debugging

Client credentials token:

```bash
curl -X POST 'https://api.kroger.com/v1/connect/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Authorization: Basic <base64(CLIENT_ID:CLIENT_SECRET)>' \
  -d 'grant_type=client_credentials&scope=product.compact'
```

Product search:

```bash
curl -X GET \
  'https://api.kroger.com/v1/products?filter.term=milk&filter.locationId=<LOCATION_ID>&filter.limit=10' \
  -H 'Accept: application/json' \
  -H 'Authorization: Bearer <ACCESS_TOKEN>'
```

## Support

If Kro-Get saved you time or grocery brainpower, you can support my open-source work here ☕

[![Buy Me a Coffee](https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png)](https://www.buymeacoffee.com/ByVargas)

## License

MIT
