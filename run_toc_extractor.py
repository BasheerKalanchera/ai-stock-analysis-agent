# run_toc_extractor.py

import sys
import os
from toc_extractor import get_toc_data

def main(file_name: str):
    """
    Runs the TOC extraction process and displays detailed debugging information.
    """
    # Assuming a 'downloads' folder in the current working directory
    pdf_path = os.path.join(os.getcwd(), "downloads", file_name)

    if not os.path.exists(pdf_path):
        print(f"Error: The file '{pdf_path}' was not found.")
        return

    print(f"--- Starting TOC Extraction for: {file_name} ---\n")
    
    toc_result = get_toc_data(pdf_path)

    if not toc_result:
        print("\n--- ‼️ TOC Extraction Failed ---")
        print("The extraction process encountered a critical error.")
        print("---------------------------------\n")
        return

    toc_title = toc_result.get('toc_title', 'Unknown')
    raw_toc = toc_result.get('raw_toc', [])
    final_toc = toc_result.get('final_toc', [])
    
    if not final_toc:
        print("\n--- ‼️ TOC Extraction Failed ---")
        print(f"Detected TOC Title: '{toc_title}'")
        print("Could not generate a valid, mapped Table of Contents from the document.")
        print("---------------------------------\n")
        return
        
    print("\n--- ✅ TOC Extraction Succeeded ---")
    print(f"Detected TOC Title: '{toc_title}'")
    print(f"AI Parser identified {len(raw_toc)} unique raw sections.")
    
    print("\n--- 🤖 Raw TOC from LLM (Sorted by Printed Page) ---")
    sorted_raw_toc = sorted(raw_toc, key=lambda x: x[2])
    for _level, title, page in sorted_raw_toc:
        print(f"  - Title: '{title.strip()}', Printed Page: {page}")

    print("\n--- 📖 Final Validated TOC Entries ---")
    print(f"Found physical pages for {len(final_toc)} of {len(raw_toc)} sections.")
    
    raw_titles = {item[1].strip() for item in raw_toc}
    final_titles = {item['title'] for item in final_toc}
    skipped_titles = raw_titles - final_titles
    
    for item in final_toc:
        start_page = item['start'] + 1
        end_page = item['end'] + 1
        print(f"  - Title: '{item['title']}'")
        print(f"    Physical Page Range: {start_page} to {end_page} (Indices: {item['start']}-{item['end']})")
    
    if skipped_titles:
        print("\n--- ⚠️ Skipped Sections ---")
        print("The following sections were skipped because their titles could not be found in the document:")
        for title in sorted(list(skipped_titles)):
             printed_page = next((p for _l, t, p in raw_toc if t.strip() == title), "N/A")
             print(f"  - {title} (Printed Page: {printed_page})")
    
    print("-------------------------------------------\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage: python run_toc_extractor.py <your_pdf_file_name.pdf>")
        print("Place the PDF inside a 'downloads' folder in the same directory as the script.\n")
    else:
        # Create 'downloads' directory if it doesn't exist to avoid errors
        if not os.path.exists("downloads"):
            os.makedirs("downloads")
            print("Created a 'downloads' directory. Please place your PDF inside it and run again.")
            sys.exit()
        main(sys.argv[1])