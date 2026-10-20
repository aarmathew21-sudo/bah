import os
import uuid
import time
import logging
import json
import re
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Response, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response as RawResponse, JSONResponse

import io
import zipfile
from pydantic import BaseModel, Field, model_validator

from ppt_parser import extract_ppt_content, validate_upload_file, validate_zip_archive_security
from pdf_parser import extract_pdf_content
from legacy_ppt_parser import extract_legacy_ppt_content
from ai_study import (
    generate_study_summary,
    generate_flashcards,
    generate_quiz,
    answer_study_chat,
    generate_quizmaster_exam,
    _get_genai_client,
    validate_and_sanitize_api_key,
    verify_gemini_api_key,
    generate_follow_up_chips,
    evaluate_feynman_explanation
)
from database import (
    init_db,
    async_save_session_presentation,
    async_get_session_presentation,
    async_save_study_cache,
    async_get_study_cache,
    async_record_card_review,
    async_get_due_flashcards,
    async_save_quiz_result,
    async_get_quiz_history,
    async_save_session_memory,
    async_get_all_session_memory,
    async_clear_session_memory,
    async_get_progress,
    async_record_progress_event,
    async_get_mastery
)
from create_sample_ppt import create_sample_presentation

logger = logging.getLogger("ppt_main_app")

app = FastAPI(
    title="PPT & PDF Text & Notes AI Study Assistant",
    description="Multi-user FastAPI application for PowerPoint (.pptx / .ppt) & PDF (.pdf) parsing, ChatGPT AI Tutoring, and SM-2 Spaced Repetition."
)

# Configure trusted origins for CORS
raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RATE_LIMIT_STORE: Dict[str, List[float]] = {}

def get_session_id(request: Request, response: Response, ppt_session_id: Optional[str] = Cookie(None)) -> str:
    if not ppt_session_id:
        ppt_session_id = str(uuid.uuid4())
        response.set_cookie(
            key="ppt_session_id",
            value=ppt_session_id,
            httponly=True,
            samesite="lax",
            max_age=86400 * 30
        )
    return ppt_session_id

def rate_limit_study_api(session_id: str = Depends(get_session_id)):
    """Rate limiter middleware ensuring max 30 AI study requests per minute per session."""
    now = time.time()
    history = RATE_LIMIT_STORE.get(session_id, [])
    valid_history = [t for t in history if now - t < 60]
    
    if len(valid_history) >= 30:
        logger.warning(f"Rate limit exceeded for session {session_id[:8]}")
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait a minute before making more AI study requests."
        )
    
    valid_history.append(now)
    RATE_LIMIT_STORE[session_id] = valid_history


@app.on_event("startup")
def startup_event():
    init_db()
    logger.info(f"Database initialized with SM-2 spaced repetition support. Trusted CORS origins: {allowed_origins}")


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4000, description="Student chat message or query")
    teacher_mode: Optional[str] = Field("tutor", description="Teacher mode: tutor, eli5, quiz_me, notes_deepdive")
    chat_history: Optional[List[Dict[str, str]]] = Field(default_factory=list, max_length=100, description="Recent conversation history")
    api_key: Optional[str] = Field(None, description="Optional Gemini API key")

    @model_validator(mode='after')
    def validate_chat_request(self):
        if not self.message or len(self.message.strip()) == 0:
            raise ValueError("Message cannot be empty.")
        if len(self.message) > 4000:
            raise ValueError("Message cannot exceed 4,000 characters.")
        if self.chat_history:
            if len(self.chat_history) > 100:
                raise ValueError("chat_history length cannot exceed 100 entries.")
            for idx, entry in enumerate(self.chat_history):
                if not isinstance(entry, dict):
                    raise ValueError(f"chat_history entry {idx} must be a dictionary.")
                total_entry_len = sum(len(str(v)) for v in entry.values())
                if total_entry_len > 4000:
                    raise ValueError(f"chat_history entry {idx} size exceeds 4,000 characters.")
        return self

class StudyRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="Optional Gemini API key")
    force_refresh: Optional[bool] = Field(False, description="Whether to bypass cache and regenerate new content")

class ReviewRequest(BaseModel):
    card_id: str = Field(..., description="Stable card ID hash")
    rating: str = Field(..., description="Rating: again, hard, good, easy")

