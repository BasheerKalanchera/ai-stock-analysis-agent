import io
import fitz
import asyncio
import google.generativeai as genai
from typing import Optional, Dict
from functools import lru_cache
import logging
import time 
import re       
import random   
from google.api_core import exceptions as google_exceptions

# --- CUSTOM LOGGER SETUP ---
# 1. Get a custom logger
logger = logging.getLogger('qualitative_agent')
logger.setLevel(logging.INFO)

# 2. Create a handler
handler = logging.StreamHandler()

# 3. Create a custom formatter and set it for the handler
formatter = logging.Formatter(f'%(asctime)s - 🟡 QUAL - %(message)s')
handler.setFormatter(formatter)

# 4. Add the handler to the logger
if not logger.handlers:
    logger.addHandler(handler)

# 5. Stop logger from propagating to the root logger
logger.propagate = False
# --- END CUSTOM LOGGER SETUP ---

# --- HELPER FUNCTIONS ---

def _parse_retry_delay(error_message: str) -> int:
    """Extracts the recommended retry delay from Gemini error messages."""
    try:
        # Regex to find 'retry_delay { seconds: 30 }' or similar patterns
        match = re.search(r'retry_delay.*seconds:\s*(\d+)', error_message, re.DOTALL | re.IGNORECASE)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0

def _log_rate_limit(analysis_type: str, attempt: int, wait_time: float, is_generic_429: bool = False):
    """
    Centralized helper to log rate limit warnings in a consistent, one-line format.
    """
    error_type = "generic 429" if is_generic_429 else "rate limit"
    logger.warning(f"'{analysis_type}' (Attempt {attempt}) encountered {error_type} - retry after {wait_time:.1f} seconds.")

