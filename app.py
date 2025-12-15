import streamlit as st
import os
import datetime
from dotenv import load_dotenv
from typing import TypedDict, Dict, Any, List, Annotated
import io
import time
import pandas as pd
import zipfile
import copy

# --- LangGraph Imports ---
from langgraph.graph import StateGraph, END

# --- Import Agent Functions ---
from Screener_Download import download_financial_data
# Note: Added run_earnings_analysis_standalone to imports
from qualitative_analysis_agent import (
    run_qualitative_analysis, 
    run_isolated_sebi_check, 
    run_earnings_analysis_standalone
)
from quantitative_agent import analyze_financials
from valuation_agent import run_valuation_analysis
from synthesis_agent import generate_investment_summary
from report_generator import create_pdf_report

# --- NEW IMPORTS: Strategy & Risk ---
from strategy_agent import strategy_analyst_agent
from risk_agent import risk_analyst_agent
# ------------------------------------

# --- Page Configuration ---
st.set_page_config(page_title="AI Stock Analysis Crew", page_icon="🤖", layout="wide")
load_dotenv()

# --- Configuration & Secret Handling ---
def get_secret(key, default=None):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except (FileNotFoundError, KeyError, st.errors.StreamlitAPIException):
        return os.getenv(key, default)

is_cloud_env = False
try:
    if st.secrets: 
        is_cloud_env = True
except (FileNotFoundError, st.errors.StreamlitAPIException):
    is_cloud_env = False

agent_configs = {
    "SCREENER_EMAIL": get_secret("SCREENER_EMAIL"),
    "SCREENER_PASSWORD": get_secret("SCREENER_PASSWORD"),
    "GOOGLE_API_KEY": get_secret("GOOGLE_API_KEY"),
    "LITE_MODEL_NAME": get_secret("LITE_MODEL_NAME", "gemini-2.0-flash-lite"),
    "HEAVY_MODEL_NAME": get_secret("HEAVY_MODEL_NAME", "gemini-2.0-flash"),
    "FALLBACK_REQUEST_MODEL": "gemini-2.0-flash-lite", 
    "FALLBACK_TOKEN_MODEL": "gemini-2.0-flash",
    "TAVILY_API_KEY": get_secret("TAVILY_API_KEY"),
    "IS_CLOUD_ENV": is_cloud_env
}

# --- Resilience Logic ---
def execute_with_fallback(func, log_accumulator, agent_name, *args, **kwargs):
    config = kwargs.get('config')
    if not config and len(args) > 0 and isinstance(args[-1], dict):
        config = args[-1]
    
    if not config:
        return func(*args, **kwargs)

    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "quota" in error_str or "resource exhausted" in error_str:
            if "token" in error_str:
                fallback_model = agent_configs['FALLBACK_TOKEN_MODEL']
                reason_msg = "Token Limit (TPM)"
            else:
                fallback_model = agent_configs['FALLBACK_REQUEST_MODEL']
                reason_msg = "Request Limit (RPD/RPM)"

            backup_config = copy.deepcopy(config)
            backup_config['LITE_MODEL_NAME'] = fallback_model
            backup_config['HEAVY_MODEL_NAME'] = fallback_model
            
            if 'config' in kwargs: kwargs['config'] = backup_config
            new_args = list(args)
            if len(new_args) > 0 and isinstance(new_args[-1], dict): new_args[-1] = backup_config
            
            time.sleep(5)
            try:
                return func(*tuple(new_args), **kwargs)
            except Exception as e2:
                return f"❌ Agent {agent_name} Failed after Retry ({reason_msg}): {str(e2)}"
        else:
            raise e

