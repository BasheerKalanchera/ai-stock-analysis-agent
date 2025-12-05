import streamlit as st
import os
import datetime
from dotenv import load_dotenv
from typing import TypedDict, Dict, Any, List, Annotated
import io
import time
import pandas as pd 

# --- LangGraph Imports ---
from langgraph.graph import StateGraph, END

# --- Import Agent Functions ---
from Screener_Download import download_financial_data
from qualitative_analysis_agent import run_qualitative_analysis
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

# --- CENTRALIZED SECRET & CONFIGURATION HANDLING ---
agent_configs = {}
try:
    # This will succeed on Streamlit Cloud
    agent_configs = {
        "SCREENER_EMAIL": st.secrets["SCREENER_EMAIL"],
        "SCREENER_PASSWORD": st.secrets["SCREENER_PASSWORD"],
        "GOOGLE_API_KEY": st.secrets["GOOGLE_API_KEY"],
        "LITE_MODEL_NAME": st.secrets.get("LITE_MODEL_NAME", "gemini-2.5-flash-lite"),
        "HEAVY_MODEL_NAME": st.secrets.get("HEAVY_MODEL_NAME", "gemini-2.5-flash"),
        "IS_CLOUD_ENV": True 
    }
except (st.errors.StreamlitAPIException, KeyError) as e:
    # This will happen locally
    if "No secrets found" in str(e) or isinstance(e, KeyError):
        agent_configs = {
            "SCREENER_EMAIL": os.getenv("SCREENER_EMAIL"),
            "SCREENER_PASSWORD": os.getenv("SCREENER_PASSWORD"),
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
            "LITE_MODEL_NAME": os.getenv("LITE_MODEL_NAME", "gemini-2.5-flash-lite"),
            "HEAVY_MODEL_NAME": os.getenv("HEAVY_MODEL_NAME", "gemini-2.5-flash"),
            "IS_CLOUD_ENV": False 
        }
    else:
        raise e

# Validate secrets
essential_keys = ["SCREENER_EMAIL", "SCREENER_PASSWORD", "GOOGLE_API_KEY"]
missing_keys = [key for key in essential_keys if not agent_configs.get(key)]
if missing_keys:
    st.error(f"Missing secrets: {', '.join(missing_keys)}.")
    st.stop()


# --- Define Graph State ---
class StockAnalysisState(TypedDict):
    """
    State container for the stock analysis workflow.
    """
    ticker: str
    company_name: str | None
    file_data: Dict[str, io.BytesIO]
    peer_data: pd.DataFrame | None 
    quant_results_structured: List[Dict[str, Any]] | None
    quant_text_for_synthesis: str | None
    
    # --- NEW STATE KEYS ---
    strategy_results: str | None
    risk_results: str | None
    # ----------------------
    
    qualitative_results: Dict[str, Any] | None
    valuation_results: Dict[str, Any] | None
    final_report: str | None
    log_file_content: Annotated[str, lambda x, y: x + y]
    pdf_report_bytes: bytes | None
    is_consolidated: bool | None
    agent_config: Dict[str, Any] 

# --- Agent Nodes ---

def fetch_data_node(state: StockAnalysisState):
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']
    config = state['agent_config']
    
    log_content_accumulator = state.get('log_file_content', "")

    company_name, file_data, peer_data = download_financial_data(
        ticker,
        config,
        is_consolidated
    )
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_header = f"AGENT 1: DOWNLOAD SUMMARY for {company_name or ticker}"
    
    peer_status = "Downloaded" if not peer_data.empty else "Not Found/Failed"

    log_entry = (f"## {log_header}\n\n"
                 f"**Timestamp**: {timestamp_str}\n\n"
                 f"**Excel Data**: {'Downloaded' if file_data.get('excel') else 'Failed'}\n\n"
                 f"**Peer Data**: {peer_status}\n\n" 
                 f"**Latest Transcript**: {'Downloaded' if file_data.get('latest_transcript') else 'Failed'}\n\n"
                 f"**PPT**: {'Downloaded' if file_data.get('investor_presentation') else 'Failed'}\n\n"
                 f"**Credit Rating**: {'Downloaded' if file_data.get('credit_rating_doc') else 'Failed'}\n\n---\n\n")
    
    log_content_accumulator += log_entry
        
    return {
        "company_name": company_name, 
        "file_data": file_data,
        "peer_data": peer_data, 
        "log_file_content": log_content_accumulator
    }

