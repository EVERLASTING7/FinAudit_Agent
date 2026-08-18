FROM python:3.10.20-slim-bookworm@sha256:9643927a6fc74bd81b0f1bbb5cce3cb4a491f46b4c5dbee770f28e575f180015

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/pyproject.toml ./pyproject.toml
RUN mkdir -p app \
    && touch app/__init__.py \
    && python -m pip install --no-cache-dir . \
    && python -m pip uninstall --yes setuptools wheel pip

ENV PYTHONPATH=/app

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY scripts/bootstrap_local_minio.py scripts/bootstrap_local_minio_worker.py \
    scripts/bootstrap_local_qdrant.py scripts/generate_local_runtime_secrets.py \
    scripts/benchmark_local_performance.py scripts/smoke_local_security.py \
    scripts/local_volume_archive.py scripts/smoke_local_bootstrap_auth.py \
    scripts/smoke_local_file_upload.py scripts/smoke_local_worker_crash_recovery.py \
    scripts/smoke_local_contract_extraction_crash_recovery.py \
    scripts/smoke_local_invoice_extraction_crash_recovery.py \
    scripts/smoke_local_audit_execution_crash_recovery.py \
    scripts/smoke_local_report_generation_crash_recovery.py \
    scripts/smoke_local_knowledge_index_crash_recovery.py \
    scripts/smoke_local_ai_audit_crash_recovery.py \
    ./scripts/
RUN mkdir -p /app/config \
    && cp /app/app/ai/artifacts/cr011_v1/ai-policy-v1.positive.json \
        /app/config/ai-policy-v1.json \
    && cp /app/app/ai/artifacts/minimax_m3_bailian_qwen37_local_v2/live-ai-policy-v2.json \
        /app/config/live-ai-policy-v2.json \
    && chmod 0444 /app/config/ai-policy-v1.json /app/config/live-ai-policy-v2.json \
    && addgroup --system --gid 10001 finaudit \
    && adduser --system --uid 10001 --ingroup finaudit --home /nonexistent finaudit

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
