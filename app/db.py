from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DB_PATH


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free',
                credits INTEGER NOT NULL DEFAULT 120,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_value TEXT,
                source_path TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT 'Na fila',
                settings_json TEXT NOT NULL,
                transcript_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS clips (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                hook TEXT,
                reason TEXT,
                video_path TEXT,
                thumbnail_path TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS creator_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                avg_duration REAL NOT NULL DEFAULT 45,
                preferred_min REAL NOT NULL DEFAULT 25,
                preferred_max REAL NOT NULL DEFAULT 75,
                aggression REAL NOT NULL DEFAULT 0.6,
                keywords TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS clip_edits (
                clip_id TEXT PRIMARY KEY,
                caption_preset_id TEXT NOT NULL DEFAULT 'green-fresh',
                layout_preset_id TEXT NOT NULL DEFAULT 'auto',
                caption_config_json TEXT NOT NULL DEFAULT '{}',
                layout_config_json TEXT NOT NULL DEFAULT '{}',
                overlay_config_json TEXT NOT NULL DEFAULT '[]',
                tracks_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS caption_cues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_id TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                text TEXT NOT NULL,
                word_index INTEGER NOT NULL DEFAULT 0,
                speaker_id TEXT,
                confidence REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_caption_cues_clip ON caption_cues(clip_id, start_time, word_index);

            CREATE TABLE IF NOT EXISTS user_presets (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                preset_type TEXT NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS clip_renders (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                progress INTEGER NOT NULL DEFAULT 0,
                settings_hash TEXT,
                video_path TEXT,
                error_message TEXT,
                encoder TEXT,
                resolution TEXT,
                file_size INTEGER,
                render_seconds REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_clip_renders_clip ON clip_renders(clip_id, kind, created_at);

            CREATE TABLE IF NOT EXISTS project_assets (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'source',
                provider TEXT,
                source_value TEXT,
                local_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS brand_assets (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                file_path TEXT,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS clip_timelines (
                clip_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL DEFAULT 3,
                timeline_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS worker_jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                target_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT,
                message TEXT NOT NULL DEFAULT 'Na fila',
                progress_current REAL NOT NULL DEFAULT 0,
                progress_total REAL NOT NULL DEFAULT 0,
                speed REAL NOT NULL DEFAULT 0,
                eta_seconds REAL,
                backend TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                control_state TEXT NOT NULL DEFAULT 'running',
                heartbeat_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_worker_jobs_target ON worker_jobs(kind,target_id,created_at);

            CREATE TABLE IF NOT EXISTS worker_job_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                progress_current REAL NOT NULL DEFAULT 0,
                progress_total REAL NOT NULL DEFAULT 0,
                speed REAL NOT NULL DEFAULT 0,
                eta_seconds REAL,
                backend TEXT,
                message TEXT,
                started_at TEXT,
                heartbeat_at TEXT,
                finished_at TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                UNIQUE(job_id,stage,attempt),
                FOREIGN KEY(job_id) REFERENCES worker_jobs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_worker_job_stages_job ON worker_job_stages(job_id,id);

            CREATE TABLE IF NOT EXISTS studio_templates (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                favorite INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_studio_templates_user ON studio_templates(user_id,favorite,updated_at);

            CREATE TABLE IF NOT EXISTS brand_kits (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_brand_kits_user ON brand_kits(user_id,updated_at);

            CREATE TABLE IF NOT EXISTS publish_queue (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                clip_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT,
                caption TEXT NOT NULL DEFAULT '',
                external_url TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_publish_queue_user ON publish_queue(user_id,status,scheduled_at,created_at);
            CREATE INDEX IF NOT EXISTS idx_publish_queue_clip ON publish_queue(clip_id,created_at);

            CREATE TABLE IF NOT EXISTS worker_pairings (
                id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            );
            """
        )

        # V4.2 Adaptive Compute Fabric + Creator Intelligence. These tables are
        # additive so a V4.1 database can be upgraded in place and rolled back.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS processing_tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                clip_id TEXT,
                task_type TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0,
                units REAL NOT NULL DEFAULT 1,
                node_kind TEXT,
                input_hash TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error_message TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_processing_tasks_project ON processing_tasks(project_id,created_at);
            CREATE INDEX IF NOT EXISTS idx_processing_tasks_state ON processing_tasks(state,task_type,created_at);

            CREATE TABLE IF NOT EXISTS performance_samples (
                id TEXT PRIMARY KEY,
                node_kind TEXT NOT NULL,
                task_type TEXT NOT NULL,
                units REAL NOT NULL,
                seconds REAL NOT NULL,
                speed REAL NOT NULL,
                ok INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_performance_samples_route ON performance_samples(node_kind,task_type,created_at);

            CREATE TABLE IF NOT EXISTS scheduler_decisions (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                task_type TEXT NOT NULL,
                selected_node TEXT NOT NULL,
                decision_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES processing_tasks(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_scheduler_decisions_task ON scheduler_decisions(task_id,created_at);

            CREATE TABLE IF NOT EXISTS task_cache (
                cache_key TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                result_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                hit_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_cache_used ON task_cache(last_used_at);

            CREATE TABLE IF NOT EXISTS clip_revisions (
                id TEXT PRIMARY KEY,
                clip_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                timeline_json TEXT NOT NULL,
                edit_state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(clip_id,revision),
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_clip_revisions_clip ON clip_revisions(clip_id,revision DESC);

            CREATE TABLE IF NOT EXISTS creator_performance (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                clip_id TEXT,
                platform TEXT NOT NULL DEFAULT 'manual',
                views INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                watch_seconds REAL,
                completion_rate REAL,
                hook_hold_rate REAL,
                published_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(clip_id) REFERENCES clips(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_creator_performance_user ON creator_performance(user_id,platform,created_at);
            """
        )

        # Idempotent columns for databases created by the MVP.
        _add_column(conn, "projects", "source_metadata_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "projects", "thumbnail_path TEXT")
        _add_column(conn, "projects", "duration REAL")
        _add_column(conn, "projects", "channel_label TEXT")
        _add_column(conn, "projects", "tracking_path TEXT")
        _add_column(conn, "projects", "tracking_summary_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "projects", "hardware_profile_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "clips", "preview_path TEXT")
        _add_column(conn, "clips", "clean_path TEXT")
        _add_column(conn, "clips", "waveform_path TEXT")
        _add_column(conn, "clips", "render_status TEXT NOT NULL DEFAULT 'rendered'")
        _add_column(conn, "clips", "render_encoder TEXT")
        _add_column(conn, "clips", "render_seconds REAL")
        _add_column(conn, "clips", "file_size INTEGER")
        _add_column(conn, "clips", "updated_at TEXT")
        _add_column(conn, "clip_edits", "revision INTEGER NOT NULL DEFAULT 1")
        _add_column(conn, "clip_edits", "aspect_ratio TEXT NOT NULL DEFAULT '9:16'")
        _add_column(conn, "clip_renders", "editor_revision INTEGER")
        _add_column(conn, "clip_renders", "snapshot_json TEXT")
        _add_column(conn, "clips", "analysis_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "projects", "brand_kit_id TEXT")
        _add_column(conn, "projects", "template_id TEXT")
        _add_column(conn, "users", "performance_mode TEXT NOT NULL DEFAULT 'auto'")
        conn.execute("UPDATE users SET performance_mode='auto' WHERE performance_mode!='auto'")
        _add_column(conn, "caption_cues", "highlight INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "caption_cues", "emoji TEXT")
        _add_column(conn, "users", "compute_mode TEXT NOT NULL DEFAULT 'auto'")
        _add_column(conn, "users", "is_admin INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE users SET is_admin=1 WHERE id=(SELECT MIN(id) FROM users) "
            "AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin=1)"
        )
        _add_column(conn, "projects", "compute_summary_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "projects", "quality_summary_json TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "clips", "creator_score REAL")
        conn.commit()


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with connect() as conn:
        conn.execute(sql, tuple(params))
        conn.commit()


def executemany(sql: str, params: Iterable[Iterable[Any]]) -> None:
    with connect() as conn:
        conn.executemany(sql, [tuple(p) for p in params])
        conn.commit()


def fetchone(sql: str, params: Iterable[Any] = ()):
    with connect() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def fetchall(sql: str, params: Iterable[Any] = ()):
    with connect() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False
