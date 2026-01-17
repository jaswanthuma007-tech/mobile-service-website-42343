import os
from functools import lru_cache


from supabase import Client, create_client


def _env(name: str) -> str:
    """Read an env var with safe stripping."""
    return (os.environ.get(name) or "").strip()


def _required_env(name: str) -> str:
    """Read required environment variable or raise a clear error."""
    value = _env(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            "Set it in the backend .env to enable Supabase/Postgres persistence."
        )
    return value


def _pick_supabase_key() -> str:
    """Pick a Supabase API key for server-side PostgREST access.

    Preference order:
      1) SUPABASE_SERVICE_ROLE_KEY (recommended for server, bypasses RLS)
      2) SUPABASE_ANON_KEY (fallback so dev can still start the backend)

    NOTE: Using anon key may be blocked by RLS depending on your Supabase policies.
    """
    service_role = _env("SUPABASE_SERVICE_ROLE_KEY")
    if service_role:
        return service_role

    anon = _env("SUPABASE_ANON_KEY")
    if anon:
        return anon

    # Neither provided: raise a single clear error message.
    raise RuntimeError(
        "Missing required environment variable SUPABASE_SERVICE_ROLE_KEY (preferred) "
        "or SUPABASE_ANON_KEY (fallback). Set it in the backend .env to enable Supabase."
    )


# PUBLIC_INTERFACE
@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached Supabase client (created lazily on first use).

    Environment variables:
      - SUPABASE_URL
      - SUPABASE_SERVICE_ROLE_KEY (preferred)
      - SUPABASE_ANON_KEY (fallback)
    """
    url = _required_env("SUPABASE_URL")
    key = _pick_supabase_key()
    return create_client(url, key)


# PUBLIC_INTERFACE
def get_supabase_schema() -> str:
    """Return the Supabase schema name (defaults to 'public')."""
    return (_env("SUPABASE_SCHEMA") or "public") or "public"
