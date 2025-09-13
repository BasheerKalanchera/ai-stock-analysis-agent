import streamlit as st
import os
import datetime
from dotenv import load_dotenv
from typing import TypedDict, Dict, Any, List

# --- LangGraph Imports ---
from langgraph.graph import StateGraph, END

# --- Import Agent Functions ---
from Screener_Download import download_financial_data
from qualitative_analysis_agent import run_qualitative_analysis
from quantitative_agent import analyze_financials
from synthesis_agent import generate_investment_summary
from report_generator import create_pdf_report

# --- Page Configuration ---
st.set_page_config(page_title="AI Stock Analysis Crew (LangGraph)", page_icon="🤖", layout="wide")
load_dotenv()

# --- Directory Setup ---
LOG_DIRECTORY = "logs"
REPORTS_DIRECTORY = "reports"
DOWNLOAD_DIRECTORY = "downloads"
for directory in [LOG_DIRECTORY, REPORTS_DIRECTORY, DOWNLOAD_DIRECTORY]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# --- Define Graph State ---
class StockAnalysisState(TypedDict):
    ticker: str
    company_name: str | None
    file_paths: Dict[str, str]
    # NEW: Structured output from quant agent (text + charts) for the PDF
    quant_results_structured: List[Dict[str, Any]] | None
    # NEW: Text-only output for the synthesis agent and logs
    quant_text_for_synthesis: str | None
    qualitative_results: Dict[str, Any] | None
    final_report: str | None
    log_file: str | None
    pdf_report_path: str | None
    # Add new state variable to pass the user's choice
    is_consolidated: bool | None

# --- Agent Nodes ---
def fetch_data_node(state: StockAnalysisState):
    st.toast("Executing Agent 1: Data Fetcher...")
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']

    if state.get('log_file'):
        log_file_path = state['log_file']
    else:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{ticker}_{timestamp}.md"
        log_file_path = os.path.join(LOG_DIRECTORY, log_filename)

    download_path = os.path.abspath(DOWNLOAD_DIRECTORY)
    # MODIFIED: Pass the is_consolidated flag to the download function
    paths = download_financial_data(ticker, os.getenv("SCREENER_EMAIL"), os.getenv("SCREENER_PASSWORD"), download_path, is_consolidated)
    company_name = paths[0]
    file_paths = {
        "excel": os.path.abspath(paths[1]) if paths[1] and os.path.exists(paths[1]) else None,
        "latest_transcript": os.path.abspath(paths[3]) if paths[3] and os.path.exists(paths[3]) else None,
        "previous_transcript": os.path.abspath(paths[4]) if paths[4] and os.path.exists(paths[4]) else None
    }
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_header = f"AGENT 1: DOWNLOAD SUMMARY for {company_name or ticker}"
    log_content = (f"**Timestamp**: {timestamp_str}\n\n"
                   f"**Excel Path**: `{file_paths['excel'] or 'Download Failed'}`\n\n"
                   f"**Latest Transcript**: `{file_paths['latest_transcript'] or 'Download Failed'}`\n\n"
                   f"**Previous Transcript**: `{file_paths['previous_transcript'] or 'Download Failed'}`")
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(f"## {log_header}\n\n{log_content}\n\n---\n\n")
        
    return {"company_name": company_name, "file_paths": file_paths, "log_file": log_file_path}

def quantitative_analysis_node(state: StockAnalysisState):
    st.toast("Executing Agent: Quantitative Analyst...")
    excel_file = state['file_paths'].get('excel')
    
    if not excel_file or not os.path.exists(excel_file):
        text_results = f"Quantitative analysis skipped: Excel file not found at '{excel_file}'."
        structured_results = [{"type": "text", "content": text_results}]
    else:
        structured_results = analyze_financials(excel_file, state['ticker'])
        text_results = "\n".join([item['content'] for item in structured_results if item['type'] == 'text'])

    with open(state['log_file'], "a", encoding="utf-8") as f:
        f.write(f"## AGENT: QUANTITATIVE ANALYSIS\n\n{text_results}\n\n---\n\n")
        
    return {
        "quant_results_structured": structured_results,
        "quant_text_for_synthesis": text_results
    }

def qualitative_analysis_node(state: StockAnalysisState):
    return {}

def synthesis_node(state: StockAnalysisState):
    return {}

def generate_report_node(state: StockAnalysisState):
    st.toast("Executing Agent: Report Generator...")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_filename = f"Report_{state['ticker']}_{timestamp}.pdf"
    pdf_path = os.path.join(REPORTS_DIRECTORY, report_filename)
    
    # Safely get data from state, providing placeholders if agents were skipped
    qualitative_data = state.get('qualitative_results') or {
        "Analysis Skipped": "Qualitative analysis was not performed in this workflow."
    }
    synthesis_data = state.get('final_report') or "## Comprehensive Investment Summary\n\n*The Synthesis Agent was bypassed in this workflow. This report contains quantitative analysis only.*"
    
    create_pdf_report(
        ticker=state['ticker'],
        company_name=state['company_name'],
        quant_results=state['quant_results_structured'],
        qual_results=qualitative_data,
        final_report=synthesis_data,
        file_path=pdf_path
    )
    return {"pdf_report_path": pdf_path}

