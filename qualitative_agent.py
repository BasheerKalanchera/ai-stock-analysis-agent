import os
import fitz  # PyMuPDF
import re
import json
from dotenv import load_dotenv

from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.chains.summarize import load_summarize_chain
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import google.generativeai as genai

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file.")
genai.configure(api_key=GOOGLE_API_KEY)

def _get_page_number_map(doc: fitz.Document) -> dict:
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
        print("Warning: No printed page numbers found. Using a simple linear map.")
        return {p + 1: p for p in range(doc.page_count)}

    first_printed_page = -1
    first_physical_index = -1
    
    # Find a valid starting point for the mapping.
    for p_num in sorted_printed_pages:
        if p_num > 0 and p_num in page_map:
            first_printed_page = p_num
            first_physical_index = page_map[p_num]
            break
    
    if first_printed_page != -1:
        # Calculate the offset more accurately.
        offset = first_physical_index - (first_printed_page - 1)
        
        # Create a complete map using this offset.
        for p_num in range(1, doc.page_count + 1):
            mapped_index = p_num + offset
            if 0 <= mapped_index < doc.page_count:
                final_page_map[p_num] = mapped_index
        
        print(f"Robust page map created with offset {offset} from page {first_printed_page}. Total entries: {len(final_page_map)}.")
        return final_page_map
    
    print("Warning: Robust page number mapping failed, using a simple linear map as fallback.")
    return {p + 1: p for p in range(doc.page_count)}

def _extract_toc_with_llm(text: str) -> list:
    """Uses Gemini to find and parse a table of contents from raw text, including sub-sections."""
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"""
    You are an expert document parser. Below is the raw text from the first few pages of an annual report.
    Extract ALL sections and sub-sections from the Table of Contents, which might be labeled "Table of Contents" or "Index".
    For each section or sub-section, provide its title and the corresponding start page number. The end page is not required.
    Focus on extracting every item that has a page number associated with it.
    Return the result as a clean JSON array of objects.
    Example format: [\{{"title": "Corporate Overview", "page": 4}}, \{{ "title": "Chairman's Message", "page": 6}}]

    RAW TEXT:
    ---
    {text}
    ---
    """
    try:
        response = model.generate_content(prompt)
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if json_match:
            toc_json = json.loads(json_match.group(0))
            return [(1, item['title'], item['page'], None) for item in toc_json]
    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"LLM TOC Extraction failed: {e}")
    return []

