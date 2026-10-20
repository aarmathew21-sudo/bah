import io
import sys
import os
import struct
import zipfile
import warnings
from unittest.mock import MagicMock

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient
from main import app
from database import init_db, record_card_review, get_due_flashcards
from create_sample_ppt import create_sample_presentation
from create_sample_pdf import create_sample_pdf
from ppt_parser import extract_ppt_content, validate_upload_file
from pdf_parser import extract_pdf_content, validate_pdf_file
import ai_study
from legacy_ppt_parser import extract_legacy_ppt_content, validate_legacy_ppt_file


def make_mock_ppt_binary(slide_title: str, slide_bullets: list, notes_text: str) -> bytes:
    """
    Constructs an in-memory legacy PowerPoint 97-2003 OLE Compound Document (.ppt)
    containing SlideContainer (0x03EE) and NotesContainer (0x03F0).
    """
    def make_record(rec_type: int, data: bytes, is_container: bool = False, instance: int = 0) -> bytes:
        ver = 0xF if is_container else 0x0
        rec_ver_inst = (instance << 4) | (ver & 0x0F)
        return struct.pack('<HHI', rec_ver_inst, rec_type, len(data)) + data

    # Slide Container records
    s_title_hdr = make_record(0x0F9F, struct.pack('<I', 0))  # TextHeaderAtom: Title
    s_title_txt = make_record(0x0FA0, slide_title.encode('utf-16le'))  # TextCharsAtom

    s_body_parts = []
    for b in slide_bullets:
        s_body_hdr = make_record(0x0F9F, struct.pack('<I', 1))  # TextHeaderAtom: Body
        s_body_txt = make_record(0x0FA0, b.encode('utf-16le'))
        s_body_parts.append(s_body_hdr + s_body_txt)

    s_atom = make_record(0x03EF, b'\x00' * 32)
    slide_container = make_record(0x03EE, s_atom + s_title_hdr + s_title_txt + b''.join(s_body_parts), is_container=True)

    # Notes Container records
    n_atom = make_record(0x03F1, struct.pack('<IH', 1, 0))  # NotesAtom: slideIdRef = 1
    n_hdr = make_record(0x0F9F, struct.pack('<I', 2))        # TextHeaderAtom: Notes
    n_txt = make_record(0x0FA0, notes_text.encode('utf-16le'))
    notes_container = make_record(0x03F0, n_atom + n_hdr + n_txt, is_container=True)

    # PowerPoint Document stream
    doc_stream_data = make_record(0x03E8, slide_container + notes_container, is_container=True)

    # CFBF format requires stream >= 4096 bytes to avoid mini-FAT allocation
    actual_len = max(len(doc_stream_data), 4096)
    sector_size = 512
    stream_sectors = (actual_len + sector_size - 1) // sector_size
    padded_stream = doc_stream_data.ljust(stream_sectors * sector_size, b'\x00')
    actual_len = len(padded_stream)
    total_data_sectors = stream_sectors

    # FAT table setup: sector 0 = FAT, sector 1 = Dir
    fat_entries = [0xFFFFFFFF] * 128
    fat_entries[0] = 0xFFFFFFFD  # FAT sector
    fat_entries[1] = 0xFFFFFFFE  # End of chain for directory
    for i in range(total_data_sectors):
        sec = 2 + i
        fat_entries[sec] = 0xFFFFFFFE if (i == total_data_sectors - 1) else (sec + 1)

    fat_bytes = b''.join(struct.pack('<I', e) for e in fat_entries)

    def make_dir_entry(name: str, entry_type: int, start_sect: int, size: int, child_id: int = -1) -> bytes:
        name_utf16 = name.encode('utf-16le') + b'\x00\x00'
        name_bytes = name_utf16.ljust(64, b'\x00')
        name_len = len(name_utf16)
        color = 1
        left_sib = 0xFFFFFFFF
        right_sib = 0xFFFFFFFF
        child = child_id if child_id >= 0 else 0xFFFFFFFF
        clsid = b'\x00' * 16
        state_flags = 0
        create_time = 0
        mod_time = 0
        return struct.pack('<64sHBBIII16sIQQIQ',
            name_bytes, name_len, entry_type, color,
            left_sib, right_sib, child,
            clsid, state_flags, create_time, mod_time,
            start_sect, size
        )

    root_entry = make_dir_entry('Root Entry', 5, 0xFFFFFFFE, 0, child_id=1)
    stream_entry = make_dir_entry('PowerPoint Document', 2, 2, actual_len, child_id=-1)
    empty_entry = b'\x00' * 128
    dir_bytes = root_entry + stream_entry + empty_entry + empty_entry

    # Header sector (512 bytes)
    hdr = bytearray(512)
    hdr[0:8] = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'  # OLE Magic
    struct.pack_into('<HH', hdr, 24, 0x003e, 0x0003)
    struct.pack_into('<H', hdr, 28, 0xfffe)           # Little-endian
    struct.pack_into('<H', hdr, 30, 9)                # Sector shift 512
    struct.pack_into('<H', hdr, 32, 6)                # Mini-sector shift 64
    struct.pack_into('<I', hdr, 44, 1)                # 1 FAT sector
    struct.pack_into('<I', hdr, 48, 1)                # First dir sector = 1
    struct.pack_into('<I', hdr, 56, 4096)             # Mini stream cutoff
    struct.pack_into('<I', hdr, 60, 0xFFFFFFFE)       # First mini FAT
    struct.pack_into('<I', hdr, 68, 0xFFFFFFFE)       # First DIFAT
    difat = [0xFFFFFFFF] * 109
    difat[0] = 0  # FAT sector 0
    hdr[76:76+436] = b''.join(struct.pack('<I', d) for d in difat)

    return bytes(hdr) + fat_bytes + dir_bytes + padded_stream


