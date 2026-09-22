import os
import sys
from create_sample_ppt import create_sample_presentation
from ppt_parser import extract_ppt_content
from ai_study import generate_study_summary, generate_flashcards, generate_quiz, answer_study_chat

def main():
    print("--- 1. Generating Sample Presentation ---")
    ppt_filename = "sample_study_presentation.pptx"
    create_sample_presentation(ppt_filename)

    print("\n--- 2. Testing PPT Text & Speaker Notes Extraction ---")
    with open(ppt_filename, "rb") as f:
        file_bytes = f.read()

    extracted = extract_ppt_content(file_bytes)

    print(f"Total Slides Extracted: {extracted['total_slides']}")
    assert extracted['total_slides'] == 3, f"Expected 3 slides, got {extracted['total_slides']}"

    # Check Slide 1 notes
    s1_notes = extracted['slides'][0]['speaker_notes']
    print(f"Slide 1 Title: {extracted['slides'][0]['title']}")
    print(f"Slide 1 Speaker Notes: {s1_notes}")
    assert "WELCOME NOTES" in s1_notes, "Slide 1 speaker notes missing!"

    # Check Slide 2 notes
    s2_notes = extracted['slides'][1]['speaker_notes']
    print(f"\nSlide 2 Title: {extracted['slides'][1]['title']}")
    print(f"Slide 2 Speaker Notes: {s2_notes}")
    assert "IMPORTANT PRESENTER NOTE" in s2_notes, "Slide 2 speaker notes missing!"

    # Check Slide 3 table & notes
    s3 = extracted['slides'][2]
    print(f"\nSlide 3 Title: {s3['title']}")
    print(f"Slide 3 Tables Count: {len(s3['tables'])}")
    print(f"Slide 3 Speaker Notes: {s3['speaker_notes']}")
    assert len(s3['tables']) == 1, "Slide 3 table extraction failed!"
    assert "SPEAKER NOTE UNDER SLIDE 3" in s3['speaker_notes'], "Slide 3 speaker notes missing!"

    print("\n--- 3. Testing AI Study Feature Generators (Smart Fallback Mode) ---")
    summary = generate_study_summary(extracted)
    print("Generated Summary Title:", summary.get("title"))
    print("Speaker Notes Highlights Count:", len(summary.get("speaker_note_highlights", [])))

    flashcards = generate_flashcards(extracted)
    print(f"Generated Flashcards Count: {len(flashcards)}")
    for card in flashcards[:3]:
        print(f"  - Card {card['id']}: Front='{card['front']}' | Category='{card['category']}'")

    quiz = generate_quiz(extracted)
    print(f"Generated Quiz Questions Count: {len(quiz)}")

    chat_reply = answer_study_chat(extracted, [], "What did the presenter note about Slide 2?")
    print("\nChat Reply for query about Slide 2 speaker notes:")
    print(chat_reply.encode('ascii', errors='backslashreplace').decode('ascii'))

    print("\n[SUCCESS] ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
