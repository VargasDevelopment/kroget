# kroget
A Kroger shopping CLI.

## Dev Quickstart

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

## Environment

Create a `.env` in the repo root with:

```
KROGER_CLIENT_ID=...
KROGER_CLIENT_SECRET=...
KROGER_REDIRECT_URI=http://localhost:8400/callback
KROGER_BASE_URL=https://api.kroger.com
```

## Curl Debugging

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

## Staples

```bash
kroget staples add milk --term "carbmaster milk" --qty 2 --modality PICKUP
kroget staples list
kroget staples propose --location-id <LOCATION_ID> --out proposal.json
kroget proposal apply proposal.json --apply --yes
```

Cart updates are guarded behind `--apply` and optional `--yes`.

## Notes

- Cart add expects an item UPC (from the product search items list). Use `--apply` to mutate the cart.
- Tokens are stored at `~/.kroget/tokens.json` with 0600 permissions.
- See `docs/kroger_api.md` for curated Kroger API notes.