# --- Define Graph State ---
class StockAnalysisState(TypedDict):
    ticker: str
    company_name: str | None
    file_data: Dict[str, io.BytesIO]
    peer_data: pd.DataFrame | None
    quant_results_structured: List[Dict[str, Any]] | None
    quant_text_for_synthesis: str | None
    strategy_results: str | None
    risk_results: str | None
    qualitative_results: Dict[str, Any] | None
    valuation_results: Dict[str, Any] | None
    final_report: str | None
    log_file_content: Annotated[str, lambda x, y: x + y]
    pdf_report_bytes: bytes | None
    is_consolidated: bool | None
    agent_config: Dict[str, Any]
    workflow_mode: str | None # Track which mode was run

# ==============================================================================
# 1. FULL WORKFLOW NODES
# ==============================================================================

def fetch_data_node(state: StockAnalysisState):
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    company_name, file_data, peer_data = download_financial_data(ticker, config, is_consolidated)
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    peer_status = "Downloaded" if not peer_data.empty else "Not Found/Failed"
    
    log_entry = (f"## AGENT 1: DOWNLOAD SUMMARY for {company_name or ticker}\n\n"
                 f"**Timestamp**: {timestamp_str}\n\n"
                 f"**Excel Data**: {'Downloaded' if file_data.get('excel') else 'Failed'}\n\n"
                 f"**Peer Data**: {peer_status}\n\n"
                 f"**Latest Transcript**: {'Downloaded' if file_data.get('latest_transcript') else 'Failed'}\n\n"
                 f"**PPT**: {'Downloaded' if file_data.get('investor_presentation') else 'Failed'}\n\n"
                 f"**Credit Rating**: {'Downloaded' if file_data.get('credit_rating_doc') else 'Failed'}\n\n---\n\n")
    
    log_content_accumulator += log_entry
        
    return {"company_name": company_name, "file_data": file_data, "peer_data": peer_data, "log_file_content": log_content_accumulator}

def quantitative_analysis_node(state: StockAnalysisState):
    excel_data = state['file_data'].get('excel')
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    if not excel_data:
        text_results = "Quantitative analysis skipped: Excel data not found."
        structured_results = [{"type": "text", "content": text_results}]
    else:
        structured_results = execute_with_fallback(
            analyze_financials, log_content_accumulator, "Quantitative",
            excel_data, state['ticker'], config
        )
        if isinstance(structured_results, str):
             text_results = structured_results
             structured_results = [{"type": "text", "content": text_results}]
        else:
             text_results = "\n".join([item['content'] for item in structured_results if item['type'] == 'text'])

    log_content_accumulator += f"## AGENT 2: QUANTITATIVE ANALYSIS\n\n{text_results}\n\n---\n\n"
    return {"quant_results_structured": structured_results, "quant_text_for_synthesis": text_results, "log_file_content": log_content_accumulator}

def strategy_analysis_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    def strategy_wrapper(f_data, cfg):
        model_to_use = cfg.get("LITE_MODEL_NAME") 
        return strategy_analyst_agent(f_data, cfg["GOOGLE_API_KEY"], model_to_use)

    result_text = execute_with_fallback(
        strategy_wrapper, log_content_accumulator, "Strategy",
        state['file_data'], config
    )

    log_content_accumulator += f"## AGENT 3: STRATEGY & ALPHA SEARCH\n\n{result_text}\n\n---\n\n"
    return {"strategy_results": result_text, "log_file_content": log_content_accumulator}

def risk_analysis_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    def risk_wrapper(f_data, cfg):
        model_to_use = cfg.get("LITE_MODEL_NAME")
        return risk_analyst_agent(f_data, cfg["GOOGLE_API_KEY"], model_to_use)

    result_text = execute_with_fallback(
        risk_wrapper, log_content_accumulator, "Risk",
        state['file_data'], config
    )

    log_content_accumulator += f"## AGENT 4: RISK & CREDIT CHECK\n\n{result_text}\n\n---\n\n"
    return {"risk_results": result_text, "log_file_content": log_content_accumulator}

