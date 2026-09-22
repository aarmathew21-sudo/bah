import pypdf
import io

def create_sample_pdf(filename="sample_lecture_notes.pdf"):
    writer = pypdf.PdfWriter()

    # Page 1
    page1 = writer.add_blank_page(width=612, height=792) # Letter size
    # We can write simple pdf content or text using pypdf writer
    # Note: pypdf creates blank pages easily, let's create a valid minimal PDF with text content
    
    # Minimal PDF structure with text content
    pdf_bytes = (
        b"%PDF-1.5\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kinds /Page /Count 1 /Kids [3 0 R]>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /Resources <</Font <</F1 4 0 R>>>> /MediaBox [0 0 612 792] /Contents 5 0 R>> endobj\n"
        b"4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        b"5 0 obj <</Length 120>> stream\n"
        b"BT\n"
        b"/F1 18 Tf\n"
        b"50 700 Td\n"
        b"(Introduction to Neural Networks PDF Notes) Tj\n"
        b"0 -30 Td\n"
        b"/F1 12 Tf\n"
        b"(PDF Lecture Note Page 1: Perceptrons and Activation Functions) Tj\n"
        b"ET\n"
        b"endstream\n"
        b"endobj\n"
        b"xref\n"
        b"0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000056 00000 n \n"
        b"0000000125 00000 n \n"
        b"0000000242 00000 n \n"
        b"0000000310 00000 n \n"
        b"trailer <</Size 6 /Root 1 0 R>>\n"
        b"startxref\n"
        b"480\n"
        b"%%EOF\n"
    )

    with open(filename, "wb") as f:
        f.write(pdf_bytes)

    print(f"Sample PDF created: {filename}")
    return pdf_bytes

if __name__ == "__main__":
    create_sample_pdf()
