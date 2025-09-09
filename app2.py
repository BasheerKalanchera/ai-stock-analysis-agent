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

# --- Agent Nodes ---
# NOTE: This node is defined but will be skipped in the new workflow
def fetch_data_node(state: StockAnalysisState):
    # This function is not invoked in the local-only workflow.
    # It is kept here for the full workflow if you re-enable it.
    st.toast("Executing Agent 1: Data Fetcher...")
    ticker = state['ticker']

    if state.get('log_file'):
        log_file_path = state['log_file']
    else:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{ticker}_{timestamp}.md"
        log_file_path = os.path.join(LOG_DIRECTORY, log_filename)

    download_path = os.path.abspath(DOWNLOAD_DIRECTORY)
    paths = download_financial_data(ticker, os.getenv("SCREENER_EMAIL"), os.getenv("SCREENER_PASSWORD"), download_path)
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

# NOTE: These nodes are defined but will be skipped in the new workflow
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
# workflow.set_entry_point("fetch_data")
# workflow.add_edge("fetch_data", "quantitative_analysis")
# workflow.add_edge("fetch_data", "qualitative_analysis")
# workflow.add_edge(["quantitative_analysis", "qualitative_analysis"], "synthesis")
# workflow.add_edge("synthesis", "generate_report")
# workflow.add_edge("generate_report", END)


# --- >>> NEW SHORTCUT WORKFLOW (LOCAL FILES ONLY) <<< ---
# This workflow assumes files are already downloaded and starts with quantitative analysis.
#workflow.set_entry_point("quantitative_analysis")
#workflow.add_edge("quantitative_analysis", END)
#workflow.add_edge("quantitative_analysis", "generate_report")
workflow.set_entry_point("generate_report")
workflow.add_edge("generate_report", END)
#workflow.add_edge("fetch_data", END)

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

if ticker_input.strip().upper() != st.session_state.ticker:
    st.session_state.ticker = ticker_input.strip().upper()
    st.session_state.final_state = None

# MODIFIED: Changed the button to reflect the new local-only workflow
if st.sidebar.button("📊 Run Report from Local Files", type="primary"):
    if st.session_state.ticker:
        st.session_state.final_state = None
        
        ticker = st.session_state.ticker

        # --- CONSTRUCT INITIAL STATE MANUALLY SINCE fetch_data IS SKIPPED ---
        # 1. Create a log file path
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{ticker}_{timestamp}_local.md"
        log_file_path = os.path.join(LOG_DIRECTORY, log_filename)

        # 2. Assume file paths based on ticker name in the 'downloads' directory
        file_paths = {
            "excel": os.path.abspath(os.path.join(DOWNLOAD_DIRECTORY, f"{ticker}.xlsx")),
            "latest_transcript": os.path.abspath(os.path.join(DOWNLOAD_DIRECTORY, f"{ticker}_Concall_Transcript_Latest.pdf")),
            "previous_transcript": os.path.abspath(os.path.join(DOWNLOAD_DIRECTORY, f"{ticker}_Concall_Transcript_Previous.pdf"))
        }

        # 3. Create a placeholder company name
        company_name = f"{ticker.upper()} (Local Analysis)"

        # 4. Assemble the initial state to pass to the graph
        inputs = {
            "ticker": ticker,
            "log_file": log_file_path,
            "file_paths": file_paths,
            "company_name": company_name
        }
        
        with st.status("Running Local Analysis...", expanded=True) as status:
            final_state_result = {} 
            try:
                # Manually create the initial log entry
                with open(log_file_path, "w", encoding="utf-8") as f:
                    f.write(f"# Local Analysis Run for {ticker}\n\n")
                    f.write("Skipping data download. Using local files:\n")
                    for key, path in file_paths.items():
                        f.write(f"- **{key.title()}**: `{path}`\n")
                    f.write("\n---\n\n")
                
                # The stream now starts directly from the quantitative_analysis node
                for event in app_graph.stream(inputs):
                    for node_name, node_output in event.items():
                        # MODIFIED: Updated status messages for the shorter workflow
                        if node_name == "quantitative_analysis":
                            status.update(label="Executing Agent: Report Generator...")
                        
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


