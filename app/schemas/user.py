from pydantic import BaseModel
from typing import Optional


class CreateUserProfile(BaseModel):
    """Schema for creating a user profile document in the database."""
    phone: Optional[str] = None
    bio: Optional[str] = None


class UpdateUserProfile(BaseModel):
    """Schema for updating a user profile document."""
    name: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None


class UserProfileResponse(BaseModel):
    """Schema for returning user profile data."""
    user_id: str
    email: str
    name: str
    phone: Optional[str] = None
    bio: Optional[str] = None
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

