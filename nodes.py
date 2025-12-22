import datetime
import io
import time
import copy
import pandas as pd
from typing import Dict, Any, List

# --- Import State Schema ---
from state import StockAnalysisState

# --- Import Agent Functions ---
# These are assumed to exist in the same directory based on original file
from Screener_Download import download_financial_data
from qualitative_analysis_agent import (
    run_qualitative_analysis, 
    run_isolated_sebi_check, 
    run_earnings_analysis_standalone,
    run_comparison_standalone,
    run_scuttlebutt_standalone
)
from quantitative_agent import analyze_financials
from valuation_agent import run_valuation_analysis
from synthesis_agent import generate_investment_summary
from report_generator import create_pdf_report
from strategy_agent import strategy_analyst_agent
from risk_agent import risk_analyst_agent

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
                fallback_model = config.get('FALLBACK_TOKEN_MODEL', 'gemini-2.0-flash')
                reason_msg = "Token Limit (TPM)"
            else:
                fallback_model = config.get('FALLBACK_REQUEST_MODEL', 'gemini-2.0-flash-lite')
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
# 4a. EARNINGS DECODER NODES (MVP)
# ==============================================================================

def screener_latest_transcript_node(state: StockAnalysisState):
    """Downloads ONLY the latest transcript."""
    ticker = state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

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

    # Update: Pass 'Latest' label
    result_text = run_earnings_analysis_standalone(company_name, transcript, config, quarter_label="Latest")

    log_entry = f"## EARNINGS DECODER: ANALYSIS\n\n{result_text}\n\n---\n"
    log_content_accumulator += log_entry

    # Store specifically in 'latest_analysis' key
    current_qual = state.get('qualitative_results') or {}
    current_qual['latest_analysis'] = result_text

    return {"qualitative_results": current_qual, "log_file_content": log_content_accumulator}

# ==============================================================================
# 4b. STRATEGIC SHIFT NODES (NEW - Phase 3)
# ==============================================================================

def screener_both_transcripts_node(state: StockAnalysisState):
    """Downloads BOTH latest and previous transcripts."""
    ticker = state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    company_name, file_data, _ = download_financial_data(
        ticker, config, 
        need_excel=False, 
        need_ppt=False, 
        need_peers=False, 
        need_credit_report=False
    )

    l_status = "Downloaded" if file_data.get('latest_transcript') else "Not Found"
    p_status = "Downloaded" if file_data.get('previous_transcript') else "Not Found"

    log_entry = (f"## STRATEGIC SHIFT: DOWNLOAD\n\n"
                 f"**Latest Transcript**: {l_status}\n"
                 f"**Previous Transcript**: {p_status}\n\n---\n")
    log_content_accumulator += log_entry
    
    return {"company_name": company_name, "file_data": file_data, "log_file_content": log_content_accumulator}

def analyze_both_transcripts_node(state: StockAnalysisState):
    """Analyzes both transcripts individually to prepare for comparison."""
    company_name = state.get('company_name') or state['ticker']
    latest_pdf = state['file_data'].get('latest_transcript')
    previous_pdf = state['file_data'].get('previous_transcript')
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']
    
    current_qual = state.get('qualitative_results') or {}

    # 1. Analyze Latest (Updated: Pass label)
    if latest_pdf:
        latest_res = run_earnings_analysis_standalone(company_name, latest_pdf, config, quarter_label="Latest")
    else:
        latest_res = "No latest transcript available."
    
    # 2. Analyze Previous (Updated: Pass label)
    if previous_pdf:
        previous_res = run_earnings_analysis_standalone(company_name, previous_pdf, config, quarter_label="Previous")
    else:
        previous_res = "No previous transcript available."

    current_qual['latest_analysis'] = latest_res
    current_qual['previous_analysis'] = previous_res

    log_entry = f"## STRATEGIC SHIFT: INDIVIDUAL ANALYSIS\n\n**Latest Status**: Done\n**Previous Status**: Done\n\n---\n"
    log_content_accumulator += log_entry

    return {"qualitative_results": current_qual, "log_file_content": log_content_accumulator}

