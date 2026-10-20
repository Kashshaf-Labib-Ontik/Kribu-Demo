FROM python:3.11.17-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/
WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY services/api/pyproject.toml services/api/pyproject.toml
RUN uv sync --frozen --no-dev --package kribu-api

COPY services/api services/api
WORKDIR /workspace/services/api

# The document store directory exists in the image so a fresh named volume inherits uid 10001.
RUN useradd --create-home --uid 10001 kribu \
    && mkdir -p /var/lib/kribu/documents \
    && chown -R kribu:kribu /workspace /var/lib/kribu
USER kribu

EXPOSE 8000
CMD ["uv", "run", "--frozen", "--no-dev", "--package", "kribu-api", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

