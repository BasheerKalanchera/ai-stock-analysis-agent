import streamlit as st
import os
import datetime
from dotenv import load_dotenv
import io
import time
import pandas as pd
import zipfile
import json 


# --- Import Graphs and State ---
import graphs
from state import StockAnalysisState

# --- Page Configuration ---
st.set_page_config(page_title="Stock Research Workbench", page_icon="🤖", layout="wide")
load_dotenv()

# --- PostgreSQL Checkpointer Setup ---
@st.cache_resource
def setup_checkpointer():
    """Initialize PostgreSQL checkpointer for crash recovery.
    Returns None if DATABASE_URL is not configured (app works without it)."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        try:
            db_url = st.secrets.get("DATABASE_URL")
        except (FileNotFoundError, KeyError, st.errors.StreamlitAPIException):
            pass
    
    if not db_url:
        return None
    
    try:
        import psycopg
        from psycopg_pool import ConnectionPool
        from langgraph.checkpoint.postgres import PostgresSaver
        from checkpointer_serde import StockAnalysisSerializer
        
        # Run one-time table/index creation with autocommit (required by Postgres)
        with psycopg.connect(db_url, autocommit=True) as setup_conn:
            PostgresSaver(setup_conn).setup()
        
        # Create connection pool for runtime checkpointing (min_size=0 + check_connection + keepalives)
        pool = ConnectionPool(
            conninfo=db_url, 
            min_size=0, 
            max_size=3,
            kwargs={
                'autocommit': True,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5
            }, # checkpointer handles transactions internally
            check=ConnectionPool.check_connection # Verify connection before use!
        )
        serde = StockAnalysisSerializer()
        checkpointer = PostgresSaver(conn=pool, serde=serde)
        
        # Recompile all graphs with the checkpointer
        graphs.recompile_with_checkpointer(checkpointer)
        return checkpointer
    except Exception as e:
        st.sidebar.warning(f"⚠️ Checkpointer disabled: {e}")
        return None

# Initialize checkpointer (runs once, cached by Streamlit)
checkpointer = setup_checkpointer()

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

import re

# --- Helper Function for UI ---
def extract_investment_thesis(full_report: str) -> str:
    try:
        # 1. Flexible regex search for Header (case-insensitive)
        # Matches: "# Investment Thesis", "## Investment Summary", "Investment Thesis\n", etc.
        match = re.search(r'(?i)(#+\s*Investment\s*(Thesis|Summary)|Investment\s*(Thesis|Summary)\s*\n)', full_report)
        
        if match:
            start_pos = match.end()
            # Find next header (## or ###) or end of string
            next_header = re.search(r'\n#+\s', full_report[start_pos:])
            if next_header:
                return full_report[start_pos:start_pos + next_header.start()].strip()
            return full_report[start_pos:].strip()
            
        # 2. Fallback: If report is reasonably short, show the whole thing
        if len(full_report) < 2000:
            return full_report

        # 3. Last Resort
        return "Investment Thesis section header not found. Please view the full report in the 'Deep-Dive Data' tab."
    except Exception:
        return "Investment thesis extraction failed."

# --- Checkpoint Cleanup ---
def cleanup_checkpoint(ticker_symbol, workflow_mode):
    """Remove checkpoint data for a completed run to keep the DB clean."""
    if not checkpointer:
        return
    thread_id = f"{ticker_symbol}-{workflow_mode.replace(' ', '_').replace('(', '').replace(')', '')}"
    try:
        with checkpointer.conn.connection() as conn:
            # Delete blobs first (if foreign keys exist, though usually loosely coupled in LangGraph)
            conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
            conn.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            conn.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
    except Exception:
        pass  # Non-critical — don't break the app if cleanup fails

# --- Runner Function ---
def run_analysis_for_ticker(ticker_symbol, is_consolidated_flag, status_container, progress_text_container, workflow_mode, resume_mode=False):
    # Deterministic thread ID: same ticker + workflow always maps to same thread
    thread_id = f"{ticker_symbol}-{workflow_mode.replace(' ', '_').replace('(', '').replace(')', '')}"
    stream_config = {"configurable": {"thread_id": thread_id}}
    
    # Smart resume: auto-detect checkpoint status per ticker
    fresh_inputs = {
        "ticker": ticker_symbol,
        "log_file_content": f"# Analysis Log for {ticker_symbol} (Mode: {workflow_mode})\n\n",
        "is_consolidated": is_consolidated_flag,
        "agent_config": agent_configs,
        "workflow_mode": workflow_mode
    }
    
    # Select target graph first (needed for checkpoint lookup)
    graph_map = {
        "Quantitative Deep-Dive": graphs.quant_only_graph,
        "Qualitative Deep-Dive": graphs.qualitative_only_graph,
        "Strategy Deep Dive": graphs.strategy_only_graph,
        "Valuation & Governance Deep-Dive": graphs.valuation_only_graph,
        "Risk Analysis Only": graphs.risk_only_graph,
        "SEBI Violations Check (MVP)": graphs.sebi_workflow,
        "Latest Concall Analysis": graphs.earnings_graph,
        "QoQ Concall Analysis": graphs.strategy_shift_graph,
        "Scuttlebutt Research": graphs.scuttlebutt_graph,
    }
    target_graph = graph_map.get(workflow_mode, graphs.app_graph)
    
    resume_next_node = None  # Track which node we're resuming from
    
    if resume_mode and checkpointer:
        try:
            existing_state = target_graph.get_state(stream_config)
            if existing_state and existing_state.values:
                if not existing_state.next:
                    # Graph already completed — skip entirely (instant)
                    progress_text_container.write(f"⏭️ {ticker_symbol} already completed — skipping")
                    result = dict(existing_state.values)
                    result['ticker'] = ticker_symbol
                    result['workflow_mode'] = workflow_mode
                    return result
                else:
                    # Partial checkpoint — resume from where it left off
                    inputs = None
                    resume_next_node = existing_state.next[0]
                    next_nodes = ", ".join(existing_state.next)
                    progress_text_container.write(f"🔄 Resuming {ticker_symbol} from checkpoint (next: {next_nodes})...")
            else:
                # No checkpoint found — start fresh
                inputs = fresh_inputs
                progress_text_container.write(f"🆕 No checkpoint for {ticker_symbol} — starting fresh...")
        except Exception:
            inputs = fresh_inputs
    else:
        inputs = fresh_inputs
    
    final_state_result = {}
    
    # --- MODE SELECTION: Set up UI placeholders ---
    if workflow_mode == "Quantitative Deep-Dive":
        placeholders = {
            "screener_for_quant": status_container.empty(),
            "isolated_quant": status_container.empty(),
        }
        placeholders["screener_for_quant"].markdown("⏳ **Downloading Excel Data...**")

    elif workflow_mode == "Qualitative Deep-Dive":
        placeholders = {
            "screener_for_qual": status_container.empty(),
            "strategy_prereq": status_container.empty(),
            "risk_prereq": status_container.empty(),
            "isolated_qual": status_container.empty(),
        }
        placeholders["screener_for_qual"].markdown("⏳ **Fetching Transcripts, PPT & Credit Docs...**")

        
    elif workflow_mode == "Strategy Deep Dive":
        placeholders = {
            "screener_for_strategy": status_container.empty(),
            "isolated_strategy": status_container.empty(),
        }
        placeholders["screener_for_strategy"].markdown("⏳ **Searching for Investor Presentation...**")

    elif workflow_mode == "Valuation & Governance Deep-Dive":
        placeholders = {
            "screener_for_valuation": status_container.empty(),
            "isolated_valuation": status_container.empty(),
        }
        placeholders["screener_for_valuation"].markdown("⏳ **Identifying Peers & Market Data...**")

    elif workflow_mode == "Risk Analysis Only":
        placeholders = {
            "screener_for_risk": status_container.empty(),
            "isolated_risk": status_container.empty(),
        }
        placeholders["screener_for_risk"].markdown("⏳ **Checking Credit Ratings...**")

    elif workflow_mode == "SEBI Violations Check (MVP)":
        placeholders = {
            "screener_metadata": status_container.empty(),
            "sebi_check": status_container.empty()
        }
        placeholders["screener_metadata"].markdown("⏳ **Identifying Company...**")

    elif workflow_mode == "Latest Concall Analysis":
        placeholders = {
            "fetch_latest": status_container.empty(),
            "analyze_latest": status_container.empty()
        }
        placeholders["fetch_latest"].markdown("⏳ **Fetching Latest Transcript...**")

    elif workflow_mode == "QoQ Concall Analysis":
        placeholders = {
            "fetch_both": status_container.empty(),
            "analyze_both": status_container.empty(),
            "compare_quarters": status_container.empty()
        }
        placeholders["fetch_both"].markdown("⏳ **Fetching History...**")

    elif workflow_mode == "Scuttlebutt Research":
        placeholders = {
            "fetch_data": status_container.empty(),
            "strategy_analysis": status_container.empty(),
            "risk_analysis": status_container.empty(),
            "scuttlebutt_analysis": status_container.empty()
        }
        placeholders["fetch_data"].markdown("⏳ **Downloading Financial Data...**")

    else: # Default: Full Workflow
        placeholders = {
            "fetch_data": status_container.empty(),
            "quant": status_container.empty(),
            "strategy": status_container.empty(),
            "risk": status_container.empty(),
            "qual": status_container.empty(),
            "valuation": status_container.empty(),
            "synthesis": status_container.empty(),
            "pdf_report": status_container.empty(),
        }
        placeholders["fetch_data"].markdown("⏳ **Downloading Financial Data...**")

    # --- Mark completed steps when resuming ---
    if resume_next_node:
        # Map: (graph node name, placeholder key, display label) in execution order
        node_to_placeholder = {
            "Full Workflow (PDF Report)": [
                ("fetch_data", "fetch_data", "Data Download"),
                ("quantitative_analysis", "quant", "Quantitative Analysis"),
                ("strategy_analysis", "strategy", "Strategy Analysis"),
                ("risk_analysis", "risk", "Risk Analysis"),
                ("qualitative_analysis", "qual", "Qualitative Analysis"),
                ("valuation_analysis", "valuation", "Valuation Analysis"),
                ("synthesis", "synthesis", "Synthesis"),
                ("generate_report", "pdf_report", "PDF Report"),
            ],
            "Quantitative Deep-Dive": [
                ("screener_for_quant", "screener_for_quant", "Excel Data Download"),
                ("isolated_quant", "isolated_quant", "Quantitative Analysis"),
            ],
            "Qualitative Deep-Dive": [
                ("screener_for_qual", "screener_for_qual", "Transcript & Docs Fetch"),
                ("strategy_prereq", "strategy_prereq", "Strategy Prereq"),
                ("risk_prereq", "risk_prereq", "Risk Prereq"),
                ("isolated_qual", "isolated_qual", "Qualitative Analysis"),
            ],
            "Strategy Deep Dive": [
                ("screener_for_strategy", "screener_for_strategy", "Investor Presentation Fetch"),
                ("isolated_strategy", "isolated_strategy", "Strategy Analysis"),
            ],
            "Valuation & Governance Deep-Dive": [
                ("screener_for_valuation", "screener_for_valuation", "Peers & Market Data"),
                ("isolated_valuation", "isolated_valuation", "Valuation Analysis"),
            ],
            "Risk Analysis Only": [
                ("screener_for_risk", "screener_for_risk", "Credit Ratings Fetch"),
                ("isolated_risk", "isolated_risk", "Risk Analysis"),
            ],
            "SEBI Violations Check (MVP)": [
                ("screener_metadata", "screener_metadata", "Company Identification"),
                ("sebi_check", "sebi_check", "SEBI Check"),
            ],
            "Latest Concall Analysis": [
                ("fetch_latest", "fetch_latest", "Transcript Fetch"),
                ("analyze_latest", "analyze_latest", "Transcript Analysis"),
            ],
            "QoQ Concall Analysis": [
                ("fetch_both", "fetch_both", "History Fetch"),
                ("analyze_both", "analyze_both", "Analysis"),
                ("compare_quarters", "compare_quarters", "Quarter Comparison"),
            ],
            "Scuttlebutt Research": [
                ("fetch_data", "fetch_data", "Financial Data Download"),
                ("strategy_analysis", "strategy_analysis", "Strategy Analysis"),
                ("risk_analysis", "risk_analysis", "Risk Analysis"),
                ("scuttlebutt_analysis", "scuttlebutt_analysis", "Scuttlebutt Analysis"),
            ],
        }
        for graph_node, placeholder_key, label in node_to_placeholder.get(workflow_mode, []):
            if graph_node == resume_next_node:
                break  # This node and beyond are pending
            if placeholder_key in placeholders:
                placeholders[placeholder_key].markdown(f"✅ **{label} — Restored from checkpoint**")

    # --- EXECUTION ---
    for event in target_graph.stream(inputs, stream_config):
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

            elif workflow_mode == "Strategy Deep Dive":
                if node_name == "screener_for_strategy":
                    c_name = node_output.get("company_name", ticker_symbol)
                    ppt_found = node_output.get("file_data", {}).get("investor_presentation")
                    
                    progress_text_container.write(f"Analyzing Strategy for {ticker_symbol} ({c_name})...")
                    
                    if ppt_found:
                        placeholders["screener_for_strategy"].markdown("✅ **Presentation Downloaded**")
                        placeholders["isolated_strategy"].markdown("⏳ **Extracting Alpha & Strategic Shifts...**")
                    else:
                        placeholders["screener_for_strategy"].markdown("❌ **Presentation Not Found**")
                        placeholders["isolated_strategy"].markdown("⚠️ **Aborting Strategy Analysis**")
                        
                elif node_name == "isolated_strategy":
                    placeholders["isolated_strategy"].markdown("✅ **Strategy Analysis Complete**")

            elif workflow_mode == "Valuation & Governance Deep-Dive":
                if node_name == "screener_for_valuation":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Fetching Peers for {ticker_symbol} ({c_name})...")
                    placeholders["screener_for_valuation"].markdown("✅ **Peer Data Retrieved**")
                    placeholders["isolated_valuation"].markdown("⏳ **Running Valuation Models...**")
                elif node_name == "isolated_valuation":
                    placeholders["isolated_valuation"].markdown("✅ **Valuation Complete**")

            elif workflow_mode == "Quantitative Deep-Dive": # <--- YOUR NEW INSERTION
                if node_name == "screener_for_quant":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Fetching Data for {ticker_symbol} ({c_name})...")
                    placeholders["screener_for_quant"].markdown("✅ **Excel Data Downloaded**")
                    placeholders["isolated_quant"].markdown("⏳ **Analyzing Financials & Generating Charts...**")
                elif node_name == "isolated_quant":
                    placeholders["isolated_quant"].markdown("✅ **Quantitative Analysis Complete**")

            elif workflow_mode == "Qualitative Deep-Dive":
                if node_name == "screener_for_qual":
                    placeholders["screener_for_qual"].markdown("✅ **Documents Downloaded**")
                    placeholders["strategy_prereq"].markdown("⏳ **Generating Strategy Context...**")
                
                elif node_name == "strategy_prereq":
                    placeholders["strategy_prereq"].markdown("✅ **Strategy Context Ready**")
                    placeholders["risk_prereq"].markdown("⏳ **Generating Risk Context...**")
                    
                elif node_name == "risk_prereq":
                    placeholders["risk_prereq"].markdown("✅ **Risk Context Ready**")
                    placeholders["isolated_qual"].markdown("⏳ **Running Deep-Dive Qualitative Analysis...**")
                    
                elif node_name == "isolated_qual":
                    placeholders["isolated_qual"].markdown("✅ **Qualitative Deep-Dive Complete**")

            elif workflow_mode == "SEBI Violations Check (MVP)":
                 if node_name == "screener_metadata":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Checking SEBI for {ticker_symbol} ({c_name})...")
                    placeholders["screener_metadata"].markdown("✅ **Company Identified**")
                    placeholders["sebi_check"].markdown("⏳ **Searching SEBI Database...**")
                 elif node_name == "sebi_check":
                    placeholders["sebi_check"].markdown("✅ **Regulatory Check Complete**")

            elif workflow_mode == "Latest Concall Analysis":
                if node_name == "fetch_latest":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Decoding Earnings for {ticker_symbol} ({c_name})...")
                    placeholders["fetch_latest"].markdown("✅ **Transcript Downloaded**")
                    placeholders["analyze_latest"].markdown("⏳ **Decoding Management Speak...**")
                elif node_name == "analyze_latest":
                    placeholders["analyze_latest"].markdown("✅ **Analysis Complete**")

            elif workflow_mode == "QoQ Concall Analysis":
                if node_name == "fetch_both":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Analyzing Shift for {ticker_symbol} ({c_name})...")
                    placeholders["fetch_both"].markdown("✅ **Transcripts Retrieved**")
                    placeholders["analyze_both"].markdown("⏳ **Reading Both Quarters...**")
                elif node_name == "analyze_both":
                    placeholders["analyze_both"].markdown("✅ **Individual Analysis Done**")
                    placeholders["compare_quarters"].markdown("⏳ **Detecting Strategic Shifts...**")
                elif node_name == "compare_quarters":
                    placeholders["compare_quarters"].markdown("✅ **Comparison Complete**")
            
            elif workflow_mode == "Scuttlebutt Research":
                if node_name == "fetch_data":
                    c_name = node_output.get("company_name", ticker_symbol)
                    progress_text_container.write(f"Researching {ticker_symbol} ({c_name})...")
                    placeholders["fetch_data"].markdown("✅ **Financials Downloaded**")
                    placeholders["strategy_analysis"].markdown("⏳ **Analyzing Strategy...**")
                elif node_name == "strategy_analysis":
                    placeholders["strategy_analysis"].markdown("✅ **Strategy Analysis Done**")
                    placeholders["risk_analysis"].markdown("⏳ **Analyzing Risk...**")
                elif node_name == "risk_analysis":
                    placeholders["risk_analysis"].markdown("✅ **Risk Analysis Done**")
                    placeholders["scuttlebutt_analysis"].markdown("⏳ **Gathering Intel (News/Forums)...**")
                elif node_name == "scuttlebutt_analysis":
                    placeholders["scuttlebutt_analysis"].markdown("✅ **Research Complete**")

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
                     placeholders["pdf_report"].markdown("⏳ **Generating PDF...**")
                elif node_name == "generate_report":
                     placeholders["pdf_report"].markdown("✅ **PDF Report Ready**")

    # If resuming, load the FULL state from checkpoint (stream only yields new events)
    if resume_mode and checkpointer:
        try:
            full_state = target_graph.get_state(stream_config)
            if full_state and full_state.values:
                final_state_result = {**full_state.values, **final_state_result}
        except Exception:
            pass  # Fall back to whatever we collected from stream
    
    final_state_result['ticker'] = ticker_symbol
    final_state_result['workflow_mode'] = workflow_mode
    return final_state_result

# --- Streamlit UI ---
st.title("🤖 AI Based Stock Research Workbench")
st.header("Please select the type of research from the side bar", divider="rainbow")

if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = {}

st.sidebar.header("Controls")

# --- MULTI-MODE WORKFLOW SELECTOR ---
workflow_mode = st.sidebar.selectbox(
    "Select Workflow",
    [
        "Full Workflow (PDF Report)",
        "Quantitative Deep-Dive",
        "Qualitative Deep-Dive",    
        "Valuation & Governance Deep-Dive",
        "Strategy Deep Dive",
        "Risk Analysis Only",
        "SEBI Violations Check (MVP)",
        "Latest Concall Analysis",
        "QoQ Concall Analysis",
        "Scuttlebutt Research" 
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
resume_mode = st.sidebar.checkbox("🔄 Resume from checkpoint", value=False, 
    help="Resume a previously interrupted run from its last completed step. Uses the same ticker + workflow to find the checkpoint.",
    disabled=(checkpointer is None))

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
                    result_state = run_analysis_for_ticker(ticker, is_consolidated, status, progress_text, workflow_mode, resume_mode)
                    
                    # 3. INCREMENTAL COMMIT (Save immediately)
                    st.session_state.analysis_results[ticker] = result_state
                    
                    status.update(label=f"Completed {ticker}!", state="complete", expanded=False)
                
            except Exception as e:
                st.error(f"Failed to process {ticker}: {str(e)}")
                # Save failure state so we know it ran
                st.session_state.analysis_results[ticker] = {"ticker": ticker, "final_report": f"Analysis Failed: {str(e)}"}
            
            progress_bar.progress((i + 1) / total_tickers)

        # CLEANUP: Remove checkpoint data only for SUCCESSFUL runs
        for ticker in tickers_to_process:
            res = st.session_state.analysis_results.get(ticker, {})
            # If the result suggests failure (or wasn't generated), SKIP cleanup so we can debug/resume
            if "Analysis Failed" in str(res.get("final_report", "")) or not res:
                continue
            cleanup_checkpoint(ticker, workflow_mode)
        
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
    
    if run_mode == "Quantitative Deep-Dive":
        st.info("📊 **Quantitative Deep-Dive**: Sequential analysis of financial trends and performance charts.")
        
        # Get the structured results from the agent
        structured_data = final_state.get('quant_results_structured', [])
        
        if structured_data:
            for item in structured_data:
                content = item.get('content')
                item_type = item.get('type')
                
                if item_type == 'chart':
                    if content is not None:
                        # Update: use width="stretch" instead of use_container_width=True
                        st.image(content, width="stretch")
                    else:
                        st.warning("A chart was expected here but the data was empty.")
                        
                elif item_type == 'table':
                    # Update: use width="stretch" instead of use_container_width=True
                    st.dataframe(content, width="stretch")
                    
                elif item_type == 'text':
                    # This ensures the explanation appears directly below the chart
                    st.markdown(content)
                    
        else:
            st.warning("No structured quantitative data found for this ticker.")
            
        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): 
                 st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "Qualitative Deep-Dive":
        st.info("🧠 **Qualitative Deep-Dive**: comprehensive analysis using Strategy and Risk profiles to drive 'Scuttlebutt' investigation.")
        
        qual_res = final_state.get('qualitative_results', {})
        
        # We use tabs to organize the heavy output
        tab_core, tab_scuttle, tab_context, tab_sebi = st.tabs([
            "📝 Core Analysis", 
            "🕵️ Scuttlebutt Intel", 
            "🧩 Context (Strat/Risk)", 
            "⚖️ SEBI Check"
        ])
        
        with tab_core:
            st.subheader("Positives & Concerns (Latest Quarter)")
            st.markdown(qual_res.get('positives_and_concerns', "Analysis not available."))
            
            st.divider()
            
            st.subheader("Strategic Shift (QoQ)")
            qoq_data = qual_res.get('qoq_comparison')
            if qoq_data:
                try:
                    # Reuse the dataframe logic for clean display
                    import json
                    clean_json = qoq_data.replace("```json", "").replace("```", "").strip()
                    df_compare = pd.DataFrame(json.loads(clean_json))
                    st.table(df_compare)
                except:
                    st.markdown(qoq_data)
            else:
                st.write("No QoQ comparison generated.")

        with tab_scuttle:
            st.markdown("### 🕵️ Scuttlebutt Investigation")
            st.markdown("This report synthesizes internal Strategy/Risk data with live external searches.")
            st.markdown(qual_res.get('scuttlebutt', "No Scuttlebutt report generated."))

        with tab_context:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Context: Strategy")
                st.markdown(final_state.get('strategy_results', "No Strategy Context"))
            with c2:
                st.subheader("Context: Risk")
                st.markdown(final_state.get('risk_results', "No Risk Context"))

        with tab_sebi:
            st.markdown(qual_res.get('sebi_check', "No SEBI check results."))
            
        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "Strategy Deep Dive":
        st.info("🎯 **Strategy Deep Dive**: Analyzes the latest Investor Presentation to identify growth pillars and strategic shifts.")
        
        strat_res = final_state.get('strategy_results', "No analysis available.")
        
        # Check if the agent returned the specific error regarding missing PPT
        if "No Investor Presentation found" in strat_res:
            st.error("Could not find an Investor Presentation (PPT) for this company. Strategy analysis requires this document.")
        else:
            st.markdown(strat_res)
            
        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "Valuation & Governance Deep-Dive":
        st.info("⚖️ **Valuation & Governance**: Relative valuation metrics and peer group comparison.")
        
        val_res = final_state.get('valuation_results', {})
        # Valuation agent usually returns a dict with 'content' and potentially 'peer_table'
        content = val_res.get('content', "No text analysis provided.") if isinstance(val_res, dict) else val_res
        
        st.markdown(content)
        
        if isinstance(val_res, dict) and 'peer_comparison_table' in val_res:
             st.subheader("📊 Peer Comparison Matrix")
             st.dataframe(val_res['peer_comparison_table'], width="stretch")
             
        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "SEBI Violations Check (MVP)":
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

    elif run_mode == "Latest Concall Analysis":
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

    elif run_mode == "QoQ Concall Analysis":
        st.info("QoQ Concall Analysis: Comparing the two most recent earnings calls to detect changes in tone, strategy, and outlook.")
        
        qual_res = final_state.get('qualitative_results', {})
        comp_json_str = qual_res.get('qoq_comparison')
        
        if comp_json_str:
            import json
            try:
                # The agent might return a string with json markdown, clean it
                clean_json = comp_json_str.replace("```json", "").replace("```", "").strip()
                comparison_data = json.loads(clean_json)
                
                st.subheader("📊 QoQ Concall Analysis")
                
                # Convert list of dicts to DataFrame for clean display
                df_compare = pd.DataFrame(comparison_data)
                
                # Header
                st.markdown("---")
                c1, c2, c3 = st.columns([1, 2, 2])
                c1.markdown("**Metric**")
                c2.markdown("**📉 Previous Quarter**")
                c3.markdown("**📈 Latest Quarter**")
                st.divider()
                
                for index, row in df_compare.iterrows():
                    metric = row.get("Metric", "N/A")
                    prev_val = row.get("Previous Quarter Analysis", "N/A")
                    curr_val = row.get("Latest Quarter Analysis", "N/A")
                    
                    c1, c2, c3 = st.columns([1, 2, 2])
                    with c1: st.markdown(f"**{metric}**")
                    with c2: st.markdown(prev_val)
                    with c3: st.markdown(curr_val)
                    st.divider()
                    
            except Exception as e:
                st.error(f"Could not parse comparison data: {e}")
                st.text(comp_json_str) # Fallback raw text
        else:
            st.warning("Comparison data could not be generated.")

        with st.expander("View Underlying Analyses"):
            tab_l, tab_p = st.tabs(["Latest Quarter Raw", "Previous Quarter Raw"])
            with tab_l: st.markdown(qual_res.get('latest_analysis', 'N/A'))
            with tab_p: st.markdown(qual_res.get('previous_analysis', 'N/A'))

        with st.expander("View Execution Logs"):
             if final_state.get('log_file_content'): st.code(final_state['log_file_content'], language='markdown')

    elif run_mode == "Scuttlebutt Research":
        st.info("Scuttlebutt Mode: 360-degree qualitative research using news, employee reviews, and industry forums.")
        
        qual_res = final_state.get('qualitative_results', {})
        scuttle_text = qual_res.get('scuttlebutt')
        
        if scuttle_text:
            st.markdown("### 🕵️ Scuttlebutt Investigation Report")
            st.markdown(scuttle_text)
        else:
            st.warning("Scuttlebutt analysis could not be generated.")

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