class QuizMasterGenerateRequest(BaseModel):
    difficulty: Optional[str] = Field("Medium", description="Exam difficulty: Easy, Medium, Hard")
    topic: Optional[str] = Field(None, description="Custom focus topic")
    question_count: Optional[int] = Field(5, description="Number of exam questions (3-20)")
    api_key: Optional[str] = Field(None, description="Optional Gemini API key")

class QuizMasterSubmitRequest(BaseModel):
    exam_title: str = Field(..., max_length=255, description="Title or description of the exam")
    score: int = Field(..., ge=0, description="Number of correct answers")
    total_questions: int = Field(..., ge=1, le=20, description="Total questions in exam")
    time_spent_seconds: int = Field(..., ge=0, description="Time taken in seconds")
    details: List[Dict[str, Any]] = Field(default_factory=list, max_length=50, description="Per-question review details")

    @model_validator(mode='after')
    def validate_exam_submission(self):
        if not (0 <= self.score <= self.total_questions):
            raise ValueError(f"Score ({self.score}) must be between 0 and total_questions ({self.total_questions}).")
        if not (1 <= self.total_questions <= 20):
            raise ValueError(f"total_questions ({self.total_questions}) must be between 1 and 20.")
        if self.time_spent_seconds < 0:
            raise ValueError("time_spent_seconds must be non-negative.")
        if len(self.details) > 50:
            raise ValueError("details cannot exceed 50 items.")
        if not self.exam_title or len(self.exam_title.strip()) == 0 or len(self.exam_title) > 255:
            raise ValueError("exam_title must be between 1 and 255 characters.")
        return self



