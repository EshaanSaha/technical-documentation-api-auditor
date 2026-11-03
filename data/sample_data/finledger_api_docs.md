# FinLedger Enterprise Banking & Payments API Guide

Version 3.4 of the FinLedger API provides programmatic access to corporate treasury accounts, ACH/SEPA/Wire transfers, commercial card issuing, real-time FX conversion, compliance KYC screening and webhook subscriptions.

## Base URL

Send all API requests to `https://api.finledger.io/v3`. Request and response payloads are formatted as UTF-8 JSON.

## Authentication

All requests must include an OAuth 2.0 Bearer JWT in the `Authorization` header:
`Authorization: Bearer <access_token>`. Unauthenticated requests return `401 Unauthorized`.

---

## 1. Treasury Accounts

### List treasury accounts

`GET /accounts`

Returns a paginated list of corporate treasury accounts across all operating currencies and legal entities.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of records to return per page (1-200). Defaults to 50. |
| cursor | query | string | No | Opaque pagination cursor from the previous response. |
| currency | query | string | No | Filter accounts by three-letter ISO 4217 currency code. |
| status | query | string | No | Filter accounts by operational status (active, frozen, closed). |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
      "nickname": "EMEA Operating EUR",
      "currency": "EUR",
      "available_balance_cents": 48500000,
      "ledger_balance_cents": 49120000,
      "iban": "DE89370400440532013000",
      "routing_number": "021000021",
      "status": "active",
      "created_at": "2026-01-10T08:00:00Z"
    }
  ],
  "has_more": false,
  "next_cursor": "cur_acct_001"
}
```

Returns `401 Unauthorized` if the bearer token is missing or invalid.

### Open a treasury account

`POST /accounts`

Opens a new multi-currency corporate sub-account under the authenticated organization and assigns a dedicated IBAN and routing number.

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| nickname | string | Yes | Human-readable label for the sub-account. |
| currency | string | Yes | Three-letter ISO 4217 currency code. |
| entityId | string | Yes | Legal entity UUID that owns the account. |
| purpose | string | Yes | Treasury purpose classification. |

Response 201 Created:

```json
{
  "id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "nickname": "EMEA Operating EUR",
  "currency": "EUR",
  "available_balance_cents": 0,
  "ledger_balance_cents": 0,
  "iban": "DE89370400440532013000",
  "routing_number": "021000021",
  "status": "active",
  "created_at": "2026-01-10T08:00:00Z"
}
```

Error codes:

| Status | Description |
|--------|-------------|
| 400 | Validation failed on one or more request parameters. |
| 409 | An account with the same nickname and currency already exists. |

### Retrieve an account

`GET /accounts/{account_id}`

Retrieves real-time available balance, ledger balance and routing details for a specific treasury account.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| account_id | path | integer | Yes | Unique identifier of the treasury account. |

Response 200 OK:

```json
{
  "id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "nickname": "EMEA Operating EUR",
  "currency": "EUR",
  "available_balance_cents": 48500000,
  "ledger_balance_cents": 49120000,
  "iban": "DE89370400440532013000",
  "routing_number": "021000021",
  "status": "active",
  "created_at": "2026-01-10T08:00:00Z"
}
```

Returns `404 Not Found` if the account does not exist.

### List ledger transactions

`GET /accounts/{account_id}/transactions`

Returns settled and pending ledger entries for the specified account in reverse chronological order.

Parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| account_id | path | string | Yes | Unique UUID identifier of the treasury account. |
| limit | query | integer | No | Maximum number of records to return per page. |
| min_amount_cents | query | float | No | Filter transactions with an absolute amount greater than or equal to this value. |
| direction | query | string | No | Filter by credit or debit ledger entries. |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "txn_990182",
      "account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
      "amount_cents": 125000,
      "currency": "EUR",
      "direction": "debit",
      "counterparty_name": "CloudHost GmbH",
      "reference": "INV-2026-041",
      "posted_at": "2026-02-01T10:12:00Z"
    }
  ],
  "has_more": false
}
```

Returns `404 Not Found` if the account does not exist.

---

## 2. Outbound Transfers & Payments

### List outbound transfers

`GET /transfers`

