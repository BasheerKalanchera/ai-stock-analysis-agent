import io
import fitz
import asyncio
import aiohttp
import google.generativeai as genai
from typing import Optional, Dict
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

# --- Core Functions ---
def _extract_text_from_pdf_buffer(pdf_buffer: io.BytesIO | None) -> str:
    """Optimized PDF text extraction"""
    print("  (BACKGROUND THREAD: STARTING PDF text extraction...)")
    if not pdf_buffer:
        return ""
    try:
        with fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        print("  (BACKGROUND THREAD: FINISHED PDF text extraction.)")    
        return full_text
    except Exception as e:
        print(f"Error reading PDF from buffer: {e}")
        return ""

@lru_cache(maxsize=32)
def _analyze_with_gemini(prompt: str, analysis_type: str, model_name: str, api_key: str) -> str:
    """Cached version of Gemini API calls that accepts an API key."""
    if not api_key:
        return f"Analysis skipped for '{analysis_type}': Google API Key is not configured."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        print(f"BACKGROUND THREAD: Finished '{analysis_type}' analysis.")
        return response.text
    except Exception as e:
        return f"Could not generate '{analysis_type}' analysis. Please check the API key and backend status.: {str(e)}"

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
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash")
    return _analyze_with_gemini(prompt, "Quarter-over-Quarter Comparison", model_name, api_key)

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
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash")
    return _analyze_with_gemini(prompt, "Positives & Concerns", model_name, api_key)

async def _perform_scuttlebutt_analysis(company_name: str, session: aiohttp.ClientSession, agent_config: dict) -> str:
    """Perform web research about the company"""
    print("  (BACKGROUND THREAD: STARTING scuttlebutt analysis...)")
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
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro")
    return _analyze_with_gemini(prompt, "Scuttlebutt Analysis", model_name, api_key)

async def _check_sebi_violations(company_name: str, session: aiohttp.ClientSession, agent_config: dict) -> str:
    """Check for any regulatory issues"""
    print("  (BACKGROUND THREAD: STARTING SEBI violations analysis...)")
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
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro")
    return _analyze_with_gemini(prompt, "SEBI Violations Analysis", model_name, api_key)

async def _perform_web_analysis(company_name: str, agent_config: dict) -> Dict[str, str]:
    """Run web-based analysis functions concurrently"""
    print("  (BACKGROUND THREAD: STARTING web analysis...)")
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(_perform_scuttlebutt_analysis(company_name, session, agent_config)),
            asyncio.create_task(_check_sebi_violations(company_name, session, agent_config))
        ]
        scuttlebutt, sebi_check = await asyncio.gather(*tasks)
        print("  (BACKGROUND THREAD: FINISHING web analysis...)")
        return {"scuttlebutt": scuttlebutt, "sebi_check": sebi_check}

def run_qualitative_analysis(
    company_name: str, 
    latest_transcript_buffer: io.BytesIO | None, 
    previous_transcript_buffer: io.BytesIO | None,
    agent_config: dict
) -> Dict[str, Optional[str]]:
    """
    Main analysis function with concurrent processing.
    Accepts an agent_config dictionary for API key and model names.
    """
    print("\n🔍 Starting Qualitative Analysis...")
    print(f"📊 Analyzing {company_name}")

    results = {
        "positives_and_concerns": None,
        "qoq_comparison": None,
        "scuttlebutt": None,
        "sebi_check": None
    }
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        print("🚀 Kicking off all analysis tasks in parallel...")

        # Submit Web Analysis task
        web_analysis_future = executor.submit(
            lambda: asyncio.run(_perform_web_analysis(company_name, agent_config))
        ) if company_name else None

        # Submit PDF processing tasks
        latest_text_future = executor.submit(_extract_text_from_pdf_buffer, latest_transcript_buffer) if latest_transcript_buffer else None
        previous_text_future = executor.submit(_extract_text_from_pdf_buffer, previous_transcript_buffer) if previous_transcript_buffer else None
        
        # Collect web analysis results
        if web_analysis_future:
            print("🌐 Collecting web analysis results...")
            results.update(web_analysis_future.result())

        # Wait for and process transcript results
        latest_text = latest_text_future.result() if latest_text_future else None
        if latest_text:
            print("📝 Analyzing latest transcript...")
            results["positives_and_concerns"] = _analyze_positives_and_concerns(latest_text, agent_config)
            
            previous_text = previous_text_future.result() if previous_text_future else None
            if previous_text:
                print("🔄 Performing QoQ comparison...")
                results["qoq_comparison"] = _compare_transcripts(latest_text, previous_text, agent_config)
        
    print("✅ Qualitative Analysis complete!\n")
    return results