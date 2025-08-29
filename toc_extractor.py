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

def _extract_toc_with_llm(text_blocks_json: str) -> List[tuple]:
    """
    Uses Gemini to parse a hierarchical TOC from a JSON string of text blocks.
    Asks the model for JSON objects, one per line, for robust parsing.
    """
    try:
        # CORRECTED: Replaced all "smart quotes" with standard apostrophes
        prompt = f"""
        You are an expert document parser. Below is a JSON representation of text blocks from a PDF's Table of Contents page, sorted in a logical, column-by-column reading order. Each block includes text and coordinates.

        Your task is to be extremely thorough and extract every single entry from the Table of Contents. Use the coordinates to correctly associate titles with their page numbers.

        The TOC may have a hierarchy (e.g., a main section is level 1, and its sub-sections are level 2). Identify this hierarchy. Some main sections might not have a page number but act as headers for the items below them.

        Return the result as a series of JSON objects, with **one object per line**. Do NOT return a JSON array. Each object must have:
        - "level": 1 for a main section, 2 for a sub-section.
        - "title": The title of the section.
        - "page": The integer page number. If a main header has no page number, use the page number of the first sub-item under it.

        Example of a perfect response for a dense layout:
        {{ "level": 1, "title": "CORPORATE OVERVIEW", "page": 6 }}
        {{ "level": 2, "title": "KFINTECH AT A GLANCE", "page": 6 }}
        {{ "level": 2, "title": "CHAIRMAN'S REVIEW", "page": 10 }}
        {{ "level": 1, "title": "STATUTORY REPORTS", "page": 100 }}
        {{ "level": 2, "title": "Board's Report", "page": 118 }}


        TEXT BLOCKS TO PARSE:
        ---
        {text_blocks_json}
        ---
        """
        response = genai.GenerativeModel('gemini-2.0-flash').generate_content(prompt)
        
        toc_entries = []
        for line in response.text.strip().splitlines():
            try:
                json_match = re.search(r'\{.*\}', line)
                if json_match:
                    item = json.loads(json_match.group(0))
                    page = item.get('page')
                    if page is not None and isinstance(page, (int, str)) and str(page).isdigit() and int(page) > 0:
                        toc_entries.append((item.get('level', 1), item['title'], int(page)))
            except (json.JSONDecodeError, KeyError):
                continue
        return toc_entries
        
    except Exception as e:
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

def _create_sanity_checked_page_map(doc: fitz.Document, start_scan_from_page: int = 0) -> Dict[int, int]:
    """
    Creates a highly accurate map of printed pages to physical indices.
    This version uses more relaxed heuristics to be more robust.
    """
    page_map = {}
    total_pages = doc.page_count
    
    for i in range(start_scan_from_page, total_pages):
        page = doc.load_page(i)
        page_height = page.rect.height
        
        words = page.get_text("words")
        
        candidate_numbers = []
        for word in words:
            _x0, y0, _x1, y1, text, _block_no, _line_no, _word_no = word
            is_in_header_footer = y1 < page_height * 0.12 or y0 > page_height * 0.88
            
            if is_in_header_footer:
                page_num = -1
                clean_text = text.strip().strip("[]()")
                if clean_text.isdigit():
                    page_num = int(clean_text)
                elif _is_roman_numeral(clean_text):
                    page_num = _roman_to_int(clean_text)
                
                if 0 < page_num < total_pages + 100:
                    candidate_numbers.append(page_num)

        if candidate_numbers:
            best_candidate = max(set(candidate_numbers), key=candidate_numbers.count)
            if best_candidate not in page_map:
                page_map[best_candidate] = i
                
    return page_map

