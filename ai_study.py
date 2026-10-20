import os
import json
import re
import random
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple

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
CANDIDATE_GEMINI_MODELS = [
    DEFAULT_GEMINI_MODEL,
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

CACHED_WORKING_MODEL: Optional[str] = None

def _is_model_not_found_error(exc: Exception) -> bool:
    """Returns True ONLY for authentic model-not-found / HTTP 404 / NOT_FOUND errors.
    Never returns True for auth, bad API key, quota (429), safety, or invalid argument errors.
    """
    err_str = str(exc)
    err_lower = err_str.lower()

    # Never retry on auth, bad API key, quota (429), safety, or invalid argument errors
    non_retryable_markers = [
        "api key", "api_key", "invalid_argument", "unauthenticated",
        "permission_denied", "resource_exhausted", "quota", "safety",
        "blocked", "billing", "unauthorized", "forbidden"
    ]
    if any(marker in err_lower for marker in non_retryable_markers):
        return False

    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (400, 401, 403, 429) or str(code) in ("400", "401", "403", "429"):
        return False

    if code == 404 or str(code) == "404":
        return True

    if "not_found" in err_lower or "404" in err_lower or "not found" in err_lower:
        return True

    return False


def _generate_content_with_fallback(client, prompt: str):
    """Attempts content generation using candidate Gemini models.
    Only moves to the next model on authentic 404/NOT_FOUND/model-not-found errors.
    Raises immediately on auth, bad API key, quota (429), or safety errors.
    Caches the first working model in CACHED_WORKING_MODEL.
    """
    global CACHED_WORKING_MODEL

    unique_models = []
    if CACHED_WORKING_MODEL:
        unique_models.append(CACHED_WORKING_MODEL)

    for m in CANDIDATE_GEMINI_MODELS:
        if m and m not in unique_models:
            m_lower = m.lower()
            # Exclude retired 1.5-* models and Pro models
            if "pro" not in m_lower and not m_lower.startswith("gemini-1.5"):
                unique_models.append(m)

    last_exc = None
    for mod in unique_models:
        try:
            logger.info(f"Attempting content generation with model: '{mod}'")
            response = client.models.generate_content(
                model=mod,
                contents=prompt
            )
            CACHED_WORKING_MODEL = mod
            return response
        except Exception as e:
            last_exc = e
            if _is_model_not_found_error(e):
                logger.warning(f"Gemini model '{mod}' was not found: {str(e)}. Falling back to next candidate model...")
                if CACHED_WORKING_MODEL == mod:
                    CACHED_WORKING_MODEL = None
                continue
            else:
                logger.error(f"Unrecoverable error with model '{mod}': {str(e)}. Aborting retry.")
                raise e

    if last_exc:
        raise last_exc


def _extract_json(txt: str) -> Any:
    """Extracts and parses JSON from model output even if wrapped in markdown code blocks or conversational text."""
    if not txt:
        return None
    cleaned = txt.strip()
    
    # 1. Direct JSON parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 2. Markdown fenced json block: ```json ... ``` or ``` ... ```
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned, re.IGNORECASE)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass

    # 3. Find outermost JSON Object { ... }
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace:last_brace + 1])
        except Exception:
            pass

    # 4. Find outermost JSON Array [ ... ]
    first_bracket = cleaned.find('[')
    last_bracket = cleaned.rfind(']')
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(cleaned[first_bracket:last_bracket + 1])
        except Exception:
            pass

    return None


def _sample_across_deck(items: List[Any], count: int) -> List[Any]:
    """
    Evenly samples up to `count` items spanning from the very beginning to the very end of `items`.
    Ensures early, middle, and late sections of large presentations (e.g. 147 slides) are represented.
    """
    if not items:
        return []
    n = len(items)
    if n <= count:
        return list(items)
    if count == 1:
        return [items[0]]
    
    step = (n - 1) / (count - 1)
    indices = [round(i * step) for i in range(count)]
    
    seen = set()
    result = []
    for idx in indices:
        if idx not in seen and 0 <= idx < n:
            seen.add(idx)
            result.append(items[idx])
    return result


