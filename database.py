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
    """Initializes SQLite database tables for sessions, slides, SM-2 reviews, and Quiz Master results."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                filename TEXT,
                total_slides INTEGER,
                full_digest TEXT,
                metadata TEXT,
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
                doc_name TEXT DEFAULT '',
                doc_slide_number INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        # Migrations for existing DB instances
        try:
            cursor.execute("ALTER TABLE slides ADD COLUMN doc_name TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE slides ADD COLUMN doc_slide_number INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN metadata TEXT DEFAULT ''")
        except Exception:
            pass
        
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
        
        # Quiz Master Exam Results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                exam_title TEXT,
                score INTEGER,
                total_questions INTEGER,
                percentage REAL,
                time_spent_seconds INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)

        # Session Memory table (commits student insights, topics explored, weak spots, custom goals)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_memory (
                session_id TEXT,
                memory_key TEXT,
                memory_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, memory_key),
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)

        # Study Progress & Gamification table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_progress (
                session_id TEXT PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                streak_days INTEGER DEFAULT 1,
                last_active_date TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)

        try:
            cursor.execute("ALTER TABLE slides ADD COLUMN has_warning INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE slides ADD COLUMN warning_message TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE card_reviews ADD COLUMN slide_number INTEGER DEFAULT 0")
        except Exception:
            pass
        
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
        cursor.execute("DELETE FROM quiz_results WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM session_memory WHERE session_id = ?", (session_id,))
        
        metadata = {
            "filenames": parsed_data.get("filenames", [parsed_data.get("filename", "presentation.pptx")]),
            "documents": parsed_data.get("documents", [])
        }

        cursor.execute("""
            INSERT OR REPLACE INTO sessions (session_id, filename, total_slides, full_digest, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            session_id,
            parsed_data.get("filename", "presentation.pptx"),
            parsed_data.get("total_slides", 0),
            parsed_data.get("full_digest", ""),
            json.dumps(metadata)
        ))
        
        for slide in parsed_data.get("slides", []):
            cursor.execute("""
                INSERT INTO slides (session_id, slide_number, title, text_content, tables, speaker_notes, raw_text, doc_name, doc_slide_number, has_warning, warning_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                slide.get("slide_number"),
                slide.get("title"),
                json.dumps(slide.get("text_content", [])),
                json.dumps(slide.get("tables", [])),
                slide.get("speaker_notes", ""),
                slide.get("raw_text", ""),
                slide.get("doc_name", parsed_data.get("filename", "")),
                slide.get("doc_slide_number", slide.get("slide_number", 1)),
                1 if slide.get("has_warning") else 0,
                slide.get("warning_message", "")
            ))
            
        # Ensure session has a progress record
        today_date = datetime.utcnow().strftime("%Y-%m-%d")
        cursor.execute("""
            INSERT OR IGNORE INTO study_progress (session_id, xp, streak_days, last_active_date)
            VALUES (?, 0, 1, ?)
        """, (session_id, today_date))

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
        
        col_names = [col[0] for col in cursor.description]
        has_doc_name = "doc_name" in col_names
        has_doc_slide_number = "doc_slide_number" in col_names
        has_warning_col = "has_warning" in col_names
        has_warning_msg_col = "warning_message" in col_names
        
        slides = []
        for r in slide_rows:
            slide_dict = {
                "slide_number": r["slide_number"],
                "title": r["title"],
                "text_content": json.loads(r["text_content"]) if r["text_content"] else [],
                "tables": json.loads(r["tables"]) if r["tables"] else [],
                "speaker_notes": r["speaker_notes"],
                "raw_text": r["raw_text"],
                "doc_name": r["doc_name"] if has_doc_name and r["doc_name"] else session_row["filename"],
                "doc_slide_number": r["doc_slide_number"] if has_doc_slide_number and r["doc_slide_number"] else r["slide_number"],
                "has_warning": bool(r["has_warning"]) if has_warning_col and r["has_warning"] else False,
                "warning_message": r["warning_message"] if has_warning_msg_col and r["warning_message"] else ""
            }
            slides.append(slide_dict)
            
        metadata = {}
        if "metadata" in session_row.keys() and session_row["metadata"]:
            try:
                metadata = json.loads(session_row["metadata"])
            except Exception:
                pass

        return {
            "session_id": session_row["session_id"],
            "filename": session_row["filename"],
            "total_slides": session_row["total_slides"],
            "full_digest": session_row["full_digest"],
            "filenames": metadata.get("filenames", [session_row["filename"]]),
            "documents": metadata.get("documents", []),
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


# --- Quiz Master Results Persistence ---

def save_quiz_result(
    session_id: str,
    exam_title: str,
    score: int,
    total_questions: int,
    percentage: float,
    time_spent_seconds: int,
    details: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Saves a Quiz Master exam result in SQLite."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO quiz_results (
                session_id, exam_title, score, total_questions, percentage, time_spent_seconds, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            exam_title,
            score,
            total_questions,
            percentage,
            time_spent_seconds,
            json.dumps(details)
        ))
        result_id = cursor.lastrowid
        conn.commit()

        return {
            "id": result_id,
            "exam_title": exam_title,
            "score": score,
            "total_questions": total_questions,
            "percentage": percentage,
            "time_spent_seconds": time_spent_seconds,
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }


def get_quiz_history(session_id: str) -> List[Dict[str, Any]]:
    """Retrieves exam score history for a session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, exam_title, score, total_questions, percentage, time_spent_seconds, created_at, details
            FROM quiz_results
            WHERE session_id = ?
            ORDER BY created_at DESC
        """, (session_id,))
        rows = cursor.fetchall()

        history = []
        for r in rows:
            history.append({
                "id": r["id"],
                "exam_title": r["exam_title"],
                "score": r["score"],
                "total_questions": r["total_questions"],
                "percentage": r["percentage"],
                "time_spent_seconds": r["time_spent_seconds"],
                "created_at": r["created_at"],
                "details": json.loads(r["details"]) if r["details"] else []
            })
        return history


# --- SM-2 Spaced Repetition Logic ---

def record_card_review(session_id: str, card_id: str, rating: str, slide_number: Optional[int] = None) -> Dict[str, Any]:
    """Implements standard SuperMemo-2 (SM-2) spaced repetition updates and associates cards with slide_number."""
    rating_map = {
        "again": 0,
        "hard": 3,
        "good": 4,
        "easy": 5
    }
    q = rating_map.get(rating.lower(), 4)

    # If slide_number not provided, attempt lookup from cached flashcards
    if not slide_number:
        try:
            cached_cards = get_study_cache(session_id, "flashcards") or []
            for c in cached_cards:
                if c.get("card_id") == card_id:
                    slide_number = c.get("slide_number", 0)
                    break
        except Exception:
            slide_number = 0

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

        ease_factor = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        if ease_factor < 1.3:
            ease_factor = 1.3

        now = datetime.utcnow()
        next_review = now + timedelta(days=interval_days)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        next_review_str = next_review.strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT OR REPLACE INTO card_reviews (
                session_id, card_id, ease_factor, interval_days, repetitions, next_review_date, last_reviewed_at, slide_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            card_id,
            ease_factor,
            interval_days,
            repetitions,
            next_review_str,
            now_str,
            slide_number or 0
        ))
        conn.commit()

        return {
            "card_id": card_id,
            "rating": rating,
            "ease_factor": ease_factor,
            "interval_days": interval_days,
            "repetitions": repetitions,
            "next_review_date": next_review_str,
            "slide_number": slide_number or 0
        }


def get_due_flashcards(session_id: str) -> Dict[str, Any]:
    """Returns flashcards due for SM-2 review."""
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
            
            if rev["next_review_date"] <= now_str:
                due_cards.append(card_copy)
        else:
            card_copy["ease_factor"] = 2.5
            card_copy["interval_days"] = 0
            card_copy["repetitions"] = 0
            card_copy["next_review_date"] = now_str
            due_cards.append(card_copy)

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

async def async_save_quiz_result(session_id: str, exam_title: str, score: int, total_questions: int, percentage: float, time_spent_seconds: int, details: List[Dict[str, Any]]):
    return await run_in_threadpool(save_quiz_result, session_id, exam_title, score, total_questions, percentage, time_spent_seconds, details)

async def async_get_quiz_history(session_id: str) -> List[Dict[str, Any]]:
    return await run_in_threadpool(get_quiz_history, session_id)


def save_session_memory(session_id: str, memory_key: str, memory_value: str):
    """Stores key insights, topics discussed, or student preferences for the active session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO session_memory (session_id, memory_key, memory_value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (session_id, memory_key, memory_value))
        conn.commit()


def get_all_session_memory(session_id: str) -> Dict[str, str]:
    """Retrieves all stored session memory items for the active session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT memory_key, memory_value FROM session_memory WHERE session_id = ? ORDER BY updated_at ASC", (session_id,))
        rows = cursor.fetchall()
        return {r["memory_key"]: r["memory_value"] for r in rows}


def clear_session_memory(session_id: str):
    """Clears all session memory for the active session."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM session_memory WHERE session_id = ?", (session_id,))
        conn.commit()


