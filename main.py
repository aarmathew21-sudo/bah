import os
import io
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ppt_parser import extract_ppt_content
from ai_study import (
    generate_study_summary,
    generate_flashcards,
    generate_quiz,
    answer_study_chat
)
from create_sample_ppt import create_sample_presentation

app = FastAPI(title="PPT Text & Notes AI Study Assistant")

PRESENTATION_STORE: Dict[str, Any] = {}

class ChatRequest(BaseModel):
    message: str
    chat_history: Optional[List[Dict[str, str]]] = []
    api_key: Optional[str] = None

class StudyRequest(BaseModel):
    api_key: Optional[str] = None


@app.post("/api/upload")
async def upload_ppt(file: UploadFile = File(...)):
    """Uploads a PowerPoint (.pptx) file, extracts content and speaker notes."""
    if not file.filename.lower().endswith((".pptx", ".ppt")):
        raise HTTPException(status_code=400, detail="Only PowerPoint (.pptx) files are currently supported.")

    try:
        content = await file.read()
        parsed_data = extract_ppt_content(content)
        parsed_data["filename"] = file.filename
        PRESENTATION_STORE["current"] = parsed_data

        return {
            "success": True,
            "filename": file.filename,
            "total_slides": parsed_data["total_slides"],
            "slides": parsed_data["slides"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse PowerPoint file: {str(e)}")


@app.post("/api/sample")
async def load_sample_ppt():
    """Loads a pre-generated sample presentation with text, tables, and speaker notes for instant demo testing."""
    sample_filename = "sample_study_presentation.pptx"
    if not os.path.exists(sample_filename):
        create_sample_presentation(sample_filename)

    with open(sample_filename, "rb") as f:
        content = f.read()

    parsed_data = extract_ppt_content(content)
    parsed_data["filename"] = "Sample_Machine_Learning_Notes.pptx"
    PRESENTATION_STORE["current"] = parsed_data

    return {
        "success": True,
        "filename": parsed_data["filename"],
        "total_slides": parsed_data["total_slides"],
        "slides": parsed_data["slides"]
    }


@app.get("/api/current")
async def get_current_presentation():
    """Returns currently loaded presentation data."""
    if "current" not in PRESENTATION_STORE:
        return {"loaded": False}
    data = PRESENTATION_STORE["current"]
    return {
        "loaded": True,
        "filename": data.get("filename"),
        "total_slides": data.get("total_slides"),
        "slides": data.get("slides")
    }


@app.post("/api/study/summary")
async def get_study_summary(req: StudyRequest = StudyRequest()):
    """Generates study guide summary."""
    if "current" not in PRESENTATION_STORE:
        raise HTTPException(status_code=400, detail="No presentation uploaded yet.")
    summary = generate_study_summary(PRESENTATION_STORE["current"], api_key=req.api_key)
    return summary


@app.post("/api/study/flashcards")
async def get_flashcards(req: StudyRequest = StudyRequest()):
    """Generates study flashcards."""
    if "current" not in PRESENTATION_STORE:
        raise HTTPException(status_code=400, detail="No presentation uploaded yet.")
    cards = generate_flashcards(PRESENTATION_STORE["current"], api_key=req.api_key)
    return {"flashcards": cards}


@app.post("/api/study/quiz")
async def get_quiz(req: StudyRequest = StudyRequest()):
    """Generates interactive quiz."""
    if "current" not in PRESENTATION_STORE:
        raise HTTPException(status_code=400, detail="No presentation uploaded yet.")
    questions = generate_quiz(PRESENTATION_STORE["current"], api_key=req.api_key)
    return {"quiz": questions}


@app.post("/api/study/chat")
async def chat_tutor(req: ChatRequest):
    """Interactive AI tutor endpoint."""
    if "current" not in PRESENTATION_STORE:
        raise HTTPException(status_code=400, detail="No presentation uploaded yet. Please upload a PPT first.")
    
    reply = answer_study_chat(
        ppt_data=PRESENTATION_STORE["current"],
        chat_history=req.chat_history or [],
        user_message=req.message,
        api_key=req.api_key
    )
    return {"reply": reply}


@app.get("/api/export/text")
async def export_full_text():
    """Exports all extracted slide text and speaker notes as a text file."""
    if "current" not in PRESENTATION_STORE:
        raise HTTPException(status_code=400, detail="No presentation loaded.")
    
    data = PRESENTATION_STORE["current"]
    filename = f"Study_Notes_{data.get('filename', 'presentation')}.txt"
    digest = data.get("full_digest", "")

    return Response(
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
    return {"message": "PPT AI Study Assistant Website API is running!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
