from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.schemas.admin import AdminDatabaseRecord, AdminRestoreRecord
from app.services import database_service, backup_service
from app.utils.dependencies import require_admin_user

router = APIRouter(prefix="/admin", tags=["Admin"])


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
                document_id=row.get("$id", ""),
                user_id=row.get("user_id", ""),
                database_type=row.get("database_type", ""),
                host=row.get("host", ""),
                port=int(row.get("port", 0) or 0),
                database_name=row.get("database_name", ""),
                username=row.get("username", ""),
                status=row.get("status", "connected"),
                created_at=row.get("created_at", ""),
                updated_at=row.get("updated_at", ""),
            )
            for row in rows
        ]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/restores", response_model=list[AdminRestoreRecord])
async def list_all_restores(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_admin_user),
):
    del current_user
    try:
        result = await backup_service.list_all_restores(limit=limit, offset=offset)
        rows = result.get("rows", result.get("documents", []))
        return [
            AdminRestoreRecord(
                restore_id=row.get("$id", ""),
                user_id=row.get("user_id", ""),
                db_config_id=row.get("db_config_id", ""),
                backup_id=row.get("backup_id", ""),
                file_name=row.get("file_name", ""),
                source=row.get("source", ""),
                status=row.get("status", ""),
                message=row.get("message", ""),
                created_at=row.get("created_at", ""),
            )
            for row in rows
        ]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