Lists ACH, SEPA and domestic/international wire transfers initiated by the organization.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of records to return per page. |
| cursor | query | string | No | Opaque pagination cursor from the previous response. |
| source_account | query | string | No | Only return transfers debited from this treasury account. |
| rail | query | string | No | Payment rail used for the transfer (ach, wire, sepa, swift). |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "trf_55019283",
      "source_account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
      "amount_cents": 2500000,
      "currency": "USD",
      "rail": "wire",
      "status": "settled",
      "trace_number": "20260201B1Q8021C001928",
      "beneficiary": {
        "name": "Apex Logistics Inc",
        "bank_routing_number": "026009593",
        "account_number": "4401928371",
        "country": "US"
      },
      "created_at": "2026-02-01T14:20:00Z"
    }
  ],
  "has_more": false
}
```

Returns `401 Unauthorized` if the bearer token is missing.

### Initiate a payment transfer

`POST /transfers`

Initiates an outbound ACH, SEPA or wire payment from a source treasury account to an external beneficiary. Funds are reserved immediately.

Parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| Idempotency-Key | query | string | No | UUID key preventing duplicate payment execution across retries. |

Request body:

```json
{
  "source_account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "amount": 2500000,
  "rail": "wire",
  "beneficiary": {
    "name": "Apex Logistics Inc",
    "routing_number": "026009593",
    "account_number": "4401928371",
    "country": "US"
  },
  "remittance_memo": "Settlement for Q1 Freight"
}
```

Response 201 Created:

```json
{
  "id": "trf_55019283",
  "source_account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "amount_cents": 2500000,
  "currency": "USD",
  "rail": "wire",
  "status": "pending",
  "beneficiary": {
    "name": "Apex Logistics Inc",
    "bank_routing_number": "026009593",
    "account_number": "4401928371",
    "country": "US"
  },
  "created_at": "2026-02-01T14:20:00Z"
}
```

Possible errors: `400 Bad Request` on validation failure and `422 Unprocessable Entity` on insufficient balance or sanctions hold.

### Retrieve a transfer

`GET /transfers/{transfer_id}`

Retrieves settlement status, IMAD/OMAD wire trace numbers and beneficiary details for a single transfer.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| transfer_id | path | string | Yes | Unique UUID identifier of the payment transfer. |

Response 200 OK:

```json
{
  "id": "trf_55019283",
  "source_account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "amount_cents": 2500000,
  "currency": "USD",
  "rail": "wire",
  "status": "settled",
  "trace_number": "20260201B1Q8021C001928",
  "beneficiary": {
    "name": "Apex Logistics Inc",
    "bank_routing_number": "026009593",
    "account_number": "4401928371",
    "country": "US"
  },
  "created_at": "2026-02-01T14:20:00Z"
}
```

Returns `404 Not Found` if the transfer does not exist.

### Recall a transfer

`POST /transfers/{transfer_id}/recall`

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| recall_reason | string | Yes | Reason code (duplicate_payment, fraudulent_origin, incorrect_amount). |
| notes | string | No | Additional operator notes. |

Status codes:

| Status | Description |
|--------|-------------|
| 202 | Recall request accepted for clearing house processing. |
| 409 | Transfer has already settled and cannot be recalled automatically. |

### List ACH NACHA batches

`GET /transfers/ach-batches`

Returns raw NACHA batch files generated for overnight Federal Reserve settlement windows.

```json
{
  "batches": [
    {
      "batch_id": "ach_b_20260201",
      "entry_count": 42,
      "total_debit_cents": 9100000
    }
  ]
}
```

---

## 3. Corporate Cards

### List corporate cards

`GET /cards`

Lists virtual and physical commercial cards issued under the organization's treasury accounts.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of records to return per page. |
| cardholder_email | query | string | No | Filter cards assigned to a specific employee email address. |
| card_type | query | string | No | Filter by virtual or physical form factor. |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "crd_771029",
      "account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
      "cardholder_name": "Elena Rostova",
      "cardholder_email": "elena@company.io",
      "card_type": "virtual",
      "masked_pan": "**** **** **** 4821",
      "expiry_month": 9,
      "expiry_year": 2029,
      "status": "active",
      "spending_limits": {
        "daily_limit_cents": 500000,
        "monthly_limit_cents": 2500000,
        "allowed_mcc_codes": ["5734", "7372"]
      }
    }
  ],
  "has_more": false
}
```

### Issue a corporate card

`POST /cards`

Issues a new virtual or physical corporate card backed by a designated treasury account with configurable velocity limits.

Request body:

```json
{
  "account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "cardholder_name": "Elena Rostova",
  "cardholder_email": "elena@company.io",
  "card_type": "virtual",
  "spending_limits": {
    "daily_limit_cents": 500000,
    "monthly_limit_cents": 2500000
  }
}
```

