from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.core.appwrite_client import users
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.utils.jwt_handler import create_access_token
from app.utils.password import hash_password, verify_password, prehash_for_appwrite
from app.utils.dependencies import get_current_user
from app.services import user_service
from appwrite.query import Query
import asyncio

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=dict)
async def register(payload: RegisterRequest):
    """Register a new user in Appwrite and return a JWT token."""
    try:
        # Hash the password (SHA-256 + bcrypt) for our database
        hashed_pw = hash_password(payload.password)

        # Appwrite's built-in auth also uses bcrypt internally and has
        # the same 72-byte limit.  Send it the SHA-256 pre-hash (44 chars)
        # so ANY length password works.  We never use Appwrite's password
        # verification — we verify against our own stored hash.
        safe_pw = prehash_for_appwrite(payload.password)

        user = await asyncio.to_thread(
            users.create,
            user_id="unique()",
            email=payload.email,
            password=safe_pw,
            name=payload.name,
        )
        user_data = user.to_dict() if hasattr(user, "to_dict") else user

        # Issue a JWT right after registration
        token = create_access_token(
            data={
                "sub": user_data["$id"],
                "email": user_data["email"],
                "name": user_data["name"],
            }
        )

        # Create user profile in the database (with hashed password)
        await user_service.create_user_profile(
            user_id=user_data["$id"],
            email=user_data["email"],
            name=user_data["name"],
            password_hash=hashed_pw,
        )

        return {
            "message": "User registered successfully",
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_data["$id"],
            "name": user_data["name"],
            "email": user_data["email"],
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """
    Authenticate user by email/password.
    Verifies the bcrypt-hashed password stored in the database,
    then returns a signed JWT access token.
    """
    try:
        # 1. Find user profile by email from database
        profile = await user_service.get_user_profile_by_email(payload.email)

        if not profile:
            return JSONResponse(
                status_code=404, content={"error": "User not found"}
            )

        # 2. Verify password against stored hash
        stored_hash = profile.get("password_hash", "")
        if not stored_hash or not verify_password(payload.password, stored_hash):
            return JSONResponse(
                status_code=401, content={"error": "Invalid email or password"}
            )

        # 3. Check if user is active
        if not profile.get("is_active", True):
            return JSONResponse(
                status_code=403, content={"error": "Account is deactivated"}
            )

        user_id = profile["user_id"]

        # 4. Issue JWT
        token = create_access_token(
            data={
                "sub": user_id,
                "email": profile.get("email", ""),
                "name": profile.get("name", ""),
            }
        )

        return TokenResponse(
            access_token=token,
            user_id=user_id,
            name=profile.get("name", ""),
            email=profile.get("email", ""),
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Protected endpoints (require valid JWT) ──────────────────────────


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's info from the token."""
    return UserResponse(
        user_id=current_user["user_id"],
        name=current_user["name"],
        email=current_user["email"],
    )


@router.get("/user/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    """Get a user by ID (protected)."""
    try:
        user = await asyncio.to_thread(users.get, user_id)
        return user
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    """List all users (protected)."""
    try:
        result = await asyncio.to_thread(users.list)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