def qualitative_analysis_node(state: StockAnalysisState):
    company = state['company_name'] or state['ticker']
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    strategy_ctx = state.get('strategy_results', "")
    risk_ctx = state.get('risk_results', "")

    results = execute_with_fallback(
        run_qualitative_analysis, log_content_accumulator, "Qualitative",
        company, 
        state['file_data'].get("latest_transcript"),
        state['file_data'].get("previous_transcript"),
        config,
        strat=strategy_ctx,
        risk=risk_ctx
    )
    
    log_entry = "## AGENT 5: QUALITATIVE ANALYSIS\n\n"
    if isinstance(results, dict):
        for key, value in results.items():
            log_entry += f"### {key.replace('_', ' ').title()}: {value}\n\n"
    else:
        log_entry += f"Analysis Status: {results}\n"
    log_entry += "---\n\n"
    
    log_content_accumulator += log_entry
    return {"qualitative_results": results if isinstance(results, dict) else {}, "log_file_content": log_content_accumulator}

def valuation_analysis_node(state: StockAnalysisState):
    ticker = state['ticker']
    company_name = state.get('company_name') 
    peer_data = state.get('peer_data')
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']
    
    results = execute_with_fallback(
        run_valuation_analysis, log_content_accumulator, "Valuation",
        ticker, company_name, peer_data, config
    )
    
    content = results.get("content", "No valuation analysis generated.") if isinstance(results, dict) else str(results)
    log_content_accumulator += f"## AGENT 6: VALUATION & GOVERNANCE ANALYSIS\n\n{content}\n\n---\n\n"
    
    return {"valuation_results": results if isinstance(results, dict) else {}, "log_file_content": log_content_accumulator}

def synthesis_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    quant_text = state.get('quant_text_for_synthesis', "Quantitative analysis was not performed.")
    
    report = execute_with_fallback(
        generate_investment_summary, log_content_accumulator, "Synthesis",
        state['company_name'] or state['ticker'],
        quant_text,
        state['qualitative_results'],
        state['valuation_results'],
        state.get('risk_results'),
        state.get('strategy_results'),
        config
    )
    
    log_content_accumulator += f"## AGENT 7: FINAL SYNTHESIS REPORT\n\n{report}\n\n---\n\n"
    return {"final_report": report, "log_file_content": log_content_accumulator}

def generate_report_node(state: StockAnalysisState):
    pdf_buffer = io.BytesIO()
    create_pdf_report(
        ticker=state['ticker'],
        company_name=state.get('company_name'),
        quant_results=state.get('quant_results_structured', []),
        qual_results=state.get('qualitative_results', {}),
        strategy_results=state.get('strategy_results', ""),
        risk_results=state.get('risk_results', ""),
        valuation_results=state.get('valuation_results', {}),
        final_report=state.get('final_report', "Report could not be fully generated."),
        file_path=pdf_buffer
    )
    pdf_buffer.seek(0)
    return {"pdf_report_bytes": pdf_buffer.getvalue()}

def delay_node(state: StockAnalysisState):
    time.sleep(30) 
    return {}

# ==============================================================================
# 2. RISK NODES (Phase 0.5)
# ==============================================================================
def screener_for_risk_node(state: StockAnalysisState):
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    company_name, file_data, peer_data = download_financial_data(
        ticker, config, is_consolidated,
        need_excel=False, need_transcripts=False, need_ppt=False, need_peers=False, need_credit_report=True 
    )
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_entry = (f"## PHASE 0.5: RISK DOWNLOAD for {company_name or ticker}\n\n"
                 f"**Timestamp**: {timestamp_str}\n\n"
                 f"**Credit Rating Doc**: {'Downloaded' if file_data.get('credit_rating_doc') else 'Failed/Not Found'}\n---\n")
    
    log_content_accumulator += log_entry
    return {"company_name": company_name, "file_data": file_data, "log_file_content": log_content_accumulator}

