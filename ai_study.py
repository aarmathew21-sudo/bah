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


DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def _generate_content_with_fallback(client, prompt: str):
    """Attempts generation with DEFAULT_GEMINI_MODEL ('gemini-2.5-flash'), and gracefully falls back to 'gemini-2.0-flash' or 'gemini-1.5-flash' if 404 / deprecated model error occurs."""
    models_to_try = [
        DEFAULT_GEMINI_MODEL,
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-pro"
    ]
    unique_models = []
    for m in models_to_try:
        if m and m not in unique_models:
            unique_models.append(m)

    last_exc = None
    for mod in unique_models:
        try:
            logger.info(f"Attempting content generation with model: '{mod}'")
            return client.models.generate_content(
                model=mod,
                contents=prompt
            )
        except Exception as e:
            last_exc = e
            err_msg = str(e).lower()
            if any(term in err_msg for term in ["not_found", "404", "no longer available", "invalid", "not found"]):
                logger.warning(f"Gemini model '{mod}' returned error ({str(e)}). Retrying with next model candidate...")
                continue
            raise e
    if last_exc:
        raise last_exc


def generate_stable_card_id(front_text: str) -> str:
    """Generates a stable 16-char SHA256 hash for card question text."""
    clean = front_text.strip().lower()
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()[:16]