def compare_quarters_node(state: StockAnalysisState):
    """Runs the comparison agent using the two summaries generated above."""
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']
    qual_res = state.get('qualitative_results', {})
    
    latest_txt = qual_res.get('latest_analysis')
    prev_txt = qual_res.get('previous_analysis')
    
    comparison_json = run_comparison_standalone(latest_txt, prev_txt, config)
    
    qual_res['qoq_comparison'] = comparison_json
    
    log_entry = f"## STRATEGIC SHIFT: COMPARISON\n\n{comparison_json}\n\n---\n"
    log_content_accumulator += log_entry
    
    return {"qualitative_results": qual_res, "log_file_content": log_content_accumulator}

# ==============================================================================
# 4c. SCUTTLEBUTT RESEARCH NODE (NEW)
# ==============================================================================
def scuttlebutt_analysis_node(state: StockAnalysisState):
    company_name = state.get('company_name') or state['ticker']
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']
    
    # Extract Strategy and Risk results from state to use as inputs
    strat_res = state.get('strategy_results')
    risk_res = state.get('risk_results')

    result_text = execute_with_fallback(
        run_scuttlebutt_standalone, log_content_accumulator, "Scuttlebutt",
        company_name, config,
        strat=strat_res, # Passing previous agent outputs as kwargs
        risk=risk_res
    )

    log_entry = f"## SCUTTLEBUTT RESEARCH\n\n{result_text}\n\n---\n"
    log_content_accumulator += log_entry

    current_qual = state.get('qualitative_results') or {}
    current_qual['scuttlebutt'] = result_text

    return {"qualitative_results": current_qual, "log_file_content": log_content_accumulator}

# ==============================================================================
# 5. QUANTITATIVE DEEP-DIVE NODES
# ==============================================================================

def screener_for_quant_node(state: StockAnalysisState):
    """
    Step 1: Streamlined Fetch. 
    Downloads ONLY the Excel data to maximize speed for quantitative analysis.
    """
    ticker = state['ticker']
    is_consolidated = state['is_consolidated']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    # Call with minimal requirements: only need_excel is True
    company_name, file_data, peer_data = download_financial_data(
        ticker, config, is_consolidated,
        need_excel=True, 
        need_transcripts=False, 
        need_ppt=False, 
        need_peers=True, # Often needed for valuation/quant ratios
        need_credit_report=False 
    )
    
    log_entry = (f"## QUANT DEEP-DIVE: FETCH for {company_name or ticker}\n"
                 f"**Excel Data**: {'Downloaded' if file_data.get('excel') else 'Failed'}\n---\n")
    
    return {
        "company_name": company_name, 
        "file_data": file_data, 
        "peer_data": peer_data,
        "log_file_content": log_content_accumulator + log_entry
    }

def isolated_quantitative_node(state: StockAnalysisState):
    """
    Step 2: Isolated Analysis.
    Processes the Excel data specifically for visual rendering in the UI.
    """
    excel_data = state['file_data'].get('excel')
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    if not excel_data:
        text_results = "Quantitative analysis skipped: Excel data not found."
        structured_results = [{"type": "text", "content": text_results}]
    else:
        # Requesting structured data (DataFrames/Charts) from the agent
        structured_results = execute_with_fallback(
            analyze_financials, log_content_accumulator, "Quantitative (Isolated)",
            excel_data, state['ticker'], config
        )
        
        if isinstance(structured_results, str):
             text_results = structured_results
             structured_results = [{"type": "text", "content": text_results}]
        else:
             text_results = "\n".join([item['content'] for item in structured_results if item['type'] == 'text'])

    log_entry = f"## QUANT DEEP-DIVE: ANALYSIS COMPLETE\n\n{text_results}\n\n---\n\n"
    
    return {
        "quant_results_structured": structured_results, 
        "quant_text_for_synthesis": text_results, 
        "log_file_content": log_content_accumulator + log_entry
    }

