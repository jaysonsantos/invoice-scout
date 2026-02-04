FROM python:3.11-alpine AS builder

WORKDIR /app

RUN apk add --no-cache build-base libffi-dev
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md /app/

RUN uv sync --frozen --no-dev
COPY invoice_scanner /app/invoice_scanner
RUN python -m compileall -q /app/invoice_scanner

FROM python:3.11-alpine

WORKDIR /app

RUN addgroup -S app && adduser -S app -G app

COPY --from=builder /app /app

ENV PYTHONUNBUFFERED=1

USER app

ENTRYPOINT [".venv/bin/python", "-m", "invoice_scanner"]
