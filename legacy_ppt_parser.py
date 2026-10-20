import io
import struct
import olefile
from typing import Dict, Any, List, Tuple, Optional


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


def _find_containers(buf: bytes, target_types: set) -> List[Tuple[int, bytes]]:
    """
    Recursively scans binary records for containers matching target record types.
    Recurses into any container record where recVer == 0xF.
    """
    found = []

    def walk(data: bytes):
        pos = 0
        data_len = len(data)
        while pos + 8 <= data_len:
            recVerInst, recType, recLen = struct.unpack("<HHI", data[pos:pos+8])
            recVer = recVerInst & 0x0F
            is_container = (recVer == 0x0F)
            payload_start = pos + 8
            payload_end = payload_start + recLen

            if payload_end > data_len:
                break

            payload = data[payload_start:payload_end]

            if recType in target_types:
                found.append((recType, payload))
            elif is_container:
                walk(payload)

            pos = payload_end

    walk(buf)
    return found


def _extract_slide_container(payload: bytes) -> Tuple[str, List[str], Optional[int]]:
    """
    Extracts title, body bullets, and optional slide ID from a SlideContainer (0x03EE).
    Uses TextHeaderAtom (0x0F9F) to distinguish title from body text.
    """
    title = ""
    body_texts = []
    slide_id = None
    curr_text_type = None

    def walk(data: bytes):
        nonlocal title, slide_id, curr_text_type
        pos = 0
        data_len = len(data)
        while pos + 8 <= data_len:
            recVerInst, recType, recLen = struct.unpack("<HHI", data[pos:pos+8])
            recVer = recVerInst & 0x0F
            is_container = (recVer == 0x0F)
            payload_start = pos + 8
            payload_end = payload_start + recLen

            if payload_end > data_len:
                break

            rec_data = data[payload_start:payload_end]

            if is_container:
                walk(rec_data)
            else:
                # TextHeaderAtom (0x0F9F)
                if recType == 0x0F9F and len(rec_data) >= 4:
                    curr_text_type = struct.unpack("<I", rec_data[:4])[0]

                # SlidePersistAtom (0x03F3)
                elif recType == 0x03F3 and len(rec_data) >= 16:
                    slide_id = struct.unpack("<I", rec_data[12:16])[0]

                # TextCharsAtom (0x0FA0 UTF-16LE) or TextBytesAtom (0x0FA8 Latin1)
                elif recType in (0x0FA0, 0x0FA8):
                    raw_str = ""
                    if recType == 0x0FA0:
                        raw_str = rec_data.decode("utf-16-le", errors="ignore")
                    else:
                        raw_str = rec_data.decode("latin1", errors="ignore")

                    clean = "".join(ch for ch in raw_str if ch.isprintable() or ch in ("\n", "\t")).strip()
                    if clean and not _is_binary_noise(clean):
                        # TextType: 0 = Title, 6 = Center Title
                        if curr_text_type in (0, 6):
                            if not title:
                                title = clean
                            else:
                                body_texts.append(clean)
                        elif not title and curr_text_type is None:
                            title = clean
                        else:
                            body_texts.append(clean)

            pos = payload_end

    walk(payload)
    return title, body_texts, slide_id


def _extract_notes_container(payload: bytes) -> Tuple[List[str], Optional[int]]:
    """
    Extracts speaker notes text and target slide ID reference from a NotesContainer (0x03F0).
    """
    notes_lines = []
    slide_id_ref = None
    curr_text_type = None

    def walk(data: bytes):
        nonlocal slide_id_ref, curr_text_type
        pos = 0
        data_len = len(data)
        while pos + 8 <= data_len:
            recVerInst, recType, recLen = struct.unpack("<HHI", data[pos:pos+8])
            recVer = recVerInst & 0x0F
            is_container = (recVer == 0x0F)
            payload_start = pos + 8
            payload_end = payload_start + recLen

            if payload_end > data_len:
                break

            rec_data = data[payload_start:payload_end]

            if is_container:
                walk(rec_data)
            else:
                # NotesAtom (0x03F1)
                if recType == 0x03F1 and len(rec_data) >= 4:
                    slide_id_ref = struct.unpack("<I", rec_data[:4])[0]

                # TextHeaderAtom (0x0F9F)
                elif recType == 0x0F9F and len(rec_data) >= 4:
                    curr_text_type = struct.unpack("<I", rec_data[:4])[0]

                # TextCharsAtom (0x0FA0) or TextBytesAtom (0x0FA8)
                elif recType in (0x0FA0, 0x0FA8):
                    raw_str = ""
                    if recType == 0x0FA0:
                        raw_str = rec_data.decode("utf-16-le", errors="ignore")
                    else:
                        raw_str = rec_data.decode("latin1", errors="ignore")

                    clean = "".join(ch for ch in raw_str if ch.isprintable() or ch in ("\n", "\t")).strip()
                    if clean and not _is_binary_noise(clean):
                        notes_lines.append(clean)

            pos = payload_end

    walk(payload)
    return notes_lines, slide_id_ref


