import io
import fitz
import asyncio
import google.generativeai as genai
from typing import Optional, Dict
from functools import lru_cache
import logging

# --- CUSTOM LOGGER SETUP ---
# 1. Get a custom logger
logger = logging.getLogger('qualitative_agent')
logger.setLevel(logging.INFO)

# 2. Create a handler
handler = logging.StreamHandler()

# 3. Create a custom formatter and set it for the handler
formatter = logging.Formatter('%(asctime)s - QUAL - %(message)s')
handler.setFormatter(formatter)

# 4. Add the handler to the logger
if not logger.handlers:
    logger.addHandler(handler)

# 5. Stop logger from propagating to the root logger
logger.propagate = False
# --- END CUSTOM LOGGER SETUP ---

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
def _analyze_with_gemini(prompt: str, analysis_type: str, model_name: str, api_key: str) -> str:
    """Cached version of Gemini API calls that accepts an API key."""
    if not api_key:
        msg = f"Analysis skipped for '{analysis_type}': Google API Key is not configured."
        logger.warning(msg)
        return msg
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        logger.info(f"Calling Gemini for '{analysis_type}' analysis...")
        response = model.generate_content(prompt)
        logger.info(f"Finished '{analysis_type}' analysis.")
        return response.text
    except Exception as e:
        logger.error(f"Could not generate '{analysis_type}' analysis. Error: {e}")
        return f"Could not generate '{analysis_type}' analysis. {str(e)}"

def _compare_transcripts(latest_text: str, previous_text: str, agent_config: dict) -> str:
    """Compare latest and previous transcripts"""
    prompt = f"""
    You are an expert financial analyst. Your task is to compare and contrast the company's performance based on the two provided earnings conference call transcripts.
    Analyze the tone, key metrics, management outlook, and any significant changes or new information between the two quarters.
    **Latest Quarter Transcript:**
    ---
    {latest_text}
    ---
    **Previous Quarter Transcript:**
    ---
    {previous_text}
    **Your Task:**
    Provide a structured comparison in Markdown format. Use bullet points and headers. Focus on:
    - **Overall Sentiment Shift:** Did the management tone become more optimistic, cautious, or stay the same?
    - **Financial & Operational Highlights:** Compare key performance indicators mentioned in both calls (e.g., revenue growth, margins, order book).
    - **Segment Performance:** Note any changes in the performance of different business segments.
    - **Outlook & Guidance:** Compare the future outlook or guidance provided in each call.
    - **Key Concerns:** Did any concerns from the previous quarter get resolved? Are there any new concerns in the latest quarter?
    Directly quote relevant phrases from BOTH transcripts to support your points.
    """
    return _analyze_with_gemini(prompt, "Quarter-over-Quarter Comparison",
                                agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
                                agent_config.get("GOOGLE_API_KEY"))

def _analyze_positives_and_concerns(transcript_text: str, agent_config: dict) -> str:
    """Extract positives and concerns from transcript"""
    prompt = f"""
    Based ONLY on the provided earnings conference call transcript, identify the key positives and areas of concern.
    Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    Under each heading, use bullet points to list the key takeaways.
    Directly quote relevant phrases or sentences from the transcript to support each point.
    **Transcript:**
    ---
    {transcript_text}
    """
    return _analyze_with_gemini(prompt, "Positives & Concerns",
                                agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
                                agent_config.get("GOOGLE_API_KEY"))

def _scuttlebutt_sync(company_name: str, agent_config: dict) -> str:
    logger.info("Starting scuttlebutt analysis...")
    prompt = f"""
    As a world-class financial analyst following Philip Fisher's "Scuttlebutt" method, conduct a deep investigation into the company: **{company_name}**.
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
                                agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro"),
                                agent_config.get("GOOGLE_API_KEY"))

# --- Async Orchestrator using asyncio.to_thread ---
async def run_qualitative_analysis_async(
    company_name: str, 
    latest_transcript_buffer: io.BytesIO | None, 
    previous_transcript_buffer: io.BytesIO | None,
    agent_config: dict
) -> Dict[str, Optional[str]]:
    logger.info(f"--- Starting Qualitative Analysis for {company_name} ---")

    results = {
        "positives_and_concerns": None,
        "qoq_comparison": None,
        "scuttlebutt": None,
        "sebi_check": None
    }

    logger.info("Kicking off all analysis tasks in parallel...")

    # Kick off Scuttlebutt + SEBI (independent, let them run in background)
    scuttlebutt_future = None
    sebi_future = None
    if company_name:
        scuttlebutt_future = asyncio.create_task(
            asyncio.to_thread(_scuttlebutt_sync, company_name, agent_config)
        )
        sebi_future = asyncio.create_task(
            asyncio.to_thread(_sebi_sync, company_name, agent_config)
        )

    # Kick off PDF extraction
    latest_future = None
    prev_future = None
    if latest_transcript_buffer:
        latest_future = asyncio.create_task(
            asyncio.to_thread(_extract_text_from_pdf_buffer, latest_transcript_buffer)
        )
    if previous_transcript_buffer:
        prev_future = asyncio.create_task(
            asyncio.to_thread(_extract_text_from_pdf_buffer, previous_transcript_buffer)
        )

    # Wait for transcripts as soon as they are ready
    latest_text = await latest_future if latest_future else None
    previous_text = await prev_future if prev_future else None

    # As soon as latest transcript is ready, analyze it
    if latest_text:
        logger.info("Analyzing latest transcript for positives and concerns...")
        results["positives_and_concerns"] = await asyncio.to_thread(
            _analyze_positives_and_concerns, latest_text, agent_config
        )

        if previous_text:
            logger.info("Performing QoQ comparison...")
            results["qoq_comparison"] = await asyncio.to_thread(
                _compare_transcripts, latest_text, previous_text, agent_config
            )

    # Meanwhile, scuttlebutt and sebi keep running in background
    if scuttlebutt_future:
        results["scuttlebutt"] = await scuttlebutt_future
    if sebi_future:
        results["sebi_check"] = await sebi_future

    logger.info(f"--- Finished Qualitative Analysis for {company_name} ---")
    return results


# Convenience sync wrapper
def run_qualitative_analysis(company_name, latest_transcript_buffer, previous_transcript_buffer, agent_config):
    return asyncio.run(run_qualitative_analysis_async(
        company_name, latest_transcript_buffer, previous_transcript_buffer, agent_config
    ))