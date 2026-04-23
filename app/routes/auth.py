from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.services.account import Account
from app.core.appwrite_client import users
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResendVerificationRequest,
    TokenResponse,
    UserResponse,
    VerificationStatusResponse,
    VerifyEmailRequest,
)
from app.config import (
    APPWRITE_EMAIL_VERIFICATION_REDIRECT_URL,
    APPWRITE_PASSWORD_RECOVERY_REDIRECT_URL,
    APPWRITE_ENDPOINT,
    EMAIL_VERIFICATION_ENABLED,
    APPWRITE_PROJECT_ID,
    USER_COLLECTION_ID,
)
from app.utils.jwt_handler import create_access_token
from app.utils.password import prehash_for_appwrite
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


def _new_account_client() -> Account:
    client = Client()
    client.set_endpoint(APPWRITE_ENDPOINT)
    client.set_project(APPWRITE_PROJECT_ID)
    return Account(client)


async def _bind_account_scope_from_session(account: Account, session_obj) -> None:
    """Attach account scope to the SDK client using session secret or JWT fallback."""
    session_data = session_obj.to_dict() if hasattr(session_obj, "to_dict") else session_obj
    if not isinstance(session_data, dict):
        return

    session_secret = str(session_data.get("secret", "") or "").strip()
    if session_secret:
        account.client.set_session(session_secret)
        return

    # Some SDK/runtime combinations may not expose session secret here.
    # Fallback to a short-lived JWT minted via admin Users API.
    session_user_id = str(session_data.get("userId", "") or "").strip()
    if session_user_id:
        jwt_obj = await asyncio.to_thread(users.create_jwt, user_id=session_user_id)
        jwt_data = jwt_obj.to_dict() if hasattr(jwt_obj, "to_dict") else jwt_obj
        jwt_token = str((jwt_data or {}).get("jwt", "") if isinstance(jwt_data, dict) else "").strip()
        if jwt_token:
            account.client.set_jwt(jwt_token)


def _normalize_appwrite_error(exc: Exception) -> tuple[int, str]:
    if not isinstance(exc, AppwriteException):
        return 500, str(exc)

    message = str(exc.message or "")
    lower_msg = message.lower()
    if "already" in lower_msg and "verif" in lower_msg:
        return 409, "Email is already verified"
    if "expired" in lower_msg or "invalid" in lower_msg or "secret" in lower_msg:
        return 400, "Invalid or expired token/link"
    if "not found" in lower_msg:
        return 404, "User not found"
    return int(exc.code or 400), message or "Appwrite request failed"


def _is_invalid_or_expired_token_error(exc: Exception) -> bool:
    if not isinstance(exc, AppwriteException):
        return False
    message = str(exc.message or "").lower()
    return ("expired" in message) or ("invalid" in message) or ("secret" in message)


async def _authenticate_and_get_appwrite_user(email: str, password: str) -> dict | None:
    """Authenticate against Appwrite and return the account payload."""
    account = _new_account_client()
    candidates = [password, prehash_for_appwrite(password)]

    for candidate in candidates:
        session_created = False
        try:
            session = await asyncio.to_thread(
                account.create_email_password_session,
                email=email,
                password=candidate,
            )
            session_created = True
            await _bind_account_scope_from_session(account, session)
            auth_user = await asyncio.to_thread(account.get)
            user_data = auth_user.to_dict() if hasattr(auth_user, "to_dict") else auth_user
            if isinstance(user_data, dict) and user_data.get("$id"):
                return user_data
        except Exception:
            continue
        finally:
            if session_created:
                try:
                    await asyncio.to_thread(account.delete_session, session_id="current")
                except Exception:
                    pass

    return None


async def _send_verification_email(email: str, password: str) -> None:
    """Create a temporary session, trigger Appwrite verification email, and clear session."""
    account = _new_account_client()
    candidates = [password, prehash_for_appwrite(password)]
    last_error: Exception | None = None

    for candidate in candidates:
        session_created = False
        try:
            session = await asyncio.to_thread(
                account.create_email_password_session,
                email=email,
                password=candidate,
            )
            session_created = True
            await _bind_account_scope_from_session(account, session)
            await asyncio.to_thread(
                account.create_verification,
                url=APPWRITE_EMAIL_VERIFICATION_REDIRECT_URL,
            )
            return
        except Exception as exc:
            last_error = exc
        finally:
            if session_created:
                try:
                    await asyncio.to_thread(account.delete_session, session_id="current")
                except Exception:
                    pass

    if last_error:
        raise last_error


async def _ensure_profile_from_auth_user(auth_user: dict) -> dict | None:
    """Ensure local profile row exists for an Appwrite auth user."""
    user_id = str(auth_user.get("$id", "") or "").strip()
    if not user_id:
        return None

    profile = await user_service.get_user_profile(user_id)
    if profile:
        return profile

    email = _normalized_email(str(auth_user.get("email", "") or ""))
    if email:
        profile = await user_service.get_user_profile_by_email(email)
        if profile:
            # If email maps to a legacy row for another user, create the missing
            # profile for the current Appwrite auth user instead.
            if str(profile.get("user_id", "")) == user_id:
                return profile

    fallback_name = str(auth_user.get("name", "") or "").strip() or (email.split("@")[0] if email else "user")
    return await user_service.create_user_profile(
        user_id=user_id,
        email=email,
        name=fallback_name,
        password_hash="",
    )