def combine_parsed_documents(parsed_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Combines multiple parsed presentations or PDFs into a unified study structure."""
    all_slides = []
    digest_blocks = []
    documents_summary = []
    filenames = []
    all_warnings = []
    global_idx = 1
    
    for doc_idx, doc in enumerate(parsed_docs, start=1):
        doc_fname = doc.get("filename", f"document_{doc_idx}")
        filenames.append(doc_fname)
        doc_slides = doc.get("slides", [])
        
        documents_summary.append({
            "doc_index": doc_idx,
            "filename": doc_fname,
            "total_slides": len(doc_slides)
        })
        
        doc_digest_lines = [
            "=" * 80,
            f"DOCUMENT {doc_idx} OF {len(parsed_docs)}: {doc_fname} ({len(doc_slides)} Slides/Pages)",
            "=" * 80
        ]
        
        for s in doc_slides:
            slide_copy = dict(s)
            orig_num = slide_copy.get("doc_slide_number") or slide_copy.get("slide_number", 1)
            slide_copy["global_slide_number"] = global_idx
            slide_copy["slide_number"] = global_idx
            slide_copy["doc_name"] = doc_fname
            slide_copy["doc_slide_number"] = orig_num
            
            if slide_copy.get("has_warning"):
                all_warnings.append({
                    "slide_number": global_idx,
                    "doc_name": doc_fname,
                    "message": slide_copy.get("warning_message", f"Slide {global_idx} could not be read.")
                })

            all_slides.append(slide_copy)
            doc_digest_lines.append(slide_copy.get("raw_text", ""))
            global_idx += 1
            
        digest_blocks.append("\n\n".join(doc_digest_lines))

    # Also capture document-level warnings
    for doc in parsed_docs:
        for w in doc.get("warnings", []):
            if not any(aw.get("slide_number") == w.get("slide_number") for aw in all_warnings):
                all_warnings.append(w)
        
    full_digest = "\n\n" + ("\n\n".join(digest_blocks))
    
    if len(filenames) == 1:
        primary_filename = filenames[0]
    elif len(filenames) == 2:
        primary_filename = f"{filenames[0]} & {filenames[1]}"
    else:
        primary_filename = f"{filenames[0]} + {len(filenames)-1} other docs"
        
    return {
        "filename": primary_filename,
        "filenames": filenames,
        "total_documents": len(filenames),
        "total_slides": len(all_slides),
        "documents": documents_summary,
        "slides": all_slides,
        "full_digest": full_digest,
        "warnings": all_warnings
    }


@app.post("/api/upload")
async def upload_document(
    request: Request,
    response: Response,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    mode: Optional[str] = "replace",
    session_id: str = Depends(get_session_id)
):
    """Uploads single or multiple PowerPoint (.pptx / .ppt), PDF (.pdf), or ZIP (.zip) files per session."""
    upload_list: List[UploadFile] = []
    if files:
        upload_list.extend(files)
    if file and file not in upload_list:
        upload_list.append(file)
        
    if not upload_list:
        raise HTTPException(status_code=400, detail="No files uploaded. Please choose PowerPoint (.pptx / .ppt), PDF (.pdf), or ZIP (.zip) files.")

    try:
        new_parsed_docs = []
        for f in upload_list:
            if not f.filename or not f.filename.lower().endswith((".pptx", ".ppt", ".pdf", ".zip")):
                raise HTTPException(status_code=400, detail=f"File '{f.filename}' is unsupported. Only .pptx, .ppt, .pdf, and .zip are supported.")

            content = await f.read()
            if len(content) > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"File '{f.filename}' too large. Maximum allowed size is 50 MB per file.")

            file_type = validate_upload_file(content, filename=f.filename, max_size_mb=50)

            if file_type == "pdf":
                pdata = extract_pdf_content(content)
                pdata["filename"] = f.filename
                new_parsed_docs.append(pdata)
            elif file_type == "ppt_legacy":
                pdata = extract_legacy_ppt_content(content)
                pdata["filename"] = f.filename
                new_parsed_docs.append(pdata)
            elif file_type == "zip":
                try:
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        validate_zip_archive_security(zf)
                        namelist = zf.namelist()
                        if "[Content_Types].xml" in namelist and any(name.startswith("ppt/") for name in namelist):
                            pdata = extract_ppt_content(content)
                            pdata["filename"] = f.filename
                            new_parsed_docs.append(pdata)
                        else:
                            inner_files = [n for n in namelist if n.lower().endswith((".pptx", ".ppt", ".pdf")) and not n.startswith("__MACOSX") and not os.path.basename(n).startswith(".")]
                            if not inner_files:
                                raise HTTPException(status_code=400, detail="ZIP archive does not contain any valid .pptx, .ppt, or .pdf files.")
                            for inner_name in inner_files:
                                inner_bytes = zf.read(inner_name)
                                inner_type = validate_upload_file(inner_bytes, filename=inner_name, max_size_mb=50)
                                if inner_type == "pdf":
                                    ipdata = extract_pdf_content(inner_bytes)
                                elif inner_type == "ppt_legacy":
                                    ipdata = extract_legacy_ppt_content(inner_bytes)
                                else:
                                    ipdata = extract_ppt_content(inner_bytes)
                                ipdata["filename"] = os.path.basename(inner_name)
                                new_parsed_docs.append(ipdata)
                except zipfile.BadZipFile:
                    raise HTTPException(status_code=400, detail="Corrupt file. Unable to read ZIP structure.")
            else:
                pdata = extract_ppt_content(content)
                pdata["filename"] = f.filename
                new_parsed_docs.append(pdata)

        existing_docs = []
        if mode == "append":
            existing_session = await async_get_session_presentation(session_id)
            if existing_session:
                existing_filenames = existing_session.get("filenames", [existing_session.get("filename", "existing_doc")])
                for efname in existing_filenames:
                    doc_slides = [s for s in existing_session.get("slides", []) if s.get("doc_name") == efname]
                    if not doc_slides:
                        doc_slides = existing_session.get("slides", [])
                    existing_docs.append({
                        "filename": efname,
                        "slides": doc_slides,
                        "total_slides": len(doc_slides)
                    })

        all_docs = existing_docs + new_parsed_docs
        combined_data = combine_parsed_documents(all_docs)

        await async_save_session_presentation(session_id, combined_data)
        logger.info(f"Successfully processed {len(all_docs)} document(s) ({combined_data['total_slides']} slides/pages) for session {session_id[:8]}...")

        return {
            "success": True,
            "filename": combined_data["filename"],
            "filenames": combined_data["filenames"],
            "total_documents": combined_data["total_documents"],
            "total_slides": combined_data["total_slides"],
            "documents": combined_data["documents"],
            "slides": combined_data["slides"],
            "warnings": combined_data.get("warnings", [])
        }
    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning(f"Upload validation failed: {str(ve)}")
        msg = str(ve).lower()
        if "exceeds" in msg or "too large" in msg or "limit of 50 mb" in msg or "limit of 200 mb" in msg or "limit" in msg:
            raise HTTPException(status_code=413, detail=str(ve))
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error processing document upload: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to parse document: {str(e)}")


@app.post("/api/sample")
async def load_sample_ppt(
    request: Request,
    response: Response,
    session_id: str = Depends(get_session_id)
):
    """Loads a pre-generated sample presentation for demo testing."""
    sample_filename = "sample_study_presentation.pptx"
    if not os.path.exists(sample_filename):
        create_sample_presentation(sample_filename)

    with open(sample_filename, "rb") as f:
        content = f.read()

    parsed_data = extract_ppt_content(content)
    parsed_data["filename"] = "Sample_Machine_Learning_Notes.pptx"
    combined_data = combine_parsed_documents([parsed_data])
    await async_save_session_presentation(session_id, combined_data)

    return {
        "success": True,
        "filename": combined_data["filename"],
        "filenames": combined_data["filenames"],
        "total_documents": 1,
        "total_slides": combined_data["total_slides"],
        "documents": combined_data["documents"],
        "slides": combined_data["slides"]
    }


@app.get("/api/current")
async def get_current_presentation(
    request: Request,
    response: Response,
    session_id: str = Depends(get_session_id)
):
    """Returns currently loaded presentation data for the user's session."""
    data = await async_get_session_presentation(session_id)
    if not data:
        return {"loaded": False}
    return {
        "loaded": True,
        "filename": data.get("filename"),
        "filenames": data.get("filenames", [data.get("filename")]),
        "documents": data.get("documents", []),
        "total_documents": len(data.get("filenames", [data.get("filename")])),
        "total_slides": data.get("total_slides"),
        "slides": data.get("slides")
    }


@app.post("/api/study/summary", dependencies=[Depends(rate_limit_study_api)])
async def get_study_summary(
    req: Optional[StudyRequest] = None,
    session_id: str = Depends(get_session_id)
):
    """Generates or retrieves study guide summary for the session."""
    req = req or StudyRequest()
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")
    
    if not req.force_refresh and not req.api_key:
        cached = await async_get_study_cache(session_id, "summary")
        if cached:
            return cached

    summary = generate_study_summary(ppt_data, api_key=req.api_key)
    await async_save_study_cache(session_id, "summary", summary)
    return summary


@app.post("/api/study/flashcards", dependencies=[Depends(rate_limit_study_api)])
async def get_flashcards(
    req: Optional[StudyRequest] = None,
    session_id: str = Depends(get_session_id)
):
    """Generates or retrieves study flashcards for the session."""
    req = req or StudyRequest()
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")
    
    if not req.force_refresh and not req.api_key:
        cached = await async_get_study_cache(session_id, "flashcards")
        if cached:
            return {"flashcards": cached}

    cards = generate_flashcards(ppt_data, api_key=req.api_key)
    await async_save_study_cache(session_id, "flashcards", cards)
    return {"flashcards": cards}


@app.get("/api/study/flashcards/due")
async def get_due_cards(
    request: Request,
    response: Response,
    api_key: Optional[str] = None,
    session_id: str = Depends(get_session_id)
):
    """Returns flashcards due for SM-2 review for this session."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")
    
    cached = await async_get_study_cache(session_id, "flashcards")
    if not cached:
        cards = generate_flashcards(ppt_data, api_key=api_key)
        await async_save_study_cache(session_id, "flashcards", cards)

    due_data = await async_get_due_flashcards(session_id)
    return due_data


@app.post("/api/study/flashcards/review")
async def review_card(
    req: ReviewRequest,
    session_id: str = Depends(get_session_id)
):
    """Updates SM-2 interval and ease factor for a reviewed flashcard."""
    valid_ratings = ["again", "hard", "good", "easy"]
    if req.rating.lower() not in valid_ratings:
        raise HTTPException(status_code=400, detail=f"Invalid rating '{req.rating}'. Must be one of: {valid_ratings}")

    cached_cards = await async_get_study_cache(session_id, "flashcards")
    if not cached_cards:
        raise HTTPException(status_code=404, detail="No cached flashcard deck found for your session.")

    valid_card_ids = {c.get("card_id") for c in cached_cards if isinstance(c, dict)}
    if req.card_id not in valid_card_ids:
        raise HTTPException(status_code=404, detail=f"Card '{req.card_id}' not found in session flashcard deck.")

    result = await async_record_card_review(session_id, req.card_id, req.rating)
    prog = await async_record_progress_event(session_id, "card_reviewed", {"rating": req.rating, "card_id": req.card_id})
    return {"success": True, "review": result, "progress": prog}


@app.post("/api/study/quiz", dependencies=[Depends(rate_limit_study_api)])
async def get_quiz(
    req: Optional[StudyRequest] = None,
    session_id: str = Depends(get_session_id)
):
    """Generates or retrieves authentic University Exam Pack (5-Mark, 10-Mark Case Studies, & MCQs) for the session."""
    req = req or StudyRequest()
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")
    
    if not req.force_refresh and not req.api_key:
        cached = await async_get_study_cache(session_id, "quiz_exam_pack_v2")
        if cached:
            if isinstance(cached, dict):
                return cached
            return {"quiz": cached, "practice_mcqs": cached, "five_mark_questions": [], "ten_mark_questions": []}

    exam_pack = generate_quiz(ppt_data, api_key=req.api_key)
    await async_save_study_cache(session_id, "quiz_exam_pack_v2", exam_pack)
    if isinstance(exam_pack, dict):
        return exam_pack
    return {"quiz": exam_pack, "practice_mcqs": exam_pack}


@app.post("/api/study/chat", dependencies=[Depends(rate_limit_study_api)])
async def chat_tutor(
    req: ChatRequest,
    session_id: str = Depends(get_session_id)
):
    """Interactive Claude / GPT-style AI tutor chat endpoint supporting dynamic session memory and presentation context."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session. Please upload a document first.")
    
    current_memory = await async_get_all_session_memory(session_id)

    reply_data = answer_study_chat(
        ppt_data=ppt_data,
        chat_history=req.chat_history or [],
        user_message=req.message,
        teacher_mode=req.teacher_mode or "tutor",
        api_key=req.api_key,
        session_memory=current_memory
    )

    if isinstance(reply_data, tuple):
        reply, new_memory = reply_data
    else:
        reply = reply_data
        new_memory = {}

    if new_memory:
        for k, v in new_memory.items():
            await async_save_session_memory(session_id, k, str(v))

    updated_memory = await async_get_all_session_memory(session_id)
    follow_ups = generate_follow_up_chips(reply, req.message, ppt_data)
    await async_record_progress_event(session_id, "chat_used", {})
    return {"reply": reply, "follow_ups": follow_ups, "session_memory": updated_memory}