# --- Build the Graph ---
workflow = StateGraph(StockAnalysisState)

# Add all nodes to the graph
workflow.add_node("fetch_data", fetch_data_node)
workflow.add_node("quantitative_analysis", quantitative_analysis_node)
workflow.add_node("qualitative_analysis", qualitative_analysis_node)
workflow.add_node("synthesis", synthesis_node)
workflow.add_node("generate_report", generate_report_node)

# --- >>> ORIGINAL FULL WORKFLOW (COMMENTED OUT) <<< ---
workflow.set_entry_point("fetch_data")
workflow.add_edge("fetch_data", "quantitative_analysis")
#workflow.add_edge("fetch_data", "qualitative_analysis")
#workflow.add_edge(["quantitative_analysis", "qualitative_analysis"], "synthesis")
#workflow.add_edge("synthesis", "generate_report")
workflow.add_edge("quantitative_analysis", END)

app_graph = workflow.compile()

# --- Streamlit UI ---
st.title("🤖 AI Stock Analysis Crew (Test Stub)")
st.header("Automated Investment Analysis Workflow", divider="rainbow")

if 'final_state' not in st.session_state:
    st.session_state.final_state = None
if 'ticker' not in st.session_state:
    st.session_state.ticker = ""

st.sidebar.header("Controls")
ticker_input = st.sidebar.text_input("Enter Stock Ticker", value="JASH")
# NEW: UI for selecting data type
data_type_choice = st.sidebar.radio("Data Type", ["Standalone", "Consolidated"])

if ticker_input.strip().upper() != st.session_state.ticker:
    st.session_state.ticker = ticker_input.strip().upper()
    st.session_state.final_state = None

# MODIFIED: Changed the button text to reflect the full workflow
if st.sidebar.button("🚀 Run Full Analysis", type="primary"):
    if st.session_state.ticker:
        st.session_state.final_state = None
        
        ticker = st.session_state.ticker
        is_consolidated = (data_type_choice == "Consolidated")

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{ticker}_{timestamp}.md"
        log_file_path = os.path.join(LOG_DIRECTORY, log_filename)

        # Assemble the initial state to pass to the graph
        inputs = {
            "ticker": ticker,
            "log_file": log_file_path,
            "is_consolidated": is_consolidated # Pass the new flag
        }
        
        with st.status("Running Full Analysis...", expanded=True) as status:
            final_state_result = {} 
            try:
                for event in app_graph.stream(inputs):
                    for node_name, node_output in event.items():
                        if node_name == "fetch_data":
                            status.update(label="Executing Agent 2 & 3: Quantitative & Qualitative Analysis...")
                        elif node_name == "synthesis":
                            status.update(label="Executing Agent 4: Generating Final Summary...")
                        elif node_name == "generate_report":
                             status.update(label="Executing Agent 5: Creating PDF Report...")
                        
                        if node_output:
                            final_state_result.update(node_output)
                
                st.session_state.final_state = final_state_result
                status.update(label="Analysis Complete!", state="complete", expanded=False)
                st.rerun()
            except Exception as e:
                status.update(label=f"An error occurred: {e}", state="error")
                st.error(f"Workflow failed: {e}")
    else:
        st.sidebar.warning("Please enter a stock ticker.")

if st.session_state.final_state:
    final_state = st.session_state.final_state
    st.header(f"Analysis Results for {final_state.get('company_name') or final_state.get('ticker')}", divider="rainbow")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Download Report")
    
    if final_state.get('pdf_report_path') and os.path.exists(final_state['pdf_report_path']):
        with open(final_state['pdf_report_path'], "rb") as pdf_file:
            st.sidebar.download_button(
                label="Download PDF Report",
                data=pdf_file,
                file_name=os.path.basename(final_state['pdf_report_path']),
                mime="application/pdf"
            )
    else:
        st.sidebar.error("PDF Report not found.")

    if final_state.get('final_report'):
        st.subheader("📈📝 Comprehensive Investment Summary")
        st.markdown(final_state['final_report'], unsafe_allow_html=True)

    with st.expander("📂 View Individual Agent Outputs & Logs", expanded=False):
        st.info(f"Full analysis log file: `{final_state.get('log_file', 'N/A')}`")
        if final_state.get('quant_text_for_synthesis'):
            st.subheader("📈 Quantitative Insights")
            st.markdown(final_state['quant_text_for_synthesis'])
        if final_state.get('qualitative_results'):
            st.subheader("📝 Qualitative Insights")
            qual_results = final_state['qualitative_results']
            for key, value in qual_results.items():
                st.markdown(f"**{key.replace('_', ' ').title()}:** {value}")
else:
    st.info("Enter a stock ticker in the sidebar and click the button to begin.")
