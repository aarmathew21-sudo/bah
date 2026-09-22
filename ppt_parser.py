import io
import zipfile
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def validate_pptx_file(file_bytes: bytes, filename: str = "", max_size_mb: int = 50):
    """
    Validates uploaded file size and inspects ZIP structure for valid PowerPoint presentation data.
    Raises ValueError with user-friendly error message if validation fails.
    """
    # 1. Size Validation
    max_bytes = max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"File size exceeds the maximum limit of {max_size_mb} MB.")

    if len(file_bytes) < 100:
        raise ValueError("File is too small to be a valid PowerPoint presentation.")

    # 2. Magic Header check for ZIP format
    if not file_bytes.startswith(b"PK\x03\x04"):
        raise ValueError("Invalid file format. The file is not a valid PowerPoint (.pptx) archive.")

    # 3. Structure check inside ZIP archive
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            namelist = zf.namelist()
            # PowerPoint files MUST contain [Content_Types].xml and ppt/presentation.xml
            if "[Content_Types].xml" not in namelist or not any(name.startswith("ppt/") for name in namelist):
                raise ValueError("Corrupt or unsupported presentation format. Missing PowerPoint XML structures.")
    except zipfile.BadZipFile:
        raise ValueError("Corrupt file. Unable to read PowerPoint ZIP structure.")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        raise ValueError(f"Failed to validate PowerPoint archive: {str(e)}")


def extract_ppt_content(file_bytes: bytes) -> dict:
    """
    Extracts all text, table data, shape text, and speaker notes from a PowerPoint presentation bytes.
    Returns a structured dictionary containing slide-by-slide information and a full text summary.
    """
    file_stream = io.BytesIO(file_bytes)
    prs = Presentation(file_stream)

    slides_data = []
    full_text_blocks = []

    for idx, slide in enumerate(prs.slides, start=1):
        slide_info = {
            "slide_number": idx,
            "title": f"Slide {idx}",
            "text_content": [],
            "tables": [],
            "speaker_notes": "",
            "raw_text": ""
        }

        # Extract title
        if slide.shapes.title and slide.shapes.title.text.strip():
            slide_info["title"] = slide.shapes.title.text.strip()

        # Extract shape text and tables
        shape_texts = []
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue

            if shape.has_text_frame:
                txt = shape.text.strip()
                if txt:
                    shape_texts.append(txt)

            if shape.has_table:
                table_data = []
                for row in shape.table.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    if any(row_data):
                        table_data.append(row_data)
                if table_data:
                    slide_info["tables"].append(table_data)
                    table_str = "\n".join([" | ".join(r) for r in table_data])
                    shape_texts.append(f"[Table Content]\n{table_str}")

            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                group_texts = _extract_group_shape_text(shape)
                shape_texts.extend(group_texts)

        slide_info["text_content"] = shape_texts

        # Extract Speaker Notes ("the under part")
        speaker_notes = ""
        try:
            if slide.has_notes_slide:
                notes_slide = slide.notes_slide
                if notes_slide and notes_slide.notes_text_frame:
                    raw_notes = notes_slide.notes_text_frame.text.strip()
                    speaker_notes = raw_notes
        except Exception:
            speaker_notes = ""

        slide_info["speaker_notes"] = speaker_notes

        # Create combined raw text representation for this slide
        combined_text_parts = [f"=== Slide {idx}: {slide_info['title']} ==="]
        if shape_texts:
            combined_text_parts.append("\n".join(shape_texts))
        if speaker_notes:
            combined_text_parts.append(f"📌 Speaker Notes (Presenter Info):\n{speaker_notes}")
        
        slide_info["raw_text"] = "\n\n".join(combined_text_parts)
        slides_data.append(slide_info)

        full_text_blocks.append(slide_info["raw_text"])

    full_digest = "\n\n" + ("=" * 40) + "\n\n".join(full_text_blocks)

    return {
        "total_slides": len(prs.slides),
        "slides": slides_data,
        "full_digest": full_digest
    }


def _extract_group_shape_text(group_shape) -> list:
    """Helper to extract text from grouped shapes."""
    texts = []
    for shape in group_shape.shapes:
        if shape.has_text_frame and shape.text.strip():
            texts.append(shape.text.strip())
        elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            texts.extend(_extract_group_shape_text(shape))
    return texts
