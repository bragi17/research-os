# ---------- base ----------
FROM python:3.12-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------- dependencies ----------
FROM base AS deps

COPY pyproject.toml ./
RUN pip install --no-cache-dir . || \
    pip install --no-cache-dir -e .

# ---------- runtime ----------
FROM base AS runtime

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
