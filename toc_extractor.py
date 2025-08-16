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
    Uses Gemini to find and parse a table of contents from raw text,
    with a flexible prompt to handle various titles and formats.
    """
    toc_title = ""
    for line in text.splitlines():
        if re.search(r'Table of Contents|Contents of Table|Inside the Report|Across the pages|Contents|What\'s inside|Index', line, re.IGNORECASE):
            toc_title = line.strip()
            print(f"Detected TOC title: '{toc_title}'")
            break

    try:
        response = genai.GenerativeModel('gemini-2.5-flash').generate_content(
            f"""You are an expert document parser. Below is the raw text from the first few pages of an annual report.
            Identify the section that lists the main report sections and their starting page numbers. This might be titled "Table of Contents", "Contents of Table", "Inside the Report", "Across the pages", "Contents", "What's inside", or "Index".
            If a Table of Contents is not found, return an empty JSON array.
            
            Extract ALL sections and sub-sections from this list. For each section, provide its title and the corresponding start page number. The end page is not required.
            Focus on extracting every item that has a page number associated with it.
            Return the result as a clean JSON array of objects.
            Example format: [\{{"title": "Corporate Overview", "page": 4}}, \{{ "title": "Chairman's Message", "page": 6}}]

            RAW TEXT:
            ---
            {text}
            ---
            """
        )
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if json_match:
            toc_json = json.loads(json_match.group(0))
            return [(1, item['title'], item['page'], None) for item in toc_json]
    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"LLM TOC Extraction failed: {e}")
    return []

def _get_page_number_map(doc: fitz.Document) -> Dict[int, int]:
    """
    Creates a robust mapping from printed page numbers to physical page indices.
    This version is more resilient to inconsistent page numbers and
    accurately handles unnumbered front matter.
    """
    page_map = {}
    for i in range(doc.page_count):
        page = doc.load_page(i)
        all_text = page.get_text().strip()
        matches = re.findall(r'\b(\d+)\b', all_text)
        
        if matches:
            potential_page_numbers = [int(m) for m in matches if int(m) <= doc.page_count + 50]
            if potential_page_numbers:
                page_number = max(potential_page_numbers)
                page_map[page_number] = i
    
    final_page_map = {}
    sorted_printed_pages = sorted(page_map.keys())

    if not sorted_printed_pages:
        return {} # Return empty dict instead of linear map

    first_printed_page = -1
    first_physical_index = -1
    
    for p_num in sorted_printed_pages:
        if p_num > 0 and p_num in page_map:
            first_printed_page = p_num
            first_physical_index = page_map[p_num]
            break
    
    if first_printed_page != -1:
        offset = first_physical_index - (first_printed_page - 1)
        for p_num in range(1, doc.page_count + 1):
            mapped_index = p_num + offset
            if 0 <= mapped_index < doc.page_count:
                final_page_map[p_num] = mapped_index
        
        print(f"Robust page map created with offset {offset} from page {first_printed_page}. Total entries: {len(final_page_map)}.")
        return final_page_map
    
    return {} # Return empty dict as a fallback

def get_toc_data(pdf_path: str) -> Optional[Dict[str, Any]]:
    """
    Main function to orchestrate TOC extraction.
    Returns a dictionary with raw_toc, page_number_map, and final_toc.
    """
    if not os.path.exists(pdf_path):
        return None
    try:
        doc = fitz.open(pdf_path)
        
        print("Deploying LLM Parser Agent to find Table of Contents...")
        first_15_pages_text = ""
        for i in range(min(15, len(doc))):
            page = doc.load_page(i)
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (b[1], b[0]))
            for block in blocks:
                first_15_pages_text += block[4] + "\n"

        raw_toc = _extract_toc_with_llm(first_15_pages_text)
        page_number_map = _get_page_number_map(doc)
        final_toc = []

        if raw_toc and page_number_map:
            raw_toc.sort(key=lambda x: x[2])
            
            for i in range(len(raw_toc)):
                level, title, printed_start_page, _ = raw_toc[i]
                
                start_page_index = page_number_map.get(printed_start_page)
                if start_page_index is None:
                    continue
                
                end_page_index = doc.page_count - 1
                if i + 1 < len(raw_toc):
                    next_printed_page = raw_toc[i+1][2]
                    next_start_page_index = page_number_map.get(next_printed_page)
                    if next_start_page_index is not None:
                        end_page_index = next_start_page_index - 1
                
                if start_page_index > end_page_index:
                    continue
                
                final_toc.append({'title': title, 'start': start_page_index, 'end': end_page_index})
        
        return {
            "raw_toc": raw_toc,
            "page_number_map": page_number_map,
            "final_toc": final_toc
        }
    
    except Exception as e:
        print(f"An error occurred during TOC extraction: {e}")
        return None