def isolated_risk_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    def risk_wrapper(f_data, cfg):
        model_to_use = cfg.get("LITE_MODEL_NAME")
        return risk_analyst_agent(f_data, cfg["GOOGLE_API_KEY"], model_to_use)

    result_text = execute_with_fallback(
        risk_wrapper, log_content_accumulator, "Risk (Isolated)",
        state['file_data'], config
    )

    log_content_accumulator += f"## PHASE 0.5: ISOLATED RISK ANALYSIS\n\n{result_text}\n\n---\n\n"
    return {"risk_results": result_text, "log_file_content": log_content_accumulator}

# ==============================================================================
# 3. SEBI MVP NODES
# ==============================================================================

def screener_metadata_node(state: StockAnalysisState):
    ticker = state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    # Call Screener with metadata_only=True
    company_name, _, _ = download_financial_data(
        ticker, config, metadata_only=True
    )

    log_entry = f"## SEBI MVP: METADATA for {ticker}\n\n**Company Name**: {company_name}\n\n---\n"
    log_content_accumulator += log_entry
    
    return {"company_name": company_name, "log_file_content": log_content_accumulator}

def sebi_check_node(state: StockAnalysisState):
    company_name = state.get('company_name') or state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    result_text = run_isolated_sebi_check(company_name, config)

    log_entry = f"## SEBI MVP: REGULATORY CHECK\n\n{result_text}\n\n---\n"
    log_content_accumulator += log_entry

    current_qual = state.get('qualitative_results') or {}
    current_qual['sebi_check'] = result_text

    return {"qualitative_results": current_qual, "log_file_content": log_content_accumulator}

# ==============================================================================
# 4. EARNINGS DECODER NODES (NEW MVP)
# ==============================================================================

def screener_latest_transcript_node(state: StockAnalysisState):
    """Downloads ONLY the latest transcript."""
    ticker = state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    # For now, we reuse the standard downloader but ignore unnecessary files in logic
    # Ideally, you would optimize download_financial_data to support 'latest_only=True'
    company_name, file_data, _ = download_financial_data(
        ticker, config, 
        need_excel=False, 
        need_ppt=False, 
        need_peers=False, 
        need_credit_report=False
    )

    status = "Downloaded" if file_data.get('latest_transcript') else "Not Found"
    log_entry = f"## EARNINGS DECODER: DOWNLOAD\n\n**Latest Transcript**: {status}\n\n---\n"
    log_content_accumulator += log_entry
    
    return {"company_name": company_name, "file_data": file_data, "log_file_content": log_content_accumulator}

def analyze_latest_transcript_node(state: StockAnalysisState):
    """Runs the specific analysis on the latest transcript."""
    company_name = state.get('company_name') or state['ticker']
    transcript = state['file_data'].get('latest_transcript')
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']

    result_text = run_earnings_analysis_standalone(company_name, transcript, config)

    log_entry = f"## EARNINGS DECODER: ANALYSIS\n\n{result_text}\n\n---\n"
    log_content_accumulator += log_entry

    # Store specifically in 'latest_analysis' key
    current_qual = state.get('qualitative_results') or {}
    current_qual['latest_analysis'] = result_text

    return {"qualitative_results": current_qual, "log_file_content": log_content_accumulator}


# ==============================================================================
# 5. BUILD GRAPHS
# ==============================================================================

# --- A. FULL WORKFLOW GRAPH ---
full_workflow = StateGraph(StockAnalysisState)
full_workflow.add_node("fetch_data", fetch_data_node)
full_workflow.add_node("quantitative_analysis", quantitative_analysis_node)
full_workflow.add_node("delay_before_strategy", delay_node)
full_workflow.add_node("strategy_analysis", strategy_analysis_node)
full_workflow.add_node("delay_before_risk", delay_node)
full_workflow.add_node("risk_analysis", risk_analysis_node)
full_workflow.add_node("qualitative_analysis", qualitative_analysis_node)
full_workflow.add_node("valuation_analysis", valuation_analysis_node)
full_workflow.add_node("synthesis", synthesis_node)
full_workflow.add_node("generate_report", generate_report_node)

