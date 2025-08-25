import streamlit as st
import os
from dotenv import load_dotenv

# --- Import Agent Functions ---
# Agent 1: Data Fetcher
from Screener_Download import download_financial_data
# Agent 2: Qualitative Analysis
from qualitative_analysis_agent import run_qualitative_analysis
# Agent 3: Quantitative Analysis (Using your provided agent)
from quantitative_agent import analyze_financials


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
if 'quantitative_results' not in st.session_state:
    st.session_state.quantitative_results = None
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
    st.session_state.quantitative_results = None
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
            
            # --- Agent 2: Quantitative Analysis ---
            with st.spinner(f"Agent 2 (Quantitative Analyst): Analyzing financial data from Excel..."):
                # Call your agent's main function
                st.session_state.quantitative_results = analyze_financials(
                    st.session_state.file_paths.get("excel"),
                    st.session_state.ticker
                )

            # --- Agent 3: Qualitative Analysis ---
            with st.spinner(f"Agent 3 (Qualitative Analyst): Analyzing transcripts and researching {st.session_state.ticker}..."):
                st.session_state.qualitative_results = run_qualitative_analysis(
                    st.session_state.ticker,
                    st.session_state.file_paths.get("latest_transcript"),
                    st.session_state.file_paths.get("previous_transcript")
                )

            st.session_state.analysis_done = True
            st.rerun()

# --- Main Analysis Display Area ---
if st.session_state.analysis_done:
    st.header(f"Analysis Results for {st.session_state.ticker}", divider="rainbow")

    # --- Display Quantitative Analysis ---
    st.subheader("📈 Quantitative Insights")
    quant_results = st.session_state.quantitative_results
    if quant_results:
        with st.expander("AI-Powered Quantitative Analysis", expanded=True):
            # Display the entire markdown report returned by your agent
            st.markdown(quant_results)
    else:
        st.warning("Quantitative analysis could not be performed. The Excel file might be missing or in an incorrect format.")


    # --- Display Qualitative Analysis ---
    st.subheader("📝 Qualitative Insights")
    qual_results = st.session_state.qualitative_results
    if not qual_results:
        st.warning("Qualitative analysis did not return any results.")
    else:
        with st.expander("✅ Positives & 😟 Concerns (Latest Quarter)", expanded=True):
            st.markdown(qual_results.get("positives_and_concerns", "Not available."))

        with st.expander("🔄 Quarter-over-Quarter Comparison", expanded=True):
            st.markdown(qual_results.get("qoq_comparison", "Not available."))

        with st.expander("🕵️‍♂️ Scuttlebutt Analysis (Philip Fisher Style)", expanded=False):
            st.markdown(qual_results.get("scuttlebutt", "Not available."))

        with st.expander("⚖️ SEBI Compliance Check", expanded=False):
            st.markdown(qual_results.get("sebi_check", "Not available."))
else:
    st.info("Enter a stock ticker in the sidebar and click 'Analyze Stock' to begin.")
