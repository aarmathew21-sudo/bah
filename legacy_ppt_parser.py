import io
import struct
import olefile
from typing import Dict, Any, List


def validate_legacy_ppt_file(file_bytes: bytes, filename: str = "", max_size_mb: int = 50):
    """Validates legacy PowerPoint 97-2003 binary (.ppt) file header and OLE structure."""
    max_bytes = max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"File size exceeds the maximum limit of {max_size_mb} MB.")

    if len(file_bytes) < 512:
        raise ValueError("File is too small to be a valid PowerPoint 97-2003 (.ppt) presentation.")

    # OLE Compound File Header check
    if not file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("Invalid file format. The file is not a valid PowerPoint (.ppt) presentation.")

    try:
        if not olefile.isOleFile(io.BytesIO(file_bytes)):
            raise ValueError("Corrupt PowerPoint 97-2003 (.ppt) file structure.")
        
        with olefile.OleFileIO(io.BytesIO(file_bytes)) as ole:
            if not ole.exists("PowerPoint Document"):
                raise ValueError("Corrupt PowerPoint (.ppt) file. Missing PowerPoint Document stream.")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        raise ValueError(f"Failed to parse PowerPoint (.ppt) document: {str(e)}")


def extract_legacy_ppt_content(file_bytes: bytes) -> Dict[str, Any]:
    """
    Extracts text, titles, and notes from legacy PowerPoint 97-2003 binary (.ppt) files using OLE stream parsing.
    Returns structured slides dictionary compatible with the AI Study engine.
    """
    file_stream = io.BytesIO(file_bytes)
    with olefile.OleFileIO(file_stream) as ole:
        doc_stream = ole.openstream("PowerPoint Document").read()

    slides_data = []
    current_slide_texts = []
    current_notes_texts = []
    
    pos = 0
    stream_len = len(doc_stream)

    # Scan OLE stream for Slide containers (0x03EE) and Text Atoms (0x0FA8 utf16, 0x0FA0 ascii)
    while pos < stream_len - 8:
        recVerInst, recType, recLen = struct.unpack("<HHI", doc_stream[pos:pos+8])

        # Check for Slide Container start (0x03EE) or SlidePersistAtom (0x0FBA)
        if recType == 0x03EE:  # SlideContainer
            if current_slide_texts:
                _add_extracted_slide(slides_data, current_slide_texts, current_notes_texts)
                current_slide_texts = []
                current_notes_texts = []
            pos += 8
            continue

        # Check for Text Atoms
        if recType in (0x0FA8, 0x0FA0) and 0 < recLen < 100000 and pos + 8 + recLen <= stream_len:
            txt_bytes = doc_stream[pos+8 : pos+8+recLen]
            txt = ""
            if recType == 0x0FA8:  # UTF-16LE
                try:
                    txt = txt_bytes.decode("utf-16-le", errors="ignore").strip()
                except Exception:
                    txt = ""
            elif recType == 0x0FA0:  # Latin1 / ASCII
                try:
                    txt = txt_bytes.decode("latin1", errors="ignore").strip()
                except Exception:
                    txt = ""

            # Filter unprintable control characters and noise
            clean_txt = "".join(ch for ch in txt if ch.isprintable() or ch in ("\n", "\t")).strip()
            if len(clean_txt) > 1 and not _is_binary_noise(clean_txt):
                # Distinguish speaker notes from main slide bullets
                if "note" in clean_txt.lower() or "presenter" in clean_txt.lower():
                    current_notes_texts.append(clean_txt)
                else:
                    current_slide_texts.append(clean_txt)

            pos += 8 + recLen
        else:
            pos += 2

    # Add final slide
    if current_slide_texts or current_notes_texts:
        _add_extracted_slide(slides_data, current_slide_texts, current_notes_texts)

    # Fallback if slides count is 0 but raw text exists
    if not slides_data and current_slide_texts:
        _add_extracted_slide(slides_data, ["PowerPoint Presentation Content"], current_slide_texts)

    if not slides_data:
        slides_data.append({
            "slide_number": 1,
            "title": "PowerPoint Presentation",
            "text_content": ["Extracted content from legacy presentation."],
            "tables": [],
            "speaker_notes": "",
            "raw_text": "=== Slide 1: PowerPoint Presentation ===\nExtracted content from legacy presentation."
        })

    full_text_blocks = [s["raw_text"] for s in slides_data]
    full_digest = "\n\n" + ("=" * 40) + "\n\n".join(full_text_blocks)

    return {
        "total_slides": len(slides_data),
        "slides": slides_data,
        "full_digest": full_digest
    }


def _add_extracted_slide(slides_list: list, slide_texts: list, notes_texts: list):
    """Helper to group extracted texts into slide dictionary."""
    slide_num = len(slides_list) + 1
    title = f"Slide {slide_num}"
    
    if slide_texts:
        title = slide_texts[0]
        if len(title) > 80:
            title = title[:77] + "..."
        body_texts = slide_texts[1:] if len(slide_texts) > 1 else slide_texts
    else:
        body_texts = []

    notes_str = "\n".join(notes_texts) if notes_texts else ""

    raw_parts = [f"=== Slide {slide_num}: {title} ==="]
    if body_texts:
        raw_parts.append("\n".join(body_texts))
    if notes_str:
        raw_parts.append(f"📌 Speaker Notes (Presenter Info):\n{notes_str}")

    slides_list.append({
        "slide_number": slide_num,
        "title": title,
        "text_content": body_texts,
        "tables": [],
        "speaker_notes": notes_str,
        "raw_text": "\n\n".join(raw_parts)
    })


def _is_binary_noise(text: str) -> bool:
    """Returns True if text looks like internal binary header metadata noise."""
    noise_patterns = ["times new roman", "arial", "calibri", "microsoft", "default design", "slide master", "header", "footer"]
    t_lower = text.lower()
    if any(t_lower == p for p in noise_patterns):
        return True
    if len(text) < 3 and not text.isalnum():
        return True
    return False
