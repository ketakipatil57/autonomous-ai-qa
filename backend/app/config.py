"""Application configuration settings loaded from environment variables and .env."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Repository root (parent of backend/)
BASE_DIR = Path(__file__).resolve().parents[2]

# Load .env file if it exists
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()


class Settings:
    """Core settings for backend and test runner."""

    BASE_DIR: Path = BASE_DIR

    # Storage and Test Directories
    STORAGE_DIR: Path = Path(os.environ.get("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
    GENERATED_TESTS_DIR: Path = Path(os.environ.get("GENERATED_TESTS_DIR", str(BASE_DIR / "generated_tests"))).resolve()

    # Timeouts (Section 8)
    TEST_TIMEOUT_SECONDS: int = int(os.environ.get("TEST_TIMEOUT_SECONDS", 20))
    SESSION_TIMEOUT_SECONDS: int = int(os.environ.get("SESSION_TIMEOUT_SECONDS", 300))

    # Safety and Limits (Section 8)
    ALLOWED_HOSTS: list[str] = [
        h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
    ]
    MAX_TESTS_PER_RUN: int = int(os.environ.get("MAX_TESTS_PER_RUN", 8))
    MAX_STEPS_PER_TEST: int = int(os.environ.get("MAX_STEPS_PER_TEST", 15))

    # Sample App Credentials (Section 8 & 13)
    TEST_USER_EMAIL: str = os.environ.get("TEST_USER_EMAIL", "test@demo.com")
    TEST_USER_PASSWORD: str = os.environ.get("TEST_USER_PASSWORD", "Test@123")
    SAMPLE_BUGS: str = os.environ.get("SAMPLE_BUGS", "on")

    # Database
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", "mysql+pymysql://qa_user:qa_password@localhost:3306/qa_agent"
    )

    # OpenAI (Optional)
    OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


settings = Settings()

# Ensure runtime directories exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.GENERATED_TESTS_DIR.mkdir(parents=True, exist_ok=True)