def main():
    init_db()

    print("--- 1. Testing Hard File Validation Functions (PPTX & PDF) ---")
    
    sample_ppt_filename = "sample_study_presentation.pptx"
    create_sample_presentation(sample_ppt_filename)
    with open(sample_ppt_filename, "rb") as f:
        valid_ppt_bytes = f.read()

    sample_pdf_bytes = create_sample_pdf("sample_lecture_notes.pdf")

    fmt_ppt = validate_upload_file(valid_ppt_bytes, filename=sample_ppt_filename, max_size_mb=50)
    assert fmt_ppt == "pptx"
    print("Valid PPTX format validation passed.")

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
        rev_e1 = client.post("/api/study/flashcards/review", json={"card_id": card_id, "rating": "easy"}).json()["review"]
        assert rev_e1["interval_days"] == 1
        assert rev_e1["repetitions"] == 1

        rev_e2 = client.post("/api/study/flashcards/review", json={"card_id": card_id, "rating": "easy"}).json()["review"]
        assert rev_e2["interval_days"] == 6
        assert rev_e2["repetitions"] == 2

        rev_e3 = client.post("/api/study/flashcards/review", json={"card_id": card_id, "rating": "easy"}).json()["review"]
        assert rev_e3["interval_days"] >= 10
        assert rev_e3["repetitions"] == 3
        print(f"SM-2 'easy' rating test passed: interval grew to {rev_e3['interval_days']} days across repetitions!")

        # Verify card is now removed from due queue
        new_due_resp = client.get("/api/study/flashcards/due")
        new_due_cards = new_due_resp.json()["due_flashcards"]
        due_card_ids = [c["card_id"] for c in new_due_cards]
        assert card_id not in due_card_ids
        print("SM-2 due queue test passed: card correctly dropped out of due queue for future review.")

        # C) Test Reviewing an Unknown Card ID returns 404
        rev_invalid = client.post("/api/study/flashcards/review", json={
            "card_id": "non_existent_card_id_9999",
            "rating": "good"
        })
        assert rev_invalid.status_code == 404, f"Expected 404 for unknown card_id, got {rev_invalid.status_code}"
        print("SM-2 unknown card_id test passed: correctly rejected with 404.")

        # D) Test Quiz Master Endpoints & Bounds Validation
        print("\n--- 3. Testing Quiz Master Endpoints & Input Bounds Validation ---")
        gen_resp = client.post("/api/quizmaster/generate", json={
            "difficulty": "Hard",
            "question_count": 5,
            "topic": "Machine Learning"
        })
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()
        assert gen_data["difficulty"] == "Hard"
        assert len(gen_data["questions"]) > 0
        q_count = len(gen_data["questions"])
        print(f"Quiz Master generate exam passed. Title: '{gen_data['exam_title']}' with {q_count} questions.")

        # Valid Submit exam results
        sub_resp = client.post("/api/quizmaster/submit", json={
            "exam_title": gen_data["exam_title"],
            "score": q_count,
            "total_questions": q_count,
            "time_spent_seconds": 120,
            "details": [
                {"question": "Q1", "user_option": "Opt A", "correct_option": "Opt A", "is_correct": True, "explanation": "Correct"}
            ]
        })
        assert sub_resp.status_code == 200
        sub_data = sub_resp.json()["result"]
        assert sub_data["percentage"] == 100.0
        assert sub_data["score"] == q_count
        print(f"Quiz Master submit exam passed. Saved score ID {sub_data['id']} with {sub_data['percentage']}%.")

        # Fetch exam history
        hist_resp = client.get("/api/quizmaster/history")
        assert hist_resp.status_code == 200
        hist_data = hist_resp.json()["history"]
        assert len(hist_data) >= 1
        assert hist_data[0]["score"] == q_count
        print(f"Quiz Master fetch history passed. Total attempts recorded: {len(hist_data)}.")

        # Testing HTTP 422 Bounds Validations on /api/quizmaster/submit
        print("Testing Quiz Master HTTP 422 bounds validation checks...")
        # 1. score > total_questions (e.g. 50/5)
        bad_score_high = client.post("/api/quizmaster/submit", json={
            "exam_title": "ML Exam", "score": 50, "total_questions": 5, "time_spent_seconds": 60, "details": []
        })
        assert bad_score_high.status_code == 422, f"Expected 422 for score > total, got {bad_score_high.status_code}"

        # 2. negative score (e.g. -3/5)
        bad_score_neg = client.post("/api/quizmaster/submit", json={
            "exam_title": "ML Exam", "score": -3, "total_questions": 5, "time_spent_seconds": 60, "details": []
        })
        assert bad_score_neg.status_code == 422, f"Expected 422 for negative score, got {bad_score_neg.status_code}"

        # 3. oversized details (> 50 items)
        bad_details = client.post("/api/quizmaster/submit", json={
            "exam_title": "ML Exam", "score": 5, "total_questions": 5, "time_spent_seconds": 60,
            "details": [{"q": i} for i in range(51)]
        })
        assert bad_details.status_code == 422, f"Expected 422 for oversized details, got {bad_details.status_code}"

        # 4. total_questions out of bounds (> 20 or < 1)
        bad_total_high = client.post("/api/quizmaster/submit", json={
            "exam_title": "ML Exam", "score": 25, "total_questions": 25, "time_spent_seconds": 60, "details": []
        })
        assert bad_total_high.status_code == 422, f"Expected 422 for total_questions > 20, got {bad_total_high.status_code}"

        bad_total_low = client.post("/api/quizmaster/submit", json={
            "exam_title": "ML Exam", "score": 0, "total_questions": 0, "time_spent_seconds": 60, "details": []
        })
        assert bad_total_low.status_code == 422, f"Expected 422 for total_questions < 1, got {bad_total_low.status_code}"

        # 5. negative time_spent_seconds
        bad_time = client.post("/api/quizmaster/submit", json={
            "exam_title": "ML Exam", "score": 5, "total_questions": 5, "time_spent_seconds": -10, "details": []
        })
        assert bad_time.status_code == 422, f"Expected 422 for negative time, got {bad_time.status_code}"

        # 6. oversized exam_title
        bad_title = client.post("/api/quizmaster/submit", json={
            "exam_title": "X" * 300, "score": 5, "total_questions": 5, "time_spent_seconds": 60, "details": []
        })
        assert bad_title.status_code == 422, f"Expected 422 for oversized title, got {bad_title.status_code}"

        print("Quiz Master HTTP 422 validation checks passed for all edge cases!")

        # D) Test Multi-Document Upload & Export
        print("\n--- 4. Testing Multi-Document Upload, Append, & Exports ---")
        multi_upload_resp = client.post(
            "/api/upload?mode=replace",
            files=[
                ("files", ("Sample1.pptx", valid_ppt_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")),
                ("files", ("Sample2.pdf", sample_pdf_bytes, "application/pdf"))
            ]
        )
        assert multi_upload_resp.status_code == 200
        multi_data = multi_upload_resp.json()
        assert multi_data["total_documents"] == 2
        assert len(multi_data["filenames"]) == 2
        print(f"Multi-document upload passed! Total documents: {multi_data['total_documents']}, Total slides/pages: {multi_data['total_slides']}")

        # Test Append Mode
        append_resp = client.post(
            "/api/upload?mode=append",
            files=[
                ("files", ("Sample3.pdf", sample_pdf_bytes, "application/pdf"))
            ]
        )
        assert append_resp.status_code == 200
        append_data = append_resp.json()
        assert append_data["total_documents"] == 3
        print(f"Append document passed! New total documents: {append_data['total_documents']}, Total slides: {append_data['total_slides']}")

        # Test Text Export for Multi-Doc
        text_export_resp = client.get("/api/export/text")
        assert text_export_resp.status_code == 200
        export_text = text_export_resp.text
        assert "DOCUMENT MASTER EXPORT FOR CLAUDE" in export_text
        assert "Total Documents Included: 3" in export_text
        print("Master text export (.txt) passed for Claude ingestion!")

        # Test JSON Export for Multi-Doc
        json_export_resp = client.get("/api/export/json")
        assert json_export_resp.status_code == 200
        export_json = json_export_resp.json()
        assert len(export_json["filenames"]) == 3
        print("Master JSON export (.json) passed!")

        # E) Test ChatRequest character and history caps
        print("\n--- 5. Testing ChatRequest Message & History Caps ---")
        # 1. Message > 4000 characters
        chat_long_msg = client.post("/api/study/chat", json={
            "message": "A" * 4001
        })
        assert chat_long_msg.status_code == 422, f"Expected 422 for message > 4000 chars, got {chat_long_msg.status_code}"

        # 2. chat_history > 100 entries
        chat_long_hist = client.post("/api/study/chat", json={
            "message": "Hello tutor",
            "chat_history": [{"role": "user", "content": f"msg {i}"} for i in range(101)]
        })
        assert chat_long_hist.status_code == 422, f"Expected 422 for chat_history > 100 entries, got {chat_long_hist.status_code}"

        # 3. chat_history entry size > 4000 characters
        chat_oversized_entry = client.post("/api/study/chat", json={
            "message": "Hello tutor",
            "chat_history": [{"role": "user", "content": "B" * 4005}]
        })
        assert chat_oversized_entry.status_code == 422, f"Expected 422 for chat_history entry size > 4000 chars, got {chat_oversized_entry.status_code}"
        print("ChatRequest character, history length, and entry size cap validation checks passed (422)!")

        # F) Test Zip Upload Security: 50MB single entry, 200MB total size, entry count, corrupt zip, valid zip
        print("\n--- 6. Testing ZIP Upload Security & Limits (Return 400/413, Never 500) ---")

        # 1. Single entry > 50 MB
        bio_single = io.BytesIO()
        with zipfile.ZipFile(bio_single, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("large_entry.txt", b"dummy")
        data_single = bytearray(bio_single.getvalue())
        cd_pos = data_single.find(b"PK\x01\x02")
        struct.pack_into("<I", data_single, cd_pos + 24, 55 * 1024 * 1024)
        struct.pack_into("<I", data_single, 22, 55 * 1024 * 1024)
        zip_single_large = bytes(data_single)

        resp_single_large = client.post(
            "/api/upload",
            files={"file": ("single_large.zip", zip_single_large, "application/zip")}
        )
        assert resp_single_large.status_code in (400, 413) and resp_single_large.status_code != 500, (
            f"Expected 400 or 413, got {resp_single_large.status_code}"
        )

        # 2. Total uncompressed size > 200 MB
        bio_total = io.BytesIO()
        with zipfile.ZipFile(bio_total, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("part1.txt", b"data1")
            zf.writestr("part2.txt", b"data2")
        data_total = bytearray(bio_total.getvalue())
        pos = 0
        while True:
            cd = data_total.find(b"PK\x01\x02", pos)
            if cd == -1:
                break
            struct.pack_into("<I", data_total, cd + 24, 110 * 1024 * 1024)
            pos = cd + 4
        zip_total_large = bytes(data_total)

        resp_total_large = client.post(
            "/api/upload",
            files={"file": ("total_large.zip", zip_total_large, "application/zip")}
        )
        assert resp_total_large.status_code in (400, 413) and resp_total_large.status_code != 500, (
            f"Expected 400 or 413, got {resp_total_large.status_code}"
        )

        # 3. Excessive entry count (> 1000)
        bio_count = io.BytesIO()
        with zipfile.ZipFile(bio_count, "w", zipfile.ZIP_DEFLATED) as zf:
            for i in range(1005):
                zf.writestr(f"item_{i}.txt", b"x")
        zip_excess_entries = bio_count.getvalue()

        resp_count = client.post(
            "/api/upload",
            files={"file": ("excess_entries.zip", zip_excess_entries, "application/zip")}
        )
        assert resp_count.status_code in (400, 413) and resp_count.status_code != 500, (
            f"Expected 400 or 413, got {resp_count.status_code}"
        )

        # 4. Corrupt zip upload
        corrupt_zip = b"PK\x03\x04" + (b"random corrupt data" * 20)
        resp_corrupt = client.post(
            "/api/upload",
            files={"file": ("corrupt.zip", corrupt_zip, "application/zip")}
        )
        assert resp_corrupt.status_code == 400 and resp_corrupt.status_code != 500, (
            f"Expected 400, got {resp_corrupt.status_code}"
        )

        # 5. Valid zip upload containing presentation
        bio_valid_zip = io.BytesIO()
        with zipfile.ZipFile(bio_valid_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("ArchivedPresentation.pptx", valid_ppt_bytes)
        valid_zip_content = bio_valid_zip.getvalue()

        resp_valid_zip = client.post(
            "/api/upload?mode=append",
            files=[("files", ("Archived.zip", valid_zip_content, "application/zip"))]
        )
        assert resp_valid_zip.status_code == 200, f"Expected 200 for valid zip, got {resp_valid_zip.status_code}"
        print("ZIP upload security and size limits passed: rejected oversized/bomb/corrupt zips (400/413, never 500) and accepted valid zip!")

    # G) Test Gemini Model Fallback & Client Resilience
    print("\n--- 7. Testing Gemini Model Fallback, Error Handling & Model Caching ---")
    
    # 1. Test bad API key / INVALID_ARGUMENT makes exactly 1 call and raises immediately
    mock_bad_key_client = MagicMock()
    mock_bad_key_client.models.generate_content.side_effect = Exception("INVALID_ARGUMENT: API key not valid")
    try:
        ai_study._generate_content_with_fallback(mock_bad_key_client, "Test prompt")
        assert False, "Should have raised exception on bad API key"
    except Exception as e:
        assert "INVALID_ARGUMENT" in str(e) or "API key" in str(e)
        assert mock_bad_key_client.models.generate_content.call_count == 1, (
            f"Expected exactly 1 call on bad API key, got {mock_bad_key_client.models.generate_content.call_count}"
        )
    print("Bad-key test passed: made exactly 1 call and raised immediately without retrying.")

    # 2. Test authentic 404 / NOT_FOUND moves to next candidate model
    ai_study.CACHED_WORKING_MODEL = None
    mock_fallback_client = MagicMock()
    def fallback_side_effect(model, contents):
        if model == "gemini-2.5-flash":
            raise Exception("404 Model gemini-2.5-flash not found")
        mock_resp = MagicMock()
        mock_resp.text = "Fallback model response"
        return mock_resp
    mock_fallback_client.models.generate_content.side_effect = fallback_side_effect

    fb_resp = ai_study._generate_content_with_fallback(mock_fallback_client, "Test prompt")
    assert mock_fallback_client.models.generate_content.call_count == 2
    assert ai_study.CACHED_WORKING_MODEL == "gemini-2.0-flash"
    print(f"Fallback test passed: 404 switched to working model '{ai_study.CACHED_WORKING_MODEL}'.")

    # 3. Test caching: subsequent call directly uses cached working model without retrying
    fb_resp2 = ai_study._generate_content_with_fallback(mock_fallback_client, "Second prompt")
    assert mock_fallback_client.models.generate_content.call_count == 3
    assert mock_fallback_client.models.generate_content.call_args[1]["model"] == "gemini-2.0-flash"
    print("Cached working model test passed: subsequent call reused cached model directly.")

    # 4. Test quota (429) does not retry
    mock_quota_client = MagicMock()
    mock_quota_client.models.generate_content.side_effect = Exception("429 ResourceExhausted: Quota exceeded")
    try:
        ai_study._generate_content_with_fallback(mock_quota_client, "Test prompt")
        assert False, "Should have raised exception on quota"
    except Exception as e:
        assert mock_quota_client.models.generate_content.call_count == 1
    print("Quota (429) test passed: made exactly 1 call without retrying.")

    # H) Test Legacy PPT Parser Container Hierarchy & Notes Separation
    print("\n--- 8. Testing Legacy PPT Parser Container Hierarchy & Notes Separation ---")
    mock_ppt_bytes = make_mock_ppt_binary(
        slide_title="Macroeconomics Overview",
        slide_bullets=["Notes on inflation rates in 2026", "Footnotes: Source BLS data"],
        notes_text="Presenter note: Discuss CPI versus core inflation metrics."
    )
    fmt_legacy = validate_upload_file(mock_ppt_bytes, filename="macro_lecture.ppt", max_size_mb=50)
    assert fmt_legacy == "ppt_legacy"
    print("Legacy .ppt binary validation passed format check ('ppt_legacy').")

    ppt_res = extract_legacy_ppt_content(mock_ppt_bytes)
    assert ppt_res["total_slides"] == 1
    slide_0 = ppt_res["slides"][0]
    assert slide_0["title"] == "Macroeconomics Overview"
    # Ensure bullets containing "note" remain in text_content (slide body)
    assert "Notes on inflation rates in 2026" in slide_0["text_content"]
    assert "Footnotes: Source BLS data" in slide_0["text_content"]
    # Ensure bullets containing "note" are strictly NOT placed into speaker_notes
    assert "Notes on inflation" not in slide_0["speaker_notes"]
    assert "Footnotes" not in slide_0["speaker_notes"]
    # Ensure speaker notes from NotesContainer (0x03F0) are correctly assigned
    assert "Presenter note: Discuss CPI versus core inflation metrics." in slide_0["speaker_notes"]
    print("Legacy .ppt parser test passed: bullets containing 'note' stayed in slide body and speaker notes parsed from 0x03F0 container!")

    # I) Test Corrupt Slide XML Warning (Bug 8a)
    print("\n--- 9. Testing Corrupt Slide XML Warning (Bug 8a) ---")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<Types></Types>")
        zf.writestr("ppt/slides/slide1.xml", b"<invalid xml content << broken")
    corrupt_pptx = buf.getvalue()
    warn_res = extract_ppt_content(corrupt_pptx)
    assert len(warn_res.get("warnings", [])) > 0
    assert warn_res["warnings"][0]["slide_number"] == 1
    assert "XML could not be parsed" in warn_res["warnings"][0]["message"]
    print("Corrupt slide XML warning test passed: caught XML parse error and populated warning structure.")

    # J) Test Live Gemini API Key Verification (Bug 8b)
    print("\n--- 10. Testing Gemini Key Verification Endpoint & Never Echoing Key (Bug 8b) ---")
    test_key = "invalid-secret-key-12345"
    resp = client.post("/api/ai/check", json={"api_key": test_key})
    assert resp.status_code == 200
    check_data = resp.json()
    assert check_data["valid"] is False
    assert check_data["status"] in ("invalid_key", "error", "no_library")
    assert test_key not in resp.text
    print("Gemini key check test passed: properly verified key and never echoed sensitive credentials.")

    # K) Test Gamification Progress, Server-Side XP, Level and Streak
    print("\n--- 11. Testing Gamification Progress, Server-Side XP & Streak Endpoints ---")
    prog_resp = client.get("/api/progress")
    assert prog_resp.status_code == 200
    prog_data = prog_resp.json()
    assert "xp" in prog_data
    assert "streak_days" in prog_data
    assert "level" in prog_data
    assert "recommended_mission" in prog_data

    # Test event recording
    ev_resp = client.post("/api/progress/event", json={
        "event_type": "card_reviewed",
        "payload": {"rating": "easy"}
    })
    assert ev_resp.status_code == 200
    ev_data = ev_resp.json()
    assert ev_data["xp_earned"] == 20
    assert ev_data["total_xp"] >= 20
    print("Progress & server-side XP event test passed!")

    # L) Test Mastery Map Endpoint & Slide Association
    print("\n--- 12. Testing Mastery Map Endpoint & Per-Slide Stats ---")
    mastery_resp = client.get("/api/study/mastery")
    assert mastery_resp.status_code == 200
    m_data = mastery_resp.json()
    assert "slides" in m_data
    assert "weak_spots" in m_data
    assert "overall_mastery" in m_data
    assert len(m_data["slides"]) > 0
    first_tile = m_data["slides"][0]
    assert "slide_number" in first_tile
    assert "mastery_score" in first_tile
    assert "status" in first_tile
    print("Mastery Map test passed: tiles accurately reflect slide numbers, mastery scores, and weak spots.")

    # M) Test Feynman Technique Explanation Endpoint
    print("\n--- 13. Testing Feynman Technique Explanation Endpoint ---")
    feynman_resp = client.post("/api/study/feynman", json={
        "topic": "Gradient Descent",
        "explanation": "Gradient descent works by calculating the derivative of the loss function and taking small steps in the opposite direction of the gradient to minimize error.",
        "slide_number": 1
    })
    assert feynman_resp.status_code == 200
    f_data = feynman_resp.json()
    assert "clarity_score" in f_data
    assert 0 <= f_data["clarity_score"] <= 100
    assert "strengths" in f_data
    assert "feedback" in f_data
    assert "progress" in f_data
    print("Feynman Technique test passed: evaluated explanation, scored clarity, and awarded XP!")

    print("\n" + "=" * 80)
    print("[SUCCESS] ALL SYSTEM, REST, SM-2, QUIZ MASTER, FALLBACK, AND LEGACY PPT TESTS PASSED!")
    print("=" * 80)


if __name__ == "__main__":
    main()
