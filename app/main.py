from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.logging_setup import setup_logging
from app.routes.auth import router as auth_router
from app.routes.user import router as user_router
from app.routes.database import router as database_router
from app.routes.backup import router as backup_router
from app.routes.schedule import router as schedule_router
from app.routes.admin import router as admin_router
from app.services.schedule_service import load_active_schedules
from app.utils.scheduler import scheduler_shutdown, scheduler_startup
from fastapi.middleware.cors import CORSMiddleware


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
app.include_router(admin_router)


@app.get("/")
def home():
    return {"message": "Database Backup Utility API Running"}

# ✅ Allowed frontend URLs
origins = [
    "http://localhost:3000",     # React / Next.js
    "http://127.0.0.1:5500",    # Live Server (VS Code)
]

# ✅ Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],   # allow all HTTP methods
    allow_headers=["*"],   # allow all headers
)