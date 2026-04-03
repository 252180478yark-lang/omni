from __future__ import annotations

import json
import logging
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("VIDEO_ANALYSIS_DATA_DIR") or "/app/data/video-analysis")
DATA_DIR = DATA_ROOT
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
CURVE_DIR = DATA_DIR / "curves"
CONFIG_PATH = DATA_DIR / "settings.json"

_DATABASE_URL: str | None = None


def _dsn() -> str:
    global _DATABASE_URL
    if _DATABASE_URL is None:
        raw = os.environ.get("DATABASE_URL", "").strip()
        if not raw:
            from app.config import settings

            raw = (settings.database_url or "").strip()
        _DATABASE_URL = raw
    if not _DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return _DATABASE_URL


@contextmanager
def _conn():
    conn = psycopg2.connect(_dsn())
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(cursor, row) -> dict[str, Any]:
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CURVE_DIR.mkdir(parents=True, exist_ok=True)


def _legacy_data_dirs() -> list[Path]:
    legacy_dirs: list[Path] = []
    legacy_backend = BASE_DIR.parent / "data"
    if legacy_backend.exists():
        legacy_dirs.append(legacy_backend)
    local = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    legacy_local = Path(local) / "ShortVideoAnalysis" / "data"
    if legacy_local.exists():
        legacy_dirs.append(legacy_local)
    return legacy_dirs


def _unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.name
    counter = 1
    while True:
        candidate = path.with_name(f"{base}.legacy{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def migrate_legacy_data() -> None:
    ensure_dirs()
    for legacy in _legacy_data_dirs():
        try:
            if legacy.resolve() == DATA_DIR.resolve():
                continue
        except Exception:
            if str(legacy) == str(DATA_DIR):
                continue
        if not legacy.exists():
            continue
        for item in legacy.iterdir():
            try:
                if item.resolve() == DATA_DIR.resolve():
                    continue
            except Exception:
                if str(item) == str(DATA_DIR):
                    continue
            target = DATA_DIR / item.name
            if target.exists():
                if item.is_dir() and target.is_dir():
                    for sub in item.iterdir():
                        dest = target / sub.name
                        if dest.exists():
                            dest = _unique_target(dest)
                        shutil.move(str(sub), str(dest))
                    try:
                        item.rmdir()
                    except Exception:
                        pass
                else:
                    dest = _unique_target(target)
                    shutil.move(str(item), str(dest))
            else:
                shutil.move(str(item), str(target))


def load_settings() -> dict[str, Any]:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def init_db() -> None:
    """Tables are created by init.sql at PostgreSQL startup; this is a no-op."""
    migrate_legacy_data()
    ensure_dirs()
    logger.info("video-analysis using PostgreSQL (schema: video_analysis)")


def create_video_record(video_id: str, original_name: str, file_path: str, metrics_json: str | None = None) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO video_analysis.videos
                    (id, original_name, file_path, created_at, status, retries, progress, status_message, metrics_json)
                VALUES (%s, %s, %s, NOW(), 'queued', 0, 0.0, '排队中', %s)
                """,
                (video_id, original_name, file_path, metrics_json),
            )


def update_video_report(
    video_id: str,
    report_md_path: str,
    report_json_path: str,
    report_txt_path: str,
    curve_path: str,
) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE video_analysis.videos
                SET report_md_path = %s, report_json_path = %s, report_txt_path = %s,
                    curve_path = %s, status = 'done', updated_at = NOW(),
                    last_error = NULL, progress = 1.0, status_message = '完成'
                WHERE id = %s
                """,
                (report_md_path, report_json_path, report_txt_path, curve_path, video_id),
            )


def mark_video_failed(video_id: str, error: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE video_analysis.videos
                SET status = 'failed', updated_at = NOW(), last_error = %s,
                    progress = 0.0, status_message = '失败'
                WHERE id = %s
                """,
                (error, video_id),
            )


def list_videos() -> list[dict[str, Any]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, original_name, created_at, status, retries, last_error,
                       progress, status_message, updated_at
                FROM video_analysis.videos
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
            return [_row_to_dict(cur, r) for r in rows]


def get_video(video_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM video_analysis.videos WHERE id = %s",
                (video_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(cur, row) if row else None


def set_video_status(
    video_id: str,
    status: str,
    error: str | None = None,
    progress: float | None = None,
    status_message: str | None = None,
) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE video_analysis.videos
                SET status = %s, updated_at = NOW(), last_error = %s,
                    progress = COALESCE(%s, progress),
                    status_message = COALESCE(%s, status_message)
                WHERE id = %s
                """,
                (status, error, progress, status_message, video_id),
            )