async def async_save_session_memory(session_id: str, memory_key: str, memory_value: str):
    return await run_in_threadpool(save_session_memory, session_id, memory_key, memory_value)


async def async_get_all_session_memory(session_id: str) -> Dict[str, str]:
    return await run_in_threadpool(get_all_session_memory, session_id)


async def async_clear_session_memory(session_id: str):
    return await run_in_threadpool(clear_session_memory, session_id)


def get_level_info(xp: int) -> Dict[str, Any]:
    """Computes level name, badge, and progress to next level based on server-side XP."""
    if xp < 100:
        return {
            "level": "Novice",
            "level_num": 1,
            "badge": "🌱 Novice",
            "current_xp": xp,
            "min_xp": 0,
            "next_level_xp": 100,
            "progress_pct": min(100, max(0, int((xp / 100) * 100)))
        }
    elif xp < 250:
        return {
            "level": "Apprentice",
            "level_num": 2,
            "badge": "⚡ Apprentice",
            "current_xp": xp,
            "min_xp": 100,
            "next_level_xp": 250,
            "progress_pct": min(100, max(0, int(((xp - 100) / 150) * 100)))
        }
    elif xp < 500:
        return {
            "level": "Scholar",
            "level_num": 3,
            "badge": "📚 Scholar",
            "current_xp": xp,
            "min_xp": 250,
            "next_level_xp": 500,
            "progress_pct": min(100, max(0, int(((xp - 250) / 250) * 100)))
        }
    elif xp < 1000:
        return {
            "level": "Master",
            "level_num": 4,
            "badge": "🛡️ Master",
            "current_xp": xp,
            "min_xp": 500,
            "next_level_xp": 1000,
            "progress_pct": min(100, max(0, int(((xp - 500) / 500) * 100)))
        }
    else:
        return {
            "level": "Sage",
            "level_num": 5,
            "badge": "🧙 Sage",
            "current_xp": xp,
            "min_xp": 1000,
            "next_level_xp": 1000,
            "progress_pct": 100
        }