def _filter_content_slides(slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters out title slides, professor/course metadata, outlines, agendas, and thank-you pages."""
    blacklist_terms = [
        "topics", "agenda", "table of contents", "outline", "syllabus", 
        "course overview", "thank you", "thanks", "q&a", "questions", 
        "references", "bibliography", "index", "contents", "announcements"
    ]
    filtered = []
    for s in slides:
        title = (s.get("title") or "").strip().lower()
        texts = s.get("text_content") or []
        notes = (s.get("speaker_notes") or "").strip()
        joined = " ".join(texts).lower()

        # Filter out obvious outline / agenda / thank-you slides
        if any(term == title or term in title for term in blacklist_terms):
            continue

        # Filter out professor title / instructor bio / course code slides
        if any(term in joined for term in ["professor", "prof.", "dr.", "department of", "faculty of", "scope, vit", "scope", "vit chennai", "course code", "school of"]):
            if len(texts) <= 4:
                continue

        # Skip slides with no content and no notes
        clean_pts = [t for t in texts if len(t.strip()) > 3]
        if not clean_pts and not notes:
            continue

        filtered.append(s)

    return filtered if len(filtered) >= 3 else slides


def generate_stable_card_id(front_text: str) -> str:
    """Generates a stable 16-char SHA256 hash for card question text."""
    clean = front_text.strip().lower()
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()[:16]


def _clean_slide_title(title: str, default: str = "Key Topic") -> str:
    """Cleans raw slide titles, stripping generic 'Slide 50' or 'Page 12' placeholders."""
    if not title:
        return default
    t = title.strip()
    if re.match(r'^(?:slide|page)\s*\d+$', t, re.IGNORECASE):
        return default
    t = re.sub(r'^(?:slide|page)\s*\d+\s*[-:]\s*', '', t, flags=re.IGNORECASE)
    return t.strip() or default


def _format_flashcard_prompt(title: str, slide_num: int, first_bullet: str = "") -> str:
    """Intelligently frames an active-recall question based on slide title and content,
    adapting to queries, problems, definitions, processes, comparisons, or general topics."""
    cleaned = _clean_slide_title(title, default=f"Slide {slide_num}")
    t_lower = cleaned.lower()

    # 1. Check if title is already a direct question
    if cleaned.endswith("?"):
        return cleaned

    # 2. Check if title represents a query, problem, exercise, or task (e.g. "Q13. Display students...", "Problem 4", "Query 2")
    q_match = re.match(r'^(?:q\d*|question\s*\d*|problem\s*\d*|query\s*\d*|task\s*\d*|exercise\s*\d*)\s*[\.:\-]\s*(.+)$', cleaned, re.IGNORECASE)
    if q_match:
        task_desc = q_match.group(1).strip()
        first_word = task_desc.split()[0].lower() if task_desc.split() else ""
        if first_word in ["write", "display", "find", "show", "calculate", "compute", "select", "create", "implement", "explain"]:
            return f"How do you solve / implement: '{task_desc}'? (Slide {slide_num})"
        return f"What is the requirement and solution for: '{task_desc}'? (Slide {slide_num})"

    if any(t_lower.startswith(v) for v in ["write ", "display ", "find ", "show ", "calculate ", "compute ", "select ", "create ", "implement "]):
        return f"How do you accomplish: '{cleaned}'? (Slide {slide_num})"

    # 3. Check for comparisons or trade-offs
    if any(k in t_lower for k in [" vs ", " versus ", " vs. ", "trade-offs", "comparison", "pros and cons", "differences"]):
        return f"Compare and contrast the key aspects of '{cleaned}' (Slide {slide_num})."

    # 4. Check for steps, process, workflow, architecture, lifecycle, algorithm
    if any(k in t_lower for k in ["process", "workflow", "steps", "algorithm", "lifecycle", "pipeline", "procedure", "methodology"]):
        return f"Explain the key steps and workflow of '{cleaned}' (Slide {slide_num})."

    # 5. Check for overview, introduction, definition, principles
    if any(k in t_lower for k in ["overview", "introduction", "basics", "fundamentals", "principles", "concept", "definition"]):
        return f"What are the core principles and definition of '{cleaned}' (Slide {slide_num})?"

    # 6. Default clean, professional active-recall prompt
    return f"What are the key concepts and core takeaways of '{cleaned}' (Slide {slide_num})?"


def generate_study_summary(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    """Generates an intuitive, Claude-style master Study Guide with real-world analogies, mental models, exam traps, and step-by-step breakdowns."""
    digest = ppt_data.get("full_digest", "")
    all_slides = ppt_data.get("slides", [])
    content_slides = _filter_content_slides(all_slides)
    total_slides = ppt_data.get("total_slides", len(all_slides))
    
    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are Claude-level Master Educator and Professor. Your goal is to make studying this entire document ({total_slides} slides) as intuitive, engaging, and effortless as possible.
Break down abstract, mathematical, or technical concepts into crystal-clear everyday analogies, intuitive mental models, and step-by-step walkthroughs.

Presentation Material & Presenter Notes:
{digest}

Task: Synthesize an elite, highly structured Study Guide that demystifies every complex idea across the ENTIRE presentation (early, middle, and late sections) using simple real-world analogies, step-by-step logic, and high-yield exam traps.

Return ONLY a valid JSON object matching this exact schema:
{{
  "title": "Clear Main Topic Title",
  "big_picture": "Why this topic exists, the core problem it solves, and why it matters in plain English",
  "summary": "3-4 sentence comprehensive, encouraging overview of what the student will master across all {total_slides} slides",
  "analogies": [
    {{
      "topic": "Key Concept / Technical Mechanism",
      "analogy": "A brilliant, intuitive real-world mental model (e.g. 'Think of this like a restaurant chef with a ticket wheel because...')",
      "why_it_works": "1-2 sentences explaining why the analogy directly mirrors the technical mechanics"
    }}
  ],
  "key_concepts": [
    {{
      "concept": "Core Concept / Term Name",
      "explanation": "Crystal-clear breakdown avoiding unnecessary jargon",
      "real_world_analogy": "A quick 1-2 sentence everyday analogy",
      "how_it_works_steps": [
        "Step 1: Description of first action/phase",
        "Step 2: Description of next action/phase",
        "Step 3: Outcome or transition"
      ],
      "slides_referenced": "Slide numbers e.g. Slide 5, Slide 42, Slide 118"
    }}
  ],
  "exam_traps": [
    {{
      "trap": "Common confusion or mistake students make on exams",
      "fix": "How to avoid this trap and get full marks"
    }}
  ],
  "memory_hooks": [
    "Catchy mnemonic, acronym, or mental trick to remember key rules effortlessly"
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
            parsed = _extract_json(response.text)
            if isinstance(parsed, dict) and "key_concepts" in parsed:
                return parsed
        except Exception as e:
            logger.warning(f"Gemini API summary error ({str(e)}). Falling back to smart local extraction across full deck.")

    # Smart local fallback extraction: Sample milestone concepts across the entire deck
    start_offset = random.randint(0, max(0, min(5, len(content_slides) - 1)))
    slice_pool = content_slides[start_offset:] + content_slides[:start_offset]
    sampled_slides = _sample_across_deck(slice_pool, min(18, len(content_slides)))
    concepts = []
    notes_highlights = []
    
    # Collect speaker notes across all slides
    for s in all_slides:
        num = s["slide_number"]
        t = _clean_slide_title(s.get("title", f"Slide {num}").strip(), default=f"Slide {num}")
        notes = s.get("speaker_notes", "").strip()
        if notes:
            notes_highlights.append(f"Slide {num} ({t}): {notes}")

    for s in sampled_slides:
        num = s["slide_number"]
        t = _clean_slide_title(s.get("title", f"Slide {num}").strip(), default=f"Slide {num}")
        texts = s.get("text_content", [])

        if texts:
            clean_text = " ".join(texts[:3])
            steps = [f"• {p}" for p in texts[:4]] if texts else [
                f"1. Review concepts outlined in Slide {num}.",
                "2. Understand core definitions, formulas, or syntax.",
                "3. Apply to practical problem scenarios."
            ]
            concepts.append({
                "concept": t,
                "explanation": f"Core takeaway: {clean_text if clean_text else 'Key slide principle.'}",
                "real_world_analogy": f"💡 Key Insight: '{t}' establishes foundational rules and parameters essential for understanding subsequent topics.",
                "how_it_works_steps": steps,
                "slides_referenced": f"Slide {num}"
            })

    # Dynamic analogies derived from slides
    dynamic_analogies = []
    for s in sampled_slides[:4]:
        num = s["slide_number"]
        t = _clean_slide_title(s.get("title", f"Slide {num}").strip(), default=f"Slide {num}")
        dynamic_analogies.append({
            "topic": t,
            "analogy": f"Think of '{t}' as a modular building block in this topic: mastering its rules ensures smooth progress in later problem-solving.",
            "why_it_works": f"Directly applies the principles and requirements defined in Slide {num}."
        })

    # Dynamic exam traps derived from slides and active study principles
    dynamic_traps = []
    for s in sampled_slides[:3]:
        num = s["slide_number"]
        t = _clean_slide_title(s.get("title", f"Slide {num}").strip(), default=f"Slide {num}")
        dynamic_traps.append({
            "trap": f"Overlooking prerequisite conditions, constraints, or syntax details in '{t}'.",
            "fix": f"Carefully review the specific criteria, parameters, and examples presented in Slide {num}."
        })
    dynamic_traps.append({
        "trap": "Relying on passive reading instead of active problem solving and recall.",
        "fix": "Test your understanding using the SM-2 Flashcards tab and the Quiz Master hub to identify retention gaps."
    })

    # Dynamic memory hooks
    memory_hooks = [
        "🧠 The 'Active Retrieval' Rule: Try explaining each slide in your own words before looking at the notes.",
        "🎯 The 'Constraint First' Principle: Always identify boundaries, parameters, and input conditions before solving.",
        "💡 The 'Spaced Review' Method: Use the SM-2 flashcard queue to reinforce difficult concepts over time."
    ]

    # Sample notes highlights evenly across the presentation
    sampled_notes = _sample_across_deck(notes_highlights, 8) if notes_highlights else [
        "Review key diagrams, equations, syntax rules, and presenter annotations emphasized during lecture."
    ]

    # Determine title
    raw_doc_title = all_slides[0].get("title", "") if all_slides else ""
    doc_title = _clean_slide_title(raw_doc_title, default="")
    if not doc_title or len(doc_title) < 4:
        fname = ppt_data.get("filename", "Document")
        doc_title = os.path.splitext(fname)[0].replace("_", " ").title()

    return {
        "title": f"{doc_title} - Master Study Guide",
        "big_picture": f"This master study guide synthesizes all {total_slides} slides of '{doc_title}'—organizing foundational concepts, core methodologies, practical examples, and high-yield review takeaways into structured study notes.",
        "summary": f"Welcome to your study guide for {doc_title}! We have distilled key concepts across all {total_slides} slides into intuitive explanations, step-by-step breakdowns, and exam tips.",
        "analogies": dynamic_analogies,
        "key_concepts": concepts,
        "exam_traps": dynamic_traps,
        "memory_hooks": memory_hooks,
        "speaker_note_highlights": sampled_notes,
        "study_tips": [
            "💡 Practice Active Recall: Test your retention using the SM-2 Flashcards tab after reviewing these concepts.",
            "🎯 University Exam Prep: Practice writing 5-Mark and 10-Mark answers in the Exam Prep hub before viewing model answers.",
            "⏱️ Timed Mock Exam: Head over to Quiz Master Hub to simulate real exam pressure with custom difficulty settings."
        ]
    }


def generate_flashcards(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generates high-yield active recall flashcards covering the entire presentation with stable card IDs for SM-2 spaced repetition tracking."""
    digest = ppt_data.get("full_digest", "")
    all_slides = ppt_data.get("slides", [])
    content_slides = _filter_content_slides(all_slides)
    total_slides = ppt_data.get("total_slides", len(all_slides))

    cards = []
    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are a master university professor and pedagogical expert crafting high-yield active-recall study flashcards across this entire document ({total_slides} slides).

Presentation Digest & Speaker Notes:
{digest}

Instructions:
1. Create 15 to 25 specific, high-yield active-recall flashcards covering all major sections of the presentation from start to finish (early chapters, middle mechanisms, and late conclusion slides).
2. STRICTLY FORBIDDEN: Do NOT create questions about slide metadata, professor names, course numbers, or presentation outlines (e.g. NEVER ask 'Who teaches this course?' or 'What is listed on Slide 1?').
3. On the front, ask a targeted conceptual or problem-solving question requiring active recall.
4. On the back, provide a thorough, easy-to-understand answer with bullet points, examples, and key takeaways.
5. In category, specify the topic and slide reference (e.g. "Slide 12: Core Concepts" or "Slide 17: Query Implementation").

Return a valid JSON array of objects with schema:
[
  {{
    "front": "Specific concept or targeted question requiring active recall...",
    "back": "Clear, comprehensive answer with key takeaways and explanation...",
    "category": "Slide reference & topic"
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
            parsed_cards = _extract_json(response.text)
            if isinstance(parsed_cards, list) and len(parsed_cards) > 0:
                cards = parsed_cards
        except Exception as e:
            logger.warning(f"Gemini API flashcard error ({str(e)}). Falling back to smart local card extraction across full deck.")

    if not cards:
        # Sample dynamic slides across the presentation with random start offset
        start_offset = random.randint(0, max(0, min(6, len(content_slides) - 1)))
        slice_pool = content_slides[start_offset:] + content_slides[:start_offset]
        sampled_slides = _sample_across_deck(slice_pool, min(20, len(content_slides)))
        
        slide_cards = []
        for s in sampled_slides:
            num = s["slide_number"]
            title = s.get("title", f"Slide {num}").strip()
            notes = (s.get("speaker_notes") or "").strip()
            text_content = s.get("text_content", [])

            clean_pts = [t.strip() for t in text_content if len(t.strip()) > 5]

            if clean_pts:
                lead_pt = clean_pts[0]
                other_pts = clean_pts[1:5]
                body_bullets = [f"• {lead_pt}"] + [f"• {p}" for p in other_pts]
                
                # Format clean question based on slide content
                q_front = _format_flashcard_prompt(title, num, lead_pt)
                cleaned_title = _clean_slide_title(title, default=f"Slide {num}")

                slide_cards.append({
                    "front": q_front,
                    "back": "Key Takeaways:\n" + "\n".join(body_bullets),
                    "category": f"Slide {num}: {cleaned_title[:28]}"
                })

            if notes and len(notes) > 15:
                cleaned_title = _clean_slide_title(title, default=f"Slide {num}")
                slide_cards.append({
                    "front": f"What instructor insight / key note is highlighted for '{cleaned_title}' (Slide {num})?",
                    "back": f"📌 Instructor Note / Key Takeaway:\n{notes}",
                    "category": f"Slide {num}: Instructor Notes"
                })

        # If we have distinct bullet points with term: definition format, create targeted cards
        for s in content_slides:
            if len(slide_cards) >= 20:
                break
            num = s["slide_number"]
            for pt in s.get("text_content", []):
                if ":" in pt and len(pt) > 20:
                    term, definition = pt.split(":", 1)
                    term = term.strip(" •-*")
                    definition = definition.strip()
                    if 3 < len(term) < 40 and len(definition) > 10:
                        slide_cards.append({
                            "front": f"In '{_clean_slide_title(s.get('title', ''))}' (Slide {num}), what is the definition / purpose of '{term}'?",
                            "back": f"• {term}: {definition}",
                            "category": f"Slide {num}: {term[:25]}"
                        })

        cards = slide_cards[:20]

    # Assign stable card_id and index
    for idx, card in enumerate(cards, start=1):
        card["card_id"] = generate_stable_card_id(card.get("front", f"card_{idx}"))
        card["id"] = idx

    return cards


def generate_quiz(ppt_data: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    """Generates an authentic University Exam Prep pack featuring 5-Mark Conceptual Short-Answer Questions, 
    10-Mark Comprehensive Case Studies with Marking Schemes & Rubrics, and Scenario MCQs without slide numbers in stems."""
    digest = ppt_data.get("full_digest", "")
    all_slides = ppt_data.get("slides", [])
    content_slides = _filter_content_slides(all_slides)
    total_slides = ppt_data.get("total_slides", len(all_slides))

    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are a master university professor and senior examiner crafting a rigorous university-level exam pack across this material ({total_slides} slides).

Presentation Material:
{digest}

Generate a JSON object with three sections:
1. "five_mark_questions": 5 distinct, university-grade 5-Mark short-answer conceptual questions testing key mechanisms and topics covered in the document.
   Each item must include:
   - "id": integer
   - "topic": concise topic title
   - "marks": 5
   - "question": academic exam question stem (STRICTLY NO SLIDE NUMBERS IN QUESTION)
   - "marking_rubric": array of rubric strings detailing point allocation (e.g. ["[1.0 Mark] Core Definition...", "[2.0 Marks] Operating Mechanics...", "[1.0 Mark] Failure Resilience...", "[1.0 Mark] Practical Application..."])
   - "model_answer": structured, high-scoring model solution with clear bullet points
   - "analogy": intuitive real-world mental model
   - "exam_trap": critical warning on where students commonly lose marks

2. "ten_mark_questions": 2 deep, multi-part 10-Mark Case Study / Systems Design Questions.
   Each item must include:
   - "id": integer
   - "title": case study title
   - "marks": 10
   - "scenario": realistic operational or implementation scenario
   - "parts": [
       {{"part": "A", "marks": 3.5, "question": "...", "model_answer": "..."}},
       {{"part": "B", "marks": 3.5, "question": "...", "model_answer": "..."}},
       {{"part": "C", "marks": 3.0, "question": "...", "model_answer": "..."}}
     ]
   - "model_answer": comprehensive combined model answer
   - "marking_rubric": overall grading criteria
   - "examiner_tips": advice from senior examiner for securing distinction marks

3. "practice_mcqs": 8 to 10 scenario-based multiple-choice practice questions (STRICTLY NO SLIDE NUMBERS IN QUESTION STEMS).
   Each item must include:
   - "id": integer
   - "question": realistic scenario/mechanism question stem
   - "options": 4 plausible options
   - "answer_index": integer 0-3
   - "explanation": detailed teacher solution explanation

Respond ONLY with valid JSON matching the schema.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
            exam_pack = _extract_json(response.text)
            if isinstance(exam_pack, dict) and "five_mark_questions" in exam_pack:
                exam_pack["quiz"] = exam_pack.get("practice_mcqs", [])
                return exam_pack
        except Exception as e:
            logger.warning(f"Gemini API Exam Pack error ({str(e)}). Falling back to smart local university exam synthesizer.")

    # Dynamic university exam generation across the uploaded document
    five_mark_pool = []
    for s in content_slides:
        pts = [p.strip() for p in s.get("text_content", []) if len(p.strip()) > 8]
        if pts:
            snum = s["slide_number"]
            raw_t = s.get("title", f"Slide {snum}")
            clean_t = _clean_slide_title(raw_t, default=f"Slide {snum}")
            notes = s.get("speaker_notes", "").strip()
            
            t_lower = clean_t.lower()
            if re.match(r'^(?:q\d*|question|problem|query|task)', t_lower) or any(t_lower.startswith(v) for v in ["write", "display", "find", "show", "select"]):
                q_prompt = f"Detail the comprehensive approach, syntax, and solution for '{clean_t}'. Explain the underlying methodology, necessary conditions, and expected output."
            else:
                q_prompt = f"Explain '{clean_t}' in detail. Discuss its core principles, operational requirements, and practical significance as presented in the lecture."

            model_ans_parts = [
                f"**1. Core Definition & Purpose:**\n'{clean_t}' addresses key objectives outlined in the course material.",
                "**2. Detailed Breakdown & Components:**\n" + "\n".join(f"• {p}" for p in pts[:5]),
            ]
            if notes:
                model_ans_parts.append(f"**3. Instructor Insight & Key Takeaway:**\n{notes}")
            else:
                model_ans_parts.append("**3. Practical Application & Implications:**\nApplying these concepts correctly ensures valid execution and avoids edge-case failures.")

            five_mark_pool.append({
                "topic": clean_t,
                "marks": 5,
                "question": q_prompt,
                "marking_rubric": [
                    "[1.5 Marks] Accurate definition and statement of primary objective.",
                    "[2.0 Marks] Detailed explanation of key components, methodology, or steps.",
                    "[1.5 Marks] Practical application, constraints, and edge-case considerations."
                ],
                "model_answer": "\n\n".join(model_ans_parts),
                "analogy": f"💡 **Key Concept Hook:** Focus on the input parameters and constraints defined for '{clean_t}' before formulating the final solution.",
                "exam_trap": f"⚠️ **Exam Trap:** Do not omit prerequisite conditions or syntax constraints specified for '{clean_t}'."
            })

    selected_five_mark = _sample_across_deck(five_mark_pool, min(6, len(five_mark_pool))) if five_mark_pool else []

    # Dynamic 10-mark case studies: group pairs of content slides
    ten_mark_pool = []
    step = max(2, len(content_slides) // 4)
    for i in range(0, len(content_slides), step):
        chunk = content_slides[i:i+3]
        if len(chunk) >= 2:
            s1, s2 = chunk[0], chunk[1]
            t1 = _clean_slide_title(s1.get("title", f"Slide {s1['slide_number']}"))
            t2 = _clean_slide_title(s2.get("title", f"Slide {s2['slide_number']}"))
            pts1 = [p.strip() for p in s1.get("text_content", []) if len(p.strip()) > 5]
            pts2 = [p.strip() for p in s2.get("text_content", []) if len(p.strip()) > 5]

            case_title = f"Case Study: Integration of {t1} and {t2}"
            scenario = (
                f"An organization is designing a system that incorporates the principles of '{t1}' "
                f"alongside '{t2}'. During deployment, the team must satisfy operational requirements, "
                f"handle edge cases, and ensure robustness."
            )

            parts = [
                {
                    "part": "A",
                    "marks": 3.5,
                    "question": f"Analyze the core principles and foundational requirements of '{t1}'.",
                    "model_answer": f"**Foundational Analysis:**\n" + "\n".join(f"• {p}" for p in (pts1[:3] or ["Key requirement defined in " + t1]))
                },
                {
                    "part": "B",
                    "marks": 3.5,
                    "question": f"Explain the implementation workflow and methodology for '{t2}'.",
                    "model_answer": f"**Implementation Workflow:**\n" + "\n".join(f"• {p}" for p in (pts2[:3] or ["Operational step defined in " + t2]))
                },
                {
                    "part": "C",
                    "marks": 3.0,
                    "question": f"Evaluate potential failure modes or trade-offs when integrating '{t1}' with '{t2}', and recommend operational best practices.",
                    "model_answer": f"**Synthesis & Trade-off Evaluation:**\nIntegrating both components requires validating preconditions early, maintaining consistent state, and monitoring for edge-case boundary errors."
                }
            ]

            ten_mark_pool.append({
                "title": case_title,
                "marks": 10,
                "scenario": scenario,
                "parts": parts,
                "model_answer": f"Integrated model answer covering foundational principles of {t1}, operational workflow of {t2}, and system resilience.",
                "marking_rubric": "Part A (3.5 Marks): Core principles; Part B (3.5 Marks): Implementation details; Part C (3.0 Marks): Robustness & failure modes.",
                "examiner_tips": "💡 Relate theoretical slide concepts directly to practical constraints and problem scenarios."
            })

    selected_ten_mark = ten_mark_pool[:3] if ten_mark_pool else []

    # Dynamic practice MCQs: generate 8 using generate_quizmaster_exam logic
    practice_mcqs = generate_quizmaster_exam(ppt_data, difficulty="Medium", question_count=8, api_key=None)

    return {
        "title": f"University Exam Preparation Master Pack",
        "five_mark_questions": selected_five_mark,
        "ten_mark_case_studies": selected_ten_mark,
        "practice_mcqs": practice_mcqs,
        "quiz": practice_mcqs
    }


def generate_quizmaster_exam(
    ppt_data: Dict[str, Any],
    difficulty: str = "Medium",
    topic: Optional[str] = None,
    question_count: int = 5,
    api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Generates a customized interactive exam for Quiz Master Hub with specific difficulty, question count, and optional topic focus, sampling across the full presentation."""
    digest = ppt_data.get("full_digest", "")
    all_slides = ppt_data.get("slides", [])
    content_slides = _filter_content_slides(all_slides)
    total_slides = ppt_data.get("total_slides", len(all_slides))

    topic_context = f"\nFocus heavily on topic/keyword: '{topic}'" if topic else ""
    difficulty_instructions = {
        "Easy": "Questions should test direct conceptual definitions, key properties, and core takeaways.",
        "Medium": "Questions should test technical mechanics, interactions between components, and key trade-offs.",
        "Hard": "Questions should feature scenario-based analysis, edge-case failures, and multi-step problem solving."
    }
    diff_desc = difficulty_instructions.get(difficulty, difficulty_instructions["Medium"])

    client = _get_genai_client(api_key)
    if client:
        prompt = f"""You are an elite university examiner creating a {difficulty} difficulty exam across this entire document ({total_slides} slides).
Total Questions: {question_count}
Difficulty Guidelines ({difficulty}): {diff_desc}{topic_context}

Presentation Material & Presenter Notes:
{digest}

Instructions:
1. Produce {question_count} deep, realistic multiple-choice exam questions distributed across the presentation material.
2. STRICTLY FORBIDDEN: Do NOT create questions referencing slide numbers (e.g. NEVER write 'Regarding Slide 50', 'According to Slide 12', etc.). Make all question stems test authentic domain concepts directly.
3. Provide 4 plausible options without placeholder text.
4. Include comprehensive, detailed solution explanations.

Return a valid JSON array of question objects:
[
  {{
    "id": 1,
    "question": "Challenging, domain-specific question stem...",
    "options": ["Plausible Option A", "Plausible Option B", "Plausible Option C", "Plausible Option D"],
    "answer_index": 0,
    "explanation": "Detailed solution breakdown with mechanism explanations.",
    "difficulty": "{difficulty}",
    "topic": "{topic or 'Core Concepts'}"
  }}
]
Respond ONLY with the JSON array.
"""
        try:
            response = _generate_content_with_fallback(client, prompt)
            exam_q = _extract_json(response.text)
            if isinstance(exam_q, list) and len(exam_q) > 0:
                for q in exam_q:
                    opts = q.get("options", [])
                    corr_idx = q.get("answer_index", 0)
                    if opts and 0 <= corr_idx < len(opts):
                        corr_opt = opts[corr_idx]
                        random.shuffle(opts)
                        q["answer_index"] = opts.index(corr_opt)
                return exam_q[:question_count]
        except Exception as e:
            logger.warning(f"Gemini API Quiz Master error ({str(e)}). Falling back to smart local exam generation across full deck.")

    # Smart local fallback exam generation: Filter pool and sample evenly across the deck
    filtered_slides = content_slides
    if topic:
        topic_lower = topic.lower()
        matched = [s for s in content_slides if topic_lower in (s.get("title", "") + s.get("raw_text", "")).lower()]
        if matched:
            filtered_slides = matched

    pool = []
    for s in filtered_slides:
        pts = [p.strip() for p in s.get("text_content", []) if len(p.strip()) > 8]
        if pts:
            pool.append((s.get("title", f"Slide {s['slide_number']}"), pts, s.get("speaker_notes", ""), s["slide_number"]))

    sampled_pool = _sample_across_deck(pool, question_count)
    exam_q = []
    for idx, (raw_title, pts, notes, snum) in enumerate(sampled_pool, start=1):
        main_pt = pts[0]
        clean_title = _clean_slide_title(raw_title, default=f"Slide {snum}")
        
        # Sourced distractors from other slides in the pool
        other_pts = [p[0] for (t, p, n, sn) in pool if t != raw_title and p and p[0] != main_pt]
        distractors = []
        if len(other_pts) >= 3:
            distractors = random.sample(other_pts, 3)
        else:
            distractors = other_pts + [
                "It operates without any defined parameters, constraints, or preconditions.",
                "It is strictly excluded from the scope and syllabus of this topic.",
                "It was deprecated and has no practical application in modern implementations."
            ][:3 - len(other_pts)]

        # Check if title indicates a query, task, or question
        t_lower = clean_title.lower()
        if re.match(r'^(?:q\d*|question|problem|query|task|exercise)', t_lower) or any(t_lower.startswith(v) for v in ["write", "display", "find", "show", "select"]):
            q_text = f"Regarding '{clean_title}', which of the following is correct?"
        elif difficulty == "Hard":
            q_text = f"In an in-depth analysis of '{clean_title}', which statement accurately evaluates its core mechanism or requirement?"
        elif difficulty == "Easy":
            q_text = f"What is a primary principle or key point associated with '{clean_title}'?"
        else:
            q_text = f"Which of the following correctly describes '{clean_title}' as presented in the material?"

        options = [main_pt] + distractors[:3]
        random.shuffle(options)
        corr_idx = options.index(main_pt)
        exp = f"Detailed Solution: '{clean_title}' specifies that: {main_pt}." + (f" (Presenter note: {notes})" if notes else "")

        exam_q.append({
            "id": idx,
            "question": q_text,
            "options": options,
            "answer_index": corr_idx,
            "explanation": exp,
            "difficulty": difficulty,
            "topic": clean_title[:40]
        })

    return exam_q[:question_count]


def answer_study_chat(
    ppt_data: Dict[str, Any],
    chat_history: List[Dict[str, str]],
    user_message: str,
    teacher_mode: str = "tutor",
    api_key: Optional[str] = None,
    session_memory: Optional[Dict[str, str]] = None
) -> Tuple[str, Dict[str, str]]:
    """Answers student questions adopting a Claude / GPT-4o pedagogical tutor persona with active session memory tracking."""
    digest = ppt_data.get("full_digest", "")
    slides = ppt_data.get("slides", [])
    total_s = ppt_data.get("total_slides", len(slides))
    fname = ppt_data.get("filename", "Presentation")
    
    session_mem = session_memory or {}
    new_memory = {}

    client = _get_genai_client(api_key)

    mode_personas = {
        "tutor": "You are Claude / ChatGPT acting as an exceptional, warm, intellectually rigorous professor and private tutor. Break complex ideas down with crystal clarity, everyday analogies, and clear logical progressions.",
        "eli5": "You are a warm, imaginative teacher explaining complex technical concepts to a curious beginner. Use vivid, delightful real-world metaphors and simple, jargon-free explanations.",
        "quiz_me": "You are an engaging Socratic examiner. Present a realistic scenario-based challenge question to test the student's conceptual intuition, then guide them to the answer.",
        "notes_deepdive": "You are an expert focusing on the presenter's hidden speaker notes and annotations. Unpack the unspoken test hints, architectural rationale, and edge cases the instructor highlighted."
    }

    selected_persona = mode_personas.get(teacher_mode, mode_personas["tutor"])

    if client:
        system_instruction = f"""{selected_persona}

Presentation Context ({total_s} Slides & Presenter Notes):
{digest}

Session Memory (Concepts & Topics Explored So Far in this Session):
{json.dumps(session_mem, indent=2)}

Voice & Tone Guidelines:
1. **Natural & Conversational:** Speak with clarity, warmth, and intellectual engagement. Avoid robotic formulas.
2. **Intuitive Mental Models:** Ground abstract or mathematical mechanisms in memorable real-world analogies before diving into technical details.
3. **Active Memory Continuity:** Seamlessly connect ideas to what the student discussed earlier in this session when relevant.
4. **Rich Formatting:** Use structured headings (`###`), bold keywords, blockquotes (`>`), and clean step-by-step logic.
5. **Thought-Partner Check:** End with a natural, intellectually stimulating question that invites the student to test or deepen their intuition.
"""
        formatted_history = ""
        for msg in chat_history[-6:]:
            role = "Student" if msg.get("role") == "user" else "Assistant"
            formatted_history += f"{role}: {msg.get('content')}\n"

        prompt = f"{system_instruction}\n\nRecent Conversation:\n{formatted_history}\nStudent: {user_message}\nAssistant:"

        try:
            response = _generate_content_with_fallback(client, prompt)
            reply_text = response.text.strip()
            new_memory["last_query"] = user_message[:50]
            return reply_text, new_memory
        except Exception as e:
            logger.warning(f"Gemini API chat error ({str(e)}). Falling back to smart Claude-style tutor engine.")

    # Smart local semantic search and tutor engine
    user_lower = user_message.lower().strip()

    STOP_WORDS = {
        "what", "was", "is", "are", "were", "this", "that", "these", "those", "there", 
        "their", "they", "some", "like", "along", "line", "lines", "called", "caleed", 
        "calld", "about", "with", "from", "have", "has", "had", "been", "where", "which", 
        "could", "would", "should", "tell", "explain", "help", "know", "mean", "something", 
        "method", "sharing", "thing", "things", "does", "done", "doing", "teach", "give", 
        "more", "also", "into", "very", "much", "wasnt", "wasn't", "isnt", "isn't", 
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "it", "its"
    }

    prev_topic = session_mem.get("last_topic", "")
    memory_bridge = f"*(Connecting this to our discussion on **{prev_topic}**...)*\n\n" if prev_topic and prev_topic not in user_lower else ""

    # Handler for Speaker Notes
    if any(k in user_lower for k in ["speaker notes", "presenter notes", "instructor annotations", "speaker note", "presenter note", "annotations", "notes"]):
        slides_with_notes = [s for s in slides if (s.get("speaker_notes") or "").strip()]
        res = f"### 📌 Presenter Notes & Instructor Clues Synthesis\n\n"
        if slides_with_notes:
            res += f"Here are the specific presenter insights and test clues extracted from your slides:\n\n"
            for s in slides_with_notes[:10]:
                s_num = s["slide_number"]
                t = _clean_slide_title(s.get("title", f"Slide {s_num}"))
                res += f"• **Slide {s_num} ({t}):**\n  > \"{s['speaker_notes'].strip()}\"\n\n"
            res += "Would you like to deep-dive into any specific presenter annotation?"
        else:
            res += "No hidden presenter speaker notes were found in the uploaded slides. All core content is contained directly on the slide pages!"
        new_memory["last_topic"] = "Speaker Notes Synthesis"
        return res, new_memory

    # Handler for Summary / Table of Contents / Overview
    if any(k in user_lower for k in ["summarize", "summary", "overview", "table of contents", "outline", "what is this presentation about"]):
        res = f"### 📚 Overview of {fname}\n\n"
        res += f"This document contains **{total_s} slides/pages**. Here is a high-level roadmap of the key topics covered:\n\n"
        content_slides = _filter_content_slides(slides)
        sampled = _sample_across_deck(content_slides, min(12, len(content_slides)))
        for s in sampled:
            s_num = s["slide_number"]
            t = _clean_slide_title(s.get("title", f"Slide {s_num}"))
            lead_pt = s.get("text_content", [""])[0] if s.get("text_content") else ""
            res += f"• **Slide {s_num} - {t}**" + (f": {lead_pt[:75]}..." if len(lead_pt) > 5 else "") + "\n"
        res += "\nFeel free to ask me to explain any of these slides or concepts in detail!"
        new_memory["last_topic"] = "Document Overview"
        return res, new_memory

    # Search for specific slide number match (e.g. "slide 17", "page 5")
    slide_num_match = re.search(r'\b(?:slide|page)\s*(\d+)\b', user_lower)
    target_slide = None
    if slide_num_match:
        target_num = int(slide_num_match.group(1))
        target_slide = next((s for s in slides if s.get("slide_number") == target_num), None)

    # Search by keyword matching across slides
    if not target_slide:
        tokens = [w for w in re.findall(r'[a-z0-9_]+', user_lower) if w not in STOP_WORDS and len(w) > 2]
        best_score = 0
        best_slide = None
        for s in slides:
            title_text = s.get("title", "").lower()
            body_text = " ".join(s.get("text_content", [])).lower()
            notes_text = s.get("speaker_notes", "").lower()
            score = 0
            for tok in tokens:
                if tok in title_text:
                    score += 5
                if tok in body_text:
                    score += 2
                if tok in notes_text:
                    score += 3
            if score > best_score:
                best_score = score
                best_slide = s
        if best_score >= 3:
            target_slide = best_slide

    if target_slide:
        s_num = target_slide["slide_number"]
        t = _clean_slide_title(target_slide.get("title", f"Slide {s_num}"))
        texts = target_slide.get("text_content", [])
        notes = (target_slide.get("speaker_notes") or "").strip()

        if teacher_mode == "eli5":
            res = f"{memory_bridge}### 🌟 Explaining **{t}** (Slide {s_num}) in Plain English\n\n"
            if texts:
                res += f"Here is the simple intuition behind this:\n\n> {texts[0]}\n\n"
                if len(texts) > 1:
                    res += "Key details to remember:\n"
                    for pt in texts[1:]:
                        res += f"• **{pt}**\n"
                    res += "\n"
            if notes:
                res += f"📌 **Presenter Note:** {notes}\n\n"
            res += "Does this simple explanation make sense, or would you like another example?"

        elif teacher_mode == "quiz_me":
            res = f"{memory_bridge}### 🎯 Quick Recall Challenge: **{t}** (Slide {s_num})\n\n"
            if texts:
                res += f"Based on the lecture material, what is the core requirement or solution for:\n\n**'{t}'**?\n\n"
                res += f"*(Hint: Think about: '{texts[0][:80]}...')*\n\n"
            else:
                res += f"What is the key takeaway of **{t}**?\n\n"
            res += "Give it a shot, and I'll review your answer!"

        elif teacher_mode == "notes_deepdive":
            res = f"{memory_bridge}### 🔍 Deep Dive: **{t}** (Slide {s_num})\n\n"
            if notes:
                res += f"**Instructor Annotation:**\n> \"{notes}\"\n\n"
            else:
                res += "*(Note: No explicit speaker notes recorded for this slide, analyzing slide body:)*\n\n"
            if texts:
                res += "### 📋 Slide Content & Points:\n"
                for pt in texts:
                    res += f"• {pt}\n"
                res += "\n"
            res += "Would you like to examine how this connects to the next slide?"

        else: # Default tutor
            res = f"{memory_bridge}### 📖 Slide {s_num}: **{t}**\n\n"
            if texts:
                res += f"**Core Concept:**\n{texts[0]}\n\n"
                if len(texts) > 1:
                    res += "**Key Points & Requirements:**\n"
                    for pt in texts[1:]:
                        res += f"• {pt}\n"
                    res += "\n"
            if notes:
                res += f"### 📌 Speaker Note Insight\n> \"{notes}\"\n\n"
            res += "Would you like me to clarify any part of this, or relate it to another slide?"

        new_memory["last_topic"] = f"Slide {s_num}: {t}"
        new_memory[f"slide_{s_num}"] = t
        return res, new_memory

    # Friendly fallback when no specific slide matches query
    content_slides = _filter_content_slides(slides)
    sampled = _sample_across_deck(content_slides, min(6, len(content_slides)))
    topic_list = "\n".join(f"• **Slide {s['slide_number']}:** {_clean_slide_title(s.get('title', ''))}" for s in sampled)

    res = (
        f"I've indexed all {total_s} slides and instructor notes in **{fname}**.\n\n"
        f"Here are some of the key topics you can ask me about:\n{topic_list}\n\n"
        f"You can ask me to:\n"
        f"• **Explain any concept:** e.g. *'What is {_clean_slide_title(sampled[0].get('title', '')) if sampled else 'this topic'}?'*\n"
        f"• **Teach a specific slide:** e.g. *'Teach me slide {sampled[0]['slide_number'] if sampled else 1}'*\n"
        f"• **Review speaker notes:** type *'show speaker notes'*\n"
        f"• **Summarize the document:** type *'summarize'*\n\n"
        f"What would you like to explore?"
    )
    return res, new_memory
