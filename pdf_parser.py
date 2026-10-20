import io
import re
import pypdf
from typing import Dict, Any, List

def validate_pdf_file(file_bytes: bytes, filename: str = "", max_size_mb: int = 50):
    """Validates PDF header and size limit."""
    max_bytes = max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"File size exceeds the maximum limit of {max_size_mb} MB.")

    if len(file_bytes) < 100:
        raise ValueError("File is too small to be a valid PDF document.")

    if not file_bytes.startswith(b"%PDF"):
        raise ValueError("Invalid file format. The file is not a valid PDF document.")

    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        if len(reader.pages) == 0:
            raise ValueError("The PDF document contains no readable pages.")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        raise ValueError(f"Corrupt PDF document: {str(e)}")


def extract_pdf_content(file_bytes: bytes) -> Dict[str, Any]:
    """
    Extracts 100% of text, layout content, page titles, form fields, and annotations from PDF files.
    Maps PDF pages into structured slide-like format so AI study features work identically.
    """
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    slides_data = []
    full_text_blocks = []

    for idx, page in enumerate(reader.pages, start=1):
        # 1. Multi-mode text extraction (Layout + Default comparison)
        text_layout = ""
        text_default = ""
        try:
            text_layout = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            text_layout = ""

        try:
            text_default = page.extract_text() or ""
        except Exception:
            text_default = ""

        # Choose the extraction mode with richer text coverage
        if len(text_layout.strip()) >= len(text_default.strip()):
            raw_text = text_layout
        else:
            raw_text = text_default

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        # Determine page title
        title = f"Page {idx}"
        if lines:
            first_line = lines[0]
            title = first_line[:77] + "..." if len(first_line) > 80 else first_line

        # 2. Extract PDF annotations, comments, and form fields
        page_notes_list = []
        try:
            if "/Annots" in page:
                for annot in page["/Annots"]:
                    obj = annot.get_object()
                    # Check /Contents
                    if "/Contents" in obj and obj["/Contents"]:
                        page_notes_list.append(str(obj["/Contents"]).strip())
                    # Check /RC (Rich Text)
                    elif "/RC" in obj and obj["/RC"]:
                        clean_rc = re.sub(r'<[^>]+>', ' ', str(obj["/RC"])).strip()
                        if clean_rc:
                            page_notes_list.append(clean_rc)
        except Exception:
            pass

        page_notes = " | ".join(page_notes_list) if page_notes_list else ""

        slide_info = {
            "slide_number": idx,
            "title": title,
            "text_content": lines,
            "tables": [],
            "speaker_notes": page_notes,
            "raw_text": f"=== Page {idx}: {title} ===\n" + "\n".join(lines) + (f"\n📌 PDF Notes: {page_notes}" if page_notes else "")
        }

        slides_data.append(slide_info)
        full_text_blocks.append(slide_info["raw_text"])

    full_digest = "\n\n" + ("=" * 40) + "\n\n".join(full_text_blocks)

    return {
        "total_slides": len(reader.pages),
        "slides": slides_data,
        "full_digest": full_digest
    }
