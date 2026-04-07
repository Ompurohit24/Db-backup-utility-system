from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.schemas.user import CreateUserProfile, UpdateUserProfile, UserProfileResponse
from app.services import user_service
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/profile", response_model=UserProfileResponse)
async def create_profile(
    payload: CreateUserProfile,
    current_user: dict = Depends(get_current_user),
):
    """Create a database profile for the currently authenticated user."""
    try:
        # Check if profile already exists
        existing = await user_service.get_user_profile(current_user["user_id"])
        if existing:
            return JSONResponse(
                status_code=409,
                content={"error": "Profile already exists for this user"},
            )

        doc = await user_service.create_user_profile(
            user_id=current_user["user_id"],
            email=current_user["email"],
            name=current_user["name"],
            phone=payload.phone,
            bio=payload.bio,
        )
        return UserProfileResponse(
            user_id=doc["user_id"],
            email=doc["email"],
            name=doc["name"],
            phone=doc.get("phone"),
            bio=doc.get("bio"),
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at", ""),
            updated_at=doc.get("updated_at", ""),
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/profile", response_model=UserProfileResponse)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Fetch the current user's database profile."""
    try:
        doc = await user_service.get_user_profile(current_user["user_id"])
        if not doc:
            return JSONResponse(
                status_code=404, content={"error": "Profile not found"}
            )
        return UserProfileResponse(
            user_id=doc["user_id"],
            email=doc["email"],
            name=doc["name"],
            phone=doc.get("phone"),
            bio=doc.get("bio"),
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at", ""),
            updated_at=doc.get("updated_at", ""),
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.put("/profile", response_model=UserProfileResponse)
async def update_my_profile(
    payload: UpdateUserProfile,
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's database profile."""
    try:
        doc = await user_service.update_user_profile(
            user_id=current_user["user_id"],
            name=payload.name,
            phone=payload.phone,
            bio=payload.bio,
        )
        return UserProfileResponse(
            user_id=doc["user_id"],
            email=doc["email"],
            name=doc["name"],
            phone=doc.get("phone"),
            bio=doc.get("bio"),
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at", ""),
            updated_at=doc.get("updated_at", ""),
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.delete("/profile")
async def delete_my_profile(current_user: dict = Depends(get_current_user)):
    """Delete the current user's database profile."""
    try:
        await user_service.delete_user_profile(current_user["user_id"])
        return {"message": "Profile deleted successfully"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/", response_model=list[UserProfileResponse])
async def list_profiles(
    limit: int = 25,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
):
    """List all user profiles (protected)."""
    try:
        result = await user_service.list_user_profiles(limit=limit, offset=offset)
        return [
            UserProfileResponse(
                user_id=doc["user_id"],
                email=doc["email"],
                name=doc["name"],
                phone=doc.get("phone"),
                bio=doc.get("bio"),
                is_active=doc.get("is_active", True),
                created_at=doc.get("created_at", ""),
                updated_at=doc.get("updated_at", ""),
            )
            for doc in result.get("rows", result.get("documents", []))
        ]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