def increment_retry(video_id: str) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE video_analysis.videos
                SET retries = retries + 1, updated_at = NOW()
                WHERE id = %s
                RETURNING retries
                """,
                (video_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def delete_video(video_id: str) -> bool:
    video = get_video(video_id)
    if not video:
        return False

    for key in ("file_path", "report_md_path", "report_json_path", "report_txt_path", "curve_path"):
        path = video.get(key)
        if path and Path(path).exists():
            try:
                Path(path).unlink()
            except Exception:
                pass

    bundle_path = REPORT_DIR / f"{video_id}_bundle.zip"
    if bundle_path.exists():
        try:
            bundle_path.unlink()
        except Exception:
            pass

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM video_analysis.cost_logs WHERE video_id = %s", (video_id,))
            cur.execute("DELETE FROM video_analysis.knowledge_base WHERE video_id = %s", (video_id,))
            cur.execute("DELETE FROM video_analysis.videos WHERE id = %s", (video_id,))
    return True


def log_cost(video_id: str, usage: dict[str, Any]) -> None:
    if not usage:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO video_analysis.cost_logs
                    (video_id, prompt_tokens, response_tokens, total_tokens, cost_usd, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    video_id,
                    usage.get("prompt_tokens"),
                    usage.get("response_tokens"),
                    usage.get("total_tokens"),
                    usage.get("cost_usd"),
                ),
            )


def get_daily_costs() -> list[dict[str, Any]]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at::date AS day,
                       COUNT(*) AS requests,
                       SUM(COALESCE(total_tokens, 0)) AS total_tokens,
                       SUM(COALESCE(cost_usd, 0)) AS cost_usd
                FROM video_analysis.cost_logs
                GROUP BY day
                ORDER BY day DESC
                """
            )
            rows = cur.fetchall()
            return [_row_to_dict(cur, r) for r in rows]


def add_knowledge_entry(video_id: str, summary: str, tags: list[str]) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO video_analysis.knowledge_base (video_id, summary, tags, created_at, kb_pushed)
                VALUES (%s, %s, %s, NOW(), 0)
                """,
                (video_id, summary, ",".join(tags)),
            )

    ok = push_to_knowledge_engine(video_id, summary, tags)
    if ok:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE video_analysis.knowledge_base SET kb_pushed = 1 WHERE video_id = %s",
                    (video_id,),
                )


def _resolve_kb_id(client: "httpx.Client", base_url: str, raw_id: str) -> str | None:
    import uuid as _uuid
    try:
        _uuid.UUID(raw_id)
        return raw_id
    except ValueError:
        pass
    try:
        resp = client.get(f"{base_url}/api/v1/knowledge/bases")
        resp.raise_for_status()
        bases = resp.json().get("data", [])
        for kb in bases:
            if kb.get("name") == raw_id:
                logger.info("Resolved KB name '%s' → %s", raw_id, kb["id"])
                return kb["id"]
        if bases:
            first = bases[0]
            logger.info("KB name '%s' not found, falling back to first KB '%s' (%s)", raw_id, first.get("name"), first["id"])
            return first["id"]
    except Exception as exc:
        logger.warning("Failed to resolve KB id '%s': %s", raw_id, exc)
    return None


def push_to_knowledge_engine(video_id: str, summary: str, tags: list[str]) -> bool:
    import time
    import httpx
    from app.config import settings

    base_url = settings.knowledge_engine_url
    with httpx.Client(timeout=30.0) as client:
        kb_id = _resolve_kb_id(client, base_url, settings.knowledge_target_kb_id)
        if not kb_id:
            logger.warning("Skipping KB push for video=%s: could not resolve KB id '%s'", video_id, settings.knowledge_target_kb_id)
            return False

        url = f"{base_url}/api/v1/knowledge/ingest"
        payload = {"kb_id": kb_id, "title": f"Video Analysis: {video_id}", "text": summary, "source_type": "video"}
        for attempt in range(3):
            try:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                logger.info("Pushed video %s analysis to knowledge-engine (kb=%s)", video_id, kb_id)
                return True
            except Exception as exc:
                if attempt < 2:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning("KB push retry %d/3 for video=%s: %s (next in %.0fs)", attempt + 1, video_id, exc, delay)
                    time.sleep(delay)
                else:
                    logger.error("KB push failed after 3 retries for video=%s: %s", video_id, exc)
    return False


def retry_failed_kb_pushes() -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT video_id, summary, tags FROM video_analysis.knowledge_base WHERE kb_pushed = 0")
            rows = cur.fetchall()

    if not rows:
        return {"pending": 0, "retried": 0, "success": 0}

    logger.info("Retrying %d failed KB pushes...", len(rows))
    success = 0
    for video_id, summary, tags_str in rows:
        tags = tags_str.split(",") if tags_str else []
        ok = push_to_knowledge_engine(video_id, summary, tags)
        if ok:
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE video_analysis.knowledge_base SET kb_pushed = 1 WHERE video_id = %s", (video_id,))
            success += 1

    logger.info("KB push retry complete: %d/%d succeeded", success, len(rows))
    return {"pending": len(rows), "retried": len(rows), "success": success}


def search_knowledge(query: str | None = None, day: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if query:
        clauses.append("(summary ILIKE %s OR tags ILIKE %s)")
        params.extend([f"%{query}%", f"%{query}%"])
    if day:
        clauses.append("created_at::date = %s")
        params.append(day)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM video_analysis.knowledge_base {where} ORDER BY created_at DESC"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [_row_to_dict(cur, r) for r in rows]
