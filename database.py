
import sqlite3
from pathlib import Path


# ==========================================
# 1. Database Configuration
# ==========================================

DB_PATH = Path(__file__).resolve().parent / "research_history.db"


# ==========================================
# 2. Database Connection
# ==========================================

def get_connection():

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    return connection


# ==========================================
# 3. Initialize Database
# ==========================================

def initialize_database():

    with get_connection() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS research_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                topic TEXT NOT NULL,

                report TEXT,

                critic_feedback TEXT,

                search_results TEXT,

                scraped_content TEXT,

                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
                )

            )
        """)


# ==========================================
# 4. Save Research
# ==========================================

def save_research(topic, result):

    if not topic or not topic.strip():
        raise ValueError("Research topic cannot be empty.")

    if not isinstance(result, dict):
        raise TypeError("Research result must be a dictionary.")

    with get_connection() as connection:

        cursor = connection.execute(
            """
            INSERT INTO research_history (
                topic,
                report,
                critic_feedback,
                search_results,
                scraped_content
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                topic.strip(),
                result.get("report", ""),
                result.get("feedback", ""),
                str(result.get("search_results", "")),
                result.get("scraped_content", ""),
            ),
        )

        return cursor.lastrowid


# ==========================================
# 5. Get All Research
# ==========================================

def get_all_research():

    with get_connection() as connection:

        rows = connection.execute(
            """
            SELECT id, topic, created_at
            FROM research_history
            ORDER BY id DESC
            """
        ).fetchall()

        return [dict(row) for row in rows]


# ==========================================
# 6. Get Research By ID
# ==========================================

def get_research_by_id(research_id):

    with get_connection() as connection:

        row = connection.execute(
            """
            SELECT *
            FROM research_history
            WHERE id = ?
            """,
            (research_id,),
        ).fetchone()

        return dict(row) if row else None


# ==========================================
# 7. Delete One Research Record
# ==========================================

def delete_research(research_id):

    with get_connection() as connection:

        connection.execute(
            """
            DELETE FROM research_history
            WHERE id = ?
            """,
            (research_id,),
        )


# ==========================================
# 8. Clear All Research History
# ==========================================

def clear_research_history():

    with get_connection() as connection:

        connection.execute(
            "DELETE FROM research_history"
        )
