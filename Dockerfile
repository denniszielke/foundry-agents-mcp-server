# ── Stage 1: build ────────────────────────────────────────────────────────────
# Alpine keeps the final image small. We compile native extensions (cryptography,
# etc.) here and carry only the venv into the final stage.
FROM python:3.13-alpine AS build

# Build-time deps for packages with native extensions (cryptography, etc.)
RUN apk add --no-cache gcc g++ musl-dev python3-dev libffi-dev openssl-dev cargo pkgconfig

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (layer-cache friendly)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -e "." 2>/dev/null || true

# Full install with the project source
COPY src/ ./src/
RUN uv pip install --system --no-cache -e "."

# ── Stage 2: final ─────────────────────────────────────────────────────────────
FROM python:3.13-alpine AS final

RUN addgroup -S app && adduser -S app -G app

# Copy installed packages and project source from build stage
COPY --from=build --chown=app:app /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=build --chown=app:app /usr/local/bin /usr/local/bin
COPY --from=build --chown=app:app /app /app

WORKDIR /app
USER app

EXPOSE 8000

# Set at runtime to override (default: HTTP transport for Container Apps)
ENV TRANSPORT=http

COPY --chown=app:app entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