def extract_legacy_ppt_content(file_bytes: bytes) -> Dict[str, Any]:
    """
    Extracts text, titles, and speaker notes from legacy PowerPoint 97-2003 binary (.ppt) files.
    Recurses through container hierarchy (record version 0xF).
    Uses SlideContainer (0x03EE) for slide content, NotesContainer (0x03F0) for speaker notes,
    and TextHeaderAtom (0x0F9F) to distinguish titles from body text.
    """
    file_stream = io.BytesIO(file_bytes)
    with olefile.OleFileIO(file_stream) as ole:
        doc_stream = ole.openstream("PowerPoint Document").read()

    # Step 1: Discover all SlideContainers (0x03EE) and NotesContainers (0x03F0)
    containers = _find_containers(doc_stream, {0x03EE, 0x03F0})

    slide_records = []
    notes_by_slide_id = {}
    notes_by_index = []

    for rec_type, payload in containers:
        if rec_type == 0x03EE:  # SlideContainer
            title, body_texts, s_id = _extract_slide_container(payload)
            slide_records.append({
                "title": title,
                "body_texts": body_texts,
                "slide_id": s_id
            })
        elif rec_type == 0x03F0:  # NotesContainer
            n_lines, s_id_ref = _extract_notes_container(payload)
            notes_str = "\n".join(n_lines).strip()
            if s_id_ref is not None and s_id_ref > 0:
                notes_by_slide_id[s_id_ref] = notes_str
            notes_by_index.append(notes_str)

    slides_data = []

    for idx, s_rec in enumerate(slide_records, start=1):
        s_title = s_rec["title"] or f"Slide {idx}"
        body = s_rec["body_texts"]
        s_id = s_rec["slide_id"]

        # Associate notes: first try slide_id match, then sequential index match
        s_notes = ""
        if s_id is not None and s_id in notes_by_slide_id:
            s_notes = notes_by_slide_id[s_id]
        elif (idx - 1) < len(notes_by_index):
            s_notes = notes_by_index[idx - 1]

        raw_parts = [f"=== Slide {idx}: {s_title} ==="]
        if body:
            raw_parts.append("\n".join(body))
        if s_notes:
            raw_parts.append(f"📌 Speaker Notes (Presenter Info):\n{s_notes}")

        slides_data.append({
            "slide_number": idx,
            "title": s_title,
            "text_content": body,
            "tables": [],
            "speaker_notes": s_notes,
            "raw_text": "\n\n".join(raw_parts)
        })

    # Fallback if no SlideContainers found (e.g. flat stream or corrupt structure)
    if not slides_data:
        fallback_texts = _fallback_text_extraction(doc_stream)
        if fallback_texts:
            f_title = fallback_texts[0]
            f_body = fallback_texts[1:]
            slides_data.append({
                "slide_number": 1,
                "title": f_title,
                "text_content": f_body,
                "tables": [],
                "speaker_notes": "",
                "raw_text": f"=== Slide 1: {f_title} ===\n" + "\n".join(f_body)
            })
        else:
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


def _fallback_text_extraction(doc_stream: bytes) -> List[str]:
    """Safety fallback scanning text atoms if container parsing produces 0 slides."""
    texts = []
    pos = 0
    stream_len = len(doc_stream)
    while pos + 8 <= stream_len:
        recVerInst, recType, recLen = struct.unpack("<HHI", doc_stream[pos:pos+8])
        if recType in (0x0FA0, 0x0FA8) and 0 < recLen < 100000 and pos + 8 + recLen <= stream_len:
            data = doc_stream[pos+8:pos+8+recLen]
            txt = data.decode("utf-16-le" if recType == 0x0FA0 else "latin1", errors="ignore").strip()
            clean = "".join(ch for ch in txt if ch.isprintable() or ch in ("\n", "\t")).strip()
            if clean and not _is_binary_noise(clean):
                texts.append(clean)
            pos += 8 + recLen
        else:
            pos += 2
    return texts


def _is_binary_noise(text: str) -> bool:
    """Returns True if text looks like internal binary header metadata noise."""
    noise_patterns = ["times new roman", "arial", "calibri", "microsoft", "default design", "slide master", "header", "footer"]
    t_lower = text.lower()
    if any(t_lower == p for p in noise_patterns):
        return True
    if len(text) < 2 and not text.isalnum():
        return True
    return False