full_workflow.set_entry_point("fetch_data")
full_workflow.add_edge("fetch_data", "quantitative_analysis")
full_workflow.add_edge("quantitative_analysis", "strategy_analysis")
full_workflow.add_edge("strategy_analysis", "risk_analysis")
full_workflow.add_edge("risk_analysis", "qualitative_analysis")
full_workflow.add_edge("qualitative_analysis", "valuation_analysis")
full_workflow.add_edge("valuation_analysis", "synthesis")
full_workflow.add_edge("synthesis", "generate_report")
full_workflow.add_edge("generate_report", END)
app_graph = full_workflow.compile()

# --- B. RISK ONLY GRAPH ---
risk_workflow = StateGraph(StockAnalysisState)
risk_workflow.add_node("screener_for_risk", screener_for_risk_node)
risk_workflow.add_node("isolated_risk", isolated_risk_node)
risk_workflow.set_entry_point("screener_for_risk")
risk_workflow.add_edge("screener_for_risk", "isolated_risk")
risk_workflow.add_edge("isolated_risk", END)
risk_only_graph = risk_workflow.compile()

# --- C. SEBI MVP GRAPH ---
sebi_workflow_def = StateGraph(StockAnalysisState)
sebi_workflow_def.add_node("screener_metadata", screener_metadata_node)
sebi_workflow_def.add_node("sebi_check", sebi_check_node)
sebi_workflow_def.set_entry_point("screener_metadata")
sebi_workflow_def.add_edge("screener_metadata", "sebi_check")
sebi_workflow_def.add_edge("sebi_check", END)
sebi_workflow = sebi_workflow_def.compile()

# --- D. EARNINGS DECODER GRAPH (NEW) ---
earnings_workflow_def = StateGraph(StockAnalysisState)
earnings_workflow_def.add_node("fetch_latest", screener_latest_transcript_node)
earnings_workflow_def.add_node("analyze_latest", analyze_latest_transcript_node)
earnings_workflow_def.set_entry_point("fetch_latest")
earnings_workflow_def.add_edge("fetch_latest", "analyze_latest")
earnings_workflow_def.add_edge("analyze_latest", END)
earnings_graph = earnings_workflow_def.compile()


# --- Helper Function for UI ---
def extract_investment_thesis(full_report: str) -> str:
    try:
        search_key = "Investment Thesis"
        start_index = full_report.lower().find(search_key.lower())
        if start_index == -1: return "Investment thesis could not be extracted."
        content_start_index = full_report.find('\n', start_index) + 1
        next_section_index = full_report.find("\n## ", content_start_index)
        if next_section_index == -1:
            return full_report[content_start_index:].strip()
        return full_report[content_start_index:next_section_index].strip()
    except Exception:
        return "Investment thesis could not be extracted."

