import os
import json
import re
import hashlib
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("ppt_study_ai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


def validate_and_sanitize_api_key(api_key: Optional[str]) -> Optional[str]:
    """Validates client-supplied API key format."""
    if not api_key:
        return None
    key = api_key.strip()
    if len(key) < 10 or any(c in key for c in ["\n", "\r", " "]):
        logger.warning("Rejected invalid API key format supplied by client.")
        return None
    return key


def mask_api_key(key: Optional[str]) -> str:
    """Helper for safe logging."""
    if not key:
        return "None"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def _get_genai_client(api_key: Optional[str] = None):
    key = validate_and_sanitize_api_key(api_key) or os.environ.get("GEMINI_API_KEY")
    if not key or not HAS_GENAI:
        return None
    try:
        logger.info(f"Initializing GenAI client with key: {mask_api_key(key)}")
        return genai.Client(api_key=key)
    except Exception as e:
        logger.error(f"Failed to create GenAI client: {str(e)}")
        return None


def generate_stable_card_id(front_text: str) -> str:
    """Generates a stable 16-char SHA256 hash for card question text."""
    clean = front_text.strip().lower()
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()[:16]


def generate_study_summary(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    """Generates structured overview and key study topics."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])
    
    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are an enthusiastic ChatGPT AI Teacher helping a student master their presentation material.

Presentation Digest (including hidden speaker notes):
{digest}

Task: Create an easy-to-understand, engaging Study Guide.
Return a valid JSON object with the following schema:
{{
  "title": "Overall Presentation Topic",
  "summary": "2-3 sentence engaging overview written like a friendly teacher introducing the topic",
  "key_concepts": [
    {{
      "concept": "Concept Name",
      "explanation": "Simple, clear breakdown with an analogy or real-world example",
      "slides_referenced": "Slide numbers e.g. Slide 1, 3"
    }}
  ],
  "speaker_note_highlights": [
    "Important presenter insights extracted from speaker notes"
  ],
  "study_tips": [
    "Actionable tip for mastering this material"
  ]
}}
Respond ONLY with the JSON block.
"""
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            txt = response.text.strip()
            txt = re.sub(r'^```json\s*', '', txt)
            txt = re.sub(r'\s*```$', '', txt)
            return json.loads(txt)
        except Exception as e:
            logger.error(f"Gemini API error in summary generation: {str(e)}")

    # Fallback smart extraction
    concepts = []
    notes_highlights = []
    for s in slides:
        num = s["slide_number"]
        t = s["title"]
        texts = s.get("text_content", [])
        notes = s.get("speaker_notes", "")

        if texts:
            concepts.append({
                "concept": t,
                "explanation": f"Key focus: {' '.join(texts[:2]) if len(texts) > 0 else 'See slide content.'}",
                "slides_referenced": f"Slide {num}"
            })
        if notes:
            notes_highlights.append(f"Slide {num} ({t}): {notes}")

    return {
        "title": slides[0]["title"] if slides else "Presentation Study Guide",
        "summary": f"Welcome! I am your AI Teacher. Here is your study roadmap for these {len(slides)} slides and speaker notes.",
        "key_concepts": concepts[:8],
        "speaker_note_highlights": notes_highlights[:5],
        "study_tips": [
            "💡 Tip: Review speaker notes closely - teachers often put test questions there!",
            "🧠 Active Recall: Use the Flashcards tab to test yourself after reading each slide."
        ]
    }


def generate_flashcards(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> List[Dict[str, str]]:
    """Generates active recall study flashcards with stable card IDs for SM-2 spaced repetition tracking."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])

    cards = []
    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are a master educator. Create 8 to 15 active-recall flashcards based on these slides and presenter notes.

Presentation Data:
{digest}

Return a valid JSON array of objects with schema:
[
  {{
    "front": "Question or term requiring active recall",
    "back": "Clear, concise answer with key takeaway",
    "category": "Slide reference or topic"
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            txt = response.text.strip()
            txt = re.sub(r'^```json\s*', '', txt)
            txt = re.sub(r'\s*```$', '', txt)
            parsed_cards = json.loads(txt)
            if isinstance(parsed_cards, list) and len(parsed_cards) > 0:
                cards = parsed_cards
        except Exception as e:
            logger.error(f"Gemini API error in flashcard generation: {str(e)}")

    if not cards:
        # Fallback cards
        for s in slides:
            num = s["slide_number"]
            title = s["title"]
            notes = s.get("speaker_notes", "")
            text_content = s.get("text_content", [])

            if text_content:
                cards.append({
                    "front": f"What are the main concepts covered in: '{title}'?",
                    "back": "\n• ".join([""] + text_content),
                    "category": f"Slide {num}"
                })

            if notes:
                cards.append({
                    "front": f"What hidden presenter note is under '{title}'?",
                    "back": notes,
                    "category": f"Slide {num} Notes"
                })

    # Assign stable card_id and index
    for idx, card in enumerate(cards, start=1):
        card["card_id"] = generate_stable_card_id(card.get("front", ""))
        card["id"] = idx

    return cards


def generate_quiz(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generates multiple-choice quiz questions."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])

    client = _get_genai_client(api_key)
    if client:
        prompt = f"""Generate a 5-10 question multiple-choice quiz based on these slides and presenter notes.

Presentation Data:
{digest}

Return a valid JSON array of question objects:
[
  {{
    "id": 1,
    "question": "Question text...",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "answer_index": 0,
    "explanation": "Friendly teacher explanation explaining why this answer is correct."
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            txt = response.text.strip()
            txt = re.sub(r'^```json\s*', '', txt)
            txt = re.sub(r'\s*```$', '', txt)
            quiz = json.loads(txt)
            if isinstance(quiz, list) and len(quiz) > 0:
                return quiz
        except Exception as e:
            logger.error(f"Gemini API error in quiz generation: {str(e)}")

    # Fallback quiz
    quiz = []
    for idx, s in enumerate(slides, start=1):
        if s.get("text_content"):
            main_pt = s["text_content"][0]
            quiz.append({
                "id": idx,
                "question": f"Regarding Slide {s['slide_number']} ({s['title']}), which statement is correct?",
                "options": [
                    main_pt,
                    "This concept is not mentioned in the presentation.",
                    "The presenter noted that this topic will be skipped.",
                    "None of the above."
                ],
                "answer_index": 0,
                "explanation": f"👨‍🏫 Teacher Note: Slide {s['slide_number']} highlights: {main_pt}"
            })
    return quiz[:8]


def answer_study_chat(
    ppt_data: Dict[str, Any],
    chat_history: List[Dict[str, str]],
    user_message: str,
    teacher_mode: str = "tutor",
    api_key: Optional[str] = None
) -> str:
    """Answers student questions adopting a ChatGPT Teacher persona."""
    digest = ppt_data.get("full_digest", "")
    client = _get_genai_client(api_key)

    mode_instructions = {
        "tutor": "You are a warm, highly effective ChatGPT AI Teacher. Break concepts down step-by-step, use formatting, and ask a quick follow-up question to ensure understanding.",
        "eli5": "You are a friendly teacher explaining complex concepts to a 5-year-old. Use fun real-world analogies, simple language, and short paragraphs.",
        "quiz_me": "You are an interactive AI examiner. Ask the student a thought-provoking practice question based on the presentation text and speaker notes, then give feedback on their response.",
        "notes_deepdive": "You are a specialist focusing on the presenter's hidden speaker notes. Explain what the presenter intended to convey beyond the bullet points on the slides."
    }

    selected_instruction = mode_instructions.get(teacher_mode, mode_instructions["tutor"])

    if client:
        system_instruction = f"""{selected_instruction}

Presentation Material (Slides & Speaker Notes):
{digest}

Behavior Rules:
1. Always be patient, encouraging, and easy to follow.
2. Highlight speaker notes explicitly when relevant using 📌 **Speaker Note Insight**.
3. Cite slide numbers e.g. [Slide 2].
4. End your message with an engaging check for understanding.
"""
        formatted_history = ""
        for msg in chat_history[-6:]:
            role = "Student" if msg.get("role") == "user" else "AI Teacher"
            formatted_history += f"{role}: {msg.get('content')}\n"

        prompt = f"{system_instruction}\n\nRecent Conversation:\n{formatted_history}\nStudent: {user_message}\nAI Teacher:"

        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API chat error: {str(e)}")
            return f"Error connecting to AI Teacher: {str(e)}"

    # Smart local fallback answer
    user_lower = user_message.lower()
    matches = []
    for s in ppt_data.get("slides", []):
        combined = s.get("raw_text", "")
        if any(w in combined.lower() for w in user_lower.split() if len(w) > 3):
            matches.append(s)

    mode_prefix = f"[{teacher_mode.upper()} MODE] " if teacher_mode != "tutor" else ""

    if matches:
        target = matches[0]
        res = f"👨‍🏫 **{mode_prefix}AI Teacher Explanation for Slide {target['slide_number']}: {target['title']}**\n\n"
        if target.get("text_content"):
            res += "Here are the core takeaways in simple terms:\n"
            for pt in target["text_content"]:
                res += f"• **{pt}**\n"
            res += "\n"
        
        if target.get("speaker_notes"):
            res += f"📌 **Hidden Presenter Note Insight**:\n\"{target['speaker_notes']}\"\n\n"

        res += "💡 *Teacher Check*: Does this explanation make sense, or would you like me to clarify a specific point?"
        res += "\n\n*(Tip: Enter a Gemini API Key in settings to unlock full conversational ChatGPT Teacher AI!)*"
        return res

    return f"👨‍🏫 **AI Teacher**: {mode_prefix}I couldn't find a direct reference to that in the slides or speaker notes. Try asking about a specific slide topic, or ask me: *'Teach me Slide 1'*!\n*(Add a Gemini API Key for unrestricted conversational AI tutoring!)*"
