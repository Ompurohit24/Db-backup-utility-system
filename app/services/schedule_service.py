"""Service layer for scheduled backups using APScheduler and Appwrite Tables."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from appwrite.query import Query
from appwrite.exception import AppwriteException

from app.config import (
    DATABASE_ID,
    BACKUP_SCHEDULES_COLLECTION_ID,
    DEFAULT_TIMEZONE,
)
from app.core.appwrite_client import tables
from app.logger import get_logger
from app.services import backup_service
from app.services.database_service import get_user_database
from app.utils.appwrite_normalize import normalize_row, normalize_row_collection
from app.utils.scheduler import get_next_run, remove_job, scheduler_startup, upsert_job


log = get_logger("scheduler")


def _build_cron_expression(
    *, frequency: str, time_str: Optional[str], day_of_week: Optional[str], cron_expression: Optional[str]
) -> str:
    if frequency == "daily":
        hour, minute = map(int, (time_str or "00:00").split(":"))
        return f"{minute} {hour} * * *"
    if frequency == "weekly":
        hour, minute = map(int, (time_str or "00:00").split(":"))
        dow = (day_of_week or "sun").lower()
        return f"{minute} {hour} * * {dow}"
    if frequency == "cron" and cron_expression:
        return cron_expression
    raise ValueError("Invalid schedule parameters")


def _normalize_timezone(tz_str: Optional[str]) -> str:
    tz = tz_str or DEFAULT_TIMEZONE
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        log.warning("Invalid timezone '%s', falling back to %s", tz, DEFAULT_TIMEZONE)
        return DEFAULT_TIMEZONE


def _cron_trigger(expression: str, tz: Optional[str]) -> CronTrigger:
    safe_tz = _normalize_timezone(tz)
    return CronTrigger.from_crontab(expression, timezone=ZoneInfo(safe_tz))


async def _run_scheduled_backup(schedule_row: dict) -> None:
    try:
        await backup_service.trigger_backup(
            db_config_id=schedule_row["db_config_id"],
            user_id=schedule_row["user_id"],
            role="system",
            ip_address=None,
            device_info="scheduler",
        )
        log.info("Scheduled backup finished schedule_id=%s", schedule_row.get("$id"))
    except Exception as exc:  # pragma: no cover - defensive
        log.error(
            "Scheduled backup failed schedule_id=%s db_config_id=%s error=%s",
            schedule_row.get("$id"),
            schedule_row.get("db_config_id"),
            exc,
        )


async def create_schedule(
    *,
    user_id: str,
    frequency: str,
    db_config_id: str,
    time_str: Optional[str],
    day_of_week: Optional[str],
    cron_expression: Optional[str],
    timezone_str: Optional[str],
    enabled: bool,
    description: Optional[str],
) -> dict:
    if not BACKUP_SCHEDULES_COLLECTION_ID:
        raise RuntimeError("BACKUP_SCHEDULES_COLLECTION_ID is not configured")

    # Ensure the DB config belongs to the user.
    db_doc = await get_user_database(db_config_id)
    if not db_doc or db_doc.get("user_id") != user_id:
        raise PermissionError("Database configuration not found for this user")

    cron_expr = _build_cron_expression(
        frequency=frequency,
        time_str=time_str,
        day_of_week=day_of_week,
        cron_expression=cron_expression,
    )
    tz = _normalize_timezone(timezone_str or DEFAULT_TIMEZONE)

    row = await asyncio.to_thread(
        tables.create_row,
        database_id=DATABASE_ID,
        table_id=BACKUP_SCHEDULES_COLLECTION_ID,
        row_id="unique()",
        data={
            "user_id": user_id,
            "db_config_id": db_config_id,
            "frequency": frequency,
            "cron_expression": cron_expr,
            "timezone": tz,
            "enabled": enabled,
            "description": description or "",
        },
    )

    schedule_row = normalize_row(row)
    
    # Fetch the complete row again to ensure we get Appwrite-generated created_at and updated_at
    created_schedule_id = schedule_row.get("$id")
    if created_schedule_id:
        try:
            fetched_row = await asyncio.to_thread(
                tables.get_row,
                database_id=DATABASE_ID,
                table_id=BACKUP_SCHEDULES_COLLECTION_ID,
                row_id=created_schedule_id,
            )
            schedule_row = normalize_row(fetched_row)
        except Exception as exc:
            log.warning("Failed to fetch created schedule for timestamps: %s", exc)
    
    if enabled:
        _register_job(schedule_row)
    return _to_schedule_out(schedule_row)


async def list_schedules(user_id: str) -> list[dict]:
    if not BACKUP_SCHEDULES_COLLECTION_ID:
        return []

    result = await asyncio.to_thread(
        tables.list_rows,
        database_id=DATABASE_ID,
        table_id=BACKUP_SCHEDULES_COLLECTION_ID,
        queries=[Query.equal("user_id", user_id), Query.order_desc("created_at")],
    )
    collection = normalize_row_collection(result)
    return [_to_schedule_out(row) for row in collection.get("rows", [])]


async def delete_schedule(schedule_id: str, user_id: str) -> None:
    if not BACKUP_SCHEDULES_COLLECTION_ID:
        return

    try:
        row = await asyncio.to_thread(
            tables.get_row,
            database_id=DATABASE_ID,
            table_id=BACKUP_SCHEDULES_COLLECTION_ID,
            row_id=schedule_id,
        )
        doc = normalize_row(row)
        if doc.get("user_id") != user_id:
            raise PermissionError("Not allowed")
    except Exception:
        # Swallow if not found/forbidden to mirror idempotent delete.
        return

    await asyncio.to_thread(
        tables.delete_row,
        database_id=DATABASE_ID,
        table_id=BACKUP_SCHEDULES_COLLECTION_ID,
        row_id=schedule_id,
    )
    remove_job(schedule_id)


async def toggle_schedule(schedule_id: str, user_id: str, enabled: bool) -> dict:
    if not BACKUP_SCHEDULES_COLLECTION_ID:
        raise RuntimeError("BACKUP_SCHEDULES_COLLECTION_ID is not configured")

    row = await asyncio.to_thread(
        tables.get_row,
        database_id=DATABASE_ID,
        table_id=BACKUP_SCHEDULES_COLLECTION_ID,
        row_id=schedule_id,
    )
    doc = normalize_row(row)
    if doc.get("user_id") != user_id:
        raise PermissionError("Not allowed")

    updated = await asyncio.to_thread(
        tables.update_row,
        database_id=DATABASE_ID,
        table_id=BACKUP_SCHEDULES_COLLECTION_ID,
        row_id=schedule_id,
        data={"enabled": enabled},
    )
    schedule_row = normalize_row(updated)
    
    # Fetch the complete row again to ensure we get Appwrite-generated created_at and updated_at
    try:
        fetched_row = await asyncio.to_thread(
            tables.get_row,
            database_id=DATABASE_ID,
            table_id=BACKUP_SCHEDULES_COLLECTION_ID,
            row_id=schedule_id,
        )
        schedule_row = normalize_row(fetched_row)
    except Exception as exc:
        log.warning("Failed to fetch updated schedule for timestamps: %s", exc)
    
    if enabled:
        _register_job(schedule_row)
    else:
        remove_job(schedule_id)
    return _to_schedule_out(schedule_row)


async def load_active_schedules() -> None:
    if not BACKUP_SCHEDULES_COLLECTION_ID:
        log.warning("Skipping scheduler bootstrap; BACKUP_SCHEDULES_COLLECTION_ID missing")
        return

    await scheduler_startup()
    try:
        result = await asyncio.to_thread(
            tables.list_rows,
            database_id=DATABASE_ID,
            table_id=BACKUP_SCHEDULES_COLLECTION_ID,
            queries=[Query.equal("enabled", True), Query.limit(200)],
        )
    except AppwriteException as exc:
        # If the collection lacks the 'enabled' attribute or schema differs, skip bootstrapping.
        log.warning("Skipping schedule bootstrap due to schema/query issue: %s", exc)
        return

    collection = normalize_row_collection(result)
    for row in collection.get("rows", []):
        try:
            _register_job(row)
        except Exception as exc:  # pragma: no cover - bootstrap resilience
            log.error(
                "Failed to register schedule_id=%s db_config_id=%s error=%s",
                row.get("$id"),
                row.get("db_config_id"),
                exc,
            )


def _register_job(schedule_row: dict) -> None:
    if not schedule_row.get("enabled"):
        return

    trigger = _cron_trigger(
        schedule_row.get("cron_expression", "0 2 * * *"),
        schedule_row.get("timezone") or DEFAULT_TIMEZONE,
    )

    upsert_job(
        schedule_row["$id"],
        trigger,
        _run_scheduled_backup,
        kwargs={"schedule_row": schedule_row},
    )


def _to_schedule_out(doc: dict) -> dict:
    return {
        "schedule_id": doc.get("$id", ""),
        "user_id": doc.get("user_id", ""),
        "db_config_id": doc.get("db_config_id", ""),
        "frequency": doc.get("frequency", ""),
        "cron_expression": doc.get("cron_expression", ""),
        "timezone": _normalize_timezone(doc.get("timezone")),
        "enabled": bool(doc.get("enabled", False)),
        "description": doc.get("description") or None,
        "next_run_time": get_next_run(doc.get("$id")),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