# --- Runner Function (Updated for Multi-Mode) ---
def run_analysis_for_ticker(ticker_symbol, is_consolidated_flag, status_container, progress_text_container, workflow_mode):
    inputs = {
        "ticker": ticker_symbol,
        "log_file_content": f"# Analysis Log for {ticker_symbol} (Mode: {workflow_mode})\n\n",
        "is_consolidated": is_consolidated_flag,
        "agent_config": agent_configs,
        "workflow_mode": workflow_mode
    }
    
    final_state_result = {}
    
    # --- MODE SELECTION LOGIC ---
    if workflow_mode == "Risk Analysis Only":
        target_graph = risk_only_graph
        placeholders = {
            "screener_for_risk": status_container.empty(),
            "isolated_risk": status_container.empty(),
        }
        placeholders["screener_for_risk"].markdown("⏳ **Checking Credit Ratings...**")

    elif workflow_mode == "SEBI Violations Check (MVP)":
        target_graph = sebi_workflow
        placeholders = {
            "screener_metadata": status_container.empty(),
            "sebi_check": status_container.empty()
        }
        placeholders["screener_metadata"].markdown("⏳ **Identifying Company...**")

    elif workflow_mode == "Latest Earnings Decoder":
        target_graph = earnings_graph
        placeholders = {
            "fetch_latest": status_container.empty(),
            "analyze_latest": status_container.empty()
        }
        placeholders["fetch_latest"].markdown("⏳ **Fetching Latest Transcript...**")
    
    else: # Default: Full Workflow
        target_graph = app_graph
        placeholders = {
            "fetch_data": status_container.empty(),
            "quant": status_container.empty(),
            "strategy": status_container.empty(),
            "risk": status_container.empty(),
            "qual": status_container.empty(),
            "valuation": status_container.empty(),
            "synthesis": status_container.empty(),
        }
        placeholders["fetch_data"].markdown("⏳ **Downloading Financial Data...**")

    # --- EXECUTION ---
    for event in target_graph.stream(inputs):
        for node_name, node_output in event.items():
            if node_output:
                final_state_result.update(node_output)
            
            # Update Status Indicators based on Mode
            if workflow_mode == "Risk Analysis Only":
                if node_name == "screener_for_risk":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Analyzing Risk for {ticker_symbol} ({c_name})...")
                    placeholders["screener_for_risk"].markdown("✅ **Credit Data Fetched**")
                    placeholders["isolated_risk"].markdown("⏳ **Generating Risk Profile...**")
                elif node_name == "isolated_risk":
                    placeholders["isolated_risk"].markdown("✅ **Risk Analysis Complete**")

            elif workflow_mode == "SEBI Violations Check (MVP)":
                 if node_name == "screener_metadata":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Checking SEBI for {ticker_symbol} ({c_name})...")
                    placeholders["screener_metadata"].markdown("✅ **Company Identified**")
                    placeholders["sebi_check"].markdown("⏳ **Searching SEBI Database...**")
                 elif node_name == "sebi_check":
                    placeholders["sebi_check"].markdown("✅ **Regulatory Check Complete**")

            elif workflow_mode == "Latest Earnings Decoder":
                if node_name == "fetch_latest":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Decoding Earnings for {ticker_symbol} ({c_name})...")
                    placeholders["fetch_latest"].markdown("✅ **Transcript Downloaded**")
                    placeholders["analyze_latest"].markdown("⏳ **Decoding Management Speak...**")
                elif node_name == "analyze_latest":
                    placeholders["analyze_latest"].markdown("✅ **Analysis Complete**")
            
            else: # Full Workflow Updates
                if node_name == "fetch_data":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Analyzing {ticker_symbol} ({c_name})...")
                    placeholders["fetch_data"].markdown("✅ **Data Downloaded**")
                    placeholders["quant"].markdown("⏳ **Running Quantitative Analysis...**")
                elif node_name == "quantitative_analysis":
                    placeholders["quant"].markdown("✅ **Quantitative Analysis Complete**")
                    placeholders["strategy"].markdown("⏳ **Analyzing Strategy...**")
                elif node_name == "strategy_analysis":
                    placeholders["strategy"].markdown("✅ **Strategy Analysis Complete**")
                    placeholders["risk"].markdown("⏳ **Analyzing Risk...**")
                elif node_name == "risk_analysis":
                    placeholders["risk"].markdown("✅ **Risk Analysis Complete**")
                    placeholders["qual"].markdown("⏳ **Running Qualitative Analysis...**")
                elif node_name == "qualitative_analysis":
                    placeholders["qual"].markdown("✅ **Qualitative Analysis Complete**")
                    placeholders["valuation"].markdown("⏳ **Running Valuation...**")
                elif node_name == "valuation_analysis":
                     placeholders["valuation"].markdown("✅ **Valuation Complete**")
                     placeholders["synthesis"].markdown("⏳ **Generating Final Summary...**")
                elif node_name == "synthesis":
                     placeholders["synthesis"].markdown("✅ **Summary Generated**")

    final_state_result['ticker'] = ticker_symbol
    final_state_result['workflow_mode'] = workflow_mode
    return final_state_result

