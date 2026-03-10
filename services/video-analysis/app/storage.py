from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("VIDEO_ANALYSIS_DATA_DIR") or "/app/data/video-analysis")
DATA_DIR = DATA_ROOT
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
CURVE_DIR = DATA_DIR / "curves"
DB_PATH = DATA_DIR / "app.db"
CONFIG_PATH = DATA_DIR / "settings.json"


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


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_db() -> None:
    migrate_legacy_data()
    ensure_dirs()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                report_md_path TEXT,
                report_json_path TEXT,
                report_txt_path TEXT,
                curve_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                status TEXT NOT NULL,
                retries INTEGER DEFAULT 0,
                last_error TEXT
            )
            """
        )
        _ensure_column(conn, "videos", "report_txt_path", "TEXT")
        _ensure_column(conn, "videos", "updated_at", "TEXT")
        _ensure_column(conn, "videos", "retries", "INTEGER DEFAULT 0")
        _ensure_column(conn, "videos", "last_error", "TEXT")
        _ensure_column(conn, "videos", "progress", "REAL DEFAULT 0")
        _ensure_column(conn, "videos", "status_message", "TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cost_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                prompt_tokens INTEGER,
                response_tokens INTEGER,
                total_tokens INTEGER,
                cost_usd REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                summary TEXT,
                tags TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_video_record(video_id: str, original_name: str, file_path: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, original_name, file_path, created_at, status, retries, progress, status_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (video_id, original_name, file_path, created_at, "queued", 0, 0.0, "排队中"),
        )
        conn.commit()


def update_video_report(
    video_id: str,
    report_md_path: str,
    report_json_path: str,
    report_txt_path: str,
    curve_path: str,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE videos
            SET report_md_path = ?, report_json_path = ?, report_txt_path = ?,
                curve_path = ?, status = ?, updated_at = ?, last_error = ?, progress = ?, status_message = ?
            WHERE id = ?
            """,
            (
                report_md_path,
                report_json_path,
                report_txt_path,
                curve_path,
                "done",
                datetime.now(timezone.utc).isoformat(),
                None,
                1.0,
                "完成",
                video_id,
            ),
        )
        conn.commit()


def mark_video_failed(video_id: str, error: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status = ?, updated_at = ?, last_error = ?, progress = ?, status_message = ?
            WHERE id = ?
            """,
            ("failed", datetime.now(timezone.utc).isoformat(), error, 0.0, "失败", video_id),
        )
        conn.commit()


def list_videos() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, original_name, created_at, status, retries, last_error, progress, status_message, updated_at
            FROM videos
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_video(video_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM videos
            WHERE id = ?
            """,
            (video_id,),
        ).fetchone()
    return dict(row) if row else None


def set_video_status(
    video_id: str,
    status: str,
    error: str | None = None,
    progress: float | None = None,
    status_message: str | None = None,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status = ?, updated_at = ?, last_error = ?,
                progress = COALESCE(?, progress),
                status_message = COALESCE(?, status_message)
            WHERE id = ?
            """,
            (
                status,
                datetime.now(timezone.utc).isoformat(),
                error,
                progress,
                status_message,
                video_id,
            ),
        )
        conn.commit()


def increment_retry(video_id: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE videos
            SET retries = retries + 1, updated_at = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), video_id),
        )
        row = conn.execute("SELECT retries FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.commit()
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

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM cost_logs WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM knowledge_base WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        conn.commit()
    return True


def log_cost(video_id: str, usage: dict[str, Any]) -> None:
    if not usage:
        return
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO cost_logs (video_id, prompt_tokens, response_tokens, total_tokens, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                usage.get("prompt_tokens"),
                usage.get("response_tokens"),
                usage.get("total_tokens"),
                usage.get("cost_usd"),
                created_at,
            ),
        )
        conn.commit()


def get_daily_costs() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) as day,
                   COUNT(*) as requests,
                   SUM(COALESCE(total_tokens, 0)) as total_tokens,
                   SUM(COALESCE(cost_usd, 0)) as cost_usd
            FROM cost_logs
            GROUP BY day
            ORDER BY day DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_knowledge_entry(video_id: str, summary: str, tags: list[str]) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO knowledge_base (video_id, summary, tags, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (video_id, summary, ",".join(tags), created_at),
        )
        conn.commit()


def search_knowledge(query: str | None = None, day: str | None = None) -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM knowledge_base WHERE 1=1"
        params: list[Any] = []
        if query:
            sql += " AND (summary LIKE ? OR tags LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        if day:
            sql += " AND substr(created_at, 1, 10) = ?"
            params.append(day)
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
