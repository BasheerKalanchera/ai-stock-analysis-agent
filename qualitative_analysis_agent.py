import os
import io
import fitz
import asyncio
import aiohttp
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Optional, Dict
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

# --- Load Environment Variables ---
load_dotenv()

# --- Google API Configuration ---
API_KEY_CONFIGURED = False
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Google API Key not found in environment variables.")
    genai.configure(api_key=api_key)
    print("Qualitative Agent: Google API Key configured successfully.")
    API_KEY_CONFIGURED = True
except (ValueError, Exception) as e:
    print(f"Qualitative Agent Error: Could not configure Google API Key. {e}")

# Load model names from .env or use defaults
LITE_MODEL_NAME = os.getenv("LITE_MODEL_NAME", "gemini-1.5-flash")
HEAVY_MODEL_NAME = os.getenv("HEAVY_MODEL_NAME", "gemini-1.5-pro")

# --- Core Functions ---
def _extract_text_from_pdf_buffer(pdf_buffer: io.BytesIO | None) -> str:
    """Optimized PDF text extraction"""
    print("  (BACKGROUND THREAD: STARTING PDF text extraction...)")
    if not pdf_buffer:
        return ""
    try:
        # Use PyMuPDF to read PDF directly from memory buffer
        with fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        print("  (BACKGROUND THREAD: FINISHED PDF text extraction.)")    
        return full_text
    except Exception as e:
        print(f"Error reading PDF from buffer: {e}")
        return ""

@lru_cache(maxsize=32)
def _analyze_with_gemini(prompt: str, model_name: str = LITE_MODEL_NAME) -> str:
    """Cached version of Gemini API calls"""
    if not API_KEY_CONFIGURED:
        return "Error: Google API Key not configured."
    
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        print("  (BACKGROUND THREAD: FINISHING analysis with gemini...)")
        return response.text
    except Exception as e:
        return f"Error in Gemini API call: {str(e)}"

def _compare_transcripts(latest_text: str, previous_text: str) -> str:
    """Compare latest and previous transcripts"""
    prompt = f"""
    Compare these two earnings call transcripts and highlight key changes:
    
    LATEST TRANSCRIPT:
    {latest_text}
    
    PREVIOUS TRANSCRIPT:
    {previous_text}
    
    Focus on:
    1. Changes in business outlook
    2. New developments or strategies
    3. Management tone changes
    4. Key metrics changes
    """
    return _analyze_with_gemini(prompt, LITE_MODEL_NAME)

def _analyze_positives_and_concerns(transcript_text: str) -> str:
    """Extract positives and concerns from transcript"""
    prompt = f"""
    Analyze this earnings call transcript and identify:
    1. Key positive points
    2. Main concerns or risks
    3. Management's forward-looking statements
    
    TRANSCRIPT:
    {transcript_text}
    """
    return _analyze_with_gemini(prompt, LITE_MODEL_NAME)

async def _perform_scuttlebutt_analysis(company_name: str, session: aiohttp.ClientSession) -> str:
    """Perform web research about the company"""
    print("  (BACKGROUND THREAD: STARTING suttlebutt analysis...)")
    prompt = f"""
    Based on recent news and market sentiment, analyze {company_name}'s:
    1. Competitive position
    2. Industry trends
    3. Market reputation
    4. Future growth prospects
    """
    print("  (BACKGROUND THREAD: FINISHED suttlebutt analysis...)")
    return _analyze_with_gemini(prompt, HEAVY_MODEL_NAME)

async def _check_sebi_violations(company_name: str, session: aiohttp.ClientSession) -> str:
    """Check for any regulatory issues"""
    print("  (BACKGROUND THREAD: STARTING SEBI violations analysis...)")
    prompt = f"""
    Research and report on {company_name}'s:
    1. Recent SEBI compliance history
    2. Any regulatory concerns
    3. Corporate governance track record
    """
    return _analyze_with_gemini(prompt, HEAVY_MODEL_NAME)

async def _perform_web_analysis(company_name: str) -> Dict[str, str]:
    """Run web-based analysis functions concurrently"""
    print("  (BACKGROUND THREAD: STARTING web analysis...)")
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(_perform_scuttlebutt_analysis(company_name, session)),
            asyncio.create_task(_check_sebi_violations(company_name, session))
        ]
        scuttlebutt, sebi_check = await asyncio.gather(*tasks)
        print("  (BACKGROUND THREAD: FINISHING web analysis...)")
        return {
            "scuttlebutt": scuttlebutt,
            "sebi_check": sebi_check
        }

def run_qualitative_analysis(
    company_name: str, 
    latest_transcript_buffer: io.BytesIO | None, 
    previous_transcript_buffer: io.BytesIO | None
) -> Dict[str, Optional[str]]:
    """
    Main analysis function with concurrent processing.
    Args:
        company_name: Name of the company to analyze
        latest_transcript_buffer: Latest transcript PDF as BytesIO
        previous_transcript_buffer: Previous transcript PDF as BytesIO
    Returns:
        Dictionary containing analysis results
    """
    print("\n🔍 Starting Qualitative Analysis...")
    print(f"📊 Analyzing {company_name}")

    results = {
        "positives_and_concerns": None,
        "qoq_comparison": None,
        "scuttlebutt": None,
        "sebi_check": None
    }

    # Use a single ThreadPoolExecutor to manage all concurrent tasks
    with ThreadPoolExecutor(max_workers=10) as executor:
        # --- Step 1: Submit ALL concurrent tasks immediately ---
        print("🚀 Kicking off all analysis tasks in parallel...")

        # Submit PDF processing tasks
        latest_text_future = None
        if latest_transcript_buffer:
            latest_text_future = executor.submit(_extract_text_from_pdf_buffer, latest_transcript_buffer)

        previous_text_future = None
        if previous_transcript_buffer:
            previous_text_future = executor.submit(_extract_text_from_pdf_buffer, previous_transcript_buffer)

        # Submit Web Analysis task using a lambda to defer execution
        web_analysis_future = None
        if company_name:
            # The lambda ensures the entire asyncio.run(...) call happens
            # inside the background thread, not in the main thread.
            web_analysis_future = executor.submit(
                lambda: asyncio.run(_perform_web_analysis(company_name))
            )

        # --- Step 2: Collect and process results as they are needed ---
        
        # Now, wait for and process the transcript results
        if latest_text_future:
            latest_text = latest_text_future.result()
            if latest_text:
                print("📝 Analyzing latest transcript...")
                results["positives_and_concerns"] = _analyze_positives_and_concerns(latest_text)
                
                if previous_text_future:
                    previous_text = previous_text_future.result()
                    if previous_text:
                        print("🔄 Performing QoQ comparison...")
                        results["qoq_comparison"] = _compare_transcripts(latest_text, previous_text)

        # Finally, wait for and collect the web analysis results
        if web_analysis_future:
            print("🌐 Collecting web analysis results...")
            web_results = web_analysis_future.result()
            results.update(web_results)

    print("✅ Qualitative Analysis complete!\n")
    return results