# --- Streamlit UI ---
st.title("🤖 AI Stock Analysis Crew (Enhanced)")
st.header("Automated Investment Analysis Workflow", divider="rainbow")

if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = {}

st.sidebar.header("Controls")

# --- MULTI-MODE WORKFLOW SELECTOR ---
workflow_mode = st.sidebar.selectbox(
    "Select Workflow",
    [
        "Full Workflow (PDF Report)",
        "Risk Analysis Only",
        "SEBI Violations Check (MVP)",
        "Latest Earnings Decoder" # <--- NEW OPTION
    ]
)
# ------------------------------------

analysis_mode = st.sidebar.radio("Analysis Mode", ["Single Ticker", "Batch Analysis"])

tickers_to_process = []
if analysis_mode == "Single Ticker":
    ticker_input = st.sidebar.text_input("Enter Stock Ticker", value="RELIANCE")
    tickers_to_process = [ticker_input.strip().upper()] if ticker_input else []
else:
    batch_input = st.sidebar.text_area("Enter Tickers (Comma/Newline separated)", 
                                       value="RELIANCE, TATASTEEL, INFY", height=150)
    raw_tickers = batch_input.replace('\n', ',').split(',')
    tickers_to_process = [t.strip().upper() for t in raw_tickers if t.strip()]

data_type_choice = st.sidebar.radio("Data Type", ["Standalone", "Consolidated"])

# CLEANUP CONTROLS
st.sidebar.markdown("---")
append_mode = st.sidebar.checkbox("Append to existing results", value=False, help="If unchecked, starting a new run wipes previous data.")

if st.sidebar.button("🗑️ Clear Results"):
    st.session_state.analysis_results = {}
    st.rerun()

if st.sidebar.button("🚀 Run Analysis", type="primary"):
    if not tickers_to_process:
        st.sidebar.warning("Please enter at least one ticker.")
    else:
        # 1. CLEANUP LOGIC
        if not append_mode:
            st.session_state.analysis_results = {}

        is_consolidated = (data_type_choice == "Consolidated")
        progress_bar = st.progress(0)
        total_tickers = len(tickers_to_process)

        st.write(f"Starting analysis for: {', '.join(tickers_to_process)}")

        for i, ticker in enumerate(tickers_to_process):
            # 2. COOL DOWN VALVE (Prevent TPM Limit)
            if i > 0:
                with st.status(f"Cooling down engines before {ticker}...", expanded=False):
                    time.sleep(10) # 10s wait between stocks to drain token bucket

            try:
                with st.status(f"Processing {ticker} ({i+1}/{total_tickers})...", expanded=True) as status:
                    progress_text = st.empty()
                    
                    # Pass workflow_mode to runner
                    result_state = run_analysis_for_ticker(ticker, is_consolidated, status, progress_text, workflow_mode)
                    
                    # 3. INCREMENTAL COMMIT (Save immediately)
                    st.session_state.analysis_results[ticker] = result_state
                    
                    status.update(label=f"Completed {ticker}!", state="complete", expanded=False)
                
            except Exception as e:
                st.error(f"Failed to process {ticker}: {str(e)}")
                # Save failure state so we know it ran
                st.session_state.analysis_results[ticker] = {"ticker": ticker, "final_report": f"Analysis Failed: {str(e)}"}
            
            progress_bar.progress((i + 1) / total_tickers)

        st.success("All requested analyses completed!")
        st.rerun()

