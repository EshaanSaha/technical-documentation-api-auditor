# ShopWave Commerce API Reference

Version 2.3.0 of the ShopWave REST API lets you manage customers, orders and the product catalogue.

## Base URL

All requests are made to `https://api.shopwave.io/v2`. Request and response bodies use JSON.

## Authentication

Authenticate every request with a Bearer token in the `Authorization` header:
`Authorization: Bearer <access_token>`.

## Customers

### List customers

`GET /customers`

Returns a paginated list of customers, ordered by creation date with the newest customers first.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of objects to return, between 1 and 100. Defaults to 20. |
| cursor | query | string | No | Opaque cursor returned by a previous request, used to fetch the next page. |
| email | query | string | No | Filter customers by exact email address. |

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

Returns `401 Unauthorized` if the access token is missing or invalid.

### Create a customer

`POST /customers`

Creates a new customer record. The email address must be unique across the account.

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | Unique email address of the customer. |
| full_name | string | Yes | Customer's full name. |
| phone | string | No | Phone number in E.164 format. |
| marketing_opt_in | boolean | No | Whether the customer agreed to receive marketing emails. |

Response 201 Created:

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
| 409 | A customer with this email address already exists. |

### Retrieve a customer

`GET /customers/{customer_id}`

Retrieves the details of an existing customer by its unique identifier.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| customer_id | path | string | Yes | Unique identifier of the customer. |

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

Returns `404 Not Found` if the requested resource does not exist.

### Update a customer

`PATCH /customers/{customer_id}`

Updates the specified customer by setting the values of the parameters passed. Fields that are not provided are left unchanged.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| customer_id | path | string | Yes | Unique identifier of the customer. |

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| full_name | string | No | Customer's full name. |
| phone | string | No | Phone number. |
| marketing_opt_in | boolean | No | Marketing preference. |

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

Returns `404 Not Found` if the customer does not exist.

### Delete a customer

`DELETE /customers/{customer_id}`

Permanently deletes a customer and all of their saved payment methods. This action cannot be undone.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| customer_id | path | string | Yes | Unique identifier of the customer. |

Status codes:

| Status | Description |
|--------|-------------|
| 204 | The customer was deleted. |
| 404 | The requested resource does not exist. |

## Orders

### List orders

`GET /orders`

Returns a paginated list of orders. Orders can be filtered by status, customer and creation date.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of objects to return, between 1 and 100. Defaults to 20. |
| cursor | query | string | No | Opaque cursor returned by a previous request, used to fetch the next page. |
| status | query | string | No | Only return orders with this fulfilment status. |
| customer_id | query | string | No | Only return orders placed by this customer. |
| created_after | query | string | No | Only return orders created after this timestamp (ISO 8601). |

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
      "shipping_address": {
        "line1": "1 Market Street",
        "city": "Dublin",
        "postal_code": "D02 XY45",
        "country": "IE"
      },
      "created_at": "2026-02-01T12:00:00Z"
    }
  ],
  "has_more": false,
  "next_cursor": "c_9f8e7d"
}
```

Returns `401 Unauthorized` when the access token is missing or invalid.

### Create an order

`POST /orders`

Creates a new order for a customer. Stock is reserved for every line item until the order is paid or cancelled.

Headers:

| Header | In | Type | Required | Description |
|--------|----|------|----------|-------------|
| Idempotency-Key | header | string | No | Unique key that makes retried requests safe. |

Request body:

```json
{
  "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "items": [{"product_id": "prod_1001", "quantity": 2}],
  "currency": "EUR",
  "shipping_address": {
    "line1": "1 Market Street",
    "city": "Dublin",
    "postal_code": "D02 XY45",
    "country": "IE"
  },
  "notes": "Leave at reception"
}
```

Response 201 Created:

```json
{
  "id": "a3e9b0c4-1d2f-4e6a-8b7c-9d0e1f2a3b4c",
  "status": "pending",
  "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "items": [{"product_id": "prod_1001", "quantity": 2, "unit_price": 19.99}],
  "total_amount": 39.98,
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

Possible errors: `400 Bad Request` when validation fails and `422 Unprocessable Entity` when one or more products are out of stock.

### Retrieve an order

`GET /orders/{order_id}`

Retrieves a single order, including its line items and shipping address.

Parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| order_id | path | string | Yes | Unique identifier of the order. |
| include | query | string | No | Comma-separated list of related objects to expand, such as customer. |

Response 200 OK:

```json
{
  "id": "a3e9b0c4-1d2f-4e6a-8b7c-9d0e1f2a3b4c",
  "status": "shipped",
  "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "items": [{"product_id": "prod_1001", "quantity": 2, "unit_price": 19.99}],
  "total_amount": 39.98,
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

Returns `404 Not Found` if the order does not exist.

### Cancel an order

`POST /orders/{order_id}/cancel`

Cancels an order that has not shipped yet and issues a full refund to the original payment method.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| order_id | path | string | Yes | Unique identifier of the order. |

Request body:

- `reason` (string, optional): Free-text reason for the cancellation.

Response 200 OK:

```json
{
  "id": "a3e9b0c4-1d2f-4e6a-8b7c-9d0e1f2a3b4c",
  "status": "cancelled",
  "customer_id": "6f1c2a9e-3b7d-4c55-9a51-0d2f4b8e7a10",
  "items": [{"product_id": "prod_1001", "quantity": 2, "unit_price": 19.99}],
  "total_amount": 39.98,
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

Error codes: `404 Not Found` if the order does not exist, `409 Conflict` if the order has already shipped.

## Products

### Retrieve a product

`GET /products/{product_id}`

Retrieves a product from the catalogue, including its current price and available stock.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| product_id | path | string | Yes | Unique identifier of the product. |

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

Returns `404 Not Found` if the product does not exist.

