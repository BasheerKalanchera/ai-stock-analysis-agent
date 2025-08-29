# Transcript.py

import streamlit as st
import fitz  # PyMuPDF
import re
import google.generativeai as genai
from io import BytesIO
import os
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="Qualitative Analysis Agent",
    page_icon="🤖",
    layout="wide"
)

# --- Google API Configuration ---
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in .env file.")
    genai.configure(api_key=api_key)
    st.sidebar.success("Google API Key loaded successfully!")
    API_KEY_CONFIGURED = True
except (ValueError, Exception) as e:
    st.sidebar.error(f"Error loading Google API Key: {e}")
    API_KEY_CONFIGURED = False


# --- Core Functions ---

def extract_text_from_pdf(pdf_file: BytesIO) -> str:
    """Extracts all text from an uploaded PDF file."""
    try:
        # The file uploader gives a file-like object, read it into bytes
        pdf_bytes = pdf_file.getvalue()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        return full_text
    except Exception as e:
        st.error(f"Error reading PDF file '{pdf_file.name}': {e}")
        return ""

def analyze_transcript(transcript_text: str, prompt_template: str, title: str) -> str:
    """
    Generic function to analyze a single transcript text based on a given prompt.
    """
    if not API_KEY_CONFIGURED:
        return "Analysis skipped: Google API Key is not configured."

    st.info(f"Analyzing: **{title}**")

    prompt = prompt_template.format(transcript=transcript_text)

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"An error occurred during analysis for '{title}': {e}")
        return "Could not generate analysis. Please check the API key and backend status."

def compare_transcripts(latest_transcript: str, previous_transcript: str, title: str) -> str:
    """
    Uses the Gemini model to compare and contrast two transcripts.
    """
    if not API_KEY_CONFIGURED:
        return "Analysis skipped: Google API Key is not configured."

    st.info(f"Analyzing: **{title}**")

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
    Provide a structured comparison. Use bullet points and headers. Focus on:
    - **Overall Sentiment Shift:** Did the management tone become more optimistic, cautious, or stay the same?
    - **Financial & Operational Highlights:** Compare key performance indicators mentioned in both calls (e.g., revenue growth, margins, order book).
    - **Segment Performance:** Note any changes in the performance of different business segments.
    - **Outlook & Guidance:** Compare the future outlook or guidance provided in each call.
    - **Key Concerns:** Did any concerns from the previous quarter get resolved? Are there any new concerns in the latest quarter?

    Directly quote relevant phrases from BOTH transcripts to support your points.
    """

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"An error occurred during comparison analysis: {e}")
        return "Could not generate analysis. Please check the API key and backend status."


def perform_scuttlebutt_analysis(company_name: str) -> str:
    """Uses the Gemini model to perform an online scuttlebutt analysis."""
    # This function remains unchanged.
    if not API_KEY_CONFIGURED:
        return "Analysis skipped: Google API Key is not configured."
    st.info(f"Performing Philip Fisher-style Scuttlebutt for: **{company_name}**")
    prompt = f"""...""" # Keeping the original prompt for brevity
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"An error occurred during scuttlebutt analysis: {e}")
        return "Could not generate analysis."


def check_sebi_violations(company_name: str) -> str:
    """Uses the Gemini model to check for SEBI violations for a given company."""
    # This function remains unchanged.
    if not API_KEY_CONFIGURED:
        return "Analysis skipped: Google API Key is not configured."
    st.info(f"Checking for SEBI violations for: **{company_name}**")
    prompt = f"""...""" # Keeping the original prompt for brevity
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"An error occurred during SEBI violation check: {e}")
        return "Could not generate analysis."

# --- Streamlit App UI ---

st.title("📄 Qualitative Analysis Agent")
st.markdown("This tool provides analysis based on **Conference Call Transcripts** and **Web-Based Research**.")

# --- Sidebar ---
st.sidebar.header("Instructions")
st.sidebar.markdown("""
1.  **Set up API Key**: Ensure your `.env` file contains your Google API Key.
2.  **Transcript Analysis**:
    - Upload the **two most recent** conference call transcripts.
    - Click 'Analyze Transcripts' to generate insights.
