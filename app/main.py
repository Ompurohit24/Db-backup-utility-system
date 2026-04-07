from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.logging_setup import setup_logging
from app.routes.auth import router as auth_router
from app.routes.user import router as user_router
from app.routes.database import router as database_router
from app.routes.backup import router as backup_router
from app.routes.schedule import router as schedule_router
from app.services.schedule_service import load_active_schedules
from app.utils.scheduler import scheduler_shutdown, scheduler_startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await scheduler_startup()
    await load_active_schedules()
    yield
    await scheduler_shutdown()


app = FastAPI(title="Database Backup Utility", version="1.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(database_router)
app.include_router(backup_router)
app.include_router(schedule_router)


@app.get("/")
def home():
    return {"message": "Database Backup Utility API Running"}