def process_annual_report(pdf_path: str):
    if not os.path.exists(pdf_path): return None
    try:
        print(f"Starting advanced processing for: {pdf_path}")
        doc = fitz.open(pdf_path)
        
        full_text = ""
        for page in doc:
            full_text += page.get_text("text") + "\n"

        print("Preprocessing: Creating a page number to index map...")
        page_number_map = _get_page_number_map(doc)
        print(f"Page map created with {len(page_number_map)} entries.")

        print("Deploying LLM Parser Agent to find Table of Contents...")
        
        first_15_pages_text = ""
        for i in range(min(15, len(doc))):
            page = doc.load_page(i)
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (b[1], b[0]))
            for block in blocks:
                first_15_pages_text += block[4] + "\n"

        toc = _extract_toc_with_llm(first_15_pages_text)

        toc_titles, section_map, full_text_docs = [], {}, []
        
        if toc and page_number_map:
            toc.sort(key=lambda x: x[2])
            print(f"AI Parser identified and sorted {len(toc)} sections.")

            final_toc = []
            for i in range(len(toc)):
                level, title, printed_start_page, _ = toc[i]
                
                start_page_index = page_number_map.get(printed_start_page)
                if start_page_index is None:
                    print(f"Warning: Could not find physical page for printed page {printed_start_page}. Skipping section '{title}'.")
                    continue
                
                end_page_index = doc.page_count - 1
                if i + 1 < len(toc):
                    next_printed_page = toc[i+1][2]
                    next_start_page_index = page_number_map.get(next_printed_page)
                    if next_start_page_index is not None:
                        end_page_index = next_start_page_index - 1
                
                if start_page_index > end_page_index:
                    print(f"Warning: Invalid page range for '{title}'. Skipping.")
                    continue
                
                final_toc.append({'title': title, 'start': start_page_index, 'end': end_page_index})
            
            if not final_toc:
                print("Warning: No valid sections could be mapped from the TOC. Falling back to full-document analysis.")
                full_text_docs.append(Document(page_content=full_text))
            else:
                print(f"Refined {len(final_toc)} section boundaries.")

                print("\n--- DEBUG: Final TOC with physical page indices ---")
                for item in final_toc:
                    print(f"Title: '{item['title']}', Start Index: {item['start']}, End Index: {item['end']}")
                print("---------------------------------------------------\n")

                for i, item in enumerate(final_toc):
                    title = item['title'].strip()
                    start_page = item['start']
                    end_page = item['end']
                    
                    if not title:
                        continue
                    
                    if i < 3 or 'management discussion' in title.lower():
                        print(f"\n--- DEBUG: Extracting text for '{title}' from physical page {start_page} to {end_page} ---")
                        
                    section_text = ""
                    for p in range(start_page, end_page + 1):
                        if 0 <= p < len(doc):
                            section_text += doc.load_page(p).get_text("text") + "\n"
                    
                    if len(section_text) < 100:
                        continue
                    
                    if i < 3 or 'management discussion' in title.lower():
                        print(f"--- DEBUG: First 500 characters of extracted text for '{title}':\n{section_text[:500]}...\n---")

                    toc_titles.append(title)
                    section_map[title] = section_text
                    full_text_docs.append(Document(page_content=section_text, metadata={"source": title}))
            
            print(f"Successfully created a clean Section Map with {len(toc_titles)} validated entries.")
        else:
            print("Warning: No valid TOC or page map found. Falling back to full-document analysis.")
            full_text_docs.append(Document(page_content=full_text))

        if toc_titles:
            print("\n--- FINAL CLEAN TOC ENTRIES ---")
            for i, title in enumerate(toc_titles):
                print(f"{i+1}: {title}")
            print("-----------------------------\n")
        else:
            print("No TOC entries found. Proceeding with full document analysis.")

        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GOOGLE_API_KEY)
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=5000, chunk_overlap=500)
        
        if not full_text_docs:
            print("Error: No documents to process. Cannot create vector store.")
            return None

        chunks = text_splitter.split_documents(full_text_docs)
        main_vector_store = FAISS.from_documents(documents=chunks, embedding=embeddings)
        print("Created main vector store for document content.")
        
        toc_vector_store = FAISS.from_texts(texts=toc_titles, embedding=embeddings) if toc_titles else None
        if toc_vector_store: print("Created TOC vector store for semantic routing.")

        return {
            "section_map": section_map,
            "main_vector_store": main_vector_store,
            "toc_vector_store": toc_vector_store
        }
    except Exception as e:
        print(f"An error occurred during PDF processing: {e}")
        return None

def answer_qualitative_question(report_data: dict, question: str) -> str:
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2, google_api_key=GOOGLE_API_KEY)
    question_lower = question.lower().strip()
    
    if report_data.get("toc_vector_store"):
        toc_vector_store = report_data['toc_vector_store']
        results_with_scores = toc_vector_store.similarity_search_with_score(question, k=1)
        
        if results_with_scores:
            best_match_title_doc, score = results_with_scores[0]
            if score < 1.2:
                matched_section_title = best_match_title_doc.page_content
                matched_section_text = report_data['section_map'].get(matched_section_title)
                
                if matched_section_text:
                    if "summarize" in question_lower or "summary" in question_lower:
                        print(f"Strategy: On-demand summarization for section '{matched_section_title}'.")
                        chain = load_summarize_chain(llm, chain_type="stuff")
                        docs = [Document(page_content=matched_section_text)]
                        summary = chain.invoke(docs)
                        return summary.get('output_text', "Could not generate summary.")
                    else:
                        print(f"Strategy: Direct section retrieval for '{matched_section_title}'.")
                        return f"**Successfully retrieved the full text for the '{matched_section_title.title()}' section.**\n\n{matched_section_text[:2000]}...\n\n*This section is long. To get a concise overview, please ask to 'summarize this section'.*"

    print("Strategy: Semantic Q&A on main document (no strong TOC match found).")
    main_vector_store = report_data.get('main_vector_store')
    if not main_vector_store: return "Error: Main vector store is not available."

    prompt_template = "You are an expert financial analyst. Answer based ONLY on the provided context. If the information is not in the context, state that clearly.\n\nCONTEXT:\n{context}\n\nQUESTION:\n{question}\n\nANSWER:"
    PROMPT = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm, chain_type="stuff",
        retriever=main_vector_store.as_retriever(search_type="similarity", search_kwargs={"k": 5}),
        chain_type_kwargs={"prompt": PROMPT}
    )
    result = qa_chain.invoke({"query": question})
    return result['result']