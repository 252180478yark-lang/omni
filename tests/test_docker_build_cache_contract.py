from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CONTENT_DOCKERFILES = {
    "services/infra-core/migrations/Dockerfile": (
        "RUN pip install --no-cache-dir -r /tmp/requirements.txt",
        "COPY scripts/apply_migrations.py",
    ),
    "services/knowledge-engine/Dockerfile": (
        "playwright install chromium",
        "COPY app /app/app",
    ),
    "services/ai-provider-hub/Dockerfile": (
        "RUN pip install --no-cache-dir",
        "COPY app /app/app",
    ),
    "services/video-analysis/Dockerfile": (
        "faster-whisper",
        "COPY app /app/app",
    ),
    "services/livestream-analysis/Dockerfile": (
        "requests openpyxl python-dotenv psycopg2-binary httpx",
        "COPY app /app/app",
    ),
    "services/scout-agent/Dockerfile": (
        "RUN playwright install chromium",
        "COPY app /app/app",
    ),
}


def test_content_images_cache_dependencies_before_build_identity() -> None:
    for relative, (dependency_marker, source_marker) in CONTENT_DOCKERFILES.items():
        content = (ROOT / relative).read_text(encoding="utf-8")
        dependency = content.rfind(dependency_marker)
        build_commit = content.index("ARG OMNI_BUILD_COMMIT=unknown")
        build_fingerprint = content.index("ARG OMNI_BUILD_SOURCE_FINGERPRINT=unknown")
        source = content.index(source_marker)

        assert dependency >= 0, relative
        assert dependency < build_commit < build_fingerprint < source, relative
        assert "OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT}" in content, relative
        assert "OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}" in content, relative
