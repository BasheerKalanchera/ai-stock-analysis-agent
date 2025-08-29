import streamlit as st
import os
import datetime
from dotenv import load_dotenv

# --- Import Agent Functions ---
from Screener_Download import download_financial_data
from qualitative_analysis_agent import run_qualitative_analysis
from quantitative_agent import analyze_financials
from synthesis_agent import generate_investment_summary
# Import the new PDF generator
from report_generator import create_pdf_report

# --- Page Configuration ---
st.set_page_config(page_title="AI Stock Analysis Crew", page_icon="🤖", layout="wide")
load_dotenv()

# --- Directory Setup ---
LOG_DIRECTORY = "logs"
REPORTS_DIRECTORY = "reports"
for directory in [LOG_DIRECTORY, REPORTS_DIRECTORY]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# --- Logging Function (for Markdown) ---
def write_to_log(log_file_path, header, content):
    """Appends a header and content to a specified log file using Markdown formatting."""
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(f"## {header}\n\n")
        if isinstance(content, dict):
            for key, value in content.items():
                f.write(f"### {key.replace('_', ' ').title()}\n{value}\n\n")
        else:
            f.write(f"{str(content)}\n\n")
        f.write("---\n\n")

# --- Session State Initialization ---
if 'ticker' not in st.session_state: st.session_state.ticker = ""
if 'company_name' not in st.session_state: st.session_state.company_name = ""
if 'log_file' not in st.session_state: st.session_state.log_file = ""
if 'pdf_report_path' not in st.session_state: st.session_state.pdf_report_path = ""
if 'data_downloaded' not in st.session_state: st.session_state.data_downloaded = False
if 'qualitative_results' not in st.session_state: st.session_state.qualitative_results = None
if 'quantitative_results' not in st.session_state: st.session_state.quantitative_results = None
if 'final_report' not in st.session_state: st.session_state.final_report = None
if 'file_paths' not in st.session_state: st.session_state.file_paths = {}


def reset_analysis_state():
    """Clears all previous results and file paths for a new analysis session."""
    st.session_state.data_downloaded = False
    st.session_state.qualitative_results = None
    st.session_state.quantitative_results = None
    st.session_state.final_report = None
    st.session_state.file_paths = {}
    st.session_state.company_name = ""
    st.session_state.log_file = ""
    st.session_state.pdf_report_path = ""

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
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{st.session_state.ticker}_{timestamp}.md"
        st.session_state.log_file = os.path.join(LOG_DIRECTORY, log_filename)
        
        DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")
        if not os.path.exists(DOWNLOAD_DIRECTORY): os.makedirs(DOWNLOAD_DIRECTORY)

        with st.spinner(f"Agent 1 (Data Fetcher): Downloading for {st.session_state.ticker}..."):
            paths = download_financial_data(st.session_state.ticker, os.getenv("SCREENER_EMAIL"), os.getenv("SCREENER_PASSWORD"), DOWNLOAD_DIRECTORY)
            st.session_state.company_name = paths[0]
            st.session_state.file_paths = {
                "excel": paths[1],
                "latest_transcript": paths[3],
                "previous_transcript": paths[4]
            }
            st.session_state.data_downloaded = True
            
            log_header = f"AGENT 1: DOWNLOAD SUMMARY for {st.session_state.company_name or st.session_state.ticker}"
            log_content = f"**Timestamp**: {timestamp}\n\n**Excel Path**: `{paths[1]}`\n\n**Latest Transcript**: `{paths[3]}`\n\n**Previous Transcript**: `{paths[4]}`"
            write_to_log(st.session_state.log_file, log_header, log_content)

        st.success(f"Downloads complete. Log saved to: {st.session_state.log_file}")
        st.rerun()

# Step 2: Quantitative Analysis
if st.sidebar.button("Step 2: Run Quantitative Analysis", disabled=not st.session_state.data_downloaded):
    excel_file = st.session_state.file_paths.get("excel")
    if not excel_file or not os.path.exists(excel_file):
        st.error("Excel file not found. Please run Step 1.")
    else:
        with st.spinner("Agent 2 (Quantitative Analyst): Analyzing financials..."):
            results = analyze_financials(excel_file, st.session_state.ticker)
            st.session_state.quantitative_results = results
            write_to_log(st.session_state.log_file, "AGENT 2: QUANTITATIVE ANALYSIS", results)
        st.success("Quantitative analysis complete. Results saved to log.")

# Step 3: Qualitative Analysis
if st.sidebar.button("Step 3: Run Qualitative Analysis", disabled=not st.session_state.data_downloaded):
    company = st.session_state.company_name or st.session_state.ticker
    with st.spinner(f"Agent 3 (Qualitative Analyst): Researching {company}..."):
        results = run_qualitative_analysis(company, st.session_state.file_paths.get("latest_transcript"), st.session_state.file_paths.get("previous_transcript"))
        st.session_state.qualitative_results = results
        write_to_log(st.session_state.log_file, "AGENT 3: QUALITATIVE ANALYSIS", results)
    st.success("Qualitative analysis complete. Results saved to log.")
    
# Step 4: Generate Final Report
st.sidebar.markdown("---")
synthesis_disabled = not (st.session_state.quantitative_results or st.session_state.qualitative_results)
if st.sidebar.button("Step 4: Generate Final Report", type="primary", disabled=synthesis_disabled):
    with st.spinner("Agent 4 (Synthesis Agent): Compiling final report..."):
        report = generate_investment_summary(st.session_state.company_name or st.session_state.ticker, st.session_state.quantitative_results, st.session_state.qualitative_results)
        st.session_state.final_report = report
        write_to_log(st.session_state.log_file, "AGENT 4: FINAL SYNTHESIS REPORT", report)
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_filename = f"Report_{st.session_state.ticker}_{timestamp}.pdf"
        pdf_path = os.path.join(REPORTS_DIRECTORY, report_filename)
        
        create_pdf_report(
            st.session_state.ticker,
            st.session_state.company_name,
            st.session_state.quantitative_results,
            st.session_state.qualitative_results,
            st.session_state.final_report,
            pdf_path
        )
        st.session_state.pdf_report_path = pdf_path
        
    st.success("Final report generated and saved as PDF.")

# --- PDF Download Button ---
if st.session_state.final_report:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Download Report")
    with open(st.session_state.pdf_report_path, "rb") as pdf_file:
        st.sidebar.download_button(
            label="Download PDF Report",
            data=pdf_file,
            file_name=os.path.basename(st.session_state.pdf_report_path),
            mime="application/pdf"
        )

# --- Main Display Area ---
st.title("🤖 AI Stock Analysis Crew")
st.header(f"Analysis Results for {st.session_state.company_name or st.session_state.ticker}", divider="rainbow")

if st.session_state.final_report:
    st.subheader("📈📝 Comprehensive Investment Summary")
    st.markdown(st.session_state.final_report, unsafe_allow_html=True)

with st.expander("📂 View Individual Agent Outputs & Download Status", expanded=False):
    if st.session_state.data_downloaded:
        st.subheader("Download Status")
        st.info(f"Analysis log file: `{st.session_state.log_file}`")
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