import io
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
    Extracts text, page titles, and page annotations from PDF files.
    Maps PDF pages into structured slide-like format so AI study features work identically.
    """
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    slides_data = []
    full_text_blocks = []

    for idx, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        # Determine page title (first non-empty line or default Page N)
        title = f"Page {idx}"
        if lines:
            title = lines[0]
            if len(title) > 80:
                title = title[:77] + "..."

        text_content = lines[1:] if len(lines) > 1 else lines

        # Extract PDF page annotations / comments (acting as speaker notes)
        page_notes = ""
        try:
            if "/Annots" in page:
                annot_list = []
                for annot in page["/Annots"]:
                    obj = annot.get_object()
                    if "/Contents" in obj:
                        annot_list.append(str(obj["/Contents"]))
                if annot_list:
                    page_notes = "PDF Annotations / Notes: " + " | ".join(annot_list)
        except Exception:
            page_notes = ""

        slide_info = {
            "slide_number": idx,
            "title": title,
            "text_content": text_content,
            "tables": [],
            "speaker_notes": page_notes,
            "raw_text": f"=== Page {idx}: {title} ===\n" + "\n".join(text_content) + (f"\n📌 PDF Notes: {page_notes}" if page_notes else "")
        }

        slides_data.append(slide_info)
        full_text_blocks.append(slide_info["raw_text"])

    full_digest = "\n\n" + ("=" * 40) + "\n\n".join(full_text_blocks)

    return {
        "total_slides": len(reader.pages),
        "slides": slides_data,
        "full_digest": full_digest
    }
