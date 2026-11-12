# DWH Code Review: one image that serves the API (/api) and the built UI on port 8080.
#
#   docker build -t dwh-code-review .
#   docker run -p 8080:8080 -v dwhcr-data:/data dwh-code-review
#
# Application data (SQLite database and encryption key) lives in the /data volume.

ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-alpine

# ---------------------------------------------------------------- UI build
FROM ${NODE_IMAGE} AS ui
WORKDIR /src
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}

# Microsoft ODBC Driver 18 for SQL Server (Alpine package, signature checked against Microsoft's key).
ARG MSODBC_VERSION=18.5.1.1-1
ARG MSODBC_URL=https://download.microsoft.com/download/fae28b9a-d880-42fd-9b98-d779f0fdd77f
ARG APP_UID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DWHCR_DATA_DIR=/data \
    DWHCR_STATIC_DIR=/app/ui

RUN set -eux; \
    apk upgrade --no-cache; \
    apk add --no-cache unixodbc libstdc++; \
    apk add --no-cache --virtual .fetch curl gnupg; \
    case "$(apk --print-arch)" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac; \
    cd /tmp; \
    curl -fsSLO "${MSODBC_URL}/msodbcsql18_${MSODBC_VERSION}_${arch}.apk"; \
    curl -fsSLO "${MSODBC_URL}/msodbcsql18_${MSODBC_VERSION}_${arch}.sig"; \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --batch --import -; \
    gpg --batch --verify "msodbcsql18_${MSODBC_VERSION}_${arch}.sig" "msodbcsql18_${MSODBC_VERSION}_${arch}.apk"; \
    echo y | apk add --no-cache --allow-untrusted "msodbcsql18_${MSODBC_VERSION}_${arch}.apk"; \
    rm -rf /tmp/msodbcsql18_* /root/.gnupg; \
    apk del .fetch

WORKDIR /app
COPY app/backend/requirements.txt /tmp/requirements.txt
# pip leaves the image once the pinned requirements are installed; nothing installs at run time.
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && python -m pip uninstall --yes pip

COPY app/backend/app ./app
COPY --from=ui /src/dist ./ui

RUN adduser -D -H -u "${APP_UID}" app \
    && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--proxy-headers"]
