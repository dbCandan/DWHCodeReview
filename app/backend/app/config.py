"""Runtime configuration: where the SQLite database and the encryption key live."""

import os
from pathlib import Path

APP_VERSION = "1.0.0"
# Set by the image build (Dockerfile ARG GIT_SHA); tells which commit a deployed pod runs.
APP_COMMIT = os.environ.get("DWHCR_COMMIT", "").strip()
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR_ENV = "DWHCR_DATA_DIR"
# Production UI build served by the backend (container); unset in development (Vite serves it).
STATIC_DIR_ENV = "DWHCR_STATIC_DIR"

CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Login timeout for SQL Server connections (seconds) and query timeout.
SQL_LOGIN_TIMEOUT_SECONDS = 10
SQL_QUERY_TIMEOUT_SECONDS = 120

# Background analysis workers.
ANALYSIS_WORKERS = 2


def default_data_dir() -> Path:
    """`DWHCR_DATA_DIR` when set, otherwise `<backend>/data`."""
    value = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(value) if value else BACKEND_DIR / "data"
