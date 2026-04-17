from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.schemas.admin import AdminBackupRecord, AdminDatabaseRecord
from app.services import database_service, backup_service
from app.utils.dependencies import require_admin_user

router = APIRouter(prefix="/admin", tags=["Admin"])


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _format_storage_label(total_size: int) -> str:
    if total_size >= 1024 ** 3:
        return f"{round(total_size / (1024 ** 3), 2)} GB"
    return f"{round(total_size / (1024 ** 2), 2)} MB"


@router.get("/databases", response_model=list[AdminDatabaseRecord])
async def list_all_databases(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_admin_user),
):
    del current_user
    try:
        result = await database_service.list_all_databases(limit=limit, offset=offset)
        rows = result.get("rows", result.get("documents", []))
        return [
            AdminDatabaseRecord(
                document_id=str(row.get("$id") or row.get("document_id") or ""),
                user_id=str(row.get("user_id") or ""),
                database_type=str(row.get("database_type") or ""),
                host=str(row.get("host") or ""),
                port=_safe_int(row.get("port"), 0),
                database_name=str(row.get("database_name") or ""),
                username=str(row.get("username") or ""),
                status=str(row.get("status") or "connected"),
                created_at=str(row.get("created_at") or row.get("$createdAt") or ""),
                updated_at=str(row.get("updated_at") or row.get("$updatedAt") or ""),
            )
            for row in rows
        ]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/backups", response_model=list[AdminBackupRecord])
async def list_all_backups(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_admin_user),
):
    del current_user
    try:
        result = await backup_service.list_all_backups(limit=limit, offset=offset)
        rows = result.get("rows", result.get("documents", []))
        return [
            AdminBackupRecord(
                backup_id=str(row.get("$id") or row.get("backup_id") or ""),
                db_config_id=str(row.get("db_config_id") or ""),
                user_id=str(row.get("user_id") or ""),
                database_type=str(row.get("database_type") or ""),
                database_name=str(row.get("database_name") or ""),
                file_name=str(row.get("file_name") or ""),
                file_size=_safe_int(row.get("file_size"), 0),
                status=str(row.get("status") or ""),
                compression=str(row.get("compression") or "none"),
                encryption=str(row.get("encryption") or "none"),
                created_at=str(row.get("created_at") or row.get("$createdAt") or ""),
            )
            for row in rows
        ]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# @router.get("/restores", response_model=list[AdminRestoreRecord])
# async def list_all_restores(
#     limit: int = Query(default=50, ge=1, le=200),
#     offset: int = Query(default=0, ge=0),
#     current_user: dict = Depends(require_admin_user),
# ):
#     del current_user
#     try:
#         result = await backup_service.list_all_restores(limit=limit, offset=offset)
#         rows = result.get("rows", result.get("documents", []))
#         return [
#             AdminRestoreRecord(
#                 restore_id=row.get("$id", ""),
#                 user_id=row.get("user_id", ""),
#                 db_config_id=row.get("db_config_id", ""),
#                 backup_id=row.get("backup_id", ""),
#                 file_name=row.get("file_name", ""),
#                 source=row.get("source", ""),
#                 status=row.get("status", ""),
#                 message=row.get("message", ""),
#                 created_at=row.get("created_at", ""),
#             )
#             for row in rows
#         ]
#     except Exception as e:
#         return JSONResponse(status_code=500, content={"error": str(e)})
@router.get("/dashboard")
async def admin_dashboard(
    current_user: dict = Depends(require_admin_user),
):
    del current_user

    try:
        # Get all databases (paged)
        db_rows = []
        db_offset = 0
        db_limit = 200
        while True:
            dbs = await database_service.list_all_databases(limit=db_limit, offset=db_offset)
            page = dbs.get("rows", dbs.get("documents", []))
            if not page:
                break
            db_rows.extend(page)
            if len(page) < db_limit:
                break
            db_offset += db_limit

        # Get all backups (paged)
        backup_rows = []
        backup_offset = 0
        backup_limit = 200
        while True:
            backups = await backup_service.list_all_backups(limit=backup_limit, offset=backup_offset)
            page = backups.get("rows", backups.get("documents", []))
            if not page:
                break
            backup_rows.extend(page)
            if len(page) < backup_limit:
                break
            backup_offset += backup_limit

        # Counts
        total_databases = len(db_rows)
        total_backups = len(backup_rows)

        failed_backups = len([
            b for b in backup_rows
            if b.get("status", "").lower() == "failed"
        ])

        success_backups = len([
            b for b in backup_rows
            if b.get("status", "").lower() == "success"
        ])

        running_jobs = len([
            b for b in backup_rows
            if b.get("status", "").lower() == "running"
        ])

        # Success %
        success_rate = 0
        if total_backups > 0:
            success_rate = round((success_backups / total_backups) * 100)

        # Storage used across all users + per-user breakdown.
        total_size = 0
        user_storage: dict[str, dict] = {}
        for row in backup_rows:
            user_id = str(row.get("user_id", "") or "unknown")
            size = _safe_int(row.get("file_size", 0))
            total_size += size

            bucket = user_storage.setdefault(user_id, {"user_id": user_id, "backup_count": 0, "storage_used_bytes": 0})
            bucket["backup_count"] += 1
            bucket["storage_used_bytes"] += size

        storage_gb = round(total_size / (1024 ** 3), 2)
        user_storage_usage = []
        for item in user_storage.values():
            bytes_used = item["storage_used_bytes"]
            user_storage_usage.append(
                {
                    "user_id": item["user_id"],
                    "backup_count": item["backup_count"],
                    "storage_used_bytes": bytes_used,
                    "storage_used_mb": round(bytes_used / (1024 ** 2), 2),
                    "storage_used_gb": round(bytes_used / (1024 ** 3), 4),
                }
            )
        user_storage_usage.sort(key=lambda x: x["storage_used_bytes"], reverse=True)

        return {
            "total_databases": total_databases,
            "total_backups": total_backups,
            "success_rate": success_rate,
            "failed_backups": failed_backups,
            "storage_used": _format_storage_label(total_size),
            "storage_used_bytes": total_size,
            "storage_used_mb": round(total_size / (1024 ** 2), 2),
            "active_jobs": running_jobs,
            "user_storage_usage": user_storage_usage,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

