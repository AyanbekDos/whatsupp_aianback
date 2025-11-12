import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = os.getenv("CONVERSATIONS_DB_PATH", os.path.join("data", "conversations.db"))
os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)


class ConversationStorage:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    name TEXT,
                    phone TEXT,
                    profile_json TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (channel, user_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_channel_user
                    ON messages(channel, user_id, id);
                """
            )

    def save_client(
        self,
        channel: str,
        user_id: str,
        *,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        profile: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "name": name,
            "phone": phone,
            "profile_json": json.dumps(profile) if profile else None,
            "updated_at": datetime.utcnow().isoformat(),
        }

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO clients (channel, user_id, name, phone, profile_json, updated_at)
                VALUES (:channel, :user_id, :name, :phone, :profile_json, :updated_at)
                ON CONFLICT(channel, user_id) DO UPDATE SET
                    name=COALESCE(excluded.name, clients.name),
                    phone=COALESCE(excluded.phone, clients.phone),
                    profile_json=COALESCE(excluded.profile_json, clients.profile_json),
                    updated_at=excluded.updated_at
                """,
                {**payload, "channel": channel, "user_id": user_id},
            )

    def add_message(
        self,
        channel: str,
        user_id: str,
        role: str,
        content: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO messages (channel, user_id, role, content, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    channel,
                    user_id,
                    role,
                    content,
                    json.dumps(meta) if meta else None,
                    datetime.utcnow().isoformat(),
                ),
            )

    def get_recent_messages(self, channel: str, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE channel = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (channel, user_id, limit),
            )
            rows = cursor.fetchall()

        return [
            {"role": row["role"], "content": row["content"]}
            for row in reversed(rows)
        ]


storage = ConversationStorage()
