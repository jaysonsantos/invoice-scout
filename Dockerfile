FROM python:3.11-alpine AS builder

WORKDIR /app

RUN apk add --no-cache build-base libffi-dev

COPY pyproject.toml uv.lock README.md /app/
COPY invoice_scanner /app/invoice_scanner

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && python -m compileall -q /app/invoice_scanner

FROM python:3.11-alpine

WORKDIR /app

RUN addgroup -S app && adduser -S app -G app

COPY --from=builder /app /app

ENV PYTHONUNBUFFERED=1

USER app

ENTRYPOINT ["python", "-m", "invoice_scanner"]