@app.get("/api/study/chat/memory")
async def get_session_memory_endpoint(
    session_id: str = Depends(get_session_id)
):
    """Retrieves all stored session memory items for this active session."""
    memory = await async_get_all_session_memory(session_id)
    return {"session_memory": memory}


@app.delete("/api/study/chat/memory")
async def clear_session_memory_endpoint(
    session_id: str = Depends(get_session_id)
):
    """Clears stored session memory for this active session."""
    await async_clear_session_memory(session_id)
    return {"success": True, "message": "Session memory cleared."}


@app.get("/api/export/text")
async def export_full_text(
    session_id: str = Depends(get_session_id)
):
    """Exports all extracted document text, tables, and speaker notes across every document and slide as a clean Markdown/Text file for Claude or AI ingestion."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document loaded for your session.")
    
    fname = ppt_data.get('filename', 'document')
    filenames = ppt_data.get('filenames', [fname])
    slides = ppt_data.get("slides", [])
    total_slides = ppt_data.get("total_slides", len(slides))

    lines = []
    lines.append("=" * 80)
    lines.append("DOCUMENT MASTER EXPORT FOR CLAUDE / AI INGESTION & STUDY")
    lines.append(f"Primary Title: {fname}")
    lines.append(f"Total Documents Included: {len(filenames)}")
    for idx, fn in enumerate(filenames, start=1):
        doc_slide_cnt = len([s for s in slides if s.get('doc_name') == fn]) or total_slides
        lines.append(f"  [{idx}] {fn} ({doc_slide_cnt} slides/pages)")
    lines.append(f"Total Extracted Slides / Pages: {total_slides}")
    lines.append("=" * 80)
    
    lines.append("\nTABLE OF CONTENTS / SLIDE DIRECTORY:")
    for idx, fn in enumerate(filenames, start=1):
        if len(filenames) > 1:
            lines.append(f"\n--- Document {idx}: {fn} ---")
        doc_slides = [s for s in slides if s.get('doc_name') == fn]
        if not doc_slides:
            doc_slides = slides
        for s in doc_slides:
            s_num = s.get('doc_slide_number', s.get('slide_number', 1))
            g_num = s.get('slide_number', s_num)
            if len(filenames) > 1:
                lines.append(f"  • Slide {s_num} (Global #{g_num}): {s.get('title', 'Untitled')}")
            else:
                lines.append(f"  • Slide {s_num}: {s.get('title', 'Untitled')}")
                
    lines.append("\n" + "=" * 80)
    lines.append("FULL SLIDE-BY-SLIDE CONTENT & SPEAKER NOTES:")
    lines.append("=" * 80 + "\n")

    for s in slides:
        s_num = s.get("doc_slide_number", s.get("slide_number", 1))
        g_num = s.get("slide_number", s_num)
        doc_name = s.get("doc_name", fname)
        s_title = s.get("title", f"Slide {s_num}")
        texts = s.get("text_content", [])
        notes = s.get("speaker_notes", "").strip()
        tables = s.get("tables", [])

        if len(filenames) > 1:
            lines.append(f"--- [DOC: {doc_name} | SLIDE {s_num} (Global #{g_num})]: {s_title} ---")
        else:
            lines.append(f"--- [SLIDE {s_num} of {total_slides}]: {s_title} ---")
            
        if texts:
            lines.append("Content:")
            for t in texts:
                lines.append(f"  {t}")
        if tables:
            lines.append("Tables:")
            for tbl in tables:
                for row in tbl:
                    lines.append(f"  | {' | '.join(row)} |")
        if notes:
            lines.append(f"📌 Presenter Notes / Speaker Annotations:\n  {notes}")
        lines.append("\n")

    full_text_export = "\n".join(lines)
    first_clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filenames[0] if filenames else 'document')
    export_fn = f"Study_Notes_{first_clean}.txt" if len(filenames) == 1 else f"Study_Notes_MultiDoc_{len(filenames)}_docs.txt"

    return RawResponse(
        content=full_text_export,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{export_fn}"'}
    )


@app.get("/api/export/json")
async def export_full_json(
    session_id: str = Depends(get_session_id)
):
    """Exports the full extracted multi-document data (all slides, notes, tables, raw text) as structured JSON."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document loaded for your session.")
    
    json_content = json.dumps(ppt_data, ensure_ascii=False, indent=2)
    fname = ppt_data.get('filename', 'document')
    filenames = ppt_data.get('filenames', [fname])
    first_clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filenames[0] if filenames else 'document')
    export_fn = f"Study_Data_{first_clean}.json" if len(filenames) == 1 else f"Study_Data_MultiDoc_{len(filenames)}_docs.json"
    
    return RawResponse(
        content=json_content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{export_fn}"'}
    )


class AiCheckRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="Gemini API key to validate")


@app.post("/api/ai/check", dependencies=[Depends(rate_limit_study_api)])
async def ai_check(req: AiCheckRequest):
    """Validates if the provided API key is functional using a live 1-token call. Never echoes the key back."""
    result = verify_gemini_api_key(req.api_key)
    return {
        "valid": result.get("valid", False),
        "status": result.get("status", "error"),
        "client_available": result.get("client_available", False),
        "reason": result.get("reason", "Verification complete.")
    }


class ProgressEventRequest(BaseModel):
    event_type: str = Field(..., max_length=50, description="Type of study event (card_reviewed, quiz_answered, exam_finished, chat_used, feynman_completed)")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Event metadata (rating, score, slide_number, etc.)")


@app.get("/api/progress")
async def get_study_progress_endpoint(session_id: str = Depends(get_session_id)):
    """Retrieves session gamification progress, streak, level, XP, and daily mission."""
    return await async_get_progress(session_id)


@app.post("/api/progress/event")
async def record_study_event_endpoint(req: ProgressEventRequest, session_id: str = Depends(get_session_id)):
    """Records a progress event with strictly server-side calculated XP and streak rules."""
    return await async_record_progress_event(session_id, req.event_type, req.payload)


@app.get("/api/study/mastery")
async def get_study_mastery_endpoint(session_id: str = Depends(get_session_id)):
    """Retrieves slide-by-slide mastery status, scores, and highlighted weak spots."""
    return await async_get_mastery(session_id)


class FeynmanRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500, description="Concept or topic being explained")
    explanation: str = Field(..., min_length=5, max_length=5000, description="Student's explanation in their own words")
    slide_number: Optional[int] = Field(None, description="Target slide number")
    api_key: Optional[str] = Field(None, description="Optional Gemini API key")


@app.post("/api/study/feynman", dependencies=[Depends(rate_limit_study_api)])
async def study_feynman_endpoint(req: FeynmanRequest, session_id: str = Depends(get_session_id)):
    """Evaluates student's explanation using the Feynman Technique and awards server-side XP."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")

    eval_result = evaluate_feynman_explanation(
        concept=req.topic,
        explanation=req.explanation,
        ppt_data=ppt_data,
        slide_number=req.slide_number,
        api_key=req.api_key
    )

    prog = await async_record_progress_event(
        session_id,
        "feynman_completed",
        {"clarity_score": eval_result.get("clarity_score", 70), "slide_number": req.slide_number}
    )
    eval_result["progress"] = prog
    return eval_result


# --- Quiz Master Hub Endpoints ---

@app.post("/api/quizmaster/generate", dependencies=[Depends(rate_limit_study_api)])
async def generate_quizmaster(
    req: Optional[QuizMasterGenerateRequest] = None,
    session_id: str = Depends(get_session_id)
):
    """Generates an interactive Quiz Master exam based on difficulty, topic, and question count."""
    req = req or QuizMasterGenerateRequest()
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")

    q_count = max(1, min(20, req.question_count or 5))
    difficulty = req.difficulty if req.difficulty in ["Easy", "Medium", "Hard"] else "Medium"
    
    questions = generate_quizmaster_exam(
        ppt_data=ppt_data,
        difficulty=difficulty,
        topic=req.topic,
        question_count=q_count,
        api_key=req.api_key
    )

    doc_name = ppt_data.get("filename", "Presentation")
    topic_str = f" ({req.topic})" if req.topic else ""
    exam_title = f"{difficulty} Exam{topic_str} - {doc_name}"

    return {
        "exam_title": exam_title,
        "difficulty": difficulty,
        "topic": req.topic,
        "question_count": len(questions),
        "time_limit_seconds": len(questions) * 60,
        "questions": questions
    }


@app.post("/api/quizmaster/submit")
async def submit_quizmaster(
    req: QuizMasterSubmitRequest,
    session_id: str = Depends(get_session_id)
):
    """Submits Quiz Master exam answers, calculates percentage score, and saves score result."""
    if not (0 <= req.score <= req.total_questions):
        raise HTTPException(status_code=422, detail=f"Score ({req.score}) must be between 0 and total_questions ({req.total_questions}).")
    if not (1 <= req.total_questions <= 20):
        raise HTTPException(status_code=422, detail=f"total_questions ({req.total_questions}) must be between 1 and 20.")
    if req.time_spent_seconds < 0:
        raise HTTPException(status_code=422, detail="time_spent_seconds must be non-negative.")
    if len(req.details) > 50:
        raise HTTPException(status_code=422, detail="details cannot exceed 50 items.")
    if not req.exam_title or len(req.exam_title.strip()) == 0 or len(req.exam_title) > 255:
        raise HTTPException(status_code=422, detail="exam_title length must be between 1 and 255 characters.")

    percentage = round((req.score / req.total_questions) * 100.0, 1)

    result = await async_save_quiz_result(
        session_id=session_id,
        exam_title=req.exam_title,
        score=req.score,
        total_questions=req.total_questions,
        percentage=percentage,
        time_spent_seconds=req.time_spent_seconds,
        details=req.details
    )

    prog = await async_record_progress_event(
        session_id,
        "exam_finished",
        {"score": req.score, "total_questions": req.total_questions}
    )

    return {"success": True, "result": result, "progress": prog}


@app.get("/api/quizmaster/history")
async def get_quizmaster_history(
    request: Request,
    response: Response,
    session_id: str = Depends(get_session_id)
):
    """Retrieves score history for all completed Quiz Master exams in this session."""
    history = await async_get_quiz_history(session_id)
    return {"history": history}


# Serve static web files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "PPT & PDF AI Study Assistant API is running!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