# ==============================================================================
# 6. VALUATION DEEP-DIVE NODES
# ==============================================================================

def screener_for_valuation_node(state: StockAnalysisState):
    """Downloads only the Metadata and Peer Data needed for valuation analysis."""
    ticker = state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    # Call with minimal requirements: only need_peers is True
    company_name, _, peer_data = download_financial_data(
        ticker, config, 
        need_excel=False, 
        need_transcripts=False, 
        need_ppt=False, 
        need_peers=True, # Often needed for valuation/quant ratios
        need_credit_report=False 
    )
    
    log_entry = (f"## VALUATION DEEP-DIVE: FETCH for {company_name or ticker}\n"
                 f"**Peer Data**: {'Downloaded' if not peer_data.empty else 'Failed/Empty'}\n---\n")
    
    return {
        "company_name": company_name, 
        "peer_data": peer_data, 
        "log_file_content": log_content_accumulator + log_entry
    }

def isolated_valuation_node(state: StockAnalysisState):
    """Executes the standalone valuation analysis."""
    ticker = state['ticker']
    company_name = state.get('company_name') 
    peer_data = state.get('peer_data')
    config = state['agent_config']
    log_content_accumulator = state['log_file_content']
    
    results = execute_with_fallback(
        run_valuation_analysis, log_content_accumulator, "Valuation (Isolated)",
        ticker, company_name, peer_data, config
    )
    
    content = results.get("content", "No valuation analysis generated.") if isinstance(results, dict) else str(results)
    log_entry = f"## VALUATION DEEP-DIVE: ANALYSIS COMPLETE\n\n{content}\n\n---\n\n"
    
    return {
        "valuation_results": results if isinstance(results, dict) else {}, 
        "log_file_content": log_content_accumulator + log_entry
    }

# ==============================================================================
# 9. STRATEGY DEEP-DIVE NODES (NEW)
# ==============================================================================

def screener_for_strategy_node(state: StockAnalysisState) -> Dict[str, Any]:
    """
    Downloads ONLY the Investor Presentation (PPT).
    Sets all other download flags to False to minimize execution time.
    """
    ticker = state['ticker']
    config = state['agent_config']
    log_content_accumulator = state.get('log_file_content', "")

    # Call with minimal requirements: only need_ppt is True
    company_name, file_data, _ = download_financial_data(
        ticker, config, 
        need_excel=False, 
        need_transcripts=False, 
        need_ppt=True,          # <--- ONLY PPT
        need_peers=False, 
        need_credit_report=False 
    )
    
    status = "Downloaded" if file_data.get('investor_presentation') else "Not Found"
    log_entry = (f"## STRATEGY DEEP-DIVE: FETCH for {company_name or ticker}\n"
                 f"**Investor Presentation**: {status}\n---\n")
    
    return {
        "company_name": company_name, 
        "file_data": file_data, 
        "log_file_content": log_content_accumulator + log_entry
    }

def isolated_strategy_node(state: StockAnalysisState) -> Dict[str, Any]:
    """
    Executes the standalone strategy analysis using the downloaded PPT.
    """
    log_content_accumulator = state['log_file_content']
    config = state['agent_config']
    
    def strategy_wrapper(f_data, cfg):
        model_to_use = cfg.get("LITE_MODEL_NAME") 
        return strategy_analyst_agent(f_data, cfg["GOOGLE_API_KEY"], model_to_use)

    result_text = execute_with_fallback(
        strategy_wrapper, log_content_accumulator, "Strategy (Isolated)",
        state['file_data'], config
    )

    log_entry = f"## STRATEGY DEEP-DIVE: ANALYSIS COMPLETE\n\n{result_text}\n\n---\n\n"
    
    return {
        "strategy_results": result_text, 
        "log_file_content": log_content_accumulator + log_entry
    }