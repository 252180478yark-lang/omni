FROM python:3.11-slim

ARG OMNI_BUILD_COMMIT=unknown
ARG OMNI_BUILD_SOURCE_FINGERPRINT=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT} \
    OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}

WORKDIR /workspace

COPY services/infra-core/migrations/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY scripts/apply_migrations.py /workspace/scripts/apply_migrations.py
COPY scripts/runtime_guard.py /workspace/scripts/runtime_guard.py
COPY scripts/runtime_allocation.py /workspace/scripts/runtime_allocation.py
COPY scripts/development_policy.py /workspace/scripts/development_policy.py
COPY services/knowledge-engine/app/runtime_preflight.py /workspace/services/knowledge-engine/app/runtime_preflight.py
COPY config/runtime-manifest.yaml /workspace/config/runtime-manifest.yaml
COPY migrations/ /workspace/migrations/

ENTRYPOINT ["python", "-B", "/workspace/scripts/apply_migrations.py"]
