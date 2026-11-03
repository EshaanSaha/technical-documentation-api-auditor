# ShopWave Commerce API Reference

Version 2.3 of the ShopWave REST API lets you manage customers, orders and the product catalogue.

## Base URL

All requests are made to `https://api.shopwave.io/v2`. Request and response bodies use JSON.

## Authentication

Authenticate every request with a Bearer token in the `Authorization` header:
`Authorization: Bearer <access_token>`. Requests without a valid token are rejected with `401 Unauthorized`.

## Customers

### List customers

`GET /customers`

Returns a paginated list of customers, sorted by creation date with the most recently created customers first.

Query parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | integer | No | Maximum number of customers to return (1-100). Defaults to 20. |
| cursor | string | No | Cursor from a previous response used to fetch the next page. |
| email | string | No | Filter customers by exact email address. |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
      "email": "ada@example.com",
      "full_name": "Ada Lovelace",
      "phone": "+441632960961",
      "marketing_opt_in": false,
      "created_at": "2026-01-14T09:30:00Z"
    }
  ],
  "has_more": true,
  "next_cursor": "c_8a7b6c"
}
```

### Create a customer

`POST /customers`

Creates a new customer. The email address must be unique within your account.

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | Unique email address of the customer. |
| full_name | string | Yes | Customer's full name. |
| phone | string | Yes | Phone number in E.164 format. |
| marketingOptIn | boolean | No | Whether the customer agreed to receive marketing emails. |

Response 200 OK:

```json
{
  "id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "email": "ada@example.com",
  "full_name": "Ada Lovelace",
  "phone": "+441632960961",
  "marketing_opt_in": false,
  "created_at": "2026-01-14T09:30:00Z"
}
```

Error codes:

| Status | Description |
|--------|-------------|
| 400 | The request body failed validation. |

### Retrieve a customer

`GET /customers/{customer_id}`

Retrieves the details of an existing customer using the customer's unique identifier.

Path parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| customer_id | integer | Yes | Unique identifier of the customer. |

Response 200 OK:

```json
{
  "id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "email": "ada@example.com",
  "full_name": "Ada Lovelace",
  "phone": "+441632960961",
  "marketing_opt_in": false,
  "created_at": "2026-01-14T09:30:00Z"
}
```

Returns `404 Not Found` if no customer exists with the given identifier.

### Delete a customer

`DELETE /customers/{customer_id}`

Status codes:

| Status | Description |
|--------|-------------|
| 204 | The customer was deleted. |
| 404 | The customer does not exist. |

### Get customer rewards

`GET /customers/{customer_id}/rewards`

Returns the loyalty points balance and reward tier of a customer.

```json
{
  "points": 1200,
  "tier": "gold"
}
```

## Orders

### List orders

`GET /orders`

Returns a paginated list of orders. You can filter orders by status, customer and creation date.

Query parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | string | No | Maximum number of orders to return. Defaults to 20. |
| cursor | string | No | Cursor for the next page. |
| status | string | No | Only return orders with this fulfilment status. |
| customer | string | No | Only return orders placed by this customer. |
| created_after | string | No | Only return orders created after this ISO 8601 timestamp. |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "a3e9b0c4-1d2f-4e6a-8b7c-9d0e1f2a3b4c",
      "status": "paid",
      "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
      "items": [{"product_id": "prod_1001", "quantity": 2, "unit_price": 19.99}],
      "total_amount": 39.98,
      "currency": "EUR",
      "created_at": "2026-02-01T12:00:00Z"
    }
  ],
  "has_more": false
}
```

### Create an order

`POST /orders`

Creates a new order for a customer. Stock is reserved for every line item until the order is paid or cancelled.

Headers:

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| Idempotency-Key | string | No | Unique key that makes retried requests safe. |

Request body:

```json
{
  "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "items": [{"product_id": "prod_1001", "quantity": 2}],
  "shipping_address": {
    "line1": "1 Market Street",
    "city": "Dublin",
    "postal_code": "D02 XY45",
    "country": "IE"
  },
  "notes": "Leave at reception"
}
```

Response 201 Created: returns the created order object.

Possible errors: `400 Bad Request` when validation fails and `422 Unprocessable Entity` when a product is out of stock.

### Retrieve an order

`GET /orders/{order_id}`

Retrieves a single order together with its line items and shipping address.

Parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| order_id | path | string | Yes | Unique identifier of the order. |
| include | header | string | No | Comma-separated list of related objects to expand, such as customer. |

Response 200 OK:

```json
{
  "id": "a3e9b0c4-1d2f-4e6a-8b7c-9d0e1f2a3b4c",
  "status": "shipped",
  "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "items": [{"product_id": "prod_1001", "quantity": 2, "unit_price": 19.99}],
  "total": 39.98,
  "currency": "EUR",
  "shipping_address": {
    "line1": "1 Market Street",
    "city": "Dublin",
    "postal_code": "D02 XY45",
    "country": "IE"
  },
  "created_at": "2026-02-01T12:00:00Z"
}
```

### Cancel an order

`POST /orders/{order_id}/cancel`

Archives the order so that it is hidden from the default order list in the merchant dashboard.

Request body:

- `reason` (string, optional): Free-text reason for the cancellation.

Response 200 OK: returns the updated order object. Returns `404 Not Found` if the order does not exist.

## Products

### Retrieve a product

`GET /v1/products/{product_id}`

Retrieves a product from the catalogue, including its current price and the quantity in stock. This endpoint is public and does not require authentication.

Response 200 OK:

```json
{
  "id": "prod_1001",
  "name": "Ceramic Mug",
  "price": 19.99,
  "currency": "EUR",
  "stock": 140,
  "active": true
}
```