3.  **Web Analysis**:
    - Enter a company name.
    - Click the respective buttons for Scuttlebutt or SEBI checks.
""")

# --- Main App Body ---

# Section 1: Transcript Analysis
st.header("1. Transcript-Based Analysis")
st.markdown("Please upload the two most recent quarterly conference call transcripts for analysis.")

uploaded_files = st.file_uploader(
    "Choose transcript PDF files (Latest and Previous Quarter)",
    type="pdf",
    accept_multiple_files=True
)

if len(uploaded_files) == 2:
    st.success(f"Files ready for analysis: '{uploaded_files[0].name}' and '{uploaded_files[1].name}'.")
    if st.button("Analyze Transcripts", type="primary", disabled=not API_KEY_CONFIGURED):
        with st.spinner("Reading PDFs and generating analysis... This might take a moment."):
            # Assume the first uploaded file is the latest, second is previous.
            # You may want to add a way for the user to specify or sort by date.
            latest_transcript_text = extract_text_from_pdf(uploaded_files[0])
            previous_transcript_text = extract_text_from_pdf(uploaded_files[1])

            if latest_transcript_text and previous_transcript_text:
                st.subheader("📊 Quarterly Analysis Results")

                # New Analysis 1: Positives and Concerns for Latest Quarter
                positives_concerns_prompt = """
                Based ONLY on the provided earnings conference call transcript, identify the key positives and areas of concern.
                Structure your answer with two clear headings: "Positives" and "Areas of Concern".
                Under each heading, use bullet points to list the key takeaways.
                Directly quote relevant phrases or sentences from the transcript to support each point.

                **Transcript:**
                ---
                {transcript}
                ---
                """
                positives_concerns_answer = analyze_transcript(
                    latest_transcript_text,
                    positives_concerns_prompt,
                    "Positives & Concerns (Latest Quarter)"
                )
                with st.expander("Highlights: Positives & Concerns (Latest Quarter)", expanded=True):
                    st.markdown(positives_concerns_answer)

                # New Analysis 2: Compare and Contrast
                comparison_answer = compare_transcripts(
                    latest_transcript_text,
                    previous_transcript_text,
                    "Quarter-over-Quarter Comparison"
                )
                with st.expander("Analysis: Quarter-over-Quarter Comparison", expanded=True):
                    st.markdown(comparison_answer)

            else:
                st.error("Could not extract text from one or both PDFs. Please ensure the files are not empty or corrupted.")

elif len(uploaded_files) > 0:
    st.warning("Please upload exactly two files to enable the comparison analysis.")


st.markdown("---")

# Section 2 & 3: Web-based Analysis
st.header("2. Web-Based Company Analysis")
st.markdown("This analysis is independent of the uploaded PDFs and uses the AI's web search capabilities.")

company_name = st.text_input("Enter Company Name for Web-Based Analysis", value="ABB India Limited")
col1, col2 = st.columns(2)

with col1:
    if st.button("🕵️‍♂️ Run Scuttlebutt Analysis", key="scuttlebutt_btn", disabled=not API_KEY_CONFIGURED):
        if company_name:
            with st.spinner(f"Conducting online research for {company_name}..."):
                scuttlebutt_result = perform_scuttlebutt_analysis(company_name)
                st.subheader(f"Scuttlebutt Analysis for {company_name}")
                st.markdown(scuttlebutt_result)
        else:
            st.warning("Please enter a company name.")

with col2:
    if st.button("⚖️ Check for SEBI Violations", key="sebi_btn", disabled=not API_KEY_CONFIGURED):
        if company_name:
            with st.spinner(f"Checking SEBI records for {company_name}..."):
                sebi_result = check_sebi_violations(company_name)
                st.subheader(f"SEBI Compliance Check for {company_name}")
                st.markdown(sebi_result)
        else:
            st.warning("Please enter a company name.")