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

    # 2. Define Regex Patterns for the columns we need
    # Key = Target standardized name, Value = Regex pattern to find it
    column_patterns = {
        'Company_Name': r'(?i)(name|company)',
        'Current_Price': r'(?i)(cmp|current\s*price|price)',
        'PE_Ratio': r'(?i)(p/e|pe\s*ratio)',
        'PEG_Ratio': r'(?i)(peg)',
        'ROCE_Percent': r'(?i)(roce)',
        'Debt_to_Equity_Ratio': r'(?i)(debt\s*/\s*eq|debt\s*to\s*equity)',
        'Promoter_Pledged_Percent': r'(?i)(pledge)',  # Matches "Pledged %", "Promoter Pledged", etc.
        'Free_Cash_Flow': r'(?i)(free\s*cash\s*flow|fcf)'
    }

    selected_cols = []
    rename_dict = {}

    # 3. Scan columns using Regex
    for col in df.columns:
        for target_name, pattern in column_patterns.items():
            if re.search(pattern, col):
                # Only add if we haven't found this target yet (prioritizing first match)
                if target_name not in rename_dict.values():
                    selected_cols.append(col)
                    rename_dict[col] = target_name
    
    # 4. Filter and Rename
    try:
        # Create a copy with only the found columns
        clean_df = df[selected_cols].copy()
        clean_df.rename(columns=rename_dict, inplace=True)
        
        # 5. Fill NaNs to avoid markdown errors
        clean_df.fillna(0, inplace=True)
        
        # DEBUG: Log what we found so we know if "Pledge" was detected
        found_cols = clean_df.columns.tolist()
        logger.info(f"Columns extracted for LLM: {found_cols}")
        
        return clean_df.head(15).to_markdown(index=False)
        
    except Exception as e:
        logger.warning(f"Column cleaning failed: {e}. Falling back to raw data.")
        return df.head(15).to_markdown(index=False)

def run_valuation_analysis(ticker: str, company_name: str, peer_df: pd.DataFrame, agent_config: dict) -> Dict[str, Any]:
    """
    Analyzes the company valuation relative to peers using Gemini.
    """
    logger.info(f"--- Starting Valuation Analysis for {ticker} ({company_name}) ---")

    if peer_df is None or peer_df.empty:
        logger.warning("No peer data provided. Skipping analysis.")
        return {"content": "Valuation analysis skipped: No peer data available."}

    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-2.0-flash") 
    
    if not api_key:
        return {"content": "ERROR: Google API Key missing for Valuation Agent."}

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # --- CLEANING STEP ---
        peer_markdown = clean_and_format_peer_data(peer_df)
        # ---------------------
        
        target_identifier = company_name if company_name else ticker

        prompt = f"""
        You are a Valuation Expert. Your goal is to perform a "Relative Valuation Analysis" for the target company: **{target_identifier}** (Ticker: {ticker}).

        **Cleaned Peer Data:**
        {peer_markdown}

        **CRITICAL INSTRUCTIONS:**
        
        1. **Identify the Target:** Locate the row in the table where 'Company_Name' matches **{target_identifier}**.
        
        2. **Identify Direct Competitors:** Select 3-5 closest peers from the list.
        
        3. **GOVERNANCE CHECK (Strict):**
           - Look specifically at the column **'Promoter_Pledged_Percent'**.
           - **DO NOT** confuse this with 'Debt_to_Equity_Ratio'.
           - If 'Promoter_Pledged_Percent' is 0 or 0.00, the company has NO pledging issues.
           - Only flag a "RED FLAG" if 'Promoter_Pledged_Percent' is > 0.

        4. **VALUATION METRICS TABLE:**
           - Create a comparison table including **{target_identifier} AND Selected Peers**. 
           - Columns: Name, Current_Price, PE_Ratio, PEG_Ratio, ROCE_Percent, Debt_to_Equity_Ratio, Promoter_Pledged_Percent.
           
           **Analysis Rules:**
           - **PEG Ratio:** < 2.0 is "Undervalued".
           - **Debt/Eq:** > 1.0 indicates high leverage.
           - **Pledged %:** High pledging is a severe governance risk.

        5. **Valuation Verdict:**
           - Compare **{target_identifier}** metrics against the average of its Peers.
           - Final Classification: "Undervalued", "Fairly Valued", or "Overvalued".
        
        Format your response in clean Markdown.
        """

        logger.info(f"Calling Gemini ({model_name}) for valuation...")
        response = generate_with_retry(model, prompt)
        logger.info("Valuation Analysis complete.")
        
        return {
            "content": response.text,
            "peer_comparison_table": peer_df # Return raw DF for UI rendering
        }

    except Exception as e:
        logger.error(f"Valuation agent failed: {e}", exc_info=True)
        return {"content": f"Valuation analysis failed due to error: {e}"}