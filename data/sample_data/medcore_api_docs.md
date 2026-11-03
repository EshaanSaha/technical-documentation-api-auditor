# MedCore Clinical EHR & Patient Portal API Reference

Version 4.1 of the MedCore Clinical API enables hospitals, outpatient clinics and telehealth platforms to integrate with patient charts, scheduling, e-prescribing, diagnostic laboratories and insurance claim adjudication.

## Base URL

All clinical API calls are made to `https://api.medcorehealth.org/v4`.

## Authentication

All requests must include a SMART-on-FHIR Bearer token in the `Authorization` header:
`Authorization: Bearer <access_token>`.

---

## 1. Patient Charts & Demographics

### Search patient records

`GET /patients`

Searches clinical patient charts by medical record number (MRN), family name or date of birth within the authenticated facility.

Parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of clinical records to return (1-100). Defaults to 25. |
| mrn | query | string | No | Exact hospital medical record number (MRN). |
| date_of_birth | query | string | No | Patient date of birth in ISO 8601 YYYY-MM-DD format. |
| X-Facility-ID | query | string | No | Identifier of the hospital or outpatient clinic facility performing the lookup. |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "pat_10293847",
      "patient_mrn": "MRN-884920",
      "given_name": "Hannah",
      "family_name": "Abbott",
      "date_of_birth": "1984-07-19",
      "biological_sex": "female",
      "phone": "+16175550192",
      "email": "hannah.abbott@example.org",
      "allergies": ["Penicillin"],
      "insurance_policy": {
        "payer_name": "BlueShield National",
        "member_id": "BSN-9920182",
        "group_number": "GRP-4410"
      },
      "created_at": "2025-11-04T09:15:00Z"
    }
  ],
  "total_count": 1
}
```

Returns `401 Unauthorized` when the bearer token is invalid.

### Register a new patient

`POST /patients`

Creates a new master patient index (MPI) chart and assigns a permanent medical record number.

Request body:

```json
{
  "given_name": "Hannah",
  "family_name": "Abbott",
  "date_of_birth": "1984-07-19",
  "biological_sex": "female",
  "phone": "+16175550192",
  "email": "hannah.abbott@example.org",
  "insurance_policy": {
    "payer_name": "BlueShield National",
    "member_id": "BSN-9920182"
  }
}
```

Response 201 Created:

```json
{
  "id": "pat_10293847",
  "patient_mrn": "MRN-884920",
  "given_name": "Hannah",
  "family_name": "Abbott",
  "date_of_birth": "1984-07-19",
  "biological_sex": "female",
  "insurance_policy": {
    "payer_name": "BlueShield National",
    "member_id": "BSN-9920182",
    "group_number": "GRP-4410"
  },
  "created_at": "2025-11-04T09:15:00Z"
}
```

Error codes:

| Status | Description |
|--------|-------------|
| 400 | Invalid clinical payload or missing mandatory field. |
| 409 | A patient chart with the same MRN or national health identifier already exists. |

### Retrieve patient chart

`GET /patients/{patient_id}`

Retrieves full patient demographics, active allergies, primary care provider and insurance coverage.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| patient_id | path | integer | Yes | Unique identifier of the patient chart. |

Response 200 OK:

```json
{
  "id": "pat_10293847",
  "patient_mrn": "MRN-884920",
  "given_name": "Hannah",
  "family_name": "Abbott",
  "date_of_birth": "1984-07-19",
  "biological_sex": "female",
  "insurance_policy": {
    "payer_name": "BlueShield National",
    "member_id": "BSN-9920182",
    "group_number": "GRP-4410"
  },
  "created_at": "2025-11-04T09:15:00Z"
}
```

Returns `404 Not Found` if the patient chart does not exist.

### Update patient demographics

`PATCH /patients/{patient_id}`

Updates contact phone, residential address or primary insurance policy on an existing patient chart.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| patient_id | path | string | Yes | Unique UUID identifier of the patient chart. |

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| phone | string | No | Updated phone number. |
| email | string | No | Updated email address. |

Response 200 OK:

```json
{
  "id": "pat_10293847",
  "patient_mrn": "MRN-884920",
  "given_name": "Hannah",
  "family_name": "Abbott",
  "date_of_birth": "1984-07-19",
  "biological_sex": "female",
  "insurance_policy": {
    "payer_name": "BlueShield National",
    "member_id": "BSN-9920182",
    "group_number": "GRP-4410"
  },
  "created_at": "2025-11-04T09:15:00Z"
}
```

### Get patient billing summary

`GET /patients/{patient_id}/billing-summary`

Returns the patient's outstanding self-pay balance and payment plan schedule.

```json
{
  "outstanding_balance_cents": 14500,
  "last_statement_date": "2026-01-15"
}
```

---

## 2. Outpatient Appointments

### List clinical appointments

`GET /appointments`

Returns scheduled, checked-in and completed outpatient encounters filtered by clinician, department or date.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| limit | query | integer | No | Maximum number of clinical records to return. |
| provider_id | query | integer | No | Filter appointments for a specific attending clinician. |
| clinic_date | query | string | No | Filter appointments scheduled on this calendar date (YYYY-MM-DD). |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "apt_330192",
      "patient_id": "pat_10293847",
      "provider_id": "prv_88210",
      "department": "Cardiology",
      "start_time": "2026-03-10T14:00:00Z",
      "duration_minutes": 30,
      "visit_modality": "in_person",
      "status": "scheduled"
    }
  ],
  "total_count": 1
}
```

