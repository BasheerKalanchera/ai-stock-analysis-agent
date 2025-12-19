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

# --- Runner Function ---
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
    if workflow_mode == "Quantitative Deep-Dive":
        target_graph = graphs.quant_only_graph
        placeholders = {
            "screener_for_quant": status_container.empty(),
            "isolated_quant": status_container.empty(),
        }
        placeholders["screener_for_quant"].markdown("⏳ **Downloading Excel Data...**")

    elif workflow_mode == "Valuation & Governance Deep-Dive":
        target_graph = graphs.valuation_only_graph
        placeholders = {
            "screener_for_valuation": status_container.empty(),
            "isolated_valuation": status_container.empty(),
        }
        placeholders["screener_for_valuation"].markdown("⏳ **Identifying Peers & Market Data...**")

    elif workflow_mode == "Risk Analysis Only":
        target_graph = graphs.risk_only_graph
        placeholders = {
            "screener_for_risk": status_container.empty(),
            "isolated_risk": status_container.empty(),
        }
        placeholders["screener_for_risk"].markdown("⏳ **Checking Credit Ratings...**")

    elif workflow_mode == "SEBI Violations Check (MVP)":
        target_graph = graphs.sebi_workflow
        placeholders = {
            "screener_metadata": status_container.empty(),
            "sebi_check": status_container.empty()
        }
        placeholders["screener_metadata"].markdown("⏳ **Identifying Company...**")

    elif workflow_mode == "Latest Earnings Decoder":
        target_graph = graphs.earnings_graph
        placeholders = {
            "fetch_latest": status_container.empty(),
            "analyze_latest": status_container.empty()
        }
        placeholders["fetch_latest"].markdown("⏳ **Fetching Latest Transcript...**")
    
    elif workflow_mode == "Strategic Shift Analyzer (QoQ)":
        target_graph = graphs.strategy_shift_graph
        placeholders = {
            "fetch_both": status_container.empty(),
            "analyze_both": status_container.empty(),
            "compare_quarters": status_container.empty()
        }
        placeholders["fetch_both"].markdown("⏳ **Fetching History...**")

    elif workflow_mode == "Scuttlebutt Research":
        target_graph = graphs.scuttlebutt_graph
        placeholders = {
            "fetch_data": status_container.empty(),
            "strategy_analysis": status_container.empty(),
            "risk_analysis": status_container.empty(),
            "scuttlebutt_analysis": status_container.empty()
        }
        placeholders["fetch_data"].markdown("⏳ **Downloading Financial Data...**")

    else: # Default: Full Workflow
        target_graph = graphs.app_graph
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
            
            elif workflow_mode == "Strategic Shift Analyzer (QoQ)":
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
        "Valuation & Governance Deep-Dive",
        "Risk Analysis Only",
        "SEBI Violations Check (MVP)",
        "Latest Earnings Decoder",
        "Strategic Shift Analyzer (QoQ)",
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

    elif run_mode == "Strategic Shift Analyzer (QoQ)":
        st.info("Strategic Shift Mode: Comparing the two most recent earnings calls to detect changes in tone, strategy, and outlook.")
        
        qual_res = final_state.get('qualitative_results', {})
        comp_json_str = qual_res.get('qoq_comparison')
        
        if comp_json_str:
            import json
            try:
                # The agent might return a string with json markdown, clean it
                clean_json = comp_json_str.replace("```json", "").replace("```", "").strip()
                comparison_data = json.loads(clean_json)
                
                st.subheader("📊 Strategic Shift Matrix")
                
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