def get_progress(session_id: str) -> Dict[str, Any]:
    """Retrieves gamification progress, streak, XP, level, and next mission recommendation."""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO sessions (session_id, filename, total_slides, full_digest, metadata) VALUES (?, '', 0, '', '')", (session_id,))
        cursor.execute("SELECT xp, streak_days, last_active_date FROM study_progress WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()

        if not row:
            cursor.execute("""
                INSERT OR IGNORE INTO study_progress (session_id, xp, streak_days, last_active_date)
                VALUES (?, 0, 1, ?)
            """, (session_id, today_str))
            conn.commit()
            xp = 0
            streak_days = 1
            last_active = today_str
        else:
            xp = row["xp"]
            streak_days = row["streak_days"]
            last_active = row["last_active_date"]

    if last_active and last_active != today_str and last_active != yesterday_str:
        streak_days = 1

    due_info = get_due_flashcards(session_id)
    cards_due_count = due_info.get("total_due", 0)

    mastery_info = get_mastery(session_id)
    weak_spots = mastery_info.get("weak_spots", [])
    weakest_slide_num = weak_spots[0] if weak_spots else (1 if mastery_info.get("slides") else None)
    weakest_title = f"Slide {weakest_slide_num}" if weakest_slide_num else "General Review"
    if weakest_slide_num and mastery_info.get("slides"):
        for sm in mastery_info["slides"]:
            if sm["slide_number"] == weakest_slide_num:
                weakest_title = sm["title"]
                break

    if cards_due_count > 0:
        recommended_mission = {
            "type": "flashcards",
            "title": f"Review {cards_due_count} Due Card{'s' if cards_due_count > 1 else ''}",
            "description": f"Solidify memory with active recall SM-2 intervals.",
            "target_tab": "tab-flashcards",
            "button_label": "Start Deck Run"
        }
    elif weakest_slide_num and weak_spots:
        recommended_mission = {
            "type": "mastery",
            "title": f"Reinforce Weak Spot: Slide {weakest_slide_num}",
            "description": f"Master '{weakest_title[:32]}' with Socratic guidance.",
            "target_tab": "tab-mastery",
            "button_label": "Review Weak Spot"
        }
    else:
        recommended_mission = {
            "type": "quizmaster",
            "title": "Challenge Quiz Master Boss",
            "description": "Put your understanding to the test in Boss Battle mode.",
            "target_tab": "tab-quizmaster",
            "button_label": "Enter Boss Battle"
        }

    level_data = get_level_info(xp)

    return {
        "xp": xp,
        "streak_days": streak_days,
        "last_active_date": last_active or today_str,
        "daily_goal_xp": 20,
        "cards_due_count": cards_due_count,
        "weak_spots": weak_spots,
        "weakest_slide": weakest_slide_num,
        "weakest_slide_title": weakest_title,
        "level": level_data,
        "recommended_mission": recommended_mission
    }


def record_progress_event(session_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Records a study event and computes server-side XP and streak increments (never trusts client XP)."""
    payload = payload or {}

    if event_type == "card_reviewed":
        rating = str(payload.get("rating", "good")).lower()
        xp_map = {"again": 5, "hard": 10, "good": 15, "easy": 20}
        earned_xp = xp_map.get(rating, 10)
    elif event_type == "quiz_answered":
        is_correct = bool(payload.get("is_correct", True))
        earned_xp = 15 if is_correct else 5
    elif event_type == "exam_finished":
        score = int(payload.get("score", 0))
        earned_xp = 50 + max(0, score * 5)
    elif event_type == "chat_used":
        earned_xp = 10
    elif event_type == "feynman_completed":
        clarity = int(payload.get("clarity_score", 70))
        earned_xp = 25 + min(50, max(0, int(clarity * 0.5)))
    else:
        earned_xp = 10

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO sessions (session_id, filename, total_slides, full_digest, metadata) VALUES (?, '', 0, '', '')", (session_id,))
        cursor.execute("SELECT xp, streak_days, last_active_date FROM study_progress WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()

        if not row:
            streak = 1
            current_xp = 0
        else:
            current_xp = row["xp"]
            last_date = row["last_active_date"]
            stored_streak = row["streak_days"]

            if not last_date:
                streak = 1
            elif last_date == today_str:
                streak = stored_streak
            elif last_date == yesterday_str:
                streak = stored_streak + 1
            else:
                streak = 1

        new_xp = current_xp + earned_xp

        cursor.execute("""
            INSERT OR REPLACE INTO study_progress (session_id, xp, streak_days, last_active_date, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (session_id, new_xp, streak, today_str))
        conn.commit()

    return {
        "success": True,
        "event_type": event_type,
        "xp_earned": earned_xp,
        "total_xp": new_xp,
        "streak_days": streak,
        "level": get_level_info(new_xp)
    }


def get_mastery(session_id: str) -> Dict[str, Any]:
    """Calculates granular slide-by-slide mastery scores based on SM-2 card intervals and quiz performance."""
    presentation = get_session_presentation(session_id)
    if not presentation:
        return {"slides": [], "weak_spots": [], "overall_mastery": 0}

    slides = presentation.get("slides", [])
    if not slides:
        return {"slides": [], "weak_spots": [], "overall_mastery": 0}

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT card_id, slide_number, ease_factor, interval_days, repetitions FROM card_reviews WHERE session_id = ?", (session_id,))
        review_rows = cursor.fetchall()
        reviews = [dict(r) for r in review_rows]

        cursor.execute("SELECT details FROM quiz_results WHERE session_id = ?", (session_id,))
        quiz_rows = cursor.fetchall()

    reviews_by_slide: Dict[int, List[Dict[str, Any]]] = {}
    for r in reviews:
        s_num = r.get("slide_number", 0)
        if s_num > 0:
            reviews_by_slide.setdefault(s_num, []).append(r)

    quiz_results_by_slide: Dict[int, List[bool]] = {}
    for qr in quiz_rows:
        if qr["details"]:
            try:
                dtls = json.loads(qr["details"])
                for d in dtls:
                    s_num = d.get("slide_number")
                    if s_num and isinstance(s_num, int):
                        is_corr = d.get("is_correct", d.get("selected_index") == d.get("correct_index"))
                        quiz_results_by_slide.setdefault(s_num, []).append(bool(is_corr))
            except Exception:
                pass

    cached_cards = get_study_cache(session_id, "flashcards") or []
    cards_count_by_slide: Dict[int, int] = {}
    for c in cached_cards:
        s_num = c.get("slide_number", 0)
        if s_num > 0:
            cards_count_by_slide[s_num] = cards_count_by_slide.get(s_num, 0) + 1

    slides_mastery = []
    total_score_sum = 0

    for s in slides:
        s_num = s["slide_number"]
        s_title = s.get("title", f"Slide {s_num}")
        has_warn = s.get("has_warning", False)
        warn_msg = s.get("warning_message", "")

        score = 0
        s_revs = reviews_by_slide.get(s_num, [])
        s_quizzes = quiz_results_by_slide.get(s_num, [])

        if s_revs:
            avg_interval = sum(r["interval_days"] for r in s_revs) / len(s_revs)
            avg_reps = sum(r["repetitions"] for r in s_revs) / len(s_revs)
            if avg_interval >= 6 or avg_reps >= 2:
                score += 55
            elif avg_interval >= 1 or avg_reps >= 1:
                score += 35
            else:
                score += 15

        if s_quizzes:
            correct_ratio = sum(1 for q in s_quizzes if q) / len(s_quizzes)
            score += int(correct_ratio * 45)

        mastery_score = min(100, score)
        total_score_sum += mastery_score

        if mastery_score == 0:
            status = "empty"
        elif mastery_score < 70:
            status = "learning"
        else:
            status = "mastered"

        slides_mastery.append({
            "slide_number": s_num,
            "title": s_title,
            "mastery_score": mastery_score,
            "status": status,
            "cards_count": cards_count_by_slide.get(s_num, len(s_revs)),
            "is_weak_spot": False,
            "has_warning": has_warn,
            "warning_message": warn_msg,
            "speaker_notes": s.get("speaker_notes", ""),
            "text_content": s.get("text_content", []),
            "tables": s.get("tables", [])
        })

    tested_weak = [sm for sm in slides_mastery if 0 < sm["mastery_score"] < 70]
    untested = [sm for sm in slides_mastery if sm["mastery_score"] == 0]

    candidate_weak = tested_weak if tested_weak else untested
    candidate_weak.sort(key=lambda x: x["mastery_score"])
    weak_spots_nums = [sm["slide_number"] for sm in candidate_weak[:3]]

    for sm in slides_mastery:
        if sm["slide_number"] in weak_spots_nums:
            sm["is_weak_spot"] = True

    overall_avg = int(total_score_sum / max(1, len(slides_mastery)))

    return {
        "slides": slides_mastery,
        "weak_spots": weak_spots_nums,
        "overall_mastery": overall_avg
    }


async def async_get_progress(session_id: str) -> Dict[str, Any]:
    return await run_in_threadpool(get_progress, session_id)


async def async_record_progress_event(session_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await run_in_threadpool(record_progress_event, session_id, event_type, payload)


async def async_get_mastery(session_id: str) -> Dict[str, Any]:
    return await run_in_threadpool(get_mastery, session_id)

