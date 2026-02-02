import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Sequence, Mapping


DB_PATH = Path(__file__).parent / "data" / "bot.db"
DB_PATH.parent.mkdir(exist_ok=True)


def get_connection():
    # check_same_thread=False — если будешь использовать соединение из разных хендлеров,
    # но лучше создавать новое подключение на запрос.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def init_db(reset: bool = False):
    conn = get_connection()
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    if reset:
        cur.execute("DROP TABLE IF EXISTS notifications;")
        cur.execute("DROP TABLE IF EXISTS events;")
    
    # таблица событий
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

    # Таблица уведомлений по событиям
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            reminder TEXT NOT NULL,
            notify_at TEXT NOT NULL,
            job_name TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );
        """
    )
    
    # удаляем просроченные события
    cur.execute(
        "DELETE FROM events WHERE start_at < datetime('now')"
    )

    # чистим таблицу с уведомлениями
    cur.execute(
        "DELETE FROM notifications"
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
        (chat_id, title, location, start_at.astimezone(timezone.utc), datetime.now(tz=timezone.utc).isoformat(), 0),
    )
    conn.commit()
    event_id = cur.lastrowid
    conn.close()

    return event_id


def add_notification_db(event_id: int, reminder: str, notify_at: int) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO notifications(event_id, reminder, notify_at, job_name, status)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (event_id, reminder, notify_at, None, "created"),
    )
    conn.commit()
    notification_id = cur.lastrowid
    conn.close()

    return notification_id


def get_notification_by_id(notification_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            *
        FROM 
            notifications 
        INNER JOIN 
            events ON notifications.event_id = events.id
        WHERE notifications.id = ?
        """,
        (notification_id,),
    )
    row = cur.fetchone()
    conn.close()

    return row


def get_notifications_by_event_id(event_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            *
        FROM 
            notifications 
        WHERE event_id = ?
        """,
        (event_id,),
    )
    rows = cur.fetchall()
    conn.close()

    return rows


def get_notifation_by_job(job_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            *
        FROM 
            notifications 
        INNER JOIN 
            events ON notifications.event_id = events.id
        WHERE notifications.job_name = ?
        """,
        (job_name,),
    )
    row = cur.fetchone()
    conn.close()

    return row


def update_notification_by_id(id, job_name, status):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE notifications SET job_name = ?, status = ? WHERE id = ?
        """,
        (job_name, status, id),
    )
    conn.commit()
    updated = cur.rowcount
    conn.close()

    return updated


def delete_event_by_id(id: int) -> int:
    conn = get_connection()
    # для каскадного удаления
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM events WHERE id = ?",
        (id,),
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def delete_notification_by_job(job_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notifications WHERE job_name = ?",
        (job_name,),
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def delete_all_notifications():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notifications",
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


def get_unschedule_events():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM events WHERE is_scheduled = ? ORDER BY start_at",
        (0,),
    )
    rows = cur.fetchall()
    conn.close()

    return rows


def bulk_insert_events(chat_id: int, events: Sequence[Mapping]) -> int:
    """Возвращает кол-во вставленных строк."""
    if not events:
        return 0

    rows = []
    for e in events:
        # здесь можно сделать парсинг/валидацию даты
        rows.append((chat_id, e["title"], e["location"], e["start_at"], datetime.now(tz=timezone.utc).isoformat(), 0))

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.executemany(
            """
            INSERT INTO events (chat_id, title, location, start_at, created_at, is_scheduled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return cur.rowcount  # может быть -1 в sqlite, можно просто len(rows)
    finally:
        conn.close()