def _find_toc_page_text(doc: fitz.Document) -> Tuple[Optional[str], str, int]:
    """
    Scans pages to find the TOC. If found, it uses dynamic column detection
    and includes the next page to handle multi-page TOCs.
    """
    print("Searching for the Table of Contents page...")
    toc_titles_keywords = {
        "Table of Contents": [re.compile(r'table\s+of\s+contents', re.IGNORECASE)],
        "Across the pages": [re.compile(r'Across', re.IGNORECASE), re.compile(r'pages', re.IGNORECASE)],
        "Contents": [re.compile(r'\bcontents\b', re.IGNORECASE)],
        "Index": [re.compile(r'\bindex\b', re.IGNORECASE)],
        "Inside the Report": [re.compile(r'inside', re.IGNORECASE), re.compile(r'report', re.IGNORECASE)],
        "What's inside": [re.compile(r"what'?s\s+inside", re.IGNORECASE)],
    }

    for i in range(min(40, doc.page_count)):
        page = doc.load_page(i)
        text = page.get_text()
        found_title = None
        for title, keywords in toc_titles_keywords.items():
            if all(keyword.search(text) for keyword in keywords):
                found_title = title
                break
        if found_title:
            print(f"Found TOC keyword(s) for '{found_title}' on physical page {i+1}.")
            
            all_blocks = []
            
            def get_sorted_blocks_from_page(p: fitz.Page) -> List[Any]:
                blocks = p.get_text("blocks")
                sorted_blocks_for_page = []
                x_coords = sorted(list(set(round(b[0]) for b in blocks)))
                
                if x_coords:
                    column_starts = [x_coords[0]]
                    for j in range(1, len(x_coords)):
                        if x_coords[j] - x_coords[j-1] > 50:
                            column_starts.append(x_coords[j])
                    
                    if i == p.number:
                        print(f"--> Dynamically detected {len(column_starts)} columns starting at x-positions: {[round(cs) for cs in column_starts]}")

                    columns = [[] for _ in column_starts]
                    for block in blocks:
                        col_idx = min(range(len(column_starts)), key=lambda k: abs(block[0] - column_starts[k]))
                        columns[col_idx].append(block)

                    for col in columns:
                        col.sort(key=lambda b: b[1])
                        sorted_blocks_for_page.extend(col)
                return sorted_blocks_for_page

            all_blocks.extend(get_sorted_blocks_from_page(page))

            if i + 1 < doc.page_count:
                next_page = doc.load_page(i + 1)
                if len(next_page.get_text("blocks")) > 15:
                     print(f"Detected a multi-page TOC, including physical page {i+2}.")
                     all_blocks.extend(get_sorted_blocks_from_page(next_page))
            
            simplified_blocks = [{"box": [round(b[0]), round(b[1]), round(b[2]), round(b[3])], "text": b[4].replace('\n', ' ')} for b in all_blocks]
            
            return json.dumps(simplified_blocks, indent=2), found_title, i

    return None, "Unknown", -1

def get_toc_data(pdf_path: str) -> Optional[Dict[str, Any]]:
    """
    Orchestrates TOC extraction with a dynamic TOC search and hierarchical parsing.
    """
    if not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        
        toc_text, toc_title, toc_page_index = _find_toc_page_text(doc)

        if not toc_text:
            print("Could not locate a Table of Contents page within the first 40 pages.")
            return {"toc_title": "Unknown", "raw_toc": [], "page_number_map": {}, "final_toc": []}

        print("Step 1b: Deploying LLM to extract hierarchical Table of Contents...")
        raw_toc = _extract_toc_with_llm(toc_text)
        
        if not raw_toc:
            print("LLM Parser did not find a valid Table of Contents from the located page.")
            return {"toc_title": toc_title, "raw_toc": [], "page_number_map": {}, "final_toc": []}

        seen = set()
        unique_raw_toc = []
        for item in raw_toc:
            identifier = (item[1].strip(), item[2])
            if identifier not in seen:
                seen.add(identifier)
                unique_raw_toc.append(item)
        
        raw_toc = sorted(unique_raw_toc, key=lambda x: x[2])
        
        print("Step 2: Building a sanity-checked map of physical pages...")
        page_number_map = _create_sanity_checked_page_map(doc, start_scan_from_page=toc_page_index)
        
        if not page_number_map:
            print("Error: Could not detect any plausible page numbers in the document.")
            return {"toc_title": toc_title, "raw_toc": raw_toc, "page_number_map": {}, "final_toc": []}

        print("Step 3: Validating TOC entries using hierarchy-aware logic...")
        final_toc = []
        for i in range(len(raw_toc)):
            _level, title, printed_start_page = raw_toc[i]
            
            start_page_index = page_number_map.get(printed_start_page)
            if start_page_index is None:
                for offset in [1, -1, 2, -2]: 
                    start_page_index = page_number_map.get(printed_start_page + offset)
                    if start_page_index is not None: break
            
            if start_page_index is None:
                print(f"  -> Skipping '{title.strip()}' (p. {printed_start_page}) - could not find its physical page.")
                continue

            end_page_index = doc.page_count - 1
            
            next_item_start_index = -1
            for j in range(i + 1, len(raw_toc)):
                _next_level_search, _next_title_search, next_printed_page_search = raw_toc[j]
                next_start_page_index_search = page_number_map.get(next_printed_page_search)
                if next_start_page_index_search is None:
                    for offset in [1, -1, 2, -2]:
                        next_start_page_index_search = page_number_map.get(next_printed_page_search + offset)
                        if next_start_page_index_search is not None: break
                
                if next_start_page_index_search is not None:
                    next_item_start_index = next_start_page_index_search
                    break

            if next_item_start_index != -1 and next_item_start_index > start_page_index:
                end_page_index = next_item_start_index - 1
            elif next_item_start_index != -1:
                 end_page_index = start_page_index

            final_toc.append({'title': title.strip(), 'start': start_page_index, 'end': end_page_index})
        
        return {
            "toc_title": toc_title,
            "raw_toc": raw_toc,
            "page_number_map": page_number_map,
            "final_toc": final_toc
        }
    
    except Exception as e:
        print(f"An unexpected error occurred during TOC extraction: {e}")
        return None