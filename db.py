import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "data" / "bot.db"
DB_PATH.parent.mkdir(exist_ok=True)


def get_connection():
    # check_same_thread=False — если будешь использовать соединение из разных хендлеров,
    # но лучше создавать новое подключение на запрос.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            location TEXT,
            start_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_scheduled BOOLEAN NOT NULL CHECK (is_scheduled IN (0, 1))
        );
        """
    )
    conn.commit()
    conn.close()


def add_event_db(chat_id: int, title: str, location: str, start_at: datetime) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events (chat_id, title, location, start_at, created_at, is_scheduled)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (chat_id, title, location, start_at.isoformat(), datetime.now(tz=timezone.utc).isoformat(), 0),
    )
    conn.commit()
    event_id = cur.lastrowid
    conn.close()

    return event_id


def delete_event_by_id(id: int) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM table_name WHERE id = ?",
        (id,),
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def get_events_for_chat_db(chat_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM events WHERE chat_id = ? ORDER BY start_at",
        (chat_id,),
    )
    rows = cur.fetchall()
    conn.close()

    return rows