def generate_study_summary(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    """Generates comprehensive structured overview and key study topics."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])
    
    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are an expert AI Educator and Professor creating a master Study Guide for a student.

Presentation Material & Presenter Notes:
{digest}

Task: Synthesize a thorough, highly readable Study Guide that extracts core domain knowledge, definitions, formulas, tables, and speaker note insights.

Return a valid JSON object with the following schema:
{{
  "title": "Clear Main Topic Title",
  "summary": "3-4 sentence comprehensive, encouraging overview outlining what the student will master from this material",
  "key_concepts": [
    {{
      "concept": "Core Concept / Term Name",
      "explanation": "Thorough, simple breakdown explaining how it works with a practical analogy or real-world example",
      "slides_referenced": "Slide numbers e.g. Slide 1, 3"
    }}
  ],
  "speaker_note_highlights": [
    "Important presenter insight or hidden test clue extracted directly from speaker notes"
  ],
  "study_tips": [
    "Actionable, high-yield tip for mastering this presentation material"
  ]
}}
Respond ONLY with the JSON block.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
            txt = response.text.strip()
            txt = re.sub(r'^```json\s*', '', txt)
            txt = re.sub(r'\s*```$', '', txt)
            return json.loads(txt)
        except Exception as e:
            logger.error(f"Gemini API error in summary generation: {str(e)}")

    # Smart local fallback extraction
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
                "explanation": f"Key takeaway: {' '.join(texts[:3]) if len(texts) > 0 else 'See slide content.'}",
                "slides_referenced": f"Slide {num}"
            })
        if notes:
            notes_highlights.append(f"Slide {num} ({t}): {notes}")

    return {
        "title": slides[0]["title"] if slides else "Presentation Study Guide",
        "summary": f"Welcome! Here is your structured study guide for these {len(slides)} slides and speaker notes.",
        "key_concepts": concepts[:8],
        "speaker_note_highlights": notes_highlights[:5],
        "study_tips": [
            "💡 Tip: Pay close attention to speaker notes - key exam insights are frequently placed there!",
            "🧠 Active Recall: Use the Flashcards and Quiz Master tabs to test your recall."
        ]
    }


def generate_flashcards(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> List[Dict[str, str]]:
    """Generates high-yield active recall flashcards with stable card IDs for SM-2 spaced repetition tracking."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])

    cards = []
    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are a master university professor and pedagogical expert crafting high-yield active-recall study flashcards.

Presentation Digest & Speaker Notes:
{digest}

Instructions:
1. Create 10 to 18 specific, high-yield active-recall flashcards based on the text, tables, and speaker notes.
2. DO NOT create vague or generic questions like "What is covered in Slide 1?". Instead, test specific definitions, core formulas, key differences, technical terminology, presenter note insights, and slide tables.
3. On the front, ask a targeted question or present a key concept to define.
4. On the back, provide a thorough, easy-to-understand answer with bullet points, examples, and key takeaways.
5. In category, specify the topic or slide reference (e.g. "Slide 3: Convolutional Nets" or "Speaker Notes Insight").

Return a valid JSON array of objects with schema:
[
  {{
    "front": "Specific concept or targeted question requiring active recall...",
    "back": "Clear, comprehensive answer with key takeaways and explanation...",
    "category": "Topic or slide reference"
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
            txt = response.text.strip()
            txt = re.sub(r'^```json\s*', '', txt)
            txt = re.sub(r'\s*```$', '', txt)
            parsed_cards = json.loads(txt)
            if isinstance(parsed_cards, list) and len(parsed_cards) > 0:
                cards = parsed_cards
        except Exception as e:
            logger.error(f"Gemini API error in flashcard generation: {str(e)}")

    if not cards:
        # Smart local fallback cards
        for s in slides:
            num = s["slide_number"]
            title = s["title"]
            notes = s.get("speaker_notes", "")
            text_content = s.get("text_content", [])

            if text_content:
                main_pts = "\n• ".join(text_content)
                cards.append({
                    "front": f"What are the core technical principles and takeaways of: '{title}'?",
                    "back": f"Key takeaway details:\n• {main_pts}",
                    "category": f"Slide {num}: {title}"
                })

            if notes:
                cards.append({
                    "front": f"What presenter note insight is associated with '{title}'?",
                    "back": f"📌 Presenter Note:\n{notes}",
                    "category": f"Slide {num} Notes"
                })

    # Assign stable card_id and index
    for idx, card in enumerate(cards, start=1):
        card["card_id"] = generate_stable_card_id(card.get("front", ""))
        card["id"] = idx

    return cards


def generate_quiz(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generates domain-specific multiple-choice quiz questions with teacher explanations."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])

    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are a senior exam designer. Create a high-quality 6 to 10 question multiple-choice practice test based on these slides and presenter notes.

Presentation Digest & Notes:
{digest}

Instructions:
1. Questions MUST test actual domain knowledge, core concepts, formulas, presenter notes, and specific slide data.
2. Create 4 realistic, distinct options (A, B, C, D). Avoid obvious throwaway options like "None of the above" or "All of the above".
3. Provide a helpful, encouraging teacher explanation for every question detailing why the correct answer is right and why distractors are incorrect.

Return a valid JSON array of question objects:
[
  {{
    "id": 1,
    "question": "Targeted question stem testing key material...",
    "options": ["Realistic Option A", "Realistic Option B", "Realistic Option C", "Realistic Option D"],
    "answer_index": 0,
    "explanation": "👨‍🏫 Teacher Explanation detailing the rationale and slide/notes citation."
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
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
                "question": f"Regarding Slide {s['slide_number']} ({s['title']}), which statement accurately reflects the core takeaway?",
                "options": [
                    main_pt,
                    f"The main focus of {s['title']} is unrelated to the presentation domain.",
                    "The presenter noted that this topic will be skipped in exams.",
                    "This concept is only relevant for initial setup."
                ],
                "answer_index": 0,
                "explanation": f"👨‍🏫 Teacher Note: Slide {s['slide_number']} highlights: {main_pt}"
            })
    return quiz[:8]


def generate_quizmaster_exam(
    ppt_data: Dict[str, Any],
    difficulty: str = "Medium",
    topic: Optional[str] = None,
    question_count: int = 5,
    api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Generates a customized interactive exam for Quiz Master Hub with specific difficulty, question count, and optional topic focus."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])

    topic_context = f"\nFocus heavily on topic/keyword: '{topic}'" if topic else ""
    difficulty_instructions = {
        "Easy": "Questions should test direct factual recall, definitions, and key slide bullet points.",
        "Medium": "Questions should test conceptual understanding, connections between topics, and presenter note insights.",
        "Hard": "Questions should feature scenario-based application, critical analysis, multi-step reasoning, and edge-case evaluation."
    }
    diff_desc = difficulty_instructions.get(difficulty, difficulty_instructions["Medium"])

    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are an elite university examiner creating a {difficulty} difficulty exam.
Total Questions: {question_count}
Difficulty Guidelines ({difficulty}): {diff_desc}{topic_context}

Presentation Material & Presenter Notes:
{digest}

Instructions:
1. Produce {question_count} deep, realistic multiple-choice exam questions tailored to the specified difficulty ({difficulty}).
2. Provide 4 plausible options without placeholder text.
3. Include comprehensive, detailed solution explanations citing specific slide numbers and presenter notes.

Return a valid JSON array of question objects:
[
  {{
    "id": 1,
    "question": "Challenging, domain-specific question stem...",
    "options": ["Plausible Option A", "Plausible Option B", "Plausible Option C", "Plausible Option D"],
    "answer_index": 0,
    "explanation": "Detailed solution breakdown with slide & speaker note citations.",
    "difficulty": "{difficulty}",
    "topic": "{topic or 'Presentation Material'}"
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
            txt = response.text.strip()
            txt = re.sub(r'^```json\s*', '', txt)
            txt = re.sub(r'\s*```$', '', txt)
            exam_q = json.loads(txt)
            if isinstance(exam_q, list) and len(exam_q) > 0:
                return exam_q[:question_count]
        except Exception as e:
            logger.error(f"Gemini API error in Quiz Master exam generation: {str(e)}")

    # Smart local fallback exam generation
    exam_q = []
    available_slides = [s for s in slides if s.get("text_content")]
    if not available_slides:
        available_slides = slides

    filtered_slides = available_slides
    if topic:
        topic_lower = topic.lower()
        matched = [s for s in available_slides if topic_lower in (s.get("title", "") + s.get("raw_text", "")).lower()]
        if matched:
            filtered_slides = matched

    for idx in range(1, question_count + 1):
        s = filtered_slides[(idx - 1) % len(filtered_slides)] if filtered_slides else {"slide_number": idx, "title": f"Topic {idx}", "text_content": ["Core Concept"], "speaker_notes": ""}
        main_pt = s.get("text_content", ["Key Concept"])[0] if s.get("text_content") else "Core slide objective"
        notes = s.get("speaker_notes", "")
        
        if difficulty == "Hard":
            q_text = f"[Hard Scenario - Slide {s.get('slide_number', idx)}] Applying the concepts from '{s.get('title')}', which solution best addresses a failure case in implementation?"
            exp = f"🔴 Hard Level Analysis: Slide {s.get('slide_number', idx)} highlights: {main_pt}. {f'Presenter note: {notes}' if notes else ''}"
        elif difficulty == "Easy":
            q_text = f"[Easy Recall - Slide {s.get('slide_number', idx)}] According to '{s.get('title')}', what is the primary takeaway stated?"
            exp = f"🟢 Easy Level Recall: Slide {s.get('slide_number', idx)} explicitly mentions: {main_pt}."
        else:
            q_text = f"[Medium Concept - Slide {s.get('slide_number', idx)}] Regarding '{s.get('title')}', which option correctly explains the mechanism?"
            exp = f"🟡 Medium Level Reasoning: Slide {s.get('slide_number', idx)} details: {main_pt}."

        exam_q.append({
            "id": idx,
            "question": q_text,
            "options": [
                main_pt,
                "This concept is explicitly refuted in the speaker notes.",
                "It applies only in legacy systems.",
                "None of the above."
            ],
            "answer_index": 0,
            "explanation": exp,
            "difficulty": difficulty,
            "topic": topic or s.get("title", f"Slide {s.get('slide_number', idx)}")
        })

    return exam_q[:question_count]


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
            response = _generate_content_with_fallback(client, prompt)
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
