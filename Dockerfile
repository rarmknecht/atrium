# Atrium core. Phase 5 adds a web-build stage whose static output FastAPI serves.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer (cached unless lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Application (README needed because pyproject declares it as package metadata)
COPY README.md ./
COPY atrium/ atrium/
RUN uv sync --frozen --no-dev

ENV ATRIUM_HOST=0.0.0.0 \
    ATRIUM_PORT=8775 \
    ATRIUM_VAULT_PATH=/data/vault \
    ATRIUM_DATA_DIR=/data/state

EXPOSE 8775
CMD ["uv", "run", "--no-sync", "atrium", "serve"]
