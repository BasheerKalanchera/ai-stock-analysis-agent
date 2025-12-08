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

# CHANGED: Icon to 🟠 (Orange) to distinguish from Synthesis (Blue/Purple)
formatter = logging.Formatter('%(asctime)s - 🟠 VALUATION - %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False
# ---------------------------

def generate_with_retry(model, prompt, max_retries=3, base_delay=30):
    """
    Helper to retry Gemini generation on rate limit errors.
    Defaults to a 30s wait which is safer for the Free Tier.
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

            # CLEAN ONE-LINE LOG
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
        
        peer_markdown = peer_df.head(15).to_markdown(index=False)
        target_identifier = company_name if company_name else ticker

        prompt = f"""
        You are a Valuation Expert. Your goal is to perform a "Relative Valuation Analysis" for the target company: **{target_identifier}** (Ticker: {ticker}).

        **Raw Peer Data (from Screener.in):**
        {peer_markdown}

        **CRITICAL INSTRUCTIONS:**
        
        1. **Identify the Target:** Locate the row in the data that corresponds to **{target_identifier}**. 
           *Important:* The 'Name' column in the table uses the company name (e.g., "{target_identifier}"), NOT the ticker. Match the name accurately.
        
        2. **Identify Direct Competitors:** Select 3-5 peers from the list that are the *closest* business match to {target_identifier}.
        
        3. **Discard Irrelevant Peers:** Explicitly discard companies that are in the same sector but have different business models or are significantly smaller/larger (outliers).
        
        4. **GOVERNANCE CHECK (Promoter Pledging):**
           - Check "Pledged percentage" for **{target_identifier}** and its Peers.
           - **RED FLAG:** > 0% is a governance risk.
           - **POSITIVE:** 0% is a clean balance sheet sign.

        5. **VALUATION METRICS TABLE:**
           - Create a comparison table including **{target_identifier} AND Selected Peers**. 
           - **Required Columns:** Name, CMP, P/E, PEG Ratio, ROCE %, FCF (Last Yr), FCF (Prec Yr).
           
           **Analysis Rules:**
           - **PEG Ratio:** < 2.0 is "Undervalued". > 2.0 is likely "Overvalued".
           - **Free Cash Flow (FCF):** Look for consistency. Positive FCF is preferred.

        6. **Valuation Verdict:** - Compare **{target_identifier}** metrics against the average of its Peers.
           - Final Classification: "Undervalued", "Fairly Valued", or "Overvalued".
        
        Format your response in clean Markdown.
        """

        logger.info(f"Calling Gemini ({model_name}) for valuation...")
        response = generate_with_retry(model, prompt)
        logger.info("Valuation Analysis complete.")
        
        return {
            "content": response.text,
            "raw_peer_data": peer_df.to_dict() 
        }

    except Exception as e:
        logger.error(f"Valuation agent failed: {e}", exc_info=True)
        return {"content": f"Valuation analysis failed due to error: {e}"}