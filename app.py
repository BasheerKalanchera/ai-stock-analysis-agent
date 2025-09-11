import streamlit as st
import os
import datetime
from dotenv import load_dotenv
from typing import TypedDict, Dict, Any, List, Annotated
import io

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

# --- UNIFIED SECRETS & ENV VARIABLE HANDLING ---
# This pattern works for both local development (using .env) and Streamlit Cloud
load_dotenv()
SCREENER_EMAIL = st.secrets.get("SCREENER_EMAIL", os.getenv("SCREENER_EMAIL"))
SCREENER_PASSWORD = st.secrets.get("SCREENER_PASSWORD", os.getenv("SCREENER_PASSWORD"))

# --- Directory Setup for Local Development ---
# On Streamlit Cloud, the filesystem is ephemeral. These directories will be temporary.
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
    quant_results_structured: List[Dict[str, Any]] | None
    quant_text_for_synthesis: str | None
    qualitative_results: Dict[str, Any] | None
    final_report: str | None
    log_file_content: Annotated[str, lambda x, y: x + y] # Use Annotated to combine log updates
    pdf_report_bytes: bytes | None # Store PDF in memory
    is_consolidated: bool | None

# --- Agent Nodes ---
def fetch_data_node(state: StockAnalysisState):
    st.toast("Executing Agent 1: Data Fetcher...")
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']
    
    # Initialize log content from the state if it exists
    log_content_accumulator = state.get('log_file_content', "")

    download_path = os.path.abspath(DOWNLOAD_DIRECTORY)
    
    paths = download_financial_data(
        ticker,
        SCREENER_EMAIL,
        SCREENER_PASSWORD,
        download_path,
        is_consolidated
    )
    company_name = paths[0]
    file_paths = {
        "excel": os.path.abspath(paths[1]) if paths[1] and os.path.exists(paths[1]) else None,
        "latest_transcript": os.path.abspath(paths[3]) if paths[3] and os.path.exists(paths[3]) else None,
        "previous_transcript": os.path.abspath(paths[4]) if paths[4] and os.path.exists(paths[4]) else None
    }
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_header = f"AGENT 1: DOWNLOAD SUMMARY for {company_name or ticker}"
    log_entry = (f"## {log_header}\n\n"
                 f"**Timestamp**: {timestamp_str}\n\n"
                 f"**Excel Path**: `{file_paths['excel'] or 'Download Failed'}`\n\n"
                 f"**Latest Transcript**: `{file_paths['latest_transcript'] or 'Download Failed'}`\n\n"
                 f"**Previous Transcript**: `{file_paths['previous_transcript'] or 'Download Failed'}`\n\n---\n\n")
    
    log_content_accumulator += log_entry
        
    return {"company_name": company_name, "file_paths": file_paths, "log_file_content": log_content_accumulator}

def quantitative_analysis_node(state: StockAnalysisState):
    st.toast("Executing Agent 2: Quantitative Analyst...")
    excel_file = state['file_paths'].get('excel')
    log_content_accumulator = state['log_file_content']
    
    if not excel_file or not os.path.exists(excel_file):
        text_results = "Quantitative analysis skipped: Excel file not found or download failed."
        structured_results = [{"type": "text", "content": text_results}]
    else:
        structured_results = analyze_financials(excel_file, state['ticker'])
        text_results = "\n".join([item['content'] for item in structured_results if item['type'] == 'text'])

    log_content_accumulator += f"## AGENT 2: QUANTITATIVE ANALYSIS\n\n{text_results}\n\n---\n\n"
        
    return {
        "quant_results_structured": structured_results,
        "quant_text_for_synthesis": text_results,
        "log_file_content": log_content_accumulator
    }

def qualitative_analysis_node(state: StockAnalysisState):
    st.toast("Executing Agent 3: Qualitative Analyst...")
    company = state['company_name'] or state['ticker']
    log_content_accumulator = state['log_file_content']
    
    results = run_qualitative_analysis(company, state['file_paths'].get("latest_transcript"), state['file_paths'].get("previous_transcript"))
    
    log_entry = "## AGENT 3: QUALITATIVE ANALYSIS\n\n"
    for key, value in results.items():
        log_entry += f"### {key.replace('_', ' ').title()}\n{value}\n\n"
    log_entry += "---\n\n"
    
    log_content_accumulator += log_entry
    return {"qualitative_results": results, "log_file_content": log_content_accumulator}

def synthesis_node(state: StockAnalysisState):
    st.toast("Executing Agent 4: Synthesis Agent...")
    log_content_accumulator = state['log_file_content']
    report = generate_investment_summary(
        state['company_name'] or state['ticker'],
        state['quant_text_for_synthesis'],
        state['qualitative_results']
    )
    
    log_content_accumulator += f"## AGENT 4: FINAL SYNTHESIS REPORT\n\n{report}\n\n---\n\n"
    return {"final_report": report, "log_file_content": log_content_accumulator}

