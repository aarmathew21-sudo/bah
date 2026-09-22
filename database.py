import sqlite3
import json
import os
from typing import Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "study_store.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


def save_session_presentation(session_id: str, parsed_data: Dict[str, Any]):
    """Saves presentation content and slides scoped to a user session_id."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Delete existing data for this session if re-uploading
        cursor.execute("DELETE FROM slides WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM study_cache WHERE session_id = ?", (session_id,))
        
        # Insert or replace session
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (session_id, filename, total_slides, full_digest)
            VALUES (?, ?, ?, ?)
        """, (
            session_id,
            parsed_data.get("filename", "presentation.pptx"),
            parsed_data.get("total_slides", 0),
            parsed_data.get("full_digest", "")
        ))
        
        # Insert slides
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
    """Retrieves session presentation data."""
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
    """Caches generated study material (summary/flashcards/quiz) for a session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO study_cache (session_id, cache_key, data)
            VALUES (?, ?, ?)
        """, (session_id, cache_key, json.dumps(data)))
        conn.commit()


def get_study_cache(session_id: str, cache_key: str) -> Optional[Any]:
    """Retrieves cached study material for a session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM study_cache WHERE session_id = ? AND cache_key = ?", (session_id, cache_key))
        row = cursor.fetchone()
        if row and row["data"]:
            return json.loads(row["data"])
        return None
