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
        response = genai.GenerativeModel('gemini-1.5-flash').generate_content(
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
            return [(item.get('level', 1), item['title'], int(item['page'])) for item in toc_json]
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
        
        footer_numbers = []
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
                                    footer_numbers.append(page_num)
        
        if not footer_numbers:
            continue

        for page_num in footer_numbers:
            if abs(page_num - (i + 1)) < 50:
                if page_num not in direct_map:
                    direct_map[page_num] = i
                
    return direct_map

def _find_toc_page_text(doc: fitz.Document) -> Tuple[Optional[str], str]:
    """
    Scans the first 40 pages to find the Table of Contents and returns its text.
    """
    print("Searching for the Table of Contents page...")
    toc_pattern = re.compile(r'\b(contents|index|table of contents)\b', re.IGNORECASE)
    
    # Scan the first 40 pages, which is a safe upper limit for most reports
    for i in range(min(40, doc.page_count)):
        page = doc.load_page(i)
        text = page.get_text()
        
        match = toc_pattern.search(text)
        if match:
            print(f"Found TOC keyword '{match.group(0)}' on physical page {i+1}.")
            # Extract text from this page and the next one in case it spans multiple pages
            toc_text = page.get_text("blocks")
            toc_text.sort(key=lambda b: (b[1], b[0]))
            
            full_toc_text = "\n".join([block[4] for block in toc_text])

            if i + 1 < doc.page_count:
                next_page_blocks = doc.load_page(i + 1).get_text("blocks")
                next_page_blocks.sort(key=lambda b: (b[1], b[0]))
                full_toc_text += "\n" + "\n".join([block[4] for block in next_page_blocks])

            return full_toc_text, match.group(0).strip()
            
    return None, "Unknown"


def get_toc_data(pdf_path: str) -> Optional[Dict[str, Any]]:
    """
    Orchestrates TOC extraction with a dynamic TOC search and hierarchical parsing.
    """
    if not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        
        # Step 1: Intelligently find the TOC text instead of assuming it's in the first 15 pages.
        toc_text, toc_title = _find_toc_page_text(doc)

        if not toc_text:
            print("Could not locate a Table of Contents page within the first 40 pages.")
            return {"toc_title": "Unknown", "raw_toc": [], "page_number_map": {}, "final_toc": []}

        print("Step 1b: Deploying LLM to extract hierarchical Table of Contents...")
        raw_toc = _extract_toc_with_llm(toc_text)
        
        if not raw_toc:
            print("LLM Parser did not find a valid Table of Contents from the located page.")
            return {"toc_title": toc_title, "raw_toc": [], "page_number_map": {}, "final_toc": []}

        raw_toc.sort(key=lambda x: x[2]) # Sort by page number
        
        print("Step 2: Building a sanity-checked map of physical pages...")
        page_number_map = _create_sanity_checked_page_map(doc)
        
        if not page_number_map:
            print("Error: Could not detect any plausible page numbers in the document.")
            return {"toc_title": toc_title, "raw_toc": raw_toc, "page_number_map": {}, "final_toc": []}

        print("Step 3: Validating TOC entries using hierarchy-aware logic...")
        final_toc = []
        for i in range(len(raw_toc)):
            level, title, printed_start_page = raw_toc[i]
            
            start_page_index = page_number_map.get(printed_start_page)
            if start_page_index is None: # Fuzzy lookup
                for offset in range(1, 4):
                    start_page_index = page_number_map.get(printed_start_page + offset)
                    if start_page_index is not None: break
            
            if start_page_index is None: continue

            end_page_index = doc.page_count - 1
            # Find the next item at the same or a higher level to determine the end page
            for j in range(i + 1, len(raw_toc)):
                next_level, _next_title, next_printed_page = raw_toc[j]
                if next_level <= level:
                    next_start_page_index = page_number_map.get(next_printed_page)
                    if next_start_page_index is None: # Fuzzy lookup
                        for offset in range(1, 4):
                            next_start_page_index = page_number_map.get(next_printed_page + offset)
                            if next_start_page_index is not None: break
                    
                    if next_start_page_index is not None:
                        end_page_index = max(start_page_index, next_start_page_index - 1)
                    break 
            
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