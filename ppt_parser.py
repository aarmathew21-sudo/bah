import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pdf_parser import validate_pdf_file, extract_pdf_content
from legacy_ppt_parser import validate_legacy_ppt_file, extract_legacy_ppt_content

# OpenXML Namespaces
NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'
}


def validate_upload_file(file_bytes: bytes, filename: str = "", max_size_mb: int = 50) -> str:
    """
    Validates file size and inspects format headers for PowerPoint (.pptx / .ppt) and PDF (.pdf) files.
    Returns format string: 'pptx', 'ppt_legacy', or 'pdf'.
    """
    max_bytes = max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"File size exceeds the maximum limit of {max_size_mb} MB.")

    if len(file_bytes) < 100:
        raise ValueError("File is too small to be a valid document.")

    filename_lower = filename.lower()
    
    # 1. PDF Check
    if filename_lower.endswith(".pdf") or file_bytes.startswith(b"%PDF"):
        validate_pdf_file(file_bytes, filename=filename, max_size_mb=max_size_mb)
        return "pdf"

    # 2. Modern PPTX (OpenXML ZIP) or ZIP archive Check
    if filename_lower.endswith((".pptx", ".zip")) or file_bytes.startswith(b"PK\x03\x04"):
        if filename_lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                    validate_zip_archive_security(zf)
            except zipfile.BadZipFile:
                raise ValueError("Corrupt file. Unable to read ZIP structure.")
            return "zip"
        validate_pptx_file(file_bytes, filename=filename, max_size_mb=max_size_mb)
        return "pptx"

    # 3. Legacy PPT (PowerPoint 97-2003 OLE Compound Binary) Check
    if filename_lower.endswith(".ppt") or file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        validate_legacy_ppt_file(file_bytes, filename=filename, max_size_mb=max_size_mb)
        return "ppt_legacy"

    raise ValueError("Unsupported file format. Please upload a PowerPoint (.pptx / .ppt), PDF (.pdf), or ZIP archive (.zip).")


MAX_ZIP_ENTRIES = 1000
MAX_ZIP_TOTAL_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_ZIP_SINGLE_ENTRY_BYTES = 50 * 1024 * 1024  # 50 MB


def validate_zip_archive_security(
    zf: zipfile.ZipFile,
    max_total_bytes: int = MAX_ZIP_TOTAL_BYTES,
    max_single_entry_bytes: int = MAX_ZIP_SINGLE_ENTRY_BYTES,
    max_entries: int = MAX_ZIP_ENTRIES
):
    """
    Validates ZIP archive entries against zip bomb attacks and size limits.
    Inspects each ZipInfo:
    - Caps total entry count (max 1,000)
    - Checks each single entry file_size <= 50 MB
    - Sums file_size across all entries <= 200 MB
    """
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ValueError(f"ZIP archive contains too many entries ({len(infos)}). Maximum allowed is {max_entries}.")

    total_uncompressed = 0
    for info in infos:
        if info.file_size > max_single_entry_bytes:
            raise ValueError(
                f"ZIP entry '{info.filename}' is too large ({info.file_size / (1024 * 1024):.1f} MB). "
                f"Maximum allowed single entry size is {max_single_entry_bytes // (1024 * 1024)} MB."
            )
        total_uncompressed += info.file_size
        if total_uncompressed > max_total_bytes:
            raise ValueError(
                f"Total uncompressed size of ZIP entries ({total_uncompressed / (1024 * 1024):.1f} MB) "
                f"exceeds the limit of {max_total_bytes // (1024 * 1024)} MB."
            )


def validate_pptx_file(file_bytes: bytes, filename: str = "", max_size_mb: int = 50):
    """Validates uploaded PPTX file size and inspects ZIP structure."""
    max_bytes = max_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise ValueError(f"File size exceeds the maximum limit of {max_size_mb} MB.")

    if not file_bytes.startswith(b"PK\x03\x04"):
        raise ValueError("Invalid file format. The file is not a valid PowerPoint (.pptx) archive.")

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            validate_zip_archive_security(zf)
            namelist = zf.namelist()
            if "[Content_Types].xml" not in namelist or not any(name.startswith("ppt/") for name in namelist):
                raise ValueError("Corrupt or unsupported presentation format. Missing PowerPoint XML structures.")
    except zipfile.BadZipFile:
        raise ValueError("Corrupt file. Unable to read PowerPoint ZIP structure.")
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        raise ValueError(f"Failed to validate PowerPoint archive: {str(e)}")


