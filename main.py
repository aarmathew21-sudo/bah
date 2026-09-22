import os
import uuid
import time
import logging
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Response, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response as RawResponse, JSONResponse
from pydantic import BaseModel, Field

from ppt_parser import extract_ppt_content, validate_upload_file
from pdf_parser import extract_pdf_content
from ai_study import (
    generate_study_summary,
    generate_flashcards,
    generate_quiz,
    answer_study_chat
)
from database import (
    init_db,
    async_save_session_presentation,
    async_get_session_presentation,
    async_save_study_cache,
    async_get_study_cache
)
from create_sample_ppt import create_sample_presentation

logger = logging.getLogger("ppt_main_app")

app = FastAPI(
    title="PPT & PDF Text & Notes AI Study Assistant",
    description="Multi-user FastAPI application for PowerPoint (.pptx) & PDF (.pdf) parsing and ChatGPT AI Tutoring."
)

# Configure trusted origins for CORS (defaulting to app's own localhost origins)
# Prevents wildcard credential reflection security vulnerabilities
raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sliding window rate limiter memory store per session_id (30 calls per minute)
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
    logger.info(f"Database initialized with threadpool async wrappers and session cleanup. Trusted CORS origins: {allowed_origins}")


class ChatRequest(BaseModel):
    message: str = Field(..., description="Student chat message or query")
    teacher_mode: Optional[str] = Field("tutor", description="Teacher mode: tutor, eli5, quiz_me, notes_deepdive")
    chat_history: Optional[List[Dict[str, str]]] = Field(default_factory=list)
    api_key: Optional[str] = Field(None, description="Optional Gemini API key")

class StudyRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="Optional Gemini API key")


@app.post("/api/upload")
async def upload_document(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    session_id: str = Depends(get_session_id)
):
    """Uploads a PowerPoint (.pptx) or PDF (.pdf) file, validates size/structure, extracts content and notes per session."""
    if not file.filename or not file.filename.lower().endswith((".pptx", ".ppt", ".pdf")):
        raise HTTPException(status_code=400, detail="Only PowerPoint (.pptx) and PDF (.pdf) files are supported.")

    try:
        content = await file.read()
        
        # 1. Size Validation (50 MB limit)
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large. Maximum allowed size is 50 MB.")

        # 2. Hard file validation (ZIP / PPTX / PDF format check)
        file_type = validate_upload_file(content, filename=file.filename, max_size_mb=50)

        # 3. Parse presentation / PDF content
        if file_type == "pdf":
            parsed_data = extract_pdf_content(content)
        else:
            parsed_data = extract_ppt_content(content)

        parsed_data["filename"] = file.filename

        # 4. Save to SQLite DB scoped to session (offloaded to threadpool)
        await async_save_session_presentation(session_id, parsed_data)
        logger.info(f"Successfully processed {file_type.upper()} upload for session {session_id[:8]}... ({parsed_data['total_slides']} pages/slides)")

        return {
            "success": True,
            "filename": file.filename,
            "total_slides": parsed_data["total_slides"],
            "slides": parsed_data["slides"]
        }
    except ValueError as ve:
        logger.warning(f"Upload validation failed: {str(ve)}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error processing document upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to parse document: {str(e)}")


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
    await async_save_session_presentation(session_id, parsed_data)

    return {
        "success": True,
        "filename": parsed_data["filename"],
        "total_slides": parsed_data["total_slides"],
        "slides": parsed_data["slides"]
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
    
    if not req.api_key:
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
    
    if not req.api_key:
        cached = await async_get_study_cache(session_id, "flashcards")
        if cached:
            return {"flashcards": cached}

    cards = generate_flashcards(ppt_data, api_key=req.api_key)
    await async_save_study_cache(session_id, "flashcards", cards)
    return {"flashcards": cards}


@app.post("/api/study/quiz", dependencies=[Depends(rate_limit_study_api)])
async def get_quiz(
    req: Optional[StudyRequest] = None,
    session_id: str = Depends(get_session_id)
):
    """Generates or retrieves practice quiz for the session."""
    req = req or StudyRequest()
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session.")
    
    if not req.api_key:
        cached = await async_get_study_cache(session_id, "quiz")
        if cached:
            return {"quiz": cached}

    questions = generate_quiz(ppt_data, api_key=req.api_key)
    await async_save_study_cache(session_id, "quiz", questions)
    return {"quiz": questions}


@app.post("/api/study/chat", dependencies=[Depends(rate_limit_study_api)])
async def chat_tutor(
    req: ChatRequest,
    session_id: str = Depends(get_session_id)
):
    """Interactive AI tutor chat endpoint supporting teacher_mode."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document uploaded yet for your session. Please upload a document first.")
    
    reply = answer_study_chat(
        ppt_data=ppt_data,
        chat_history=req.chat_history or [],
        user_message=req.message,
        teacher_mode=req.teacher_mode or "tutor",
        api_key=req.api_key
    )
    return {"reply": reply}


@app.get("/api/export/text")
async def export_full_text(
    session_id: str = Depends(get_session_id)
):
    """Exports all extracted document text and notes as a text file."""
    ppt_data = await async_get_session_presentation(session_id)
    if not ppt_data:
        raise HTTPException(status_code=400, detail="No document loaded for your session.")
    
    filename = f"Study_Notes_{ppt_data.get('filename', 'document')}.txt"
    digest = ppt_data.get("full_digest", "")

    return RawResponse(
        content=digest,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


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
