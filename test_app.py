import io
import sys
import os
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient
from main import app
from database import init_db
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

    # Validate PPT
    fmt_ppt = validate_upload_file(valid_ppt_bytes, filename=sample_ppt_filename, max_size_mb=50)
    assert fmt_ppt == "pptx"
    print("Valid PPT format validation passed.")

    # Validate PDF
    fmt_pdf = validate_upload_file(sample_pdf_bytes, filename="sample_lecture_notes.pdf", max_size_mb=50)
    assert fmt_pdf == "pdf"
    print("Valid PDF format validation passed.")

    # PDF extraction test
    pdf_data = extract_pdf_content(sample_pdf_bytes)
    assert pdf_data["total_slides"] == 1
    assert "Neural Networks" in pdf_data["full_digest"]
    print(f"PDF extraction succeeded! Pages: {pdf_data['total_slides']}")

    print("\n--- 2. Testing FastAPI REST Endpoints via TestClient ---")

    with TestClient(app) as client:
        # A) Test CORS Preflight Options for trusted origin
        cors_resp = client.options(
            "/api/upload",
            headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "POST"}
        )
        assert cors_resp.status_code == 200
        assert cors_resp.headers.get("access-control-allow-origin") == "http://localhost:8000"
        assert cors_resp.headers.get("access-control-allow-credentials") == "true"
        print("CORS preflight check for trusted origin passed.")

        # Test CORS preflight for untrusted origin (should NOT echo untrusted origin)
        cors_bad = client.options(
            "/api/upload",
            headers={"Origin": "http://malicious-site.com", "Access-Control-Request-Method": "POST"}
        )
        assert cors_bad.headers.get("access-control-allow-origin") != "http://malicious-site.com"
        print("CORS security check: untrusted origins correctly blocked.")

        # B) Test PDF upload endpoint
        pdf_resp = client.post(
            "/api/upload",
            files={"file": ("lecture.pdf", sample_pdf_bytes, "application/pdf")}
        )
        assert pdf_resp.status_code == 200, f"Expected 200 OK for PDF upload, got {pdf_resp.status_code}: {pdf_resp.text}"
        pdf_upload_data = pdf_resp.json()
        assert pdf_upload_data["success"] is True
        print(f"PDF Upload Endpoint succeeded! Pages: {pdf_upload_data['total_slides']}")

        # C) Test PPT upload endpoint
        resp = client.post(
            "/api/upload",
            files={"file": ("presentation.pptx", valid_ppt_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
        )
        assert resp.status_code == 200
        print("PPT Upload Endpoint succeeded!")

        # D) Test /api/study/summary
        resp = client.post("/api/study/summary", json={})
        assert resp.status_code == 200
        print("POST /api/study/summary endpoint verified.")

        # E) Test Rate Limiter Throttling
        print("Testing rate limiter protection on /api/study/*...")
        with TestClient(app) as rate_client:
            rate_client.post("/api/upload", files={"file": ("presentation.pptx", valid_ppt_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
            
            rate_limit_hit = False
            for i in range(35):
                r = rate_client.post("/api/study/summary", json={})
                if r.status_code == 429:
                    rate_limit_hit = True
                    break
            assert rate_limit_hit, "Expected rate limit 429 Too Many Requests after 30 calls!"
            print("Rate limiter throttling (429 Too Many Requests) verified successfully.")

    print("\n[SUCCESS] ALL PPT, PDF, CORS SECURITY, AND RATE LIMITER TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