def quantitative_analysis_node(state: StockAnalysisState):
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

# --- NEW NODE: STRATEGY ANALYSIS ---
def strategy_analysis_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    # Use heavy model for complex reasoning
    model_name = config.get("HEAVY_MODEL_NAME")
    api_key = config.get("GOOGLE_API_KEY")

    result_text = strategy_analyst_agent(state['file_data'], api_key, model_name)

    log_content_accumulator += f"## AGENT 3: STRATEGY & ALPHA SEARCH\n\n{result_text}\n\n---\n\n"
    return {"strategy_results": result_text, "log_file_content": log_content_accumulator}
# -----------------------------------

# --- NEW NODE: RISK ANALYSIS ---
def risk_analysis_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    model_name = config.get("HEAVY_MODEL_NAME") 
    api_key = config.get("GOOGLE_API_KEY")

    result_text = risk_analyst_agent(state['file_data'], api_key, model_name)

    log_content_accumulator += f"## AGENT 4: RISK & CREDIT CHECK\n\n{result_text}\n\n---\n\n"
    return {"risk_results": result_text, "log_file_content": log_content_accumulator}
# -----------------------------------

def qualitative_analysis_node(state: StockAnalysisState):
    company = state['company_name'] or state['ticker']
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    # --- UPDATED: Get Context from Strategy & Risk ---
    # These will be populated because of the new graph order
    strategy_ctx = state.get('strategy_results', "")
    risk_ctx = state.get('risk_results', "")
    # -------------------------------------------------

    results = run_qualitative_analysis(
        company, 
        state['file_data'].get("latest_transcript"),
        state['file_data'].get("previous_transcript"),
        config,
        strategy_context=strategy_ctx, # Pass context
        risk_context=risk_ctx          # Pass context
    )
    
    log_entry = "## AGENT 5: QUALITATIVE ANALYSIS\n\n"
    for key, value in results.items():
        log_entry += f"### {key.replace('_', ' ').title()}\n{value}\n\n"
    log_entry += "---\n\n"
    
    log_content_accumulator += log_entry
    return {"qualitative_results": results, "log_file_content": log_content_accumulator}

def valuation_analysis_node(state: StockAnalysisState):
    ticker = state['ticker']
    company_name = state.get('company_name') 
    peer_data = state.get('peer_data')
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']
    
    results = run_valuation_analysis(ticker, company_name, peer_data, config)
    content = results.get("content", "No valuation analysis generated.")
    
    log_content_accumulator += f"## AGENT 6: VALUATION & GOVERNANCE ANALYSIS\n\n{content}\n\n---\n\n"
    
    return {
        "valuation_results": results,
        "log_file_content": log_content_accumulator
    }

def delay_node(state: StockAnalysisState):
    time.sleep(60) # Wait to respect rate limits
    return {}

def synthesis_node(state: StockAnalysisState):
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    quant_text = state.get('quant_text_for_synthesis', "Quantitative analysis was not performed.")
    
    # --- UPDATED: Pass Strategy & Risk to Synthesis ---
    report = generate_investment_summary(
        state['company_name'] or state['ticker'],
        quant_text,
        state['qualitative_results'],
        state['valuation_results'],
        state.get('risk_results'),      # NEW
        state.get('strategy_results'),  # NEW
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
        strategy_results=state.get('strategy_results', ""), # New
        risk_results=state.get('risk_results', ""),         # New
        valuation_results=state.get('valuation_results', {}), # New
        final_report=state.get('final_report', "Report could not be fully generated."),
        file_path=pdf_buffer
    )
    pdf_buffer.seek(0)
    return {"pdf_report_bytes": pdf_buffer.getvalue()}

