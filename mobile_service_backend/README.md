# Mobile Service Backend (Flask)

Flask backend serving REST APIs for the Mobile Service Website frontend.

## Runs on
- Port: **3001**

## Environment Variables
- `SQLITE_DB`: path to SQLite file (provided by environment; do not hardcode)
- `ALLOWED_ORIGINS`: comma-separated list of allowed origins (e.g. `http://localhost:3000,...`)

## API Endpoints
- `GET /` health check
- `GET /api/services` returns `{ services: [...] }`
- `GET /api/about` returns about content
- `GET /api/contact` returns contact info
- `POST /api/submit_form` stores form submission

Swagger UI is served at:
- `/docs`
