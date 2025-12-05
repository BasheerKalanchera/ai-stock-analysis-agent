import os
import io
import logging
import google.generativeai as genai
from pypdf import PdfReader  # Requires: pip install pypdf

# Setup Logger
logger = logging.getLogger('risk_agent')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - 🔴 RISK AGENT - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def extract_text_from_buffer(buffer, file_type):
    """Extracts clean text from BytesIO (PDF) or returns String (HTML)."""
    if file_type == 'html':
        return buffer  # It's already a string
    
    if file_type == 'pdf':
        try:
            reader = PdfReader(buffer)
            text = ""
            # Read entire PDF
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
    
    # 1. Check Availability
    if 'credit_rating_doc' not in file_buffers:
        logger.info("No credit rating document found. Skipping.")
        return "### Risk Profile\n\n*No Credit Rating data available for this company.*"

    # 2. Extract Text
    doc = file_buffers['credit_rating_doc']
    doc_type = file_buffers.get('credit_rating_type', 'html')
    
    raw_text = extract_text_from_buffer(doc, doc_type)
    
    if not raw_text or len(raw_text) < 100:
        return "### Risk Profile\n\n*Credit Rating found, but text extraction failed or file was empty.*"

    # 3. Context Window Management
    # Using full text as Gemini Flash context window is large enough
    context_text = raw_text
    
    logger.info(f"Analyzing full document ({len(context_text)} characters)...")

    # 4. LLM Call
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

        response = model.generate_content(prompt)
        logger.info("Analysis complete.")
        return response.text

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}")
        return f"### Error\nFailed to generate risk profile: {str(e)}"