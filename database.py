import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("ppt_study_db")
DB_PATH = os.path.join(os.path.dirname(__file__), "study_store.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes SQLite database tables for multi-user session management, card reviews (SM-2), and study caching."""
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
        
        # Study items cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_cache (
                session_id TEXT,
                cache_key TEXT,
                data TEXT,
                PRIMARY KEY (session_id, cache_key),
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        # Spaced Repetition (SM-2) Card Reviews table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS card_reviews (
                session_id TEXT,
                card_id TEXT,
                ease_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 0,
                repetitions INTEGER DEFAULT 0,
                next_review_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, card_id),
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
    
    # Run routine session cleanup on initialization
    cleanup_expired_sessions(max_age_days=30)


def cleanup_expired_sessions(max_age_days: int = 30):
    """Evicts sessions created older than max_age_days to prevent database bloat."""
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
    """Saves presentation content and slides scoped to a user session_id."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM slides WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM study_cache WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM card_reviews WHERE session_id = ?", (session_id,))
        
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


# --- SM-2 Spaced Repetition Logic ---

def record_card_review(session_id: str, card_id: str, rating: str) -> Dict[str, Any]:
    """
    Implements standard SuperMemo-2 (SM-2) spaced repetition updates:
    Rating maps to quality q: 'again' -> 0, 'hard' -> 3, 'good' -> 4, 'easy' -> 5.
    Calculates interval_days, ease_factor, repetitions, and next_review_date.
    """
    rating_map = {
        "again": 0,
        "hard": 3,
        "good": 4,
        "easy": 5
    }
    q = rating_map.get(rating.lower(), 4)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ease_factor, interval_days, repetitions FROM card_reviews WHERE session_id = ? AND card_id = ?",
            (session_id, card_id)
        )
        row = cursor.fetchone()

        if row:
            ease_factor = row["ease_factor"]
            interval_days = row["interval_days"]
            repetitions = row["repetitions"]
        else:
            ease_factor = 2.5
            interval_days = 0
            repetitions = 0

        # Standard SM-2 interval update logic
        if q < 3:
            repetitions = 0
            interval_days = 1
        else:
            if repetitions == 0:
                interval_days = 1
            elif repetitions == 1:
                interval_days = 6
            else:
                interval_days = max(1, int(round(interval_days * ease_factor)))
            repetitions += 1

        # Ease factor update formula
        ease_factor = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        if ease_factor < 1.3:
            ease_factor = 1.3

        now = datetime.utcnow()
        next_review = now + timedelta(days=interval_days)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        next_review_str = next_review.strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT OR REPLACE INTO card_reviews (
                session_id, card_id, ease_factor, interval_days, repetitions, next_review_date, last_reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            card_id,
            ease_factor,
            interval_days,
            repetitions,
            next_review_str,
            now_str
        ))
        conn.commit()

        return {
            "card_id": card_id,
            "rating": rating,
            "ease_factor": ease_factor,
            "interval_days": interval_days,
            "repetitions": repetitions,
            "next_review_date": next_review_str
        }


def get_due_flashcards(session_id: str) -> Dict[str, Any]:
    """
    Returns flashcards from the session's cached deck where next_review_date <= now or unreviewed.
    Cards are sorted so overdue cards come first.
    """
    all_cards = get_study_cache(session_id, "flashcards") or []
    if not all_cards:
        return {"due_flashcards": [], "total_due": 0, "total_cards": 0}

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM card_reviews WHERE session_id = ?", (session_id,))
        review_rows = cursor.fetchall()
        
        reviews_map = {r["card_id"]: dict(r) for r in review_rows}

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    due_cards = []
    for card in all_cards:
        cid = card.get("card_id")
        rev = reviews_map.get(cid)
        
        card_copy = dict(card)
        if rev:
            card_copy["ease_factor"] = rev["ease_factor"]
            card_copy["interval_days"] = rev["interval_days"]
            card_copy["repetitions"] = rev["repetitions"]
            card_copy["next_review_date"] = rev["next_review_date"]
            card_copy["last_reviewed_at"] = rev["last_reviewed_at"]
            
            # Due if next_review_date <= now
            if rev["next_review_date"] <= now_str:
                due_cards.append(card_copy)
        else:
            # Unreviewed card is due
            card_copy["ease_factor"] = 2.5
            card_copy["interval_days"] = 0
            card_copy["repetitions"] = 0
            card_copy["next_review_date"] = now_str
            due_cards.append(card_copy)

    # Sort due cards: unreviewed first, then by next_review_date ascending
    due_cards.sort(key=lambda c: c.get("next_review_date", now_str))

    return {
        "due_flashcards": due_cards,
        "total_due": len(due_cards),
        "total_cards": len(all_cards)
    }


# Threadpool Async Wrappers to prevent event-loop blocking under load
async def async_save_session_presentation(session_id: str, parsed_data: Dict[str, Any]):
    return await run_in_threadpool(save_session_presentation, session_id, parsed_data)

async def async_get_session_presentation(session_id: str) -> Optional[Dict[str, Any]]:
    return await run_in_threadpool(get_session_presentation, session_id)

async def async_save_study_cache(session_id: str, cache_key: str, data: Any):
    return await run_in_threadpool(save_study_cache, session_id, cache_key, data)

async def async_get_study_cache(session_id: str, cache_key: str) -> Optional[Any]:
    return await run_in_threadpool(get_study_cache, session_id, cache_key)

async def async_record_card_review(session_id: str, card_id: str, rating: str) -> Dict[str, Any]:
    return await run_in_threadpool(record_card_review, session_id, card_id, rating)

async def async_get_due_flashcards(session_id: str) -> Dict[str, Any]:
    return await run_in_threadpool(get_due_flashcards, session_id)
