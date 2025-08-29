# qualitative_analysis_agent.py

import os
import fitz  # PyMuPDF
import google.generativeai as genai
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()

# --- Google API Configuration ---
API_KEY_CONFIGURED = False
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in .env file.")
    genai.configure(api_key=api_key)
    print("Qualitative Agent: Google API Key configured successfully.")
    API_KEY_CONFIGURED = True
except (ValueError, Exception) as e:
    print(f"Qualitative Agent Error: Could not configure Google API Key. {e}")


# --- Core Functions ---

def _extract_text_from_pdf_path(pdf_path: str) -> str:
    """Extracts all text from a PDF file given its path."""
    try:
        with fitz.open(pdf_path) as doc:
            full_text = "".join(page.get_text() for page in doc)
        return full_text
    except Exception as e:
        print(f"Error reading PDF file '{pdf_path}': {e}")
        return ""

def _analyze_with_gemini(prompt: str, analysis_type: str) -> str:
    """Generic function to call the Gemini model with a given prompt."""
    if not API_KEY_CONFIGURED:
        return f"Analysis skipped for '{analysis_type}': Google API Key is not configured."
    
    print(f"Qualitative Agent: Starting '{analysis_type}' analysis...")
    try:
        # Using a specific model, you can change it if needed e.g., 'gemini-pro'
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        print(f"Qualitative Agent: Finished '{analysis_type}' analysis.")
        return response.text
    except Exception as e:
        print(f"An error occurred during '{analysis_type}' analysis: {e}")
        return f"Could not generate '{analysis_type}' analysis. Please check the API key and backend status."

def _compare_transcripts(latest_transcript: str, previous_transcript: str) -> str:
    """
    Uses the Gemini model to compare and contrast two transcripts.
    """
    prompt = f"""
    You are an expert financial analyst. Your task is to compare and contrast the company's performance based on the two provided earnings conference call transcripts.

    Analyze the tone, key metrics, management outlook, and any significant changes or new information between the two quarters.

    **Latest Quarter Transcript:**
    ---
    {latest_transcript}
    ---

    **Previous Quarter Transcript:**
    ---
    {previous_transcript}
    ---

    **Your Task:**
    Provide a structured comparison in Markdown format. Use bullet points and headers. Focus on:
    - **Overall Sentiment Shift:** Did the management tone become more optimistic, cautious, or stay the same?
    - **Financial & Operational Highlights:** Compare key performance indicators mentioned in both calls (e.g., revenue growth, margins, order book).
    - **Segment Performance:** Note any changes in the performance of different business segments.
    - **Outlook & Guidance:** Compare the future outlook or guidance provided in each call.
    - **Key Concerns:** Did any concerns from the previous quarter get resolved? Are there any new concerns in the latest quarter?

    Directly quote relevant phrases from BOTH transcripts to support your points.
    """
    return _analyze_with_gemini(prompt, "Quarter-over-Quarter Comparison")

def _analyze_positives_and_concerns(transcript_text: str) -> str:
    """Analyzes a single transcript for positives and concerns."""
    prompt = f"""
    Based ONLY on the provided earnings conference call transcript, identify the key positives and areas of concern.
    Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    Under each heading, use bullet points to list the key takeaways.
    Directly quote relevant phrases or sentences from the transcript to support each point.

    **Transcript:**
    ---
    {transcript_text}
    ---
    """
    return _analyze_with_gemini(prompt, "Positives & Concerns")

def _perform_scuttlebutt_analysis(company_name: str) -> str:
    """Uses the Gemini model to perform an online scuttlebutt analysis."""
    prompt = f"""
    As a world-class financial analyst following Philip Fisher's "Scuttlebutt" method, conduct a deep investigation into the company: **{company_name}**.
    
    Your goal is to gather qualitative insights that are not typically found in financial statements. Search for and synthesize information from a wide range of sources including:
    - Recent news articles (last 6-12 months)
    - Industry reports and forums
    - Employee reviews (e.g., Glassdoor)
    - Customer feedback and reviews
    - Management interviews or public statements
    - Supply chain or partner commentary
    
    **Synthesize your findings into a concise report covering these key areas:**
    1.  **Competitive Landscape:** How is the company positioned against its main competitors? What are its key competitive advantages (moat)?
    2.  **Management Quality & Culture:** What is the reputation of the CEO and the senior management team? What is the overall employee morale and company culture like?
    3.  **Customer & Product Perception:** How do customers perceive the company's products or services? Are they seen as innovative, reliable, or a leader in their category?
    4.  **Industry Trends & Headwinds:** What are the major tailwinds (positive trends) and headwinds (challenges) facing the industry and the company?
    5.  **Red Flags:** Are there any potential issues, controversies, or risks that an investor should be aware of?

    Provide a final summary of your overall impression. Use Markdown for formatting.
    """
    return _analyze_with_gemini(prompt, f"Scuttlebutt Analysis for {company_name}")

def _check_sebi_violations(company_name: str) -> str:
    """Uses the Gemini model to check for SEBI violations for a given company."""
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
    return _analyze_with_gemini(prompt, f"SEBI Violations Check for {company_name}")


def run_qualitative_analysis(company_name: str, latest_transcript_path: str | None, previous_transcript_path: str | None) -> dict:
    """
    The main function to run the entire qualitative analysis pipeline.
    It orchestrates transcript analysis and web-based research.
    """
    results = {
        "positives_and_concerns": None,
        "qoq_comparison": None,
        "scuttlebutt": None,
        "sebi_check": None
    }

    # --- Transcript-Based Analysis ---
    if latest_transcript_path and os.path.exists(latest_transcript_path):
        latest_text = _extract_text_from_pdf_path(latest_transcript_path)
        if latest_text:
            results["positives_and_concerns"] = _analyze_positives_and_concerns(latest_text)
            
            if previous_transcript_path and os.path.exists(previous_transcript_path):
                previous_text = _extract_text_from_pdf_path(previous_transcript_path)
                if previous_text:
                    results["qoq_comparison"] = _compare_transcripts(latest_text, previous_text)
                else:
                    results["qoq_comparison"] = "Could not extract text from the previous quarter's transcript."
            else:
                 results["qoq_comparison"] = "Previous quarter transcript not available for comparison."
        else:
            results["positives_and_concerns"] = "Could not extract text from the latest transcript."
            results["qoq_comparison"] = "Analysis skipped as latest transcript could not be read."
    else:
        results["positives_and_concerns"] = "Latest transcript not available."
        results["qoq_comparison"] = "Latest transcript not available."


    # --- Web-Based Analysis ---
    if company_name:
        results["scuttlebutt"] = _perform_scuttlebutt_analysis(company_name)
        results["sebi_check"] = _check_sebi_violations(company_name)
    
    return results

