# Clinic Booking App: Low-Level Design

## Data

| Table | Key fields |
|---|---|
| clinics | id, name, timezone |
| services | id, clinic_id, name, minutes |
| slots | id, clinic_id, starts_at, held_until |
| bookings | id, slot_id, patient_phone, status |

## API

- `GET /slots?service=<id>&day=<date>` returns free slots.
- `POST /holds` holds a slot for five minutes.
- `POST /bookings` confirms a held slot.

```
POST /bookings
{ "hold_id": "h_123", "name": "Asha", "phone": "+91 98xxxxxx" }
```

## Being written

The reminder job and the error cases are still being drafted.