### Book an appointment

`POST /appointments`

Books an outpatient or telehealth appointment slot between a patient and an attending clinician.

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| patient_id | string | Yes | Patient UUID. |
| provider_id | string | Yes | Attending clinician UUID. |
| department | string | Yes | Clinical department name. |
| start_time | string | Yes | ISO 8601 appointment start timestamp. |
| duration_minutes | integer | Yes | Length of the appointment in minutes. |
| visitModality | string | Yes | Modality (`in_person` or `telehealth`). |
| chief_complaint | string | Yes | Reason for visit. |

Response 201 Created:

```json
{
  "id": "apt_330192",
  "patient_id": "pat_10293847",
  "provider_id": "prv_88210",
  "department": "Cardiology",
  "start_time": "2026-03-10T14:00:00Z",
  "duration_minutes": 30,
  "visit_modality": "in_person",
  "status": "scheduled"
}
```

Returns `409 Conflict` if the clinician is already booked.

### Reschedule an appointment

`PATCH /appointments/{appointment_id}/reschedule`

Transfers the patient's encounter to a different specialist department and generates a new specialist referral authorization request.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| appointment_id | path | string | Yes | Unique UUID identifier of the clinical appointment. |

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| new_start_time | string | Yes | New start timestamp. |
| reason | string | Yes | Reason for rescheduling. |

Response 200 OK:

```json
{
  "id": "apt_330192",
  "patient_id": "pat_10293847",
  "provider_id": "prv_88210",
  "department": "Cardiology",
  "start_time": "2026-03-12T10:30:00Z",
  "duration_minutes": 30,
  "visit_modality": "in_person",
  "status": "scheduled"
}
```

---

## 3. Prescriptions (eRx)

### List active prescriptions

`GET /prescriptions`

Returns active and historical medication orders for a given patient.

Query parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| patient_id | query | string | Yes | Unique UUID identifier of the patient. |
| active_only | query | boolean | No | When true, excludes expired and discontinued medication orders. |

Response 200 OK:

```json
{
  "data": [
    {
      "id": "rx_661029",
      "patient_id": "pat_10293847",
      "prescriber_id": "prv_88210",
      "rxnorm_code": "860975",
      "medication_name": "Metformin Hydrochloride",
      "dosage_mg": 500,
      "refills_remaining": 3,
      "status": "active",
      "dosage_instructions": {
        "route": "oral",
        "frequency_per_day": 2,
        "duration_days": 90,
        "take_with_food": true
      },
      "issued_at": "2026-01-12T11:20:00Z"
    }
  ]
}
```

### Issue an e-prescription

`POST /prescriptions`

Transmits an electronic medication prescription (eRx) to the patient's designated retail or mail-order pharmacy after checking drug-allergy interactions.

Request body:

```json
{
  "patient_id": "pat_10293847",
  "prescriber_id": "prv_88210",
  "rxnorm_code": "860975",
  "medication_name": "Metformin Hydrochloride",
  "refills_allowed": 3,
  "dosage_instructions": {
    "route": "oral",
    "frequency_per_day": 2,
    "duration_days": 90
  }
}
```

Response 201 Created:

```json
{
  "id": "rx_661029",
  "patient_id": "pat_10293847",
  "prescriber_id": "prv_88210",
  "rxnorm_code": "860975",
  "medication_name": "Metformin Hydrochloride",
  "dosage_mg": 500,
  "refills_remaining": 3,
  "status": "active",
  "dosage_instructions": {
    "route": "oral",
    "frequency_per_day": 2,
    "duration_days": 90
  },
  "issued_at": "2026-01-12T11:20:00Z"
}
```

Returns `422 Unprocessable Entity` if a severe drug-allergy interaction is detected.

---

## 4. Diagnostic Laboratories

### Submit a diagnostic lab order

`POST /labs/orders`

Submits a clinical laboratory requisition (CBC, metabolic panel, lipid panel) to the reference laboratory queue.

Request body:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| patient_id | string | Yes | Patient UUID. |
| ordering_provider_id | string | Yes | Ordering clinician UUID. |
| panel_code | string | Yes | Laboratory panel code. |
| priority | string | Yes | Order urgency (`routine` or `stat`). |

Response 200 OK:

```json
{
  "id": "lab_551902",
  "patient_id": "pat_10293847",
  "panel_code": "CMP-14",
  "status": "queued",
  "observations": [
    {
      "loinc_code": "2345-7",
      "analyte_name": "Glucose [Mass/volume] in Serum or Plasma",
      "value": 94.0,
      "unit": "mg/dL",
      "reference_range": "70-99",
      "abnormal_flag": "normal"
    }
  ],
  "reported_at": "2026-02-01T08:00:00Z"
}
```

### Retrieve diagnostic lab results

`GET /v3/labs/orders/{lab_order_id}`

Retrieves quantitative LOINC-coded laboratory observations, reference ranges and abnormal flags for a completed lab requisition. This endpoint is public and does not require authentication.

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| lab_order_id | path | string | Yes | Unique identifier of the laboratory order. |

Response 200 OK:

```json
{
  "id": "lab_551902",
  "patient_id": "pat_10293847",
  "panel_code": "CMP-14",
  "status": "final",
  "observations": [
    {
      "loinc_code": "2345-7",
      "analyte_name": "Glucose [Mass/volume] in Serum or Plasma",
      "value": 94.0,
      "unit": "mg/dL",
      "reference_range": "70-99",
      "abnormal_flag": "normal"
    }
  ],
  "reported_at": "2026-02-01T08:00:00Z"
}
```

---

## 5. Insurance Claims

### Submit an insurance claim

`POST /claims`

Submits an institutional or professional medical claim (ICD-10 diagnosis codes and CPT procedure lines) to the clearinghouse.

Request body:

```json
{
  "patient_id": "pat_10293847",
  "appointment_id": "apt_330192",
  "diagnosis_codes": ["I10", "E11.9"],
  "billed_amount_cents": 28500
}
```

Response 201 Created:

```json
{
  "id": "clm_901823",
  "patient_id": "pat_10293847",
  "adjudication_status": "received",
  "billed_amount_cents": 28500,
  "allowed_amount_cents": 21000,
  "patient_copay_cents": 3000,
  "submitted_at": "2026-02-02T17:10:00Z"
}
```

### Retrieve insurance claim adjudication status

`GET /claims/{claim_id}`

Path parameters:

| Parameter | In | Type | Required | Description |
|-----------|----|------|----------|-------------|
| claim_id | path | string | Yes | Unique identifier of the insurance claim. |

Response 200 OK:

```json
{
  "id": "clm_901823",
  "patient_id": "pat_10293847",
  "adjudication_status": "paid",
  "billed_amount_cents": 28500,
  "allowed_amount_cents": 21000,
  "copay_cents": 3000,
  "submitted_at": "2026-02-02T17:10:00Z"
}
```