# --- Build the Graph ---
workflow = StateGraph(StockAnalysisState)
workflow.add_node("fetch_data", fetch_data_node)
workflow.add_node("quantitative_analysis", quantitative_analysis_node)
workflow.add_node("strategy_analysis", strategy_analysis_node) # NEW
workflow.add_node("risk_analysis", risk_analysis_node)         # NEW
workflow.add_node("qualitative_analysis", qualitative_analysis_node)
workflow.add_node("valuation_analysis", valuation_analysis_node)
workflow.add_node("delay_before_synthesis", delay_node)
workflow.add_node("synthesis", synthesis_node)
workflow.add_node("generate_report", generate_report_node)

workflow.set_entry_point("fetch_data")

# --- SEQUENTIAL FLOW UPDATED FOR CONTEXT ---
# 1. Fetch
# 2. Quant
# 3. Strategy (Extracts Company Context)
# 4. Risk (Extracts Risk Context)
# 5. Qual (Uses Strategy/Risk Context for Scuttlebutt)
# 6. Valuation
# 7. Synthesis

workflow.add_edge("fetch_data", "quantitative_analysis")
workflow.add_edge("quantitative_analysis", "strategy_analysis") 
workflow.add_edge("strategy_analysis", "risk_analysis")
workflow.add_edge("risk_analysis", "qualitative_analysis") # <--- Qual now has access to previous results
workflow.add_edge("qualitative_analysis", "valuation_analysis") 
workflow.add_edge("valuation_analysis", "delay_before_synthesis") 
workflow.add_edge("delay_before_synthesis", "synthesis")

workflow.add_edge("synthesis", "generate_report")
workflow.add_edge("generate_report", END)

app_graph = workflow.compile()

# --- Helper Function for UI ---
def extract_investment_thesis(full_report: str) -> str:
    try:
        search_key = "Investment Thesis"
        start_index = full_report.lower().find(search_key.lower())
        if start_index == -1: return "Investment thesis could not be extracted."
        content_start_index = full_report.find('\n', start_index) + 1
        next_section_index = full_report.find("\n## ", content_start_index)
        if next_section_index == -1:
            thesis_content = full_report[content_start_index:].strip()
        else:
            thesis_content = full_report[content_start_index:next_section_index].strip()
        return thesis_content
    except Exception as e:
        return "Investment thesis could not be extracted due to a formatting error."

