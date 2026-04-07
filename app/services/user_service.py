import asyncio
from datetime import datetime, timezone
from typing import Optional

from appwrite.query import Query

from app.core.appwrite_client import tables   # ← new TablesDB API
from app.config import DATABASE_ID, USER_COLLECTION_ID
from app.utils.appwrite_normalize import normalize_row, normalize_row_collection


async def create_user_profile(
    user_id: str,
    email: str,
    name: str,
    password_hash: str = "",
    phone: Optional[str] = None,
    bio: Optional[str] = None,
) -> dict:
    """Create a new user profile row in the Appwrite database."""
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "password_hash": password_hash,
        "phone": phone or "",
        "bio": bio or "",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    response = await asyncio.to_thread(
        tables.create_row,
        database_id=DATABASE_ID,
        table_id=USER_COLLECTION_ID,
        row_id=user_id,   # use auth user_id as row id
        data=data,
    )
    return normalize_row(response)


async def get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch a single user profile by user_id."""
    try:
        response = await asyncio.to_thread(
            tables.get_row,
            database_id=DATABASE_ID,
            table_id=USER_COLLECTION_ID,
            row_id=user_id,
        )
        normalized = normalize_row(response)
        return normalized or None
    except Exception:
        return None


async def get_user_profile_by_email(email: str) -> Optional[dict]:
    """Fetch a user profile by email."""
    result = await asyncio.to_thread(
        tables.list_rows,
        database_id=DATABASE_ID,
        table_id=USER_COLLECTION_ID,
        queries=[Query.equal("email", email)],
    )
    rows = normalize_row_collection(result).get("rows", [])
    return rows[0] if rows else None


async def update_user_profile(
    user_id: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    bio: Optional[str] = None,
) -> dict:
    """Update an existing user profile row."""
    data: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if name is not None:
        data["name"] = name
    if phone is not None:
        data["phone"] = phone
    if bio is not None:
        data["bio"] = bio

    response = await asyncio.to_thread(
        tables.update_row,
        database_id=DATABASE_ID,
        table_id=USER_COLLECTION_ID,
        row_id=user_id,
        data=data,
    )
    return normalize_row(response)


async def delete_user_profile(user_id: str) -> None:
    """Delete a user profile row from the database."""
    await asyncio.to_thread(
        tables.delete_row,
        database_id=DATABASE_ID,
        table_id=USER_COLLECTION_ID,
        row_id=user_id,
    )


async def list_user_profiles(limit: int = 25, offset: int = 0) -> dict:
    """List user profile rows with pagination."""
    response = await asyncio.to_thread(
        tables.list_rows,
        database_id=DATABASE_ID,
        table_id=USER_COLLECTION_ID,
        queries=[
            Query.limit(limit),
            Query.offset(offset),
        ],
    )
    return normalize_row_collection(response)
