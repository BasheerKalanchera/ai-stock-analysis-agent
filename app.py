import streamlit as st
import os
from dotenv import load_dotenv

# --- Import Agent Functions ---
from Screener_Download import download_financial_data
from qualitative_analysis_agent import run_qualitative_analysis
from quantitative_agent import analyze_financials
from synthesis_agent import generate_investment_summary

# --- Page Configuration ---
st.set_page_config(page_title="AI Stock Analysis Crew", page_icon="🤖", layout="wide")
load_dotenv()

st.title("🤖 AI Stock Analysis Crew")
st.markdown("Enter a stock ticker and run the analysis agents step-by-step.")

# --- Session State Initialization ---
if 'ticker' not in st.session_state:
    st.session_state.ticker = ""
if 'company_name' not in st.session_state:
    st.session_state.company_name = ""
if 'data_downloaded' not in st.session_state:
    st.session_state.data_downloaded = False
if 'qualitative_results' not in st.session_state:
    st.session_state.qualitative_results = None
if 'quantitative_results' not in st.session_state:
    st.session_state.quantitative_results = None
if 'final_report' not in st.session_state:
    st.session_state.final_report = None
if 'file_paths' not in st.session_state:
    st.session_state.file_paths = {}

# --- Helper function to reset state ---
def reset_analysis_state():
    """Clears all previous results and file paths."""
    st.session_state.data_downloaded = False
    st.session_state.qualitative_results = None
    st.session_state.quantitative_results = None
    st.session_state.final_report = None
    st.session_state.file_paths = {}
    st.session_state.company_name = ""

# --- Sidebar Controls ---
st.sidebar.header("Controls")
ticker_input = st.sidebar.text_input("Enter Stock Ticker", value="RELIANCE")

if ticker_input.strip().upper() != st.session_state.ticker:
    st.session_state.ticker = ticker_input.strip().upper()
    reset_analysis_state()
    st.info(f"Ticker changed to {st.session_state.ticker}. Please run the agents.")

# --- Agent Buttons ---
st.sidebar.subheader("Run Agents Manually")

# Step 1: Data Fetcher
if st.sidebar.button("Step 1: Download Financial Data"):
    if st.session_state.ticker:
        reset_analysis_state()
        DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")
        if not os.path.exists(DOWNLOAD_DIRECTORY): os.makedirs(DOWNLOAD_DIRECTORY)

        with st.spinner(f"Agent 1 (Data Fetcher): Downloading documents for {st.session_state.ticker}..."):
            company_name, excel_path, _, latest_transcript, prev_transcript = download_financial_data(
                st.session_state.ticker, os.getenv("SCREENER_EMAIL"), os.getenv("SCREENER_PASSWORD"), DOWNLOAD_DIRECTORY
            )
            st.session_state.company_name = company_name
            st.session_state.file_paths = {
                "excel": excel_path,
                "latest_transcript": latest_transcript,
                "previous_transcript": prev_transcript
            }
            st.session_state.data_downloaded = True
        st.success("Agent 1 (Data Fetcher): Download complete.")
        st.rerun()

# Step 2: Quantitative Analysis
if st.sidebar.button("Step 2: Run Quantitative Analysis", disabled=not st.session_state.data_downloaded):
    excel_file = st.session_state.file_paths.get("excel")
    if not excel_file or not os.path.exists(excel_file):
        st.error("Quantitative analysis requires the Excel file, which was not found. Please run Step 1.")
    else:
        with st.spinner("Agent 2 (Quantitative Analyst): Analyzing financial data..."):
            st.session_state.quantitative_results = analyze_financials(excel_file, st.session_state.ticker)
        st.success("Agent 2 (Quantitative Analyst): Analysis complete.")

# Step 3: Qualitative Analysis
if st.sidebar.button("Step 3: Run Qualitative Analysis", disabled=not st.session_state.data_downloaded):
    latest_transcript = st.session_state.file_paths.get("latest_transcript")
    prev_transcript = st.session_state.file_paths.get("previous_transcript")
    if not (st.session_state.company_name and st.session_state.company_name != st.session_state.ticker):
         st.warning("Could not find company name, web-based analysis might be less accurate.")

    with st.spinner(f"Agent 3 (Qualitative Analyst): Researching {st.session_state.company_name or st.session_state.ticker}..."):
        st.session_state.qualitative_results = run_qualitative_analysis(
            st.session_state.company_name or st.session_state.ticker,
            latest_transcript,
            prev_transcript
        )
    st.success("Agent 3 (Qualitative Analyst): Analysis complete.")

# --- Button for Final Agent: Synthesis ---
st.sidebar.markdown("---")

# --- KEY CHANGE START ---
# Changed the logic from 'and' to 'or'.
# The button is now enabled if EITHER quantitative OR qualitative analysis is complete.
synthesis_disabled = not (st.session_state.quantitative_results or st.session_state.qualitative_results)
# --- KEY CHANGE END ---

if st.sidebar.button("Step 4: Generate Final Report", type="primary", disabled=synthesis_disabled):
    with st.spinner("Agent 4 (Synthesis Agent): Compiling the final investment report..."):
        st.session_state.final_report = generate_investment_summary(
            st.session_state.company_name or st.session_state.ticker,
            st.session_state.quantitative_results,
            st.session_state.qualitative_results
        )
    st.success("Agent 4 (Synthesis Agent): Final report generated.")

# --- Main Analysis Display Area ---
st.header(f"Analysis Results for {st.session_state.company_name or st.session_state.ticker}", divider="rainbow")

if st.session_state.final_report:
    st.subheader("📈📝 Comprehensive Investment Summary")
    st.markdown(st.session_state.final_report)

with st.expander("📂 View Individual Agent Outputs & Download Status", expanded=False):
    if st.session_state.data_downloaded:
        st.subheader("Download Status")
        files = st.session_state.file_paths
        st.success(f"**Excel Report:** `{files.get('excel', 'Not found')}`")
        st.info(f"**Latest Transcript:** `{files.get('latest_transcript', 'Not found')}`")
        st.info(f"**Previous Transcript:** `{files.get('previous_transcript', 'Not found')}`")
    else:
        st.info("Start by entering a stock ticker and clicking 'Step 1: Download Financial Data' in the sidebar.")

    if st.session_state.quantitative_results:
        st.subheader("📈 Quantitative Insights")
        st.markdown(st.session_state.quantitative_results)

    if st.session_state.qualitative_results:
        st.subheader("📝 Qualitative Insights")
        qual_results = st.session_state.qualitative_results
        st.markdown(f"**Positives & Concerns:** {qual_results.get('positives_and_concerns', 'N/A')}")
        st.markdown(f"**QoQ Comparison:** {qual_results.get('qoq_comparison', 'N/A')}")
        st.markdown(f"**Scuttlebutt Analysis:** {qual_results.get('scuttlebutt', 'N/A')}")
        st.markdown(f"**SEBI Check:** {qual_results.get('sebi_check', 'N/A')}")