# --- Streamlit UI ---
st.title("🤖 AI Stock Analysis Crew (Enhanced)")
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
        
        initial_msg = f"Our analysis crew is working on the report for {st.session_state.ticker}..."
        
        with st.status(initial_msg, expanded=True) as status:
            final_state_result = {}
            try:
                placeholders = {
                    "fetch_data": st.empty(),
                    "quant": st.empty(),
                    "strategy": st.empty(),
                    "risk": st.empty(),
                    "qual": st.empty(),
                    "valuation": st.empty(),
                    "synthesis": st.empty(),
                }
                
                placeholders["fetch_data"].markdown("⏳ **Downloading Financial Data...**")

                for event in app_graph.stream(inputs):
                    for node_name, node_output in event.items():
                        
                        if node_name == "fetch_data":
                            c_name = node_output.get("company_name")
                            if c_name:
                                status.update(label=f"Analyzing {st.session_state.ticker} ({c_name})...")
                            placeholders["fetch_data"].markdown("✅ **Data Downloaded**")
                            placeholders["quant"].markdown("⏳ **Running Quantitative Analysis...**")
                        
                        elif node_name == "quantitative_analysis":
                            placeholders["quant"].markdown("✅ **Quantitative Analysis Complete**")
                            placeholders["strategy"].markdown("⏳ **Analyzing Strategy & PPT...**")
                        
                        elif node_name == "strategy_analysis":
                            placeholders["strategy"].markdown("✅ **Strategy Analysis Complete**")
                            placeholders["risk"].markdown("⏳ **Analyzing Credit Risk...**")

                        elif node_name == "risk_analysis":
                            placeholders["risk"].markdown("✅ **Risk Analysis Complete**")
                            placeholders["qual"].markdown("⏳ **Running Qualitative & Scuttlebutt Analysis...**")

                        elif node_name == "qualitative_analysis":
                            placeholders["qual"].markdown("✅ **Qualitative Analysis Complete**")
                            placeholders["valuation"].markdown("⏳ **Running Valuation & Governance Check...**")
                        
                        elif node_name == "valuation_analysis":
                             placeholders["valuation"].markdown("✅ **Valuation Check Complete**")
                             placeholders["synthesis"].markdown("⏳ **Generating Final Summary (Wait ~60s)...**")

                        elif node_name == "synthesis":
                             placeholders["synthesis"].markdown("✅ **Final Summary Generated**")
                        
                        elif node_name == "generate_report":
                             pass

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

    if final_state.get('final_report'):
        st.subheader("📈📝 Investment Thesis")
        investment_thesis = extract_investment_thesis(final_state['final_report'])
        st.markdown(investment_thesis, unsafe_allow_html=True)
    
    st.markdown("---") 

    if final_state.get('pdf_report_bytes'):
        st.info("Download full report for charts, logs and deep-dive data.")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_filename = f"Report_{final_state.get('ticker', 'STOCK')}_{timestamp}.pdf"
        col1, col2, col3 = st.columns([2, 3, 2])
        with col2:
            st.download_button(
                label="**Download Full PDF Report**",
                data=final_state['pdf_report_bytes'],
                file_name=report_filename,
                mime="application/pdf",
                use_container_width=True
            )

    with st.expander("📂 View Detailed Agent Outputs & Logs", expanded=False):
        
        # Using Tabs for cleaner organization of the multiple agents
        tab_strat, tab_risk, tab_val, tab_qual, tab_quant, tab_log = st.tabs([
            "Strategy", "Risk", "Valuation", "Qualitative", "Quantitative", "Execution Logs"
        ])
        
        with tab_strat:
            st.subheader("🎯 Strategy & Alpha Analysis")
            if final_state.get('strategy_results'):
                st.markdown(final_state['strategy_results'])
            else:
                st.warning("Strategy analysis not available.")

        with tab_risk:
            st.subheader("🛡️ Risk & Credit Profile")
            if final_state.get('risk_results'):
                st.markdown(final_state['risk_results'])
            else:
                st.warning("Risk analysis not available.")

        with tab_val:
            st.subheader("⚖️ Valuation & Governance")
            if final_state.get('valuation_results'):
                 st.markdown(final_state['valuation_results']['content'])
            else:
                 st.warning("Valuation analysis not available.")

        with tab_qual:
            st.subheader("📝 Qualitative Insights")
            if final_state.get('qualitative_results'):
                qual_results = final_state['qualitative_results']
                for key, value in qual_results.items():
                    st.markdown(f"**{key.replace('_', ' ').title()}:** {value}")
            else:
                st.warning("Qualitative analysis not available.")

        with tab_quant:
            st.subheader("📈 Quantitative Insights")
            if final_state.get('quant_text_for_synthesis'):
                st.markdown(final_state['quant_text_for_synthesis'])

        with tab_log:
            if final_state.get('log_file_content'):
                 st.code(final_state['log_file_content'], language='markdown')

else:
    st.info("Enter a stock ticker in the sidebar and click 'Run Full Analysis' to begin.")