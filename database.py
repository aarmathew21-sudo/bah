import sqlite3
import json
import os
import logging
from typing import Dict, Any, Optional
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("ppt_study_db")
DB_PATH = os.path.join(os.path.dirname(__file__), "study_store.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes SQLite database tables for multi-user session management and study caching."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                filename TEXT,
                total_slides INTEGER,
                full_digest TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Slides table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS slides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                slide_number INTEGER,
                title TEXT,
                text_content TEXT,
                tables TEXT,
                speaker_notes TEXT,
                raw_text TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        # Study items cache table (for summaries, flashcards, quizzes per session)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_cache (
                session_id TEXT,
                cache_key TEXT,
                data TEXT,
                PRIMARY KEY (session_id, cache_key),
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
    
    # Run routine session cleanup on initialization
    cleanup_expired_sessions(max_age_days=30)


def cleanup_expired_sessions(max_age_days: int = 30):
    """
    Evicts sessions created older than max_age_days to prevent database bloat.
    Cascading deletes remove associated slides and cached study items automatically.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE created_at < datetime('now', ?)", (f"-{max_age_days} days",))
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info(f"Evicted {deleted} expired session(s) older than {max_age_days} days.")
    except Exception as e:
        logger.error(f"Error executing session cleanup: {str(e)}")


def save_session_presentation(session_id: str, parsed_data: Dict[str, Any]):
    """Synchronous core save function."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM slides WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM study_cache WHERE session_id = ?", (session_id,))
        
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (session_id, filename, total_slides, full_digest, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            session_id,
            parsed_data.get("filename", "presentation.pptx"),
            parsed_data.get("total_slides", 0),
            parsed_data.get("full_digest", "")
        ))
        
        for slide in parsed_data.get("slides", []):
            cursor.execute("""
                INSERT INTO slides (session_id, slide_number, title, text_content, tables, speaker_notes, raw_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                slide.get("slide_number"),
                slide.get("title"),
                json.dumps(slide.get("text_content", [])),
                json.dumps(slide.get("tables", [])),
                slide.get("speaker_notes", ""),
                slide.get("raw_text", "")
            ))
            
        conn.commit()


def get_session_presentation(session_id: str) -> Optional[Dict[str, Any]]:
    """Synchronous core retrieval function."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        session_row = cursor.fetchone()
        
        if not session_row:
            return None
            
        cursor.execute("SELECT * FROM slides WHERE session_id = ? ORDER BY slide_number ASC", (session_id,))
        slide_rows = cursor.fetchall()
        
        slides = []
        for r in slide_rows:
            slides.append({
                "slide_number": r["slide_number"],
                "title": r["title"],
                "text_content": json.loads(r["text_content"]) if r["text_content"] else [],
                "tables": json.loads(r["tables"]) if r["tables"] else [],
                "speaker_notes": r["speaker_notes"],
                "raw_text": r["raw_text"]
            })
            
        return {
            "session_id": session_row["session_id"],
            "filename": session_row["filename"],
            "total_slides": session_row["total_slides"],
            "full_digest": session_row["full_digest"],
            "slides": slides
        }


def save_study_cache(session_id: str, cache_key: str, data: Any):
    """Synchronous core cache function."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO study_cache (session_id, cache_key, data)
            VALUES (?, ?, ?)
        """, (session_id, cache_key, json.dumps(data)))
        conn.commit()


def get_study_cache(session_id: str, cache_key: str) -> Optional[Any]:
    """Synchronous core cache retrieval function."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM study_cache WHERE session_id = ? AND cache_key = ?", (session_id, cache_key))
        row = cursor.fetchone()
        if row and row["data"]:
            return json.loads(row["data"])
        return None


# Threadpool Async Wrappers to prevent event-loop blocking under load
async def async_save_session_presentation(session_id: str, parsed_data: Dict[str, Any]):
    return await run_in_threadpool(save_session_presentation, session_id, parsed_data)

async def async_get_session_presentation(session_id: str) -> Optional[Dict[str, Any]]:
    return await run_in_threadpool(get_session_presentation, session_id)

async def async_save_study_cache(session_id: str, cache_key: str, data: Any):
    return await run_in_threadpool(save_study_cache, session_id, cache_key, data)

async def async_get_study_cache(session_id: str, cache_key: str) -> Optional[Any]:
    return await run_in_threadpool(get_study_cache, session_id, cache_key)
