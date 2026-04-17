from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from appwrite.client import Client
from appwrite.services.account import Account
from app.core.appwrite_client import users
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.config import APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID
from app.utils.jwt_handler import create_access_token
from app.utils.password import hash_password, verify_password, prehash_for_appwrite
from app.utils.dependencies import get_current_user
from app.services import user_service
from appwrite.query import Query
import asyncio

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _normalized_email(email: str) -> str:
    return (email or "").strip().lower()


async def _find_appwrite_user_by_email(email: str) -> dict | None:
    normalized_email = _normalized_email(email)

    def _extract_users(result_obj) -> list[dict]:
        payload = result_obj.to_dict() if hasattr(result_obj, "to_dict") else result_obj
        if not isinstance(payload, dict):
            return []
        rows = payload.get("users", [])
        return rows if isinstance(rows, list) else []

    # Strategy 1: direct Query.equal("email", ...)
    try:
        result = await asyncio.to_thread(
            users.list,
            queries=[Query.equal("email", normalized_email), Query.limit(1)],
        )
        rows = _extract_users(result)
        if rows:
            return rows[0]
    except Exception:
        pass

    # Strategy 2: search mode (supported in many Appwrite versions)
    try:
        result = await asyncio.to_thread(users.list, search=normalized_email)
        rows = _extract_users(result)
        for row in rows:
            if _normalized_email(str(row.get("email", ""))) == normalized_email:
                return row
    except Exception:
        pass

    # Strategy 3: paginated scan fallback for compatibility.
    page_limit = 100
    offset = 0
    while True:
        try:
            result = await asyncio.to_thread(
                users.list,
                queries=[Query.limit(page_limit), Query.offset(offset)],
            )
        except Exception:
            break

        rows = _extract_users(result)
        if not rows:
            break

        for row in rows:
            if _normalized_email(str(row.get("email", ""))) == normalized_email:
                return row

        if len(rows) < page_limit:
            break
        offset += page_limit

    return None


async def _verify_appwrite_credentials(email: str, password: str) -> bool:
    client = Client()
    client.set_endpoint(APPWRITE_ENDPOINT)
    client.set_project(APPWRITE_PROJECT_ID)
    account = Account(client)

    # Try plain password first (normal Appwrite users), then prehash variant
    # for users created through backend docs flow.
    candidates = [password, prehash_for_appwrite(password)]
    for candidate in candidates:
        try:
            session = await asyncio.to_thread(
                account.create_email_password_session,
                email=email,
                password=candidate,
            )
            session_data = session.to_dict() if hasattr(session, "to_dict") else session
            session_id = (session_data or {}).get("$id", "") if isinstance(session_data, dict) else ""
            if session_id:
                try:
                    await asyncio.to_thread(account.delete_session, session_id="current")
                except Exception:
                    pass
            return True
        except Exception:
            continue

    return False


async def _authenticate_and_get_appwrite_user(email: str, password: str) -> dict | None:
    """Authenticate with Appwrite and return the authenticated user payload."""
    client = Client()
    client.set_endpoint(APPWRITE_ENDPOINT)
    client.set_project(APPWRITE_PROJECT_ID)
    account = Account(client)

    candidates = [password, prehash_for_appwrite(password)]
    for candidate in candidates:
        try:
            session = await asyncio.to_thread(
                account.create_email_password_session,
                email=email,
                password=candidate,
            )

            session_data = session.to_dict() if hasattr(session, "to_dict") else session
            session_user_id = ""
            if isinstance(session_data, dict):
                session_user_id = str(session_data.get("userId", "") or "")

            user_data = None
            if session_user_id:
                # Minimal identity from session is enough for login/profile sync.
                user_data = {
                    "$id": session_user_id,
                    "email": _normalized_email(email),
                    "name": "",
                }

                # Best-effort enrichment when Users read scope is available.
                try:
                    fetched = await asyncio.to_thread(users.get, user_id=session_user_id)
                    fetched_data = fetched.to_dict() if hasattr(fetched, "to_dict") else fetched
                    if isinstance(fetched_data, dict):
                        user_data.update(
                            {
                                "email": fetched_data.get("email", user_data["email"]),
                                "name": fetched_data.get("name", user_data["name"]),
                            }
                        )
                except Exception:
                    pass

            if not user_data:
                try:
                    auth_user = await asyncio.to_thread(account.get)
                    user_data = auth_user.to_dict() if hasattr(auth_user, "to_dict") else auth_user
                except Exception:
                    user_data = None

            try:
                await asyncio.to_thread(account.delete_session, session_id="current")
            except Exception:
                pass

            if isinstance(user_data, dict) and user_data.get("$id"):
                return user_data
        except Exception:
            continue

    return None


@router.post("/register", response_model=dict)
async def register(payload: RegisterRequest):
    """Register a new user in Appwrite and return a JWT token."""
    try:
        normalized_email = _normalized_email(payload.email)

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
            email=normalized_email,
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
            email=normalized_email,
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
        return JSONResponse(status_code=400, content={"detail": str(e)})


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """
    Authenticate user by email/password.
    Verifies the bcrypt-hashed password stored in the database,
    then returns a signed JWT access token.
    """
    try:
        normalized_email = _normalized_email(payload.email)

        # 1) Primary path: authenticate with Appwrite (matches frontend behavior).
        appwrite_user = await _authenticate_and_get_appwrite_user(
            normalized_email,
            payload.password,
        )

        profile = None
        if appwrite_user:
            appwrite_user_id = str(appwrite_user.get("$id", ""))
            profile = await user_service.get_user_profile(appwrite_user_id)
            if not profile:
                # Fallback by email in case row id is not aligned with auth user id.
                profile = await user_service.get_user_profile_by_email(normalized_email)

            if not profile:
                fallback_name = str(appwrite_user.get("name", "")).strip() or normalized_email.split("@")[0]
                profile = await user_service.create_user_profile(
                    user_id=appwrite_user_id,
                    email=normalized_email,
                    name=fallback_name,
                    password_hash=hash_password(payload.password),
                )
        else:
            # 2) Legacy fallback: local profile + bcrypt hash verification.
            profile = await user_service.get_user_profile_by_email(normalized_email)
            if not profile:
                return JSONResponse(
                    status_code=404, content={"error": "User not found"}
                )

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
        # token = create_access_token(
        #     data={
        #         "sub": user_id,
        #         "email": profile.get("email", ""),
        #         "name": profile.get("name", ""),
        #     }
        # )
        token = create_access_token(
            data={
                "sub": user_id,
                "user_id": user_id,
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
