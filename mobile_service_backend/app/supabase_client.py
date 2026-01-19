import os
from functools import lru_cache

from supabase import Client, create_client


def _required_env(name: str) -> str:
    """Read required environment variable or raise a clear error."""
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            "Set it in the backend .env to enable Supabase/Postgres persistence."
        )
    return value


# PUBLIC_INTERFACE
def is_supabase_configured() -> bool:
    """Return True if required Supabase environment variables are present.

    This helper lets the app start in a limited mode when Supabase isn't configured yet.
    Required env vars:
      - SUPABASE_URL
      - SUPABASE_SERVICE_ROLE_KEY
    """
    return bool((os.environ.get("SUPABASE_URL") or "").strip()) and bool(
        (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    )


# PUBLIC_INTERFACE
@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached Supabase client.

    Environment variables:
      - SUPABASE_URL
      - SUPABASE_SERVICE_ROLE_KEY
    """
    url = _required_env("SUPABASE_URL")
    key = _required_env("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


# PUBLIC_INTERFACE
def get_supabase_schema() -> str:
    """Return the Supabase schema name (defaults to 'public')."""
    return (os.environ.get("SUPABASE_SCHEMA") or "public").strip() or "public"
