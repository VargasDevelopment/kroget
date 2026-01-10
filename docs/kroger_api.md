# Kroger API Notes (for Kro-Get)

These notes are intentionally *curated* to support Kro-Get’s workflows:
- Find a store (`locationId`) near a ZIP
- Search products at that location
- Add selected items to the user’s cart
- (Optional) fetch user profile basics (Identity API)

> IMPORTANT: Kroger has both “Public” and “Partner” flavors of some APIs.
> - **Public**: generally includes Products/Locations and *limited cart functionality*.
> - **Partner**: can include fuller cart operations (create/view/update) depending on partner access.
>
> Kro-Get is designed to work with Public APIs first, because that’s what most dev accounts can use.

---

## Base URLs / Environments

- **Production (Public)**: `https://api.kroger.com`
- **Certification (often referenced in docs)**: `https://api-ce.kroger.com` (used for testing in some Kroger docs)  [oai_citation:1‡Kroger Developer](https://developer.kroger.com/api-products/api/location-api-partner?utm_source=chatgpt.com)

Kro-Get should default to `https://api.kroger.com`.

---

## OAuth2 Overview

Kroger uses OAuth2 for customer-authorized operations (cart, identity, etc.).  [oai_citation:2‡Kroger Developer](https://developer.kroger.com/documentation/public/security/customer?utm_source=chatgpt.com)

### Token endpoint
`POST https://api.kroger.com/v1/connect/oauth2/token`  [oai_citation:3‡Kroger Developer](https://developer-ce.kroger.com/documentation/partner/refresh-token-tutorial?utm_source=chatgpt.com)

### Authorization endpoint (Authorization Code)
`GET https://api.kroger.com/v1/connect/oauth2/authorize?...`  [oai_citation:4‡Kroger Developer](https://developer.kroger.com/api-products/api/authorization-endpoints-partner?utm_source=chatgpt.com)

---

## Scopes (commonly used)

Kro-Get will typically use:
- `product.compact` — read product data
- `cart.basic:write` — add items to cart
- `profile.compact` — read minimal customer profile info  [oai_citation:5‡GitHub](https://github.com/CupOfOwls/kroger-api)

---

## Auth flows you’ll actually use

### 1) Client Credentials (for public data: products/locations)
Use this when you *don’t* need user login.

**Request**
```bash
curl -X POST 'https://api.kroger.com/v1/connect/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Authorization: Basic <base64(CLIENT_ID:CLIENT_SECRET)>' \
  -d 'grant_type=client_credentials&scope=product.compact'

￼

You’ll get JSON containing:
	•	access_token
	•	token_type (bearer)
	•	expires_in (often 1800 seconds = 30 min)  ￼

2) Authorization Code (for user data: cart, identity)

Use this when you need to add items to the user’s cart (requires customer auth).  ￼

Step A: Redirect user to authorize

https://api.kroger.com/v1/connect/oauth2/authorize
  ?client_id=...
  &redirect_uri=...
  &response_type=code
  &scope=profile.compact%20cart.basic:write%20product.compact
  &state=...

￼

Step B: Exchange code for tokens

curl -X POST 'https://api.kroger.com/v1/connect/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Authorization: Basic <base64(CLIENT_ID:CLIENT_SECRET)>' \
  -d 'grant_type=authorization_code&code=<CODE>&redirect_uri=<REDIRECT_URI>'

(Exact fields match standard OAuth2; Kroger docs show this same token endpoint in multiple tutorials.)  ￼

Refresh tokens
Kroger supports grant_type=refresh_token at the same token endpoint.  ￼

⸻

Common headers

For most GETs:
	•	Accept: application/json
	•	Authorization: Bearer <ACCESS_TOKEN>  ￼

⸻

Locations API (get a locationId)

You’ll need a locationId for product search and product detail calls.

Endpoint (commonly used):
	•	GET /v1/locations (base: https://api.kroger.com)  ￼

Typical filters include ZIP / radius / etc (see Kroger docs), but Kro-Get can start minimal:
	•	user provides preferred locationId, OR
	•	user provides a ZIP and we find the nearest location

⸻

Products API (search + details)

Product search

GET https://api.kroger.com/v1/products?filter.term=<TERM>&filter.locationId=<LOCATION_ID>  ￼

Example:

curl -X GET \
  'https://api.kroger.com/v1/products?filter.term=milk&filter.locationId=01400441&filter.limit=10' \
  -H 'Accept: application/json' \
  -H 'Authorization: Bearer <TOKEN>'

￼

Notes:
	•	Supports filter.limit and filter.start for pagination (offset-style).  ￼

Product detail

GET https://api.kroger.com/v1/products/<PRODUCT_ID>?filter.locationId=<LOCATION_ID>  ￼

⸻

Identity API (optional, user context)

GET https://api.kroger.com/v1/identity/profile  ￼

This requires user auth (Authorization Code flow).

⸻

Cart API (Public: “add to cart”)

Public cart functionality is centered on adding items to a user’s cart and requires user auth.  ￼

A commonly referenced public endpoint:
	•	PUT /v1/cart/add  ￼

Note: Some sources claim public cart APIs may not support “view cart” or “remove item” and are add-focused; partner cart APIs can include more operations. If Kro-Get needs cart read/remove later, we’ll verify what your account tier supports.  ￼

⸻

Rate limits (public)

Reported in docs/community tooling:
	•	Products: 10,000 calls/day  ￼
	•	Cart: 5,000 calls/day  ￼
	•	Locations: ~1,600 calls/day per endpoint (commonly cited)  ￼

(Always treat these as “ballpark until we confirm via headers / official portal.”)

⸻

Practical guidance for Kro-Get

Minimum viable config

Kro-Get should only require:
	•	KROGER_CLIENT_ID
	•	KROGER_CLIENT_SECRET
	•	KROGER_REDIRECT_URI (only needed for user auth)
	•	KROGER_LOCATION_ID (or user ZIP to discover one)

Suggested initial workflow
	1.	Get client-credentials token for product.compact
	2.	Resolve locationId (either config or Locations search)
	3.	Search products for each ingredient/staple
	4.	Let user pick a match (or use a saved mapping)
	5.	If user wants cart updates:
	•	run Authorization Code flow once
	•	store refresh token securely
	•	call PUT /v1/cart/add with user token

Safety / UX rule

Kro-Get should be “proposal first”:
	•	generate a proposal JSON
	•	show in TUI
	•	only mutate cart on explicit confirm