# --- Results Display ---
if st.session_state.analysis_results:
    st.divider()

    # Batch Download (Only for Full Mode)
    if len(st.session_state.analysis_results) > 0:
        zip_buffer = io.BytesIO()
        has_pdfs = False
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for ticker, state in st.session_state.analysis_results.items():
                if state.get('pdf_report_bytes'):
                    has_pdfs = True
                    timestamp = datetime.datetime.now().strftime('%Y%m%d')
                    filename = f"Report_{ticker}_{timestamp}.pdf"
                    zf.writestr(filename, state['pdf_report_bytes'])

        if has_pdfs:
            st.download_button(
                label="📦 **Download All Reports (ZIP)**",
                data=zip_buffer.getvalue(),
                file_name=f"Batch_Reports_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True,
                type="primary"
            )
            st.divider()

    # View Selector
    available_tickers = list(st.session_state.analysis_results.keys())
    col_sel, col_info = st.columns([1, 3])
    with col_sel:
        selected_ticker = st.selectbox("Select Report to View:", available_tickers, index=len(available_tickers)-1)

    final_state = st.session_state.analysis_results[selected_ticker]
    run_mode = final_state.get('workflow_mode', "Full Workflow (PDF Report)")
    company_display_name = final_state.get('company_name') or final_state.get('ticker')

    with col_info:
        st.subheader(f"Results for: {company_display_name} ({run_mode})")

    # --- DISPLAY LOGIC BY MODE ---
    
    if run_mode == "SEBI Violations Check (MVP)":
        st.info("SEBI Check Mode: Scanned for official regulatory orders/penalties using live search.")
        st.markdown("### 🏛️ SEBI Regulatory Status")
        qual_res = final_state.get('qualitative_results', {})
        sebi_res = qual_res.get('sebi_check')
        if sebi_res: st.markdown(sebi_res)
        else: st.warning("No SEBI check results found.")
        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "Risk Analysis Only":
        st.info("Risk Analysis Mode: Only Credit/Risk data was analyzed.")
        st.markdown("### 🛡️ Credit Risk Profile")
        if final_state.get('risk_results'): st.markdown(final_state['risk_results'])
        else: st.warning("No risk results found.")
        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "Latest Earnings Decoder":
        st.info("Earnings Decoder Mode: Focused analysis of the most recent quarterly conference call.")
        
        qual_res = final_state.get('qualitative_results', {})
        analysis_text = qual_res.get('latest_analysis')
        
        if analysis_text:
            st.markdown("### 🎙️ Latest Quarter Insights")
            st.markdown(analysis_text)
        else:
            st.warning("Analysis could not be generated.")

        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')
    
    else:
        # Full Workflow View
        if final_state.get('final_report'):
            st.markdown("### 📈📝 Investment Thesis")
            thesis = extract_investment_thesis(final_state['final_report'])
            st.markdown(thesis, unsafe_allow_html=True)

        st.markdown("---")

        if final_state.get('pdf_report_bytes'):
            col1, col2, col3 = st.columns([2, 3, 2])
            with col2:
                st.download_button(
                    label=f"**Download PDF for {selected_ticker}**",
                    data=final_state['pdf_report_bytes'],
                    file_name=f"Report_{selected_ticker}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

        with st.expander(f"📂 Deep-Dive Data: {selected_ticker}", expanded=False):
            tab_strat, tab_risk, tab_val, tab_qual, tab_quant, tab_log = st.tabs([
                "Strategy", "Risk", "Valuation", "Qualitative", "Quantitative", "Execution Logs"
            ])
            
            with tab_strat:
                if final_state.get('strategy_results'): st.markdown(final_state['strategy_results'])
                else: st.warning("Not available.")
            with tab_risk:
                if final_state.get('risk_results'): st.markdown(final_state['risk_results'])
                else: st.warning("Not available.")
            with tab_val:
                if final_state.get('valuation_results'): 
                    val_data = final_state['valuation_results']
                    st.markdown(val_data.get('content', val_data) if isinstance(val_data, dict) else val_data)
                else: st.warning("Not available.")
            with tab_qual:
                if final_state.get('qualitative_results'):
                    for k, v in final_state['qualitative_results'].items():
                        st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")
                else: st.warning("Not available.")
            with tab_quant:
                if final_state.get('quant_text_for_synthesis'): st.markdown(final_state['quant_text_for_synthesis'])
            with tab_log:
                if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

elif not st.session_state.analysis_results:
    st.info("No reports generated yet.")