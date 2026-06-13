# ---- Stage 1: build the React UI ----
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- Stage 2: Atrium server (serves the built UI) ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer (cached unless the lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Application + built UI
COPY README.md ./
COPY atrium/ atrium/
COPY --from=web /web/dist web/dist
RUN uv sync --frozen --no-dev

ENV ATRIUM_HOST=0.0.0.0 \
    ATRIUM_PORT=8775 \
    ATRIUM_VAULT_PATH=/data/vault \
    ATRIUM_DATA_DIR=/data/state \
    ATRIUM_WEB_DIST=/app/web/dist \
    ATRIUM_CORS_ORIGINS=[]

EXPOSE 8775
CMD ["uv", "run", "--no-sync", "atrium", "serve"]