def _chunk_text(text: str, chunk_size: int = 25000) -> list[str]:
    """Splits text into chunks of approximately chunk_size characters."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

# --- Core Functions ---

def _extract_text_from_pdf_buffer(pdf_buffer: io.BytesIO | None) -> str:
    """Optimized PDF text extraction"""
    logger.info("Starting PDF text extraction...")
    if not pdf_buffer:
        return ""
    try:
        with fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        logger.info("Finished PDF text extraction.")
        return full_text
    except Exception as e:
        logger.error(f"Error reading PDF from buffer: {e}")
        return ""

@lru_cache(maxsize=32)
def _analyze_with_gemini(prompt: str, analysis_type: str, model_name: str, api_key: str, max_retries: int = 6) -> str:
    """
    Cached version of Gemini API calls with robust retry logic.
    Now accepts 'max_retries' to allow faster failover for specific tasks.
    """
    if not api_key:
        msg = f"Analysis skipped for '{analysis_type}': Google API Key is not configured."
        logger.warning(msg)
        return msg
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    base_delay_seconds = 30 

    for attempt in range(max_retries):
        try:
            logger.info(f"Calling Gemini for '{analysis_type}' analysis... (Attempt {attempt + 1}/{max_retries})")
            response = model.generate_content(prompt)
            logger.info(f"Finished '{analysis_type}' analysis.")
            return response.text
        
        # Specific catch for 429 Resource Exhausted errors
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
            error_str = str(e)
            api_suggested_wait = _parse_retry_delay(error_str)
            
            # Smart Logic: Use API suggestion if available, else use base_delay
            if api_suggested_wait > 0:
                wait_time = api_suggested_wait + 5
            else:
                wait_time = base_delay_seconds + random.uniform(0, 2) # Add small jitter

            if attempt < max_retries - 1:
                # Use Clean Logging Helper
                _log_rate_limit(analysis_type, attempt + 1, wait_time, is_generic_429=False)
                time.sleep(wait_time)
            else:
                logger.error(f"Final attempt failed for '{analysis_type}'.")
                return f"Could not generate '{analysis_type}' analysis after {max_retries} attempts. Rate limit exceeded. {str(e)}"
        
        # Catch for other errors
        except Exception as e:
            # Check if it's a 429 wrapped in a generic exception
            if "429" in str(e):
                 # Default to base delay for generic 429s
                 wait_time = base_delay_seconds + random.uniform(0, 2)
                 
                 if attempt < max_retries - 1:
                    # Use Clean Logging Helper
                    _log_rate_limit(analysis_type, attempt + 1, wait_time, is_generic_429=True)
                    time.sleep(wait_time)
                 else:
                    logger.error(f"Final attempt failed for '{analysis_type}'.")
                    return f"Could not generate '{analysis_type}' analysis after {max_retries} attempts. Rate limit exceeded. {str(e)}"
            else:
                # This was a non-retryable error
                logger.error(f"Could not generate '{analysis_type}' analysis. Error: {e}")
                return f"Could not generate '{analysis_type}' analysis. {str(e)}"
    
    # This line should not be reachable, but as a fallback:
    return f"Could not generate '{analysis_type}' analysis after {max_retries} attempts."

def _compare_transcripts(latest_analysis: str, previous_analysis: str, agent_config: dict) -> str:
    """Compare latest and previous analyses (inputs are now summaries, not raw text)"""
    prompt = f"""
    You are an expert financial analyst. Your task is to compare the company's performance based on the provided **analysis summaries** of the last two quarters.

    **CRITICAL INSTRUCTION:** You **must** generate your response as a single, valid JSON array of objects. Do not include any text, code blocks, or explanations before or after the JSON.
    
    The JSON array must contain objects with these exact keys:
    1.  "Metric"
    2.  "Latest Quarter Analysis"
    3.  "Previous Quarter Analysis"

    **FORMATTING:** For the analysis values, use a single string. Inside that string, use Markdown bullets (`* `).
    **IMPORTANT:** All newlines inside the JSON strings **MUST be escaped as `\\n`**. Do not use literal newlines.

    **JSON STRUCTURE EXAMPLE (Note the `\\n`):**
    [
      {{
        "Metric": "Overall Sentiment Shift",
        "Latest Quarter Analysis": "* The tone is cautious.\\n* Focus on cost cutting.",
        "Previous Quarter Analysis": "* The tone was optimistic.\\n* Focus on expansion."
      }}
    ]

    **You must include rows for at least the following metrics:**
    * Overall Sentiment Shift
    * Financial & Operational Highlights
    * Segment Performance
    * Outlook & Guidance
    * Key Concerns / New Issues

    **Latest Quarter Analysis Summary:**
    ---
    {latest_analysis}
    ---

    **Previous Quarter Analysis Summary:**
    ---
    {previous_analysis}
    ---

    **Your Output (VALID JSON array only):**
    """
    return _analyze_with_gemini(prompt, "Quarter-over-Quarter Comparison",
                                agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
                                agent_config.get("GOOGLE_API_KEY"))

def _analyze_positives_and_concerns(transcript_text: str, agent_config: dict) -> str:
    """
    Two-Phase Analysis Strategy:
    1. Try Direct Analysis (Preferred): Faster and more accurate. Tries 2 times.
    2. Fallback to Map-Reduce: Used if Direct Analysis fails (due to Token Limit or Rate Limit).
    """
    
    # --- PHASE 1: DIRECT ATTEMPT ---
    logger.info(f"Attempting Direct Analysis of transcript ({len(transcript_text)} chars)...")
    
    prompt = f"""
    Based ONLY on the provided earnings conference call transcript, identify the key positives and areas of concern.
    Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    Under each heading, use bullet points to list the key takeaways.
    Directly quote relevant phrases or sentences from the transcript to support each point.
    **Transcript:**
    ---
    {transcript_text}
    """
    
    # Try just 2 times. If it fails (likely due to size/rate limits), we move to fallback immediately.
    direct_result = _analyze_with_gemini(
        prompt, 
        "Positives & Concerns (Direct)",
        agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
        agent_config.get("GOOGLE_API_KEY"),
        max_retries=2 
    )

    # Check if Direct Attempt Succeeded
    # If the result contains error keywords, we treat it as a failure
    if "Could not generate" not in direct_result and "Rate limit exceeded" not in direct_result:
        return direct_result
    
    # --- PHASE 2: FALLBACK TO MAP-REDUCE ---
    logger.warning("Direct Analysis failed or hit limits. Switching to Map-Reduce Fallback Strategy...")
    
    # Split into chunks of ~24k chars (approx 6k tokens)
    chunks = _chunk_text(transcript_text, chunk_size=24000)
    chunk_summaries = []
    
    # MAP STEP
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing Fallback Map Chunk {i+1}/{len(chunks)}...")
        chunk_prompt = f"""
        Analyze this PARTIAL SECTION of an earnings call transcript.
        Extract any key "Positives" (Growth, wins, margin expansion) and "Areas of Concern" (Headwinds, cost pressure, delays).
        Be concise. If no significant points are found in this section, reply with "No key points".
        
        **Transcript Part {i+1}:**
        ---
        {chunk}
        """
        
        # We use standard retries (6) for these smaller chunks to ensure they pass
        summary = _analyze_with_gemini(
            chunk_prompt, 
            f"Positives Map Chunk {i+1}",
            agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
            agent_config.get("GOOGLE_API_KEY"),
            max_retries=6
        )
        chunk_summaries.append(summary)
        
        # Pacing
        if i < len(chunks) - 1:
            time.sleep(5) 

    # REDUCE STEP
    logger.info("Reducing fallback summaries into final report...")
    combined_summaries = "\n\n".join(chunk_summaries)
    
    final_prompt = f"""
    You are an expert financial analyst. Below are summaries extracted from different parts of an earnings call transcript.
    Your task is to consolidate these partial points into one final, coherent report.
    
    1. Remove duplicates.
    2. Merge related points.
    3. Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    4. Use bullet points.
    
    **Combined Summaries:**
    ---
    {combined_summaries}
    """
    
    return _analyze_with_gemini(
        final_prompt, 
        "Positives & Concerns (Reduce Step)",
        agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
        agent_config.get("GOOGLE_API_KEY")
    )

def _scuttlebutt_sync(company_name: str, context_text: str, agent_config: dict) -> str:
    logger.info("Starting scuttlebutt analysis...")
    
    # Add context section if available to ground the analysis
    context_instruction = ""
    if context_text and len(context_text) > 10:
        context_instruction = f"""
        **COMPANY BACKGROUND & CONTEXT:**
        Use the following summary to GROUND your research. Ensure the information you find online relates specifically to the company described below.
        
        {context_text}
        """

    prompt = f"""
    As a world-class financial analyst following Philip Fisher's "Scuttlebutt" method, conduct a deep investigation into the company: **{company_name}**.
    
    {context_instruction}

    Your goal is to gather qualitative insights that are not typically found in financial statements. Search for and synthesize the most up-to-date information available as of **September 2025** from a wide range of sources including:
    - Recent news articles, focusing on the period from **late 2024 to the present day**
    - The latest industry reports and forum discussions
    - Employee reviews (e.g., Glassdoor) posted within the last year
    - Recent customer feedback and reviews
    - Management interviews or public statements from **2025**
    - Any recent supply chain or partner commentary
    
    **Synthesize your findings into a concise report covering these key areas:**
    1.  **Competitive Landscape:** How is the company positioned against its main competitors? What are its key competitive advantages (moat)?
    2.  **Management Quality & Culture:** What is the reputation of the CEO and the senior management team? What is the overall employee morale and company culture like?
    3.  **Customer & Product Perception:** How do customers perceive the company's products or services? Are they seen as innovative, reliable, or a leader in their category?
    4.  **Industry Trends & Headwinds:** What are the major tailwinds (positive trends) and headwinds (challenges) facing the industry and the company?
    5.  **Red Flags:** Are there any potential issues, controversies, or risks that an investor should be aware of?
    
    Provide a final summary of your overall impression. Use Markdown for formatting.
    """
    return _analyze_with_gemini(prompt, "Scuttlebutt Analysis",
                                agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro"),
                                agent_config.get("GOOGLE_API_KEY"))

def _sebi_sync(company_name: str, agent_config: dict) -> str:
    logger.info("Starting SEBI violations analysis...")
    prompt = f"""
    As a compliance officer, please conduct a thorough search for any publicly reported regulatory actions, penalties, or ongoing investigations by the Securities and Exchange Board of India (SEBI) involving the company: **{company_name}**.
    Search for information related to:
    - Insider trading violations.
    - Financial misrepresentation or accounting fraud.
    - Market manipulation.
    - Non-compliance with listing obligations and disclosure requirements.
    - Any other significant regulatory censures or penalties.
    Please summarize your findings. If there are notable issues, provide a brief description and, if possible, the year of the event. If no significant violations are found in publicly accessible records, please state that clearly.
    """
    return _analyze_with_gemini(prompt, "SEBI Violations Analysis",
                                agent_config.get("LITE_MODEL_NAME", "gemini-1.5-pro"),
                                agent_config.get("GOOGLE_API_KEY"))

# --- Async Orchestrator using asyncio.to_thread ---
async def run_qualitative_analysis_async(
    company_name: str, 
    latest_transcript_buffer: io.BytesIO | None, 
    previous_transcript_buffer: io.BytesIO | None,
    agent_config: dict,
    strategy_context: str = "", 
    risk_context: str = ""
) -> Dict[str, Optional[str]]:
    logger.info(f"--- Starting Qualitative Analysis for {company_name} ---")

    results = {
        "positives_and_concerns": None,
        "qoq_comparison": None,
        "scuttlebutt": None,
        "sebi_check": None
    }

    logger.info("Kicking off all analysis tasks in parallel...")

    # Combine context for Scuttlebutt grounding
    combined_context = ""
    if strategy_context:
        combined_context += f"--- STRATEGIC CONTEXT ---\n{strategy_context}\n\n"
    if risk_context:
        combined_context += f"--- RISK PROFILE CONTEXT ---\n{risk_context}\n\n"

    # 1. Kick off Scuttlebutt + SEBI (independent background tasks)
    scuttlebutt_future = None
    sebi_future = None
    if company_name:
        scuttlebutt_future = asyncio.create_task(
            asyncio.to_thread(_scuttlebutt_sync, company_name, combined_context, agent_config)
        )
        sebi_future = asyncio.create_task(
            asyncio.to_thread(_sebi_sync, company_name, agent_config)
        )

    # 2. Kick off PDF extraction
    latest_text_future = None
    prev_text_future = None
    if latest_transcript_buffer:
        latest_text_future = asyncio.create_task(
            asyncio.to_thread(_extract_text_from_pdf_buffer, latest_transcript_buffer)
        )
    if previous_transcript_buffer:
        prev_text_future = asyncio.create_task(
            asyncio.to_thread(_extract_text_from_pdf_buffer, previous_transcript_buffer)
        )

    # Wait for transcripts
    latest_text = await latest_text_future if latest_text_future else None
    previous_text = await prev_text_future if prev_text_future else None

    # 3. Analyze Transcripts (Map Step)
    latest_analysis_result = None
    previous_analysis_result = None

    
    # Analyze Latest
    if latest_text:
        time.sleep(30)
        logger.info("Analyzing latest transcript for positives and concerns...")
        latest_analysis_result = await asyncio.to_thread(
            _analyze_positives_and_concerns, latest_text, agent_config
        )
        results["positives_and_concerns"] = latest_analysis_result

    # Analyze Previous (if it exists)
    if previous_text:
        time.sleep(30)
        logger.info("Analyzing previous transcript for intermediate summary...")
        previous_analysis_result = await asyncio.to_thread(
            _analyze_positives_and_concerns, previous_text, agent_config
        )

    # 4. Perform QoQ Comparison (Reduce Step)
    # Now we compare the ANALYSIS RESULTS, not the raw text
    if latest_analysis_result and previous_analysis_result:
        time.sleep(30)
        logger.info("Performing QoQ comparison using summarized analyses...")
        results["qoq_comparison"] = await asyncio.to_thread(
            _compare_transcripts, latest_analysis_result, previous_analysis_result, agent_config
        )
    elif latest_analysis_result:
        logger.warning("Skipping QoQ comparison: Previous transcript analysis missing.")
    
    # 5. Gather background tasks
    if scuttlebutt_future:
        results["scuttlebutt"] = await scuttlebutt_future
    if sebi_future:
        results["sebi_check"] = await sebi_future

    logger.info(f"--- Finished Qualitative Analysis for {company_name} ---")
    return results


# Convenience sync wrapper
def run_qualitative_analysis(
    company_name, 
    latest_transcript_buffer, 
    previous_transcript_buffer, 
    agent_config,
    strategy_context="",
    risk_context=""
):
    return asyncio.run(run_qualitative_analysis_async(
        company_name, 
        latest_transcript_buffer, 
        previous_transcript_buffer, 
        agent_config,
        strategy_context,
        risk_context
    ))