# toc_extractor.py

import os
import fitz  # PyMuPDF
import re
import json
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
import google.generativeai as genai

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file.")
genai.configure(api_key=GOOGLE_API_KEY)

def _extract_toc_with_llm(text: str) -> List[tuple]:
    """
    Uses Gemini to find and parse a table of contents from raw text.
    """
    try:
        response = genai.GenerativeModel('gemini-1.5-flash').generate_content(
            f"""You are an expert document parser. Below is the raw text from the first few pages of a PDF.
            Your task is to identify the Table of Contents. It might be titled "Table of Contents", "Contents", "Index", "Inside the Report", or other variations.
            
            From this section, extract EVERY item that has a page number. This includes main sections and any sub-sections listed. Ensure you extract every single line item exactly as it appears.
            
            Return the result as a clean JSON array of objects. Each object must have a "title" and a "page" key.
            If no Table of Contents can be found in the text, you MUST return an empty JSON array `[]`.

            Example of a perfect response:
            ```json
            [
              {{"title": "Corporate Overview", "page": 4}},
              {{"title": "Chairman's Message", "page": 6}}
            ]
            ```

            RAW TEXT TO PARSE:
            ---
            {text}
            ---
            """
        )
        
        json_match = re.search(r'```json\s*(\[.*\])\s*```|(\[.*\])', response.text, re.DOTALL)
        if json_match:
            json_str = next(group for group in json_match.groups() if group is not None)
            toc_json = json.loads(json_str)
            return [(1, item['title'], int(item['page']), None) for item in toc_json]
    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"LLM TOC Extraction failed: {e}")
    
    return []

def _create_sanity_checked_page_map(doc: fitz.Document) -> Dict[int, int]:
    """
    Creates a highly accurate map of printed pages to physical indices by using
    a coordinate-based search with a plausibility "sanity check".
    """
    direct_map = {}
    for i in range(doc.page_count):
        page = doc.load_page(i)
        page_height = page.rect.height
        
        blocks = page.get_text("dict")["blocks"]
        
        potential_page_numbers = []
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        is_in_lower_part = span["bbox"][3] > page_height * 0.75
                        if is_in_lower_part:
                            text = span["text"].strip()
                            if text.isdigit():
                                page_num = int(text)
                                if 0 < page_num <= doc.page_count + 50:
                                    potential_page_numbers.append(page_num)

        if not potential_page_numbers:
            continue

        for page_num in potential_page_numbers:
            if abs(page_num - (i + 1)) < 50:
                if page_num not in direct_map:
                    direct_map[page_num] = i
                
    return direct_map


def get_toc_data(pdf_path: str) -> Optional[Dict[str, Any]]:
    """
    Orchestrates TOC extraction using fuzzy page lookups for resilience.
    """
    if not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        
        print("Step 1: Deploying LLM to extract raw Table of Contents...")
        first_pages_text = ""
        for i in range(min(15, doc.page_count)):
            page = doc.load_page(i)
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (b[1], b[0]))
            for block in blocks:
                first_pages_text += block[4]

        toc_title = "Unknown"
        toc_title_match = re.search(r'(Table of Contents|Contents of Table|Inside the Report|Across the pages|Contents|What\'s inside|Index)', first_pages_text, re.IGNORECASE)
        if toc_title_match:
            toc_title = toc_title_match.group(0).strip()

        raw_toc = _extract_toc_with_llm(first_pages_text)
        
        if raw_toc:
            unique_toc, seen = [], set()
            for entry in raw_toc:
                key = (entry[1].strip(), entry[2])
                if key not in seen:
                    unique_toc.append(entry)
                    seen.add(key)
            if len(unique_toc) < len(raw_toc):
                print(f"Removed {len(raw_toc) - len(unique_toc)} duplicate entries.")
            raw_toc = unique_toc

        if not raw_toc:
            print("LLM Parser did not find a valid Table of Contents.")
            return {"toc_title": toc_title, "raw_toc": [], "page_number_map": {}, "final_toc": []}

        raw_toc.sort(key=lambda x: x[2])
        
        print("Step 2: Building a sanity-checked map of physical pages...")
        page_number_map = _create_sanity_checked_page_map(doc)
        
        if not page_number_map:
            print("Error: Could not detect any plausible page numbers in the document.")
            return {"toc_title": toc_title, "raw_toc": raw_toc, "page_number_map": {}, "final_toc": []}

        print("Step 3: Validating TOC entries against the map with fuzzy lookup...")
        final_toc = []
        for i in range(len(raw_toc)):
            _level, title, printed_start_page, _ = raw_toc[i]
            
            start_page_index = page_number_map.get(printed_start_page)
            
            # --- FUZZY LOOKUP LOGIC ---
            # If the exact page isn't found, search for the next few pages.
            if start_page_index is None:
                for offset in range(1, 4): # Look ahead up to 3 pages
                    next_page_to_try = printed_start_page + offset
                    start_page_index = page_number_map.get(next_page_to_try)
                    if start_page_index is not None:
                        print(f"  -> Note: Page {printed_start_page} not found for '{title}'. Using next available page {next_page_to_try} instead.")
                        break
            # --------------------------

            if start_page_index is None:
                continue
            
            end_page_index = doc.page_count - 1
            if i + 1 < len(raw_toc):
                next_printed_page = raw_toc[i+1][2]
                next_start_page_index = page_number_map.get(next_printed_page)
                # Also apply fuzzy lookup for the end page calculation
                if next_start_page_index is None:
                    for offset in range(1, 4):
                        next_page_to_try = next_printed_page + offset
                        next_start_page_index = page_number_map.get(next_page_to_try)
                        if next_start_page_index is not None:
                            break
                
                if next_start_page_index is not None:
                    end_page_index = max(start_page_index, next_start_page_index - 1)
            
            if start_page_index > end_page_index:
                end_page_index = start_page_index
            
            final_toc.append({'title': title, 'start': start_page_index, 'end': end_page_index})
        
        return {
            "toc_title": toc_title,
            "raw_toc": raw_toc,
            "page_number_map": page_number_map,
            "final_toc": final_toc
        }
    
    except Exception as e:
        print(f"An unexpected error occurred during TOC extraction: {e}")
        return None