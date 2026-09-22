import io
import sys
import os
from fastapi.testclient import TestClient

from main import app
from database import init_db
from create_sample_ppt import create_sample_presentation
from ppt_parser import extract_ppt_content, validate_pptx_file

def main():
    # Ensure database tables exist for tests
    init_db()

    print("--- 1. Testing Hard File Validation Functions ---")
    
    sample_filename = "sample_study_presentation.pptx"
    create_sample_presentation(sample_filename)

    with open(sample_filename, "rb") as f:
        valid_ppt_bytes = f.read()

    validate_pptx_file(valid_ppt_bytes, filename=sample_filename, max_size_mb=50)
    print("Valid PPT byte validation passed.")

    try:
        validate_pptx_file(b"Hello world invalid content", filename="fake.pptx")
        assert False, "Should have failed validation for non-zip bytes!"
    except ValueError as ve:
        print(f"Caught expected invalid file error: {ve}")

    print("\n--- 2. Testing FastAPI REST Endpoints via TestClient ---")

    with TestClient(app) as client:
        # A) Test upload without presentation / bad file type
        resp = client.post("/api/upload", files={"file": ("test.txt", b"some text content", "text/plain")})
        assert resp.status_code == 400, f"Expected 400 Bad Request for text file, got {resp.status_code}"
        print("Non-PPT upload correctly rejected with 400 Bad Request.")

        # B) Test study endpoint without uploaded presentation (new isolated session client)
        with TestClient(app) as new_client:
            resp = new_client.post("/api/study/summary", json={})
            assert resp.status_code == 400, f"Expected 400 Bad Request when no presentation uploaded, got {resp.status_code}"
            print("Study summary without presentation correctly rejected with 400 Bad Request.")

        # C) Test valid .pptx upload
        resp = client.post(
            "/api/upload",
            files={"file": ("presentation.pptx", valid_ppt_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
        )
        assert resp.status_code == 200, f"Expected 200 OK for upload, got {resp.status_code}: {resp.text}"
        upload_data = resp.json()
        assert upload_data["success"] is True
        assert upload_data["total_slides"] == 3
        print(f"PPT Upload Endpoint succeeded! Total Slides: {upload_data['total_slides']}")

        # D) Test /api/current session retrieval
        resp = client.get("/api/current")
        assert resp.status_code == 200
        current_data = resp.json()
        assert current_data["loaded"] is True
        assert current_data["filename"] == "presentation.pptx"
        print("GET /api/current session retrieval verified.")

        # E) Test /api/study/summary
        resp = client.post("/api/study/summary", json={})
        assert resp.status_code == 200
        summary_data = resp.json()
        assert "summary" in summary_data or "title" in summary_data
        print("POST /api/study/summary endpoint verified.")

        # F) Test /api/study/flashcards
        resp = client.post("/api/study/flashcards", json={})
        assert resp.status_code == 200
        fc_data = resp.json()
        assert "flashcards" in fc_data and len(fc_data["flashcards"]) > 0
        print(f"POST /api/study/flashcards endpoint verified ({len(fc_data['flashcards'])} cards).")

        # G) Test /api/study/quiz
        resp = client.post("/api/study/quiz", json={})
        assert resp.status_code == 200
        quiz_data = resp.json()
        assert "quiz" in quiz_data and len(quiz_data["quiz"]) > 0
        print(f"POST /api/study/quiz endpoint verified ({len(quiz_data['quiz'])} questions).")

        # H) Test /api/study/chat with various teacher_mode options
        teacher_modes = ["tutor", "eli5", "quiz_me", "notes_deepdive"]
        for mode in teacher_modes:
            resp = client.post("/api/study/chat", json={
                "message": "Explain Slide 2 speaker notes",
                "teacher_mode": mode
            })
            assert resp.status_code == 200
            reply = resp.json().get("reply", "")
            assert len(reply) > 0
            print(f"POST /api/study/chat verified for teacher_mode='{mode}'.")

        # I) Test text export endpoint
        resp = client.get("/api/export/text")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert len(resp.text) > 50
        print("GET /api/export/text verified.")

    print("\n[SUCCESS] ALL FASTAPI ENDPOINTS & HARDENING TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