def generate_report_node(state: StockAnalysisState):
    st.toast("Executing Agent 5: Report Generator...")
    
    pdf_buffer = io.BytesIO()
    
    create_pdf_report(
        ticker=state['ticker'],
        company_name=state['company_name'],
        quant_results=state['quant_results_structured'],
        qual_results=state['qualitative_results'],
        final_report=state['final_report'],
        file_path=pdf_buffer
    )
    pdf_buffer.seek(0)
    return {"pdf_report_bytes": pdf_buffer.getvalue()}

# --- Build the Graph ---
workflow = StateGraph(StockAnalysisState)
workflow.add_node("fetch_data", fetch_data_node)
workflow.add_node("quantitative_analysis", quantitative_analysis_node)
workflow.add_node("qualitative_analysis", qualitative_analysis_node)
workflow.add_node("synthesis", synthesis_node)
workflow.add_node("generate_report", generate_report_node)

workflow.set_entry_point("fetch_data")

workflow.add_edge("fetch_data", "quantitative_analysis")
workflow.add_edge("fetch_data", "qualitative_analysis")
workflow.add_edge(["quantitative_analysis", "qualitative_analysis"], "synthesis")
workflow.add_edge("synthesis", "generate_report")
workflow.add_edge("generate_report", END)

app_graph = workflow.compile()

# --- Streamlit UI ---
st.title("🤖 AI Stock Analysis Crew (LangGraph Edition)")
st.header("Automated Investment Analysis Workflow", divider="rainbow")

if 'final_state' not in st.session_state:
    st.session_state.final_state = None
if 'ticker' not in st.session_state:
    st.session_state.ticker = ""

st.sidebar.header("Controls")
ticker_input = st.sidebar.text_input("Enter Stock Ticker", value="RELIANCE")
data_type_choice = st.sidebar.radio(
    "Data Type",
    ["Standalone", "Consolidated"]
)

if ticker_input.strip().upper() != st.session_state.ticker:
    st.session_state.ticker = ticker_input.strip().upper()
    st.session_state.final_state = None

if st.sidebar.button("🚀 Run Full Analysis", type="primary"):
    if st.session_state.ticker:
        st.session_state.final_state = None
        
        is_consolidated = (data_type_choice == "Consolidated")
        inputs = {
            "ticker": st.session_state.ticker,
            "log_file_content": f"# Analysis Log for {st.session_state.ticker}\n\n",
            "is_consolidated": is_consolidated
        }
        
        with st.status("Running Analysis Crew...", expanded=True) as status:
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
                
                # Manually add the ticker to the final result dictionary
                final_state_result['ticker'] = st.session_state.ticker

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

    # --- ADDED: SAVE FILES LOCALLY FOR DEBUGGING ---
    # This block saves a copy of the in-memory log and PDF for your local records.
    ticker = final_state.get('ticker', 'STOCK')
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Save the log file
    if final_state.get('log_file_content'):
        log_filename = f"log_{ticker}_{timestamp}.md"
        log_filepath = os.path.join(LOG_DIRECTORY, log_filename)
        with open(log_filepath, "w", encoding="utf-8") as f:
            f.write(final_state['log_file_content'])
        st.sidebar.info(f"Log file saved to: `{log_filepath}`")

    # Save the PDF report
    if final_state.get('pdf_report_bytes'):
        pdf_filename = f"Report_{ticker}_{timestamp}.pdf"
        pdf_filepath = os.path.join(REPORTS_DIRECTORY, pdf_filename)
        with open(pdf_filepath, "wb") as f:
            f.write(final_state['pdf_report_bytes'])
        st.sidebar.info(f"PDF report saved to: `{pdf_filepath}`")
    # --- END OF ADDED BLOCK ---

    st.sidebar.markdown("---")
    st.sidebar.subheader("Download Report")
    
    if final_state.get('pdf_report_bytes'):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_filename = f"Report_{final_state.get('ticker', 'STOCK')}_{timestamp}.pdf"
        st.sidebar.download_button(
            label="Download PDF Report",
            data=final_state['pdf_report_bytes'],
            file_name=report_filename,
            mime="application/pdf"
        )
    else:
        st.sidebar.error("PDF Report not generated.")

    if final_state.get('final_report'):
        st.subheader("📈📝 Comprehensive Investment Summary")
        st.markdown(final_state['final_report'], unsafe_allow_html=True)

    with st.expander("📂 View Individual Agent Outputs & Logs", expanded=False):
        if final_state.get('log_file_content'):
             st.code(final_state['log_file_content'], language='markdown')
        if final_state.get('quant_text_for_synthesis'):
            st.subheader("📈 Quantitative Insights")
            st.markdown(final_state['quant_text_for_synthesis'])
        if final_state.get('qualitative_results'):
            st.subheader("📝 Qualitative Insights")
            qual_results = final_state['qualitative_results']
            for key, value in qual_results.items():
                st.markdown(f"**{key.replace('_', ' ').title()}:** {value}")
else:
    st.info("Enter a stock ticker in the sidebar and click 'Run Full Analysis' to begin.")