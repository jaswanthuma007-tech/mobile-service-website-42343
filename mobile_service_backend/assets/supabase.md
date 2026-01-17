# Supabase integration (Mobile Service Backend)

This backend is migrating from local SQLite to **Supabase Postgres** as the primary database for:
- bookings (create/update/list/admin status updates/track)
- customer_requests (submit_form)
- site_content (about/contact)
- device catalog (brands/models/repair services)
- optionally `services` section (legacy table in SQLite)

The Flask backend uses the Supabase Python client to access PostgREST.

---

## Required environment variables

Add these to the backend `.env` (do not hardcode them in code):

- `SUPABASE_URL`  
  Example: `https://<project-ref>.supabase.co`

- `SUPABASE_SERVICE_ROLE_KEY`  
  Service role key (server-side only). Required because the backend performs admin reads/writes.  
  IMPORTANT: Never expose this key to the browser.

Optional / recommended:
- `SUPABASE_SCHEMA` (default: `public`)  
  If you place tables in a different schema.

Existing env vars remain used:
- `ALLOWED_ORIGINS`, `ADMIN_API_KEY`, `ADMIN_LOGIN_ENABLED`, `ADMIN_TOKENS`, etc.

---

## Database schema (tables)

Create the following tables in Supabase (SQL editor). Types are suggestions; keep them close to current SQLite structure.

### 1) bookings

**Authoritative requirements (migration attachment):**
- `id` UUID primary key
- `name` text
- `phone` varchar(10)
- `pincode` varchar(6)
- `brand` text
- `model` text
- `service` text
- `status` text enum-like (Pending, In Progress, Completed)
- `created_at` timestamp

Recommended additional columns (optional but useful for admin ops):
- `updated_at` timestamptz default now()
- `notes` text null

#### SQL (run in Supabase SQL editor)

```sql
-- Needed for gen_random_uuid()
create extension if not exists pgcrypto;

create table if not exists public.bookings (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  phone varchar(10) not null,
  pincode varchar(6) not null,
  brand text null,
  model text null,
  service text null,
  status text not null default 'Pending'
    check (status in ('Pending','In Progress','Completed')),
  notes text null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists bookings_phone_idx on public.bookings (phone);
create index if not exists bookings_created_at_idx on public.bookings (created_at desc);

-- updated_at trigger
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_bookings_updated_at on public.bookings;
create trigger trg_bookings_updated_at
before update on public.bookings
for each row execute function public.set_updated_at();
```

#### RLS policies (public insert; admin-only read/update via service role)

Notes:
- Your Flask backend uses `SUPABASE_SERVICE_ROLE_KEY`. The **service role bypasses RLS**, so it can read/update bookings regardless of policies.
- These policies are for future-proofing (e.g., if you ever use anon/authenticated keys directly from the client).

```sql
alter table public.bookings enable row level security;

-- Public can create a booking (required for POST /book or /api/bookings if ever done client-side)
drop policy if exists "public_insert_bookings" on public.bookings;
create policy "public_insert_bookings"
on public.bookings
for insert
to anon, authenticated
with check (true);

-- Public cannot read/update/delete bookings
drop policy if exists "public_select_bookings" on public.bookings;
drop policy if exists "public_update_bookings" on public.bookings;
drop policy if exists "public_delete_bookings" on public.bookings;

-- If you later add Supabase Auth and want a customer to read their own booking,
-- you must add an ownership model (e.g., user_id) or a secure function.
```

### 2) customer_requests

- `id` bigint identity pk
- `name` text not null
- `phone` text not null
- `email` text not null
- `mobile_model` text not null
- `problem` text not null
- `created_at` timestamptz not null default now()

### 3) site_content

- `key` text primary key
- `value` text not null
- `updated_at` timestamptz not null default now()

Seed keys (same as backend defaults):
- `about_description`
- `contact_hours`
- `contact_phone`
- `contact_email`

### 4) device_brands

- `id` bigint identity pk
- `name` text unique not null
- `sort_order` int not null default 0

### 5) device_models

- `id` bigint identity pk
- `brand` text not null
- `name` text not null
- `sort_order` int not null default 0

### 6) repair_services

- `id` bigint identity pk
- `title` text not null
- `icon` text null
- `price_hint` text null
- `sort_order` int not null default 0

### 7) services (optional legacy)

If the frontend uses `/api/services` and expects the older catalog:
- `id` bigint identity pk
- `title` text not null
- `description` text not null
- `icon` text null
- `price_hint` text null
- `sort_order` int not null default 0
- `created_at` timestamptz not null default now()

---

## Row Level Security (RLS)

Because this backend is server-side and uses `SUPABASE_SERVICE_ROLE_KEY`, RLS can remain enabled without blocking server operations.
However, you should still configure sensible policies for any future client-side use.

Recommended:
- Enable RLS on all tables.
- Start with **no anon/user policies** (deny by default).
- If later exposing read-only data to anon users:
  - allow SELECT on `device_brands`, `device_models`, `repair_services`, `site_content`, `services`
  - keep `bookings` and `customer_requests` restricted.

---

## Notes on security / architecture

- The backend uses `SUPABASE_SERVICE_ROLE_KEY` and therefore can bypass RLS. Treat the backend as a trusted server component.
- Admin authentication in this project is still handled by backend env-based token rules (not Supabase Auth).
- Do not store Supabase keys in frontend env vars.

---
