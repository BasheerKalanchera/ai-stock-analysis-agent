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
st.set_page_config(page_title="AI Stock Analysis Crew", page_icon="🤖", layout="wide")
load_dotenv() # Load .env file for local development

# --- CENTRALIZED SECRET & CONFIGURATION HANDLING ---
agent_configs = {}
try:
    # This will succeed on Streamlit Cloud, setting IS_CLOUD_ENV to True
    agent_configs = {
        "SCREENER_EMAIL": st.secrets["SCREENER_EMAIL"],
        "SCREENER_PASSWORD": st.secrets["SCREENER_PASSWORD"],
        "GOOGLE_API_KEY": st.secrets["GOOGLE_API_KEY"],
        "LITE_MODEL_NAME": st.secrets.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
        "HEAVY_MODEL_NAME": st.secrets.get("HEAVY_MODEL_NAME", "gemini-1.5-pro"),
        "IS_CLOUD_ENV": True # Explicitly set environment flag
    }
except (st.errors.StreamlitAPIException, KeyError) as e:
    # This will happen locally if secrets.toml doesn't exist or is incomplete
    if "No secrets found" in str(e) or isinstance(e, KeyError):
        agent_configs = {
            "SCREENER_EMAIL": os.getenv("SCREENER_EMAIL"),
            "SCREENER_PASSWORD": os.getenv("SCREENER_PASSWORD"),
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
            "LITE_MODEL_NAME": os.getenv("LITE_MODEL_NAME", "gemini-1.5-flash"),
            "HEAVY_MODEL_NAME": os.getenv("HEAVY_MODEL_NAME", "gemini-1.5-pro"),
            "IS_CLOUD_ENV": False # Explicitly set environment flag
        }
    else:
        raise e

# Validate that essential secrets were loaded
essential_keys = ["SCREENER_EMAIL", "SCREENER_PASSWORD", "GOOGLE_API_KEY"]
missing_keys = [key for key in essential_keys if not agent_configs.get(key)]

if missing_keys:
    st.error(f"The following secrets are missing: {', '.join(missing_keys)}. Please set them in your .env file locally or in st.secrets for cloud deployment.")
    st.stop()
# --- END OF CONFIGURATION HANDLING ---


# --- Define Graph State ---
class StockAnalysisState(TypedDict):
    """
    State container for the stock analysis workflow.
    All file data is stored in memory using BytesIO objects.
    """
    ticker: str
    company_name: str | None
    file_data: Dict[str, io.BytesIO]
    quant_results_structured: List[Dict[str, Any]] | None
    quant_text_for_synthesis: str | None
    qualitative_results: Dict[str, Any] | None
    final_report: str | None
    log_file_content: Annotated[str, lambda x, y: x + y]
    pdf_report_bytes: bytes | None
    is_consolidated: bool | None
    agent_config: Dict[str, Any] # Holds all secrets and configs

# --- Agent Nodes ---
def fetch_data_node(state: StockAnalysisState):
    st.toast("Executing Agent 1: Data Fetcher...")
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']
    config = state['agent_config'] # Get config from state
    
    log_content_accumulator = state.get('log_file_content', "")

    # Pass the entire config object
    company_name, file_data = download_financial_data(
        ticker,
        config,
        is_consolidated
    )
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_header = f"AGENT 1: DOWNLOAD SUMMARY for {company_name or ticker}"
    log_entry = (f"## {log_header}\n\n"
                 f"**Timestamp**: {timestamp_str}\n\n"
                 f"**Excel Data**: {'Downloaded' if file_data.get('excel') else 'Failed'}\n\n"
                 f"**Latest Transcript**: {'Downloaded' if file_data.get('latest_transcript') else 'Failed'}\n\n"
                 f"**Previous Transcript**: {'Downloaded' if file_data.get('previous_transcript') else 'Failed'}\n\n---\n\n")
    
    log_content_accumulator += log_entry
        
    return {
        "company_name": company_name, 
        "file_data": file_data,
        "log_file_content": log_content_accumulator
    }

def quantitative_analysis_node(state: StockAnalysisState):
    st.toast("Executing Agent 2: Quantitative Analyst...")
    excel_data = state['file_data'].get('excel')
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    if not excel_data:
        text_results = "Quantitative analysis skipped: Excel data not found."
        structured_results = [{"type": "text", "content": text_results}]
    else:
        structured_results = analyze_financials(excel_data, state['ticker'], config)
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
    config = state['agent_config']
    
    results = run_qualitative_analysis(
        company, 
        state['file_data'].get("latest_transcript"),
        state['file_data'].get("previous_transcript"),
        config
    )
    
    log_entry = "## AGENT 3: QUALITATIVE ANALYSIS\n\n"
    for key, value in results.items():
        log_entry += f"### {key.replace('_', ' ').title()}\n{value}\n\n"
    log_entry += "---\n\n"
    
    log_content_accumulator += log_entry
    return {"qualitative_results": results, "log_file_content": log_content_accumulator}

def synthesis_node(state: StockAnalysisState):
    st.toast("Executing Agent 4: Synthesis Agent...")
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    quant_text = state.get('quant_text_for_synthesis', "Quantitative analysis was not performed.")
    
    report = generate_investment_summary(
        state['company_name'] or state['ticker'],
        quant_text,
        state['qualitative_results'],
        config
    )
    
    log_content_accumulator += f"## AGENT 4: FINAL SYNTHESIS REPORT\n\n{report}\n\n---\n\n"
    return {"final_report": report, "log_file_content": log_content_accumulator}

def generate_report_node(state: StockAnalysisState):
    st.toast("Executing Agent 5: Report Generator...")
    
    pdf_buffer = io.BytesIO()
    
    create_pdf_report(
        ticker=state['ticker'],
        company_name=state.get('company_name'),
        quant_results=state.get('quant_results_structured', []),
        qual_results=state.get('qualitative_results', {}),
        final_report=state.get('final_report', "Report could not be fully generated."),
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
st.title("🤖 AI Stock Analysis Crew")
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
            "is_consolidated": is_consolidated,
            "agent_config": agent_configs
        }
        
        with st.status("Running Analysis Crew...", expanded=True) as status:
            final_state_result = {}
            try:
                for event in app_graph.stream(inputs):
                    for node_name, node_output in event.items():
                        status_messages = {
                            "fetch_data": "Downloading financial data...",
                            "quantitative_analysis": "Running quantitative analysis...",
                            "qualitative_analysis": "Analyzing qualitative data...",
                            "synthesis": "Generating final summary...",
                            "generate_report": "Creating PDF report..."
                        }
                        if node_name in status_messages:
                            status.update(label=status_messages[node_name])
                        
                        if node_output:
                            final_state_result.update(node_output)
                
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