async def _ensure_profile_from_user_id(user_id: str) -> dict | None:
    """Ensure profile exists for a verified Appwrite Auth user."""
    auth_user = await asyncio.to_thread(users.get, user_id=user_id)
    auth_payload = auth_user.to_dict() if hasattr(auth_user, "to_dict") else auth_user
    if not isinstance(auth_payload, dict):
        return None
    return await _ensure_profile_from_auth_user(auth_payload)


@router.post("/register", response_model=dict)
async def register(payload: RegisterRequest):
    """Register a new user in Appwrite."""
    try:
        normalized_email = _normalized_email(payload.email)

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

        # If verification is disabled, keep legacy immediate profile creation behavior.
        if not EMAIL_VERIFICATION_ENABLED:
            await user_service.create_user_profile(
                user_id=user_data["$id"],
                email=normalized_email,
                name=user_data["name"],
                password_hash="",
            )

        verification_sent = False
        if EMAIL_VERIFICATION_ENABLED:
            await _send_verification_email(normalized_email, payload.password)
            verification_sent = True

        return {
            "message": "User registered successfully",
            "user_id": user_data["$id"],
            "name": user_data["name"],
            "email": user_data["email"],
            "email_verification_required": bool(EMAIL_VERIFICATION_ENABLED),
            "verification_email_sent": verification_sent,
        }
    except AppwriteException as e:
        message_text = str(e.message or "")
        if int(e.code or 0) == 409 and "already exists" in message_text.lower():
            existing_user = await _find_appwrite_user_by_email(_normalized_email(payload.email))
            if not existing_user:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "User already exists. Please login or reset password."},
                )

            synced_profile = await _ensure_profile_from_auth_user(existing_user)
            auth_user_id = str(existing_user.get("$id", "") or "")
            synced_user_id = str((synced_profile or {}).get("user_id", "") or "")

            # Strong confirmation: profile must be readable from the user table by auth user id.
            confirmed_profile = await user_service.get_user_profile(auth_user_id)
            confirmed_user_id = str((confirmed_profile or {}).get("user_id", "") or "")

            if not synced_profile or synced_user_id != auth_user_id or not confirmed_profile or confirmed_user_id != auth_user_id:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "User exists in Appwrite Auth, but profile sync failed. Please contact admin.",
                        "user_id": auth_user_id,
                        "profile_table": USER_COLLECTION_ID,
                    },
                )

            return JSONResponse(
                status_code=200,
                content={
                    "message": "User already exists. Profile synchronized.",
                    "user_id": existing_user.get("$id", ""),
                    "name": existing_user.get("name", ""),
                    "email": existing_user.get("email", _normalized_email(payload.email)),
                    "profile_table": USER_COLLECTION_ID,
                    "profile_row_id": str(confirmed_profile.get("$id", auth_user_id)),
                },
            )

        status_code, message = _normalize_appwrite_error(e)
        return JSONResponse(status_code=status_code, content={"detail": message})
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

        if not appwrite_user:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid email or password"},
            )

        if EMAIL_VERIFICATION_ENABLED and not bool(appwrite_user.get("emailVerification", False)):
            return JSONResponse(
                status_code=403,
                content={"error": "Email not verified"},
            )

        appwrite_user_id = str(appwrite_user.get("$id", ""))
        profile = await user_service.get_user_profile(appwrite_user_id)
        if not profile:
            # Fallback by email in case row id is not aligned with auth user id.
            profile = await user_service.get_user_profile_by_email(normalized_email)

            # If email resolves to a legacy profile row, do not issue tokens for that old id.
            if profile and str(profile.get("user_id", "")) != appwrite_user_id:
                fallback_name = str(appwrite_user.get("name", "")).strip() or normalized_email.split("@")[0]
                profile = await user_service.create_user_profile(
                    user_id=appwrite_user_id,
                    email=normalized_email,
                    name=fallback_name,
                    password_hash="",
                )

        if not profile:
            fallback_name = str(appwrite_user.get("name", "")).strip() or normalized_email.split("@")[0]
            profile = await user_service.create_user_profile(
                user_id=appwrite_user_id,
                email=normalized_email,
                name=fallback_name,
                password_hash="",
            )

        # 3. Check if user is active
        profile_status = str(profile.get("status", "active") or "active").strip().lower()
        if profile_status == "suspended" or not profile.get("is_active", True):
            return JSONResponse(
                status_code=403, content={"error": "Account is suspended"}
            )

        # Always bind auth to the Appwrite auth user id (source of truth).
        user_id = appwrite_user_id

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


