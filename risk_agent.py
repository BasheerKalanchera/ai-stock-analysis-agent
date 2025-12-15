import os
import io
import logging
import time
import random
import re
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from pypdf import PdfReader  # Requires: pip install pypdf

# Setup Logger
logger = logging.getLogger('risk_agent')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - 🔴 RISK AGENT - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def generate_with_retry(model, prompt, max_retries=3, base_delay=30):
    """
    Helper to retry Gemini generation on rate limit errors.
    Defaults to a 30s wait which is safer for the Free Tier.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
            retry_seconds = base_delay 
            try:
                match = re.search(r'retry_delay.*seconds:\s*(\d+)', str(e), re.DOTALL | re.IGNORECASE)
                if match:
                    retry_seconds = int(match.group(1)) + 5 
            except:
                pass

            if retry_seconds == base_delay:
                retry_seconds = base_delay + random.uniform(1, 5)

            logger.warning(f"Generation (Attempt {attempt + 1}/{max_retries}) encountered rate limit - retry after {retry_seconds:.1f} seconds.")
            time.sleep(retry_seconds)
            
        except Exception as e:
            if "429" in str(e):
                retry_seconds = base_delay + random.uniform(1, 5)
                logger.warning(f"Generation (Attempt {attempt + 1}/{max_retries}) encountered generic 429 - retry after {retry_seconds:.1f} seconds.")
                time.sleep(retry_seconds)
            else:
                raise e
                
    raise Exception(f"Max retries ({max_retries}) exceeded. The API is too busy.")

def validate_pdf_header(file_buffer):
    """
    Simple check to ensure the file buffer actually starts with %PDF.
    Prevents crashes when the downloader returns an HTML error page instead of a PDF.
    """
    if not file_buffer:
        return False
    try:
        # Remember current position
        pos = file_buffer.tell()
        file_buffer.seek(0)
        header = file_buffer.read(4)
        # Reset position for the next reader
        file_buffer.seek(pos)
        
        # Check for standard PDF signature
        return header == b'%PDF'
    except Exception:
        return False

def extract_text_from_buffer(buffer, file_type):
    """Extracts clean text from BytesIO (PDF) or returns String (HTML)."""
    if file_type == 'html':
        return buffer  # It's already a string
    
    if file_type == 'pdf':
        # --- NEW VALIDATION CHECK ---
        if not validate_pdf_header(buffer):
            logger.error("❌ PDF Extraction failed: Invalid file header (Not a PDF). Likely an HTML error page.")
            return ""
        # ----------------------------

        try:
            reader = PdfReader(buffer)
            text = ""
            for page in reader.pages: 
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"PDF Extraction failed: {e}")
            return ""
    return ""

def risk_analyst_agent(file_buffers, api_key, model_name):
    """
    Analyzes credit rating documents to produce a risk profile.
    """
    logger.info(f"Agent started using model: {model_name}")
    
    if 'credit_rating_doc' not in file_buffers:
        logger.info("No credit rating document found. Skipping.")
        return "### Risk Profile\n\n*No Credit Rating data available for this company.*"

    doc = file_buffers['credit_rating_doc']
    doc_type = file_buffers.get('credit_rating_type', 'html')
    
    raw_text = extract_text_from_buffer(doc, doc_type)
    
    if not raw_text or len(raw_text) < 100:
        return "### Risk Profile\n\n*Credit Rating found, but text extraction failed (Invalid PDF or Empty File).*"

    context_text = raw_text
    
    logger.info(f"Analyzing full document ({len(context_text)} characters)...")

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name) 

        prompt = f"""
        You are a Senior Credit Risk Analyst acting as a skeptical Financial Forensics Investigator. 
        Analyze the following text extracted from a Credit Rating Agency Report (CRISIL/ICRA/CARE/Ind-Ra/Fitch/Acuité/Infomerics/Brickwork).
        
        Input Text:
        {context_text}
        
        ---
        Your Task:
        Produce a strict Markdown report summarizing the credit health, stripping away marketing glamour to focus on raw solvency.
        
        Format:
        ### Company Overview
        [A short, 2-3 sentence paragraph summarizing what the company does, its industry, and key products/services based on the report.]

        ### Credit Summary
        [A short, 3-4 sentence paragraph summarizing the findings the sections below ]

        ### Credit Rating & Outlook
        [Extract the specific rating, e.g., "CRISIL AA+ / Stable". If multiple ratings exist, list the long-term one.]
        
        ### Key Strengths (The Shields)
        * [Point 1 - Focus on competitive advantages or market dominance]
        * [Point 2]

        ### The "Antagonists" (Structural Risks)
        [Identify specific structural risks that could threaten survival. Look specifically for:]
        * **Promoter Issues:** [Check for share pledges or governance risks.]
        * **Working Capital Traps:** [Check for high inventory days, stuck receivables, or reliance on short-term funding.]
        * **Cyclicality:** [How vulnerable are they to an industry downturn or recession?]

        ### The "Liquidity" Shield
        [Analyze their cash reserves, debt levels, and ability to service interest. Are they living paycheck-to-paycheck, or do they have a "fortress balance sheet"?]

        ### Debt Profile
        * [Mention total debt, specific instruments, or key ratios like Debt/Equity or Interest Coverage if detailed in the text]
        """

        response = generate_with_retry(model, prompt)
        logger.info("Analysis complete.")
        return response.text

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}")
        return f"### Error\nFailed to generate risk profile: {str(e)}"