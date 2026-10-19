"""FastAPI main application entrypoint with CORS, static storage mounting, and routers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.config import settings
from backend.app.db import init_db
from backend.app.routers import regression, results, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing database table creation and resource cleanup."""
    # Ensure tables exist on startup
    init_db()
    # Ensure storage and generated test directories exist
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    settings.GENERATED_TESTS_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Autonomous AI QA Engineer API",
    description="REST API powering AI test planning, Playwright execution, verification, and bug reporting.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Configuration (Section 9: enable for http://localhost:5173)
origins = settings.CORS_ORIGINS if hasattr(settings, "CORS_ORIGINS") and settings.CORS_ORIGINS else [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(sessions.router)
app.include_router(results.router)
app.include_router(regression.router)

# Mount Static File Storage for screenshots and reports (Section 9)
storage_dir = Path(settings.STORAGE_DIR).resolve()
storage_dir.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(storage_dir), check_dir=False), name="storage")


@app.get("/", tags=["health"])
def root_status():
    """Healthcheck and API metadata endpoint."""
    return {
        "service": "Autonomous AI QA Engineer API",
        "status": "healthy",
        "version": "1.0.0",
        "storage_dir": str(storage_dir),
    }


@app.get("/health", tags=["health"])
def health():
    """Service liveness probe."""
    return {"status": "ok"}