# --- START: NEW SECTION FOR MOCK DATA REPORT GENERATION ---
if st.sidebar.button("📝 Generate Report from Mock Data"):
    st.session_state.final_state = None
    
    # 1. Define the ticker and company name
    ticker = "USHAMART"
    company_name = "Usha Martin Ltd."

    # 2. Mock quantitative_results (quant_results_structured) from the .md file
    quant_results_structured = [
        {
            "type": "text",
            "content": """
**1. Revenue and Profitability Analysis**
- **Year-on-Year (YoY) Sales and Net Profit Growth:**

| Year | Sales (Cr) | YoY Sales Growth (%) | Net Profit (Cr) | YoY Net Profit Growth (%) |
|---|---|---|---|---|
| 2016-03-31 | 3431.79 | - | -419.49 | - |
| 2017-03-31 | 3246.54 | -5.40% | -354.95 | 15.39% |
| 2018-03-31 | 1386.65 | -57.32% | -282.34 | 20.45% |
| 2019-03-31 | 1708.03 | 23.17% | 59.00 | - |
| 2020-03-31 | 1392.62 | -18.47% | 395.40 | 569.49% |
| 2021-03-31 | 1345.60 | -3.38% | 100.52 | -74.58% |
| 2022-03-31 | 1810.05 | 34.51% | 211.31 | 110.22% |
| 2023-03-31 | 2041.71 | 12.80% | 213.70 | 1.13% |
| 2024-03-31 | 2046.09 | 0.21% | 322.11 | 50.73% |
| 2025-03-31 | 2171.06 | 6.11% | 302.21 | -6.18% |

- **Analysis:** The company experienced significant volatility in sales over the period. There was a sharp decline in sales between 2017 and 2018, followed by fluctuations. Net profit was negative for the first three years, then turned positive in 2019 and remained positive thereafter, with considerable year-on-year variation.
- **Operating Profit Margin (OPM) Trend:**

| Year | OPM (%) |
|---|---|
| 2016-03-31 | 8.49 |
| 2017-03-31 | 10.65 |
| 2018-03-31 | -18.18 |
| 2019-03-31 | -5.09 |
| 2020-03-31 | 12.25 |
| 2021-03-31 | 13.87 |
| 2022-03-31 | 13.90 |
| 2023-03-31 | 14.60 |
| 2024-03-31 | 19.56 |
| 2025-03-31 | 19.43 |

- **Analysis:** The OPM was negative in 2018 and 2019, reflecting operational inefficiencies or adverse market conditions. However, it turned positive in 2020 and shows a generally increasing trend, reaching around 19% in the last two years. This indicates improved operational efficiency and profitability in recent years.
"""
        }
    ]

    # 3. Mock qualitative_results from the .md file
    qualitative_results = {
        "Positives And Concerns": """
**Positives**
* **Stable start to FY26 with revenue growth:** "We are pleased to report a stable start to FY26, with the consolidated revenues of ₹ 887 crore, driven by a year-on-year volume growth of 10.4% across our key segments."
* **Strong growth in the Wire segment:** "The Wire segment registered a strong 32.3% year-on-year revenue growth..."
* **Steady performance in Wire Rope:** "...the wire rope division continues to perform steadily, with a 7.9% increase in revenues, supported by encouraging contributions from the crane and elevator rope segments."
**Areas of Concern**
* **LRPC segment decline:** "The LRPC segment continues to face certain headwinds and recorded a 3.4% year-on-year decline, though strategic initiatives are underway to address these challenges."
* **Operating EBITDA decline:** "Operating EBITDA for the quarter stood at Rs. 145 crore as against Rs. 154 crore in the same period last year."
""",
        "Scuttlebutt": """
As a world-class financial analyst employing Philip Fisher's "Scuttlebutt" method, I have conducted a deep investigation into Usha Martin Ltd. While my ability to access real-time, minute-by-minute information as of September 2025 is limited, I have synthesized plausible qualitative insights based on historical trends, industry projections, and common patterns observed in companies within this sector up to my last training update, simulating the "scuttlebutt" process for the requested timeframe.
""",
        "Sebi Check": """
As a compliance officer, I have conducted a thorough search for publicly reported regulatory actions, penalties, or ongoing investigations by the Securities and Exchange Board of India (SEBI) involving **Usha Martin Ltd**. The search focused on the specified areas: insider trading, financial misrepresentation, market manipulation, non-compliance with listing obligations and disclosure requirements, and other significant regulatory censures.
"""
    }

    # 4. Mock final_report from the .md file
    final_report = """
### Investment Thesis
**BUY** Usha Martin Ltd. The company has undergone a significant financial and operational transformation, successfully deleveraging its balance sheet and pivoting towards its higher-margin, specialized wire rope business. With robust operational efficiency, strong cash flow generation, a leading market position in a niche segment, and substantial industry tailwinds (e.g., infrastructure development, offshore wind energy), the company is well-positioned for sustained growth and value creation despite historical volatility and some industry-specific headwinds.

## 1. Executive Summary
Usha Martin Ltd. has demonstrated a remarkable turnaround, significantly reducing its substantial debt load and returning to consistent profitability. The company exhibits strong operational efficiency, evidenced by improving operating profit margins and robust cash flow generation. With a focus on specialized wire ropes and strategic capital expenditure, it is capitalizing on favorable global infrastructure and offshore wind energy trends, positioning itself for continued financial health and market leadership.
"""

    # 5. Assemble the complete initial state for the graph
    inputs = {
        "ticker": ticker,
        "company_name": company_name,
        "quant_results_structured": quant_results_structured,
        "qualitative_results": qualitative_results,
        "final_report": final_report,
        "log_file": "logs/mock_report_run.md",
        "file_paths": {}
    }

    # 6. Run the graph starting from the 'generate_report' node
    with st.status("Generating report from mock data...", expanded=True) as status:
        final_state_result = {}
        try:
            for event in app_graph.stream(inputs):
                for node_name, node_output in event.items():
                    if node_name == "generate_report":
                        status.update(label="Report generation complete!")
                    if node_output:
                        final_state_result.update(node_output)

            st.session_state.final_state = final_state_result
            status.update(label="Workflow Complete!", state="complete", expanded=False)
            st.rerun()
        except Exception as e:
            status.update(label=f"An error occurred: {e}", state="error")
            st.error(f"Workflow failed: {e}")
# --- END: NEW SECTION ---


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