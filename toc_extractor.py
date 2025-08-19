# toc_extractor.py

import os
import fitz  # PyMuPDF
import re
import json
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional, Tuple
import google.generativeai as genai

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file.")
genai.configure(api_key=GOOGLE_API_KEY)

def _extract_toc_with_llm(text: str) -> List[tuple]:
    """
    Uses Gemini to find and parse a hierarchical table of contents from raw text.
    It now identifies main sections (level 1) and sub-sections (level 2).
    """
    try:
        # This prompt is specifically designed to understand and extract hierarchical TOCs.
        response = genai.GenerativeModel('gemini-2.5-flash').generate_content(
             f"""You are an expert document parser. Below is the raw text from the first few pages of a PDF.
            Your task is to identify the Table of Contents. It might be titled "Table of Contents", "Contents of table", "Contents", "Index", "Inside the Report", "Across the pages","What's inside", or other variations.
            
            The TOC may have a hierarchy:
            1. Main sections (e.g., "Corporate Overview 2-21", "Statutory Reports 22-97").
            2. Sub-sections under each main section (e.g., "Cupid At a Glance 4", "Product Portfolio 8").

            Your task is to extract EVERY entry, both main and sub-sections.
            Return the result as a clean JSON array of objects. Each object must have:
            - "level": 1 for a main section, 2 for a sub-section. If there is no clear hierarchy, use level 1 for all.
            - "title": The title of the section.
            - "page": The starting page number.

            Example of a perfect response for a hierarchical format:
            ```json
            [
              {{ "level": 1, "title": "Corporate Overview", "page": 2 }},
              {{ "level": 2, "title": "Cupid At a Glance", "page": 4 }},
              {{ "level": 1, "title": "Statutory Reports", "page": 22 }}
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
            return [
                (item.get('level', 1), item['title'], int(item['page']))
                for item in toc_json
                if item.get('page') is not None
            ]
    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"LLM TOC Extraction failed: {e}")
    
    return []

def _is_roman_numeral(s: str) -> bool:
    """Checks if a string is a valid Roman numeral (up to 39)."""
    return bool(re.match(r'^(x{0,3})(i[vx]|v?i{0,3})$', s, re.IGNORECASE))

def _roman_to_int(s: str) -> int:
    """Converts a Roman numeral string to an integer."""
    roman_map = {'I': 1, 'V': 5, 'X': 10}
    s = s.upper()
    i = 0
    num = 0
    while i < len(s):
        if i + 1 < len(s) and roman_map[s[i]] < roman_map[s[i+1]]:
            num += roman_map[s[i+1]] - roman_map[s[i]]
            i += 2
        else:
            num += roman_map[s[i]]
            i += 1
    return num

def _create_sanity_checked_page_map(doc: fitz.Document) -> Dict[int, int]:
    """
    Creates a highly accurate map of printed pages to physical indices.
    - Handles both Arabic and Roman numerals.
    - Searches only in typical header/footer areas.
    - Uses a smarter heuristic to select the most plausible page number.
    """
    page_map = {}
    total_pages = doc.page_count
    for i in range(total_pages):
        page = doc.load_page(i)
        page_height = page.rect.height
        
        words = page.get_text("words")
        
        candidate_numbers = []
        # Search in the top 15% (header) and bottom 15% (footer) of the page
        for word in words:
            _x0, y0, _x1, y1, text, _block_no, _line_no, _word_no = word
            is_in_header_footer = y1 < page_height * 0.15 or y0 > page_height * 0.85
            
            if is_in_header_footer:
                page_num = -1
                if text.isdigit():
                    page_num = int(text)
                elif _is_roman_numeral(text):
                    page_num = _roman_to_int(text)
                
                # Stricter sanity check: Page number must be plausible
                if 0 < page_num <= total_pages + 20 and abs(page_num - (i + 1)) < 50:
                    candidate_numbers.append(page_num)

        if candidate_numbers:
            # Smarter selection: Choose the number closest to the physical page index
            best_candidate = min(candidate_numbers, key=lambda x: abs(x - (i + 1)))
            if best_candidate not in page_map:
                page_map[best_candidate] = i
                
    return page_map

def _find_toc_page_text(doc: fitz.Document) -> Tuple[Optional[str], str]:
    """
    Scans the first 40 pages to find the Table of Contents and returns its text.
    This version is robust against out-of-order text extraction and character variations.
    """
    print("Searching for the Table of Contents page...")

    # Define sets of keywords for each potential TOC title with robust patterns
    toc_titles_keywords = {
        "Table of Contents": [re.compile(r'table', re.IGNORECASE), re.compile(r'contents', re.IGNORECASE)],
        "Across the pages": [re.compile(r'Across', re.IGNORECASE), re.compile(r'pages', re.IGNORECASE)],
        "Contents": [re.compile(r'contents', re.IGNORECASE)],
        "Index": [re.compile(r'index', re.IGNORECASE)],
        "Inside the Report": [re.compile(r'inside', re.IGNORECASE), re.compile(r'report', re.IGNORECASE)],
        "What's inside": [re.compile(r"what[\u2019']s\s+inside", re.IGNORECASE)],
    }

    # Scan the first 40 pages
    for i in range(min(40, doc.page_count)):
        page = doc.load_page(i)
        text = page.get_text()

        found_title = None
        # Check if all keywords for any TOC title are present on the page
        for title, keywords in toc_titles_keywords.items():
            if all(keyword.search(text) for keyword in keywords):
                found_title = title
                break

        if found_title:
            print(f"Found TOC keyword(s) for '{found_title}' on physical page {i+1}.")
            
            toc_text_blocks = page.get_text("blocks")
            toc_text_blocks.sort(key=lambda b: (b[1], b[0]))
            full_toc_text = "\n".join([block[4] for block in toc_text_blocks])

            if i + 1 < doc.page_count:
                next_page_blocks = doc.load_page(i + 1).get_text("blocks")
                next_page_blocks.sort(key=lambda b: (b[1], b[0]))
                full_toc_text += "\n" + "\n".join([block[4] for block in next_page_blocks])

            return full_toc_text, found_title

    return None, "Unknown"

def get_toc_data(pdf_path: str) -> Optional[Dict[str, Any]]:
    """
    Orchestrates TOC extraction with a dynamic TOC search and hierarchical parsing.
    """
    if not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        
        toc_text, toc_title = _find_toc_page_text(doc)

        if not toc_text:
            print("Could not locate a Table of Contents page within the first 40 pages.")
            return {"toc_title": "Unknown", "raw_toc": [], "page_number_map": {}, "final_toc": []}

        print("Step 1b: Deploying LLM to extract hierarchical Table of Contents...")
        raw_toc = _extract_toc_with_llm(toc_text)
        
        if not raw_toc:
            print("LLM Parser did not find a valid Table of Contents from the located page.")
            return {"toc_title": toc_title, "raw_toc": [], "page_number_map": {}, "final_toc": []}

        raw_toc.sort(key=lambda x: x[2])
        
        print("Step 2: Building a sanity-checked map of physical pages...")
        page_number_map = _create_sanity_checked_page_map(doc)
        
        if not page_number_map:
            print("Error: Could not detect any plausible page numbers in the document.")
            return {"toc_title": toc_title, "raw_toc": raw_toc, "page_number_map": {}, "final_toc": []}

        print("Step 3: Validating TOC entries using hierarchy-aware logic...")
        final_toc = []
        for i in range(len(raw_toc)):
            _level, title, printed_start_page = raw_toc[i]
            
            start_page_index = page_number_map.get(printed_start_page)
            if start_page_index is None: # Fuzzy lookup
                for offset in [1, -1, 2]: # Check +1, -1, +2 pages
                    start_page_index = page_number_map.get(printed_start_page + offset)
                    if start_page_index is not None: break
            
            if start_page_index is None:
                print(f"  -> Skipping '{title}' (p. {printed_start_page}) - could not find its physical page.")
                continue

            end_page_index = doc.page_count - 1
            
            if i + 1 < len(raw_toc):
                _next_level, _next_title, next_printed_page = raw_toc[i+1]
                next_start_page_index = page_number_map.get(next_printed_page)
                
                if next_start_page_index is None: # Fuzzy lookup for the next item
                     for offset in [1, -1, 2]:
                        next_start_page_index = page_number_map.get(next_printed_page + offset)
                        if next_start_page_index is not None: break
                
                if next_start_page_index is not None and next_start_page_index > start_page_index:
                    end_page_index = next_start_page_index - 1
                else:
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