# run_toc_extractor.py

import sys
import os
from toc_extractor import get_toc_data

def main(file_name: str):
    """
    Runs the TOC extraction process and displays detailed debugging information.
    """
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
    page_number_map = toc_result.get('page_number_map', {})
    final_toc = toc_result.get('final_toc', [])
    
    if not final_toc:
        print("\n--- ‼️ TOC Extraction Failed ---")
        print(f"Detected TOC Title: '{toc_title}'")
        print("Could not generate a valid, mapped Table of Contents from the document.")
        # Also print the map for debugging
        if page_number_map:
            print("\n--- 🗺️ Generated Page Map (Debug Sample) ---")
            map_items = list(sorted(page_number_map.items()))
            for p_page, p_index in map_items[:15]:
                print(f"  - Printed page '{p_page}' -> Physical page {p_index + 1} (Index: {p_index})")
        print("---------------------------------\n")
        return
        
    print("\n--- ✅ TOC Extraction Succeeded ---")
    print(f"Detected TOC Title: '{toc_title}'")
    print(f"AI Parser identified {len(raw_toc)} unique sections.")
    print(f"Page mapping created with {len(page_number_map)} entries.")

    print("\n--- 🤖 Raw TOC from LLM (Sorted & Unique) ---")
    for item in raw_toc:
        print(f"  - Title: '{item[1]}', Printed Page: {item[2]}")
    
    print("\n--- 🗺️ Generated Page Map (Sample) ---")
    # Sort the map by physical index for a more intuitive display
    map_items = list(sorted(page_number_map.items(), key=lambda item: item[1]))
    if len(map_items) > 10:
        for p_page, p_index in map_items[:5]:
            print(f"  - Printed page '{p_page}' -> Physical page {p_index + 1} (Index: {p_index})")
        print("  ...")
        for p_page, p_index in map_items[-5:]:
            print(f"  - Printed page '{p_page}' -> Physical page {p_index + 1} (Index: {p_index})")
    else:
        for p_page, p_index in map_items:
            print(f"  - Printed page '{p_page}' -> Physical page {p_index + 1} (Index: {p_index})")

    print("\n--- 📖 Final Validated TOC Entries ---")
    print(f"Validated and refined {len(final_toc)} of {len(raw_toc)} sections.")
    
    raw_titles = {item[1] for item in raw_toc}
    final_titles = {item['title'] for item in final_toc}
    skipped_titles = raw_titles - final_titles
    
    for item in final_toc:
        start_page = item['start'] + 1
        end_page = item['end'] + 1
        print(f"  - Title: '{item['title']}'")
        print(f"    Physical Page Range: {start_page} to {end_page} (Indices: {item['start']}-{item['end']})")
    
    if skipped_titles:
        print("\n--- ⚠️ Skipped Sections ---")
        print("The following sections were skipped because their page numbers could not be found in the map:")
        for title in sorted(list(skipped_titles)):
             # Find the printed page for the skipped title for better debug info
             printed_page = next((p for l,t,p,_ in raw_toc if t == title), "N/A")
             print(f"  - {title} (Printed Page: {printed_page})")
    
    print("-------------------------------------------\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUsage: python run_toc_extractor.py <your_pdf_file_name.pdf>")
        print("Place the PDF inside the 'downloads' folder.\n")
    else:
        main(sys.argv[1])