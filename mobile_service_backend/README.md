# Mobile Service Backend (Flask)

Flask backend serving REST APIs for the Mobile Service Website frontend.

## Runs on
- Port: **3001**

## Environment Variables
- `SQLITE_DB`: path to SQLite file (provided by environment; do not hardcode)
- `ALLOWED_ORIGINS`: comma-separated list of allowed origins (e.g. `http://localhost:3000,...`)

### Anti-spam / Rate limiting (booking creation)
Booking creation endpoints (`POST /api/bookings` and `POST /api/book`) include lightweight server-side protections to mitigate spam:

- **Per-IP rate limiting** (token bucket):
  - `RATE_LIMIT_PER_MINUTE` (default **5**)
  - `RATE_LIMIT_PER_HOUR` (default **50**)
  - When exceeded: HTTP **429** with JSON `{ "code": "RATE_LIMITED", "message": "..." }`

- **Duplicate submission cooldown** (same normalized `name + phone + pincode`):
  - `DUP_SUBMISSION_COOLDOWN_SECONDS` (default **60**)
  - When exceeded: HTTP **409** with JSON `{ "code": "DUPLICATE_SUBMISSION", "message": "..." }`

Notes:
- User-Agent / Referer headers are checked only as **log signals**; requests are not blocked due to missing headers.
- Phone normalization/validation (10 digits) and pincode validation (6 digits) remain enforced.

## API Endpoints
- `GET /` health check
- `GET /api/services` returns `{ services: [...] }`
- `GET /api/about` returns about content
- `GET /api/contact` returns contact info
- `POST /api/submit_form` stores form submission
- `POST /api/bookings` create booking
- `POST /api/book` create booking (alias)

Swagger UI is served at:
- `/docs`