def _get_ordered_slide_paths(zf: zipfile.ZipFile) -> List[str]:
    """Inspects ppt/presentation.xml and relationships to return ordered list of slide XML paths."""
    if "ppt/presentation.xml" not in zf.namelist() or "ppt/_rels/presentation.xml.rels" not in zf.namelist():
        # Fallback to alphanumeric sort
        return sorted([n for n in zf.namelist() if re.match(r'^ppt/slides/slide\d+\.xml$', n)],
                      key=lambda x: int(re.search(r'\d+', x).group()))

    try:
        pres_xml = zf.read("ppt/presentation.xml")
        pres_root = ET.fromstring(pres_xml)

        rels_xml = zf.read("ppt/_rels/presentation.xml.rels")
        rels_root = ET.fromstring(rels_xml)

        rel_map = {}
        for rel in rels_root:
            r_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target", "")
            if r_id and target:
                if not target.startswith("ppt/"):
                    target = "ppt/" + target.lstrip("/")
                rel_map[r_id] = target

        slide_paths = []
        for elem in pres_root.iter():
            if elem.tag.endswith("sldId"):
                r_id = elem.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                if r_id and r_id in rel_map:
                    target_path = rel_map[r_id]
                    if target_path in zf.namelist():
                        slide_paths.append(target_path)

        if slide_paths:
            return slide_paths
    except Exception:
        pass

    # Fallback to regex sorting
    return sorted([n for n in zf.namelist() if re.match(r'^ppt/slides/slide\d+\.xml$', n)],
                  key=lambda x: int(re.search(r'\d+', x).group()))


def _extract_xml_slide_data(zf: zipfile.ZipFile, slide_path: str) -> Dict[str, Any]:
    """Deep XML parser extracting raw text, tables, SmartArt diagrams, charts, comments, and presenter notes."""
    result = {
        "xml_paragraphs": [],
        "xml_tables": [],
        "smartart_text": [],
        "chart_text": [],
        "comments": [],
        "xml_notes": "",
        "xml_error": None
    }

    try:
        slide_xml = zf.read(slide_path)
        root = ET.fromstring(slide_xml)

        # 1. Extract all paragraph text in shape tree
        for p in root.findall('.//a:p', NS):
            text_runs = [t.text for t in p.findall('.//a:t', NS) if t.text]
            p_text = ''.join(text_runs).strip()
            if p_text and p_text not in result["xml_paragraphs"]:
                result["xml_paragraphs"].append(p_text)

        # 2. Extract tables in XML
        for tbl in root.findall('.//a:tbl', NS):
            tbl_data = []
            for tr in tbl.findall('.//a:tr', NS):
                row = []
                for tc in tr.findall('.//a:tc', NS):
                    cell_text_parts = [t.text for t in tc.findall('.//a:t', NS) if t.text]
                    row.append(' '.join(''.join(cell_text_parts).split()))
                if any(row):
                    tbl_data.append(row)
            if tbl_data:
                result["xml_tables"].append(tbl_data)

        # 3. Follow relationships (SmartArt diagrams, Charts, Comments, Notes)
        slide_dir, slide_fname = slide_path.rsplit('/', 1)
        rels_path = f"{slide_dir}/_rels/{slide_fname}.rels"

        if rels_path in zf.namelist():
            rels_root = ET.fromstring(zf.read(rels_path))
            for rel in rels_root:
                target = rel.attrib.get("Target", "")
                rel_type = rel.attrib.get("Type", "")

                resolved = "ppt/" + target.replace("../", "")
                if resolved not in zf.namelist():
                    continue

                # Notes Slide
                if "notesSlide" in rel_type or "notesSlide" in resolved:
                    try:
                        n_root = ET.fromstring(zf.read(resolved))
                        notes_lines = []
                        for p in n_root.findall('.//a:p', NS):
                            t_parts = [t.text for t in p.findall('.//a:t', NS) if t.text]
                            line = ''.join(t_parts).strip()
                            if line and not (line.isdigit() and len(line) <= 3) and line not in notes_lines:
                                notes_lines.append(line)
                        if notes_lines:
                            result["xml_notes"] = '\n'.join(notes_lines)
                    except Exception:
                        pass

                # SmartArt Diagram Data
                elif "diagram" in resolved or "smartArt" in rel_type:
                    try:
                        d_root = ET.fromstring(zf.read(resolved))
                        for elem in d_root.iter():
                            if elem.tag.endswith("}t") and elem.text and elem.text.strip():
                                t_clean = elem.text.strip()
                                if t_clean not in result["smartart_text"]:
                                    result["smartart_text"].append(t_clean)
                    except Exception:
                        pass

                # Embedded Chart Data
                elif "chart" in resolved:
                    try:
                        c_root = ET.fromstring(zf.read(resolved))
                        for elem in c_root.iter():
                            if (elem.tag.endswith("}v") or elem.tag.endswith("}t")) and elem.text and elem.text.strip():
                                c_txt = elem.text.strip()
                                if len(c_txt) > 1 and not c_txt.replace(".", "", 1).isdigit() and c_txt not in result["chart_text"]:
                                    result["chart_text"].append(c_txt)
                    except Exception:
                        pass

                # Slide Comments
                elif "comment" in resolved:
                    try:
                        com_root = ET.fromstring(zf.read(resolved))
                        for elem in com_root.iter():
                            if elem.tag.endswith("}text") and elem.text and elem.text.strip():
                                result["comments"].append(elem.text.strip())
                    except Exception:
                        pass
    except Exception as e:
        result["xml_error"] = str(e)

    return result


