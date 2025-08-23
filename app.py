import streamlit as st
import os
from dotenv import load_dotenv

# --- Import Agent Functions ---
# Agent 1: Data Fetcher
from Screener_Download import download_financial_data
# Agent 2: Qualitative Analysis
from qualitative_analysis_agent import run_qualitative_analysis

# --- Page Configuration ---
st.set_page_config(page_title="AI Stock Analysis Crew", page_icon="🤖", layout="wide")
load_dotenv()

st.title("🤖 AI Stock Analysis Crew")
st.markdown("Enter a stock ticker to perform a comprehensive quantitative and qualitative analysis.")

# --- Session State Initialization ---
if 'ticker' not in st.session_state:
    st.session_state.ticker = ""
if 'analysis_done' not in st.session_state:
    st.session_state.analysis_done = False
if 'qualitative_results' not in st.session_state:
    st.session_state.qualitative_results = None
if 'file_paths' not in st.session_state:
    st.session_state.file_paths = {}


# --- Sidebar Controls ---
st.sidebar.header("Controls")
ticker_input = st.sidebar.text_input("Enter Stock Ticker", value="RELIANCE")

if st.sidebar.button("Analyze Stock", type="primary"):
    # --- Reset state for a new analysis ---
    st.session_state.ticker = ticker_input.strip().upper()
    st.session_state.analysis_done = False
    st.session_state.qualitative_results = None
    st.session_state.file_paths = {}
    
    if not st.session_state.ticker:
        st.error("Please enter a stock ticker.")
    else:
        # --- Run Analysis Pipeline ---
        SCREENER_EMAIL = os.getenv("SCREENER_EMAIL")
        SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")
        
        if not SCREENER_EMAIL or not SCREENER_PASSWORD:
            st.error("Screener credentials not found in .env file. Please set SCREENER_EMAIL and SCREENER_PASSWORD.")
        else:
            DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")
            if not os.path.exists(DOWNLOAD_DIRECTORY): os.makedirs(DOWNLOAD_DIRECTORY)

            # --- Agent 1: Data Fetcher ---
            with st.spinner(f"Agent 1 (Data Fetcher): Downloading financial documents for {st.session_state.ticker}..."):
                excel_path, pdf_path, latest_transcript, prev_transcript = download_financial_data(
                    st.session_state.ticker, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY
                )
                st.session_state.file_paths = {
                    "excel": excel_path,
                    "annual_report": pdf_path,
                    "latest_transcript": latest_transcript,
                    "previous_transcript": prev_transcript
                }
            st.success(f"Agent 1 (Data Fetcher): Download complete.")
            
            # --- Agent 2: Qualitative Analysis ---
            with st.spinner(f"Agent 2 (Qualitative Analyst): Analyzing transcripts and researching {st.session_state.ticker}... This may take a few moments."):
                results = run_qualitative_analysis(
                    st.session_state.ticker,
                    st.session_state.file_paths.get("latest_transcript"),
                    st.session_state.file_paths.get("previous_transcript")
                )
                st.session_state.qualitative_results = results

            st.session_state.analysis_done = True
            st.rerun() # Rerun the script to display the results below

# --- Main Analysis Display Area ---
if st.session_state.analysis_done:
    st.header(f"Analysis Results for {st.session_state.ticker}", divider="rainbow")

    results = st.session_state.qualitative_results
    if not results:
        st.warning("Qualitative analysis did not return any results.")
    else:
        # --- Display Transcript Analysis ---
        st.subheader("Transcript-Based Insights")
        
        with st.expander("✅ Positives & 😟 Concerns (Latest Quarter)", expanded=True):
            if results.get("positives_and_concerns"):
                st.markdown(results["positives_and_concerns"])
            else:
                st.info("Analysis on positives and concerns could not be generated.")

        with st.expander("🔄 Quarter-over-Quarter Comparison", expanded=True):
            if results.get("qoq_comparison"):
                st.markdown(results["qoq_comparison"])
            else:
                st.info("Quarterly comparison could not be generated.")

        # --- Display Web-Based Analysis ---
        st.subheader("Web-Based Insights")

        with st.expander("🕵️‍♂️ Scuttlebutt Analysis (Philip Fisher Style)", expanded=False):
            # FIXED: Corrected the key from "scuttlebut" to "scuttlebutt"
            if results.get("scuttlebutt"):
                st.markdown(results["scuttlebutt"])
            else:
                st.info("Scuttlebutt analysis could not be generated.")

        with st.expander("⚖️ SEBI Compliance Check", expanded=False):
            if results.get("sebi_check"):
                st.markdown(results["sebi_check"])
            else:
                st.info("SEBI compliance check could not be generated.")
else:
    st.info("Enter a stock ticker in the sidebar and click 'Analyze Stock' to begin.")

