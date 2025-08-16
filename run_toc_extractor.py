# run_toc_extractor.py

import sys
import os
import fitz
import re
import json
from toc_extractor import get_toc_data
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

# Ensure the required environment variables are loaded
load_dotenv()

def main(file_name: str):
    """
    This script runs the TOC extraction and validation process on a specified PDF file and
    displays detailed debugging information.
    """
    downloads_dir = os.path.join(os.getcwd(), "downloads")
    pdf_path = os.path.join(downloads_dir, file_name)

    if not os.path.exists(pdf_path):
        print(f"Error: The file '{pdf_path}' was not found.")
        return

    print(f"Starting TOC extraction for: {file_name}")
    
    try:
        doc = fitz.open(pdf_path)
        
        toc_result = get_toc_data(pdf_path)

        if not toc_result:
            print("\n--- TOC Extraction Failed ---")
            print("No valid Table of Contents was found or an error occurred.")
            return

        raw_toc = toc_result.get('raw_toc')
        page_number_map = toc_result.get('page_number_map')
        
        # This part of the code was causing the 'doc' not defined error
        # Re-implementing the validation and refinement logic here
        final_toc = []
        if raw_toc and page_number_map:
            print("\n--- TOC Extraction Succeeded ---")
            print(f"AI Parser identified and sorted {len(raw_toc)} sections.")
            print(f"Page mapping created with {len(page_number_map)} entries.")

            # Display raw TOC from LLM
            print("\nRaw TOC from LLM (Initial Extraction):")
            for item in raw_toc:
                print(f"  - Title: '{item[1]}', Printed Page: {item[2]}")

            # Display the page map
            print("\nGenerated Page Map (First 10 entries for brevity):")
            for printed_page, physical_index in list(page_number_map.items())[:10]:
                print(f"  - Printed page {printed_page} maps to physical index {physical_index}")
            if len(page_number_map) > 10:
                print("  ...")
            
            # This is the section that validates and refines the TOC
            for i in range(len(raw_toc)):
                level, title, printed_start_page, _ = raw_toc[i]
                
                # Check for an exact match for the printed page number in the generated map
                start_page_index = page_number_map.get(printed_start_page)
                
                if start_page_index is None:
                    print(f"Skipping section '{title}' (Printed Page: {printed_start_page}) because no physical page index was found.")
                    continue
                
                end_page_index = doc.page_count - 1
                if i + 1 < len(raw_toc):
                    next_printed_page = raw_toc[i+1][2]
                    next_start_page_index = page_number_map.get(next_printed_page)
                    if next_start_page_index is not None:
                        end_page_index = next_start_page_index - 1
                
                if start_page_index > end_page_index:
                    print(f"Skipping section '{title}' (Printed Page: {printed_start_page}) because of invalid page range (Start: {start_page_index}, End: {end_page_index}).")
                    continue
                
                final_toc.append({'title': title, 'start': start_page_index, 'end': end_page_index})
        
            print(f"\nRefined {len(final_toc)} section boundaries after validation.")
            print("--- FINAL TOC with Physical Page Indices ---")
            for item in final_toc:
                print(f"  - Title: '{item['title']}', Start Index: {item['start']}, End Index: {item['end']}")
            print("-------------------------------------------\n")

            toc_titles = [item['title'] for item in final_toc]
            if toc_titles:
                print("--- FINAL VALIDATED TOC ENTRIES ---")
                for i, title in enumerate(toc_titles):
                    print(f"{i+1}: {title}")
                print("-----------------------------------\n")

        else:
            print("\n--- TOC Extraction Failed ---")
            print("No valid Table of Contents was found by the LLM parser.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_toc_extractor.py <pdf_file_name>")
    else:
        main(sys.argv[1])