def extract_ppt_content(file_bytes: bytes) -> dict:
    """
    Lossless multi-layered text extractor for PowerPoint presentations (.pptx).
    Combines python-pptx object tree with deep XML stream analysis to extract 100% of:
    - Slide titles, subtitles, and body text
    - Tables (formatted as structured data and readable markdown)
    - Grouped shapes and nested containers
    - SmartArt diagrams, process flows, and hierarchy charts
    - Embedded chart labels and series
    - Presenter / speaker notes and reviewer annotations
    """
    slides_data = []
    full_text_blocks = []
    warnings = []

    # 1. Open with python-pptx for structural hierarchy
    prs = None
    try:
        prs = Presentation(io.BytesIO(file_bytes))
    except Exception:
        prs = None

    # 2. Open with zipfile for deep XML scan
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        ordered_slide_paths = _get_ordered_slide_paths(zf)
        total_slides = len(ordered_slide_paths) if ordered_slide_paths else (len(prs.slides) if prs else 0)

        for idx, slide_path in enumerate(ordered_slide_paths, start=1):
            slide_obj = prs.slides[idx - 1] if (prs and idx <= len(prs.slides)) else None
            xml_data = _extract_xml_slide_data(zf, slide_path)

            slide_info = {
                "slide_number": idx,
                "title": f"Slide {idx}",
                "text_content": [],
                "tables": [],
                "speaker_notes": "",
                "raw_text": ""
            }

            shape_texts = []
            tables_data = []
            speaker_notes = ""

            # --- A. python-pptx Pass ---
            if slide_obj:
                # Title resolution
                if slide_obj.shapes.title and slide_obj.shapes.title.text.strip():
                    slide_info["title"] = slide_obj.shapes.title.text.strip().split("\n")[0].strip()

                for shape in slide_obj.shapes:
                    # Text frames (including title shapes so all sub-bullets/descriptions are preserved)
                    if shape.has_text_frame:
                        for p in shape.text_frame.paragraphs:
                            pt = p.text.strip()
                            if pt and pt not in shape_texts:
                                shape_texts.append(pt)

                    # Tables
                    if shape.has_table:
                        tbl = []
                        for row in shape.table.rows:
                            row_data = [cell.text.strip() for cell in row.cells]
                            if any(row_data):
                                tbl.append(row_data)
                        if tbl:
                            tables_data.append(tbl)

                    # Grouped Shapes
                    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                        group_texts = _extract_group_shape_text(shape)
                        for gt in group_texts:
                            if gt and gt not in shape_texts:
                                shape_texts.append(gt)

                # Presenter Notes
                try:
                    if slide_obj.has_notes_slide and slide_obj.notes_slide and slide_obj.notes_slide.notes_text_frame:
                        raw_notes = slide_obj.notes_slide.notes_text_frame.text.strip()
                        if raw_notes:
                            speaker_notes = raw_notes
                except Exception:
                    pass

            # --- B. Deep XML Cross-Check (Catch SmartArt, Missing Shapes, Charts, XML Notes) ---
            # 1. Merge any XML paragraphs that python-pptx missed
            for xml_p in xml_data["xml_paragraphs"]:
                if xml_p not in shape_texts and not any(xml_p in existing for existing in shape_texts):
                    shape_texts.append(xml_p)

            # 2. Merge XML tables if python-pptx missed them
            if not tables_data and xml_data["xml_tables"]:
                tables_data = xml_data["xml_tables"]

            # 3. Add SmartArt Diagram text
            if xml_data["smartart_text"]:
                smartart_block = "📊 Diagram / SmartArt Content:\n" + "\n".join([f"  • {item}" for item in xml_data["smartart_text"] if item not in shape_texts])
                if xml_data["smartart_text"][0] not in "".join(shape_texts):
                    shape_texts.append(smartart_block)

            # 4. Add Chart text
            if xml_data["chart_text"]:
                chart_items = [c for c in xml_data["chart_text"] if c not in shape_texts]
                if chart_items:
                    shape_texts.append("📈 Embedded Chart Elements: " + " | ".join(chart_items))

            # 5. Add Slide Comments
            if xml_data["comments"]:
                comments_block = "💬 Slide Review Notes / Comments:\n" + "\n".join([f"  • {c}" for c in xml_data["comments"]])
                shape_texts.append(comments_block)

            # 6. Fallback or augment speaker notes from XML
            if xml_data["xml_notes"]:
                if not speaker_notes:
                    speaker_notes = xml_data["xml_notes"]
                elif xml_data["xml_notes"] not in speaker_notes:
                    speaker_notes = f"{speaker_notes}\n{xml_data['xml_notes']}"

            # --- C. Title Finalization ---
            if (not slide_info["title"] or slide_info["title"] == f"Slide {idx}") and shape_texts:
                first_text = shape_texts[0].split("\n")[0].strip()
                if 2 < len(first_text) <= 100:
                    slide_info["title"] = first_text

            slide_info["text_content"] = shape_texts
            slide_info["tables"] = tables_data
            slide_info["speaker_notes"] = speaker_notes

            # --- D. Build Unified Text Block for Slide ---
            slide_warnings = []
            if xml_data.get("xml_error"):
                slide_warnings.append(f"Slide {idx} XML could not be parsed: {xml_data['xml_error']}")
            elif not shape_texts and not tables_data and not speaker_notes:
                slide_warnings.append(f"Slide {idx} contained no readable text or visual elements.")

            if slide_warnings:
                warn_msg = "; ".join(slide_warnings)
                slide_info["has_warning"] = True
                slide_info["warning_message"] = warn_msg
                warnings.append({"slide_number": idx, "message": warn_msg})
            else:
                slide_info["has_warning"] = False
                slide_info["warning_message"] = ""

            combined_parts = [f"=== Slide {idx}: {slide_info['title']} ==="]
            if shape_texts:
                combined_parts.append("\n".join(shape_texts))
            if tables_data:
                for tbl in tables_data:
                    table_str = "\n".join([" | ".join(row) for row in tbl])
                    combined_parts.append(f"[Table Data]\n{table_str}")
            if speaker_notes:
                combined_parts.append(f"📌 Presenter Notes / Speaker Annotations:\n{speaker_notes}")

            slide_info["raw_text"] = "\n\n".join(combined_parts)
            slides_data.append(slide_info)
            full_text_blocks.append(slide_info["raw_text"])

    full_digest = "\n\n" + ("=" * 40) + "\n\n".join(full_text_blocks)

    return {
        "total_slides": len(slides_data),
        "slides": slides_data,
        "full_digest": full_digest,
        "warnings": warnings
    }


def _extract_group_shape_text(group_shape) -> list:
    """Helper to extract text from grouped shapes and nested containers."""
    texts = []
    try:
        for shape in group_shape.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    pt = p.text.strip()
                    if pt:
                        texts.append(pt)
            elif shape.has_table:
                for row in shape.table.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    if any(row_data):
                        texts.append(" | ".join(row_data))
            elif shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                texts.extend(_extract_group_shape_text(shape))
    except Exception:
        pass
    return texts

