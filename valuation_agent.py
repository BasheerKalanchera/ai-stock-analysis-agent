"""
valuation_agent.py
==================
Agent responsible for performing relative valuation against peer companies.

CHANGE LOG
----------
[2026-03-09] Dynamic Sector-Specific Valuation via Skills
  - Expanded `run_valuation_analysis` to dynamically load sector-specific methodology 
    using Markdown skill files (`skills_loader.py`).
  - Added support for fetching and formatting context directly from prior Qualitative 
    and quantitative analytical extractions.
  - Added grounding rules to prevent the LLM from hallucinating missing ratios.
"""

import logging
import pandas as pd
import google.generativeai as genai
from typing import Dict, Any
import time
import random
import re
from google.api_core import exceptions as google_exceptions

# --- CUSTOM LOGGER SETUP ---
logger = logging.getLogger('valuation_agent')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - 🟠 VALUATION - %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False

def generate_with_retry(model, prompt, max_retries=3, base_delay=30):
    """
    Helper to retry Gemini generation on rate limit errors.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
            retry_seconds = base_delay 
            try:
                match = re.search(r'retry_delay.*seconds:\s*(\d+)', str(e), re.DOTALL | re.IGNORECASE)
                if match:
                    retry_seconds = int(match.group(1)) + 5 
            except:
                pass

            if retry_seconds == base_delay:
                retry_seconds = base_delay + random.uniform(1, 5)

            logger.warning(f"Generation (Attempt {attempt + 1}/{max_retries}) encountered rate limit - retry after {retry_seconds:.1f} seconds.")
            time.sleep(retry_seconds)
            
        except Exception as e:
            if "429" in str(e):
                retry_seconds = base_delay + random.uniform(1, 5)
                logger.warning(f"Generation (Attempt {attempt + 1}/{max_retries}) encountered generic 429 - retry after {retry_seconds:.1f} seconds.")
                time.sleep(retry_seconds)
            else:
                raise e
                
    raise Exception(f"Max retries ({max_retries}) exceeded. The API is too busy.")

def clean_and_format_peer_data(df: pd.DataFrame) -> str:
    """
    Prepares a clean, narrow markdown table for the LLM using REGEX matching.
    This ensures we find columns even if they have extra spaces or slight name variations.
    """
    if df.empty:
        return ""

    # 1. Normalize Header: Strip whitespace and newlines
    df.columns = [str(c).strip().replace('\n', ' ') for c in df.columns]

    # 2. Define Regex Patterns for the core columns we want standardized
    column_patterns = {
        'Company_Name': r'(?i)(name|company)',
        'Current_Price': r'(?i)(cmp|current\s*price|price)',
        'Market_Cap': r'(?i)(mar\s*cap|market\s*cap)',
        'PE_Ratio': r'(?i)(^p/e$|pe\s*ratio)',
        'PEG_Ratio': r'(?i)(peg)',
        'Price_to_Book': r'(?i)(p/b|price\s*to\s*book|cmp\s*/\s*bv)',
        'EV_to_EBITDA': r'(?i)(ev\s*/\s*ebitda)',
        'ROCE_Percent': r'(?i)(roce)',
        'Debt_to_Equity_Ratio': r'(?i)(debt\s*/\s*eq|debt\s*to\s*equity)',
        'Promoter_Pledged_Percent': r'(?i)(pledge)',
        'Free_Cash_Flow': r'(?i)(free\s*cash\s*flow|fcf)'
    }

    rename_dict = {}

    # 3. Scan columns using Regex
    for col in df.columns:
        for target_name, pattern in column_patterns.items():
            if re.search(pattern, col) and target_name not in rename_dict.values():
                rename_dict[col] = target_name
                break # Move to next column once matched
    
    # 4. Filter and Rename
    try:
        # KEEP ALL COLUMNS, just rename the known ones so custom metrics stay available
        clean_df = df.rename(columns=rename_dict)
        
        # 5. Fill NaNs to avoid markdown errors
        clean_df.fillna(0, inplace=True)
        
        # DEBUG: Log what we found
        logger.info(f"Columns extracted for LLM (including custom): {clean_df.columns.tolist()}")
        
        return clean_df.head(15).to_markdown(index=False)
        
    except Exception as e:
        logger.warning(f"Column cleaning failed: {e}. Falling back to raw data.")
        return df.head(15).to_markdown(index=False)

def run_valuation_analysis(ticker: str, company_name: str, peer_df: pd.DataFrame, agent_config: dict, sector: str = None, **kwargs) -> Dict[str, Any]:
    """
    Analyzes the company valuation relative to peers using Gemini.
    Loads sector-specific valuation methodology from Skills .md files.
    Accepts optional quant_context and strategy_context for richer analysis.
    """
    logger.info(f"--- Starting Valuation Analysis for {ticker} ({company_name}) ---")

    if peer_df is None or peer_df.empty:
        logger.warning("No peer data provided. Skipping analysis.")
        return {"content": "Valuation analysis skipped: No peer data available."}

    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-2.5-flash") 
    
    if not api_key:
        return {"content": "ERROR: Google API Key missing for Valuation Agent."}

    # Extract optional context from kwargs
    quant_context = kwargs.get('quant_context', '')
    strategy_context = kwargs.get('strategy_context', '')

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # --- CLEANING STEP ---
        peer_markdown = clean_and_format_peer_data(peer_df)
        # ---------------------

        # --- SKILL LOADING ---
        from skills_loader import load_skill_for_sector
        skill_content, skill_file = load_skill_for_sector(sector or "Unknown")
        logger.info(f"📚 Using valuation skill: {skill_file} (sector: {sector or 'Unknown'})")
        # ---------------------
        
        target_identifier = company_name if company_name else ticker
        sector_label = sector if sector and sector != "Unknown" else "General"

        # --- BUILD OPTIONAL CONTEXT SECTIONS ---
        additional_context = ""
        if quant_context and quant_context.strip():
            additional_context += f"""
        **Target Company Financial Summary (from Quantitative Analysis):**
        This contains revenue trends, margins, debt levels, and cash flow data for {target_identifier}.
        {quant_context}
        """
            logger.info("📊 Quant context injected into valuation prompt.")

        if strategy_context and strategy_context.strip():
            additional_context += f"""
        **Target Company Strategy & Sector KPIs (from Investor Presentation):**
        This may contain sector-specific operational metrics (e.g., NIM for banks, ARPOB for hospitals, order book for equipment companies).
        {strategy_context}
        """
            logger.info("🎯 Strategy context injected into valuation prompt.")

        prompt = f"""
        You are a Valuation Expert specializing in the **{sector_label}** sector.
        Your goal is to perform a "Relative Valuation Analysis" for the target company: **{target_identifier}** (Ticker: {ticker}).

        **SECTOR-SPECIFIC VALUATION METHODOLOGY:**
        {skill_content}

        **Cleaned Peer Data (Comparative):**
        {peer_markdown}
        {additional_context}

        **CRITICAL INSTRUCTIONS:**
        
        1. **Identify the Target:** Locate the row in the table where 'Company_Name' closely matches or is a substring of **{target_identifier}**. Do NOT demand an exact string match (e.g., "Cello World" matches "Cello World Ltd").
        
        2. **Identify Direct Competitors:** Select 3-5 closest peers from the list.
        
        3. **SECTOR-SPECIFIC METRIC CHECK (MANDATORY):**
           - First, print a header exactly like this: `### {sector_label} Sector Specific Valuation Check`
           - Then, you MUST create a **Markdown Table** evaluating EVERY SINGLE metric requested in the "Core Financials" and "Strategy & Narrative KPIs" sections of the Sector Methodology above.
           - The table MUST have these exact columns: | Metric | Value | Sector Benchmark/Rule | Assessment |
           - **CRITICAL MATH RULE:** When evaluating metrics like CFO/PAT, Growth Rates, or Margins, you MUST extract the exact numbers already calculated for you in the "Target Company Financial Summary" context text. DO NOT perform your own mathematical calculations from raw tables. Look for the summarized ratios already provided.
           - The 'Assessment' column should contain a brief, punchy qualitative takeaway (e.g., "Weak; significant margin erosion" or "Strong; indicates asset efficiency"). Do not write long paragraphs.
           - If a metric is not found in the context after strict searching, you MUST NOT skip it. You MUST list it and state: "**Data Not Available** — verify from company filings."
        
        4. **GOVERNANCE CHECK (Strict):**
           - Look specifically at the column **'Promoter_Pledged_Percent'**.
           - **DO NOT** confuse this with 'Debt_to_Equity_Ratio'.
           - If 'Promoter_Pledged_Percent' is 0 or 0.00, the company has NO pledging issues.
           - Only flag a "RED FLAG" if 'Promoter_Pledged_Percent' is > 0.

        5. **VALUATION METRICS TABLE:**
           - Create a comparison table including **{target_identifier} AND Selected Peers**. 
           - Use the sector-specific metrics from the methodology above as your primary columns.
           - Also include: Name, Current_Price, Promoter_Pledged_Percent.
           
           Apply the sector-specific analysis rules from the methodology above.

        6. **Valuation Verdict:**
           - Compare **{target_identifier}** metrics against the average of its Peers.
           - Apply the sector-specific rules to arrive at a final classification.
           - Final Classification: "Undervalued", "Fairly Valued", or "Overvalued".
        
        **⚠️ GROUNDING CONSTRAINT:**
        - You MUST ONLY cite values and metrics that are explicitly present in the data provided above (Peer Table, Financial Summary, or Strategy/PPT data).
        - **Synonym Mapping Allowed:** If a metric is requested (e.g., 'EBITDA Margin', 'Revenue Growth') but the provided data uses a synonymous term (e.g., 'OPM', 'Sales Growth'), you MUST use that data. Do not say it's unavailable if the concept exists.
        - If a metric mentioned in the Sector Methodology is genuinely NOT present in any of the provided data, explicitly state: "**[Metric Name]: Data Not Available** — verify from company filings."
        - Do NOT infer, estimate, or recall metric values from your training knowledge. Only use what is given.
        
        Format your response in clean Markdown.
        """

        logger.info(f"Calling Gemini ({model_name}) for valuation...")
        response = generate_with_retry(model, prompt)
        logger.info("Valuation Analysis complete.")
        
        return {
            "content": response.text,
            "peer_comparison_table": peer_df, # Return raw DF for UI rendering
            "sector": sector or "Unknown",
            "skill_file_used": skill_file
        }

    except Exception as e:
        logger.error(f"Valuation agent failed: {e}", exc_info=True)
        return {"content": f"Valuation analysis failed due to error: {e}"}