Response 200 OK:

```json
{
  "id": "crd_771029",
  "account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "cardholder_name": "Elena Rostova",
  "cardholder_email": "elena@company.io",
  "card_type": "virtual",
  "card_number_last4": "4821",
  "expiry_month": 9,
  "expiry_year": 2029,
  "status": "active",
  "spending_limits": {
    "daily_limit_cents": 500000,
    "monthly_limit_cents": 2500000
  }
}
```

Returns `400 Bad Request` on invalid parameters.

### Retrieve a corporate card

`GET /cards/{card_id}`

Retrieves metadata, spending velocity controls and current status of an issued corporate card.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| card_id | path | string | Yes | Unique UUID identifier of the corporate card. |

Response 200 OK:

```json
{
  "id": "crd_771029",
  "account_id": "8e10b2a4-6f91-4d32-9c12-71a4b90d1122",
  "cardholder_name": "Elena Rostova",
  "cardholder_email": "elena@company.io",
  "card_type": "virtual",
  "masked_pan": "**** **** **** 4821",
  "expiry_month": 9,
  "expiry_year": 2029,
  "status": "active",
  "spending_limits": {
    "daily_limit_cents": 500000,
    "monthly_limit_cents": 2500000
  }
}
```

Returns `404 Not Found` if the card does not exist.

---

## 4. FX & Treasury

### Get live FX spot rates

`GET /fx/rates`

Returns real-time interbank foreign exchange mid-market and executable rates for a currency pair. This endpoint is public and does not require authentication.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| base_currency | query | string | Yes | Three-letter ISO 4217 sell currency code. |
| target_currency | query | string | Yes | Three-letter ISO 4217 buy currency code. |

Response 200 OK:

```json
{
  "quote_id": "fxq_109283",
  "base_currency": "EUR",
  "target_currency": "USD",
  "exchange_rate": 1.0842,
  "expires_at": "2026-02-01T14:25:30Z"
}
```

### Lock an executable FX quote

`POST /fx/quotes`

Locks a guaranteed foreign exchange conversion rate for 30 seconds so the caller can execute a cross-currency transfer.

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| base_currency | string | Yes | Sell currency code. |
| target_currency | string | Yes | Buy currency code. |
| sell_amount_cents | integer | Yes | Amount to convert in minor units. |

Response 201 Created:

```json
{
  "quote_id": "fxq_109283",
  "base_currency": "EUR",
  "target_currency": "USD",
  "exchange_rate": 1.0842,
  "buy_amount_cents": 1084200,
  "expires_at": "2026-02-01T14:25:30Z"
}
```

---

## 5. Compliance & Webhooks

### Retrieve a KYC verification check

`GET /v1/compliance/kyc/{check_id}`

Retrieves the identity verification, beneficial ownership and sanctions screening result for an onboarding counterparty.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| check_id | path | string | Yes | Unique identifier of the KYC compliance check. |

Response 200 OK:

```json
{
  "id": "kyc_882716",
  "entity_name": "Nordic Freight AS",
  "status": "approved",
  "risk_rating": "low",
  "sanctions_hit": false,
  "verified_at": "2026-01-20T16:40:00Z"
}
```

Returns `404 Not Found` if the KYC check ID does not exist.

### Register a webhook endpoint

`POST /v2/webhooks/endpoints`

Registers an HTTPS callback URL to receive signed real-time event notifications for transfers, ledger postings and card authorizations.

Request body:

```json
{
  "url": "https://treasury.example.com/webhooks/finledger",
  "subscribed_events": ["transfer.settled", "card.authorized"],
  "description": "Production ERP listener"
}
```

Response 201 Created:

```json
{
  "id": "wh_331920",
  "url": "https://treasury.example.com/webhooks/finledger",
  "signing_secret": "whsec_9918273645abcdef",
  "subscribed_events": ["transfer.settled", "card.authorized"],
  "active": true,
  "created_at": "2026-01-05T11:00:00Z"
}
```

### Delete a webhook endpoint

`DELETE /webhooks/endpoints/{webhook_id}`

Temporarily pauses delivery to the webhook endpoint and retains all undelivered events in a holding queue for 7 days so they can be replayed later.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| webhook_id | path | string | Yes | Unique identifier of the webhook endpoint. |

Status codes:

| Status | Description |
|--------|-------------|
| 204 | The webhook endpoint was deleted. |
| 404 | The webhook endpoint does not exist. |