@router.get("/verify-email", response_model=dict)
async def verify_email_get(userId: str, secret: str):
    """Handle Appwrite verification callback from frontend URL query params."""
    if not EMAIL_VERIFICATION_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"success": False, "message": "Email verification is temporarily disabled"},
        )
    try:
        account = _new_account_client()
        await asyncio.to_thread(account.update_verification, user_id=userId, secret=secret)
        await _ensure_profile_from_user_id(userId)
        return {"success": True, "message": "Email verified successfully"}
    except AppwriteException as e:
        # Idempotent behavior: old/used links should still report success if
        # account is already verified.
        if _is_invalid_or_expired_token_error(e):
            try:
                auth_user = await asyncio.to_thread(users.get, user_id=userId)
                auth_payload = auth_user.to_dict() if hasattr(auth_user, "to_dict") else auth_user
                if bool((auth_payload or {}).get("emailVerification", False)):
                    await _ensure_profile_from_user_id(userId)
                    return {"success": True, "message": "Email already verified"}
            except Exception:
                pass

        status_code, message = _normalize_appwrite_error(e)
        return JSONResponse(status_code=status_code, content={"success": False, "message": message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/verify-email", response_model=dict)
async def verify_email_post(payload: VerifyEmailRequest):
    """Alternative verification endpoint for frontend POST callback handling."""
    if not EMAIL_VERIFICATION_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"success": False, "message": "Email verification is temporarily disabled"},
        )
    return await verify_email_get(userId=payload.user_id, secret=payload.secret)


@router.post("/resend-verification", response_model=dict)
async def resend_verification(payload: ResendVerificationRequest):
    """Resend Appwrite verification email for users who are not verified yet."""
    if not EMAIL_VERIFICATION_ENABLED:
        return JSONResponse(
            status_code=503,
            content={"success": False, "message": "Email verification is temporarily disabled"},
        )
    try:
        normalized_email = _normalized_email(payload.email)
        user_data = await _authenticate_and_get_appwrite_user(normalized_email, payload.password)
        if not user_data:
            return JSONResponse(status_code=401, content={"error": "Invalid email or password"})

        if bool(user_data.get("emailVerification", False)):
            return JSONResponse(status_code=409, content={"error": "Email is already verified"})

        await _send_verification_email(normalized_email, payload.password)
        return {
            "success": True,
            "message": "Verification email sent",
            "verification_redirect_url": APPWRITE_EMAIL_VERIFICATION_REDIRECT_URL,
        }
    except AppwriteException as e:
        status_code, message = _normalize_appwrite_error(e)
        return JSONResponse(status_code=status_code, content={"success": False, "message": message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/forgot-password", response_model=dict)
async def forgot_password(payload: ForgotPasswordRequest):
    """Trigger Appwrite password recovery email."""
    try:
        account = _new_account_client()
        await asyncio.to_thread(
            account.create_recovery,
            email=_normalized_email(payload.email),
            url=APPWRITE_PASSWORD_RECOVERY_REDIRECT_URL,
        )
        return {
            "success": True,
            "message": "If the account exists, a password reset email has been sent.",
            "reset_redirect_url": APPWRITE_PASSWORD_RECOVERY_REDIRECT_URL,
        }
    except AppwriteException:
        # Prevent user enumeration by returning a generic success message.
        return {
            "success": True,
            "message": "If the account exists, a password reset email has been sent.",
            "reset_redirect_url": APPWRITE_PASSWORD_RECOVERY_REDIRECT_URL,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/reset-password", response_model=dict)
async def reset_password(payload: ResetPasswordRequest):
    """Complete password reset using Appwrite recovery userId + secret."""
    if payload.password != payload.confirm_password:
        return JSONResponse(status_code=400, content={"success": False, "message": "Passwords do not match"})

    try:
        account = _new_account_client()
        safe_password = prehash_for_appwrite(payload.password)
        await asyncio.to_thread(
            account.update_recovery,
            user_id=payload.user_id,
            secret=payload.secret,
            password=safe_password,
            password_again=safe_password,
        )
        return {"success": True, "message": "Password reset successful"}
    except AppwriteException as e:
        status_code, message = _normalize_appwrite_error(e)
        if status_code == 400:
            message = "Invalid or expired password reset link"
        return JSONResponse(status_code=status_code, content={"success": False, "message": message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/verification-status", response_model=VerificationStatusResponse)
async def verification_status(current_user: dict = Depends(get_current_user)):
    """Post-login guard endpoint to check whether the authenticated user is verified."""
    if not EMAIL_VERIFICATION_ENABLED:
        return VerificationStatusResponse(
            user_id=current_user["user_id"],
            email=current_user.get("email", ""),
            email_verified=True,
        )
    try:
        auth_user = await asyncio.to_thread(users.get, user_id=current_user["user_id"])
        auth_payload = auth_user.to_dict() if hasattr(auth_user, "to_dict") else auth_user
        return VerificationStatusResponse(
            user_id=current_user["user_id"],
            email=str((auth_payload or {}).get("email", current_user.get("email", ""))),
            email_verified=bool((auth_payload or {}).get("emailVerification", False)),
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
