import io
import sys
import os
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient
from main import app
from database import init_db, record_card_review, get_due_flashcards
from create_sample_ppt import create_sample_presentation
from create_sample_pdf import create_sample_pdf
from ppt_parser import extract_ppt_content, validate_upload_file
from pdf_parser import extract_pdf_content, validate_pdf_file

def main():
    init_db()

    print("--- 1. Testing Hard File Validation Functions (PPT & PDF) ---")
    
    sample_ppt_filename = "sample_study_presentation.pptx"
    create_sample_presentation(sample_ppt_filename)
    with open(sample_ppt_filename, "rb") as f:
        valid_ppt_bytes = f.read()

    sample_pdf_bytes = create_sample_pdf("sample_lecture_notes.pdf")

    fmt_ppt = validate_upload_file(valid_ppt_bytes, filename=sample_ppt_filename, max_size_mb=50)
    assert fmt_ppt == "pptx"
    print("Valid PPT format validation passed.")

    fmt_pdf = validate_upload_file(sample_pdf_bytes, filename="sample_lecture_notes.pdf", max_size_mb=50)
    assert fmt_pdf == "pdf"
    print("Valid PDF format validation passed.")

    pdf_data = extract_pdf_content(sample_pdf_bytes)
    assert pdf_data["total_slides"] == 1
    assert "Neural Networks" in pdf_data["full_digest"]
    print(f"PDF extraction succeeded! Pages: {pdf_data['total_slides']}")

    print("\n--- 2. Testing FastAPI REST Endpoints & SM-2 Spaced Repetition ---")

    with TestClient(app) as client:
        # Upload presentation
        upload_resp = client.post(
            "/api/upload",
            files={"file": ("presentation.pptx", valid_ppt_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
        )
        assert upload_resp.status_code == 200

        # Fetch due cards
        due_resp = client.get("/api/study/flashcards/due")
        assert due_resp.status_code == 200
        due_data = due_resp.json()
        assert "due_flashcards" in due_data
        due_cards = due_data["due_flashcards"]
        assert len(due_cards) > 0
        target_card = due_cards[0]
        card_id = target_card["card_id"]
        print(f"Fetched {len(due_cards)} due flashcards. Target card_id: {card_id}")

        # A) Test reviewing card as "again" -> short interval (1 day)
        rev_again = client.post("/api/study/flashcards/review", json={
            "card_id": card_id,
            "rating": "again"
        })
        assert rev_again.status_code == 200
        again_data = rev_again.json()["review"]
        assert again_data["interval_days"] == 1
        assert again_data["repetitions"] == 0
        print("SM-2 'again' rating test passed: interval set to 1 day, repetitions reset to 0.")

        # B) Test reviewing card as "easy" repeatedly -> interval growth & queue removal
        # Review 1: Easy (repetitions = 1, interval = 1)
        rev_e1 = client.post("/api/study/flashcards/review", json={"card_id": card_id, "rating": "easy"}).json()["review"]
        assert rev_e1["interval_days"] == 1
        assert rev_e1["repetitions"] == 1

        # Review 2: Easy (repetitions = 2, interval = 6)
        rev_e2 = client.post("/api/study/flashcards/review", json={"card_id": card_id, "rating": "easy"}).json()["review"]
        assert rev_e2["interval_days"] == 6
        assert rev_e2["repetitions"] == 2

        # Review 3: Easy (repetitions = 3, interval >= 10)
        rev_e3 = client.post("/api/study/flashcards/review", json={"card_id": card_id, "rating": "easy"}).json()["review"]
        assert rev_e3["interval_days"] >= 10
        assert rev_e3["repetitions"] == 3
        print(f"SM-2 'easy' rating test passed: interval grew to {rev_e3['interval_days']} days across repetitions!")

        # Verify card is now removed from due queue (since next_review_date is 15+ days in future)
        new_due_resp = client.get("/api/study/flashcards/due")
        new_due_cards = new_due_resp.json()["due_flashcards"]
        due_card_ids = [c["card_id"] for c in new_due_cards]
        assert card_id not in due_card_ids
        print("SM-2 due queue test passed: card correctly dropped out of due queue for future review.")

    print("\n[SUCCESS] ALL SM-2 SPACED REPETITION, ENDPOINTS, AND VALIDATION TESTS PASSED!")

if __name__ == "__main__":
    main()
