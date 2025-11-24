import logging
import pandas as pd
import google.generativeai as genai
from typing import Dict, Any

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

def run_valuation_analysis(ticker: str, peer_df: pd.DataFrame, agent_config: dict) -> Dict[str, Any]:
    """
    Analyzes the company valuation relative to peers using Gemini.
    Includes 'Smart Filtering', 'Promoter Pledge', 'PEG Ratio', and 'FCF' checks.
    """
    logger.info(f"--- Starting Valuation Analysis for {ticker} ---")

    # 1. Safety Checks
    if peer_df is None or peer_df.empty:
        logger.warning("No peer data provided. Skipping analysis.")
        return {"content": "Valuation analysis skipped: No peer data available."}

    # 2. Setup Gemini
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-2.5-flash") 
    
    if not api_key:
        return {"content": "ERROR: Google API Key missing for Valuation Agent."}

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # 3. Prepare Data for LLM
        # Limit to top 15 rows to ensure context fits
        peer_markdown = peer_df.head(15).to_markdown(index=False)

        prompt = f"""
        You are a Valuation Expert. Your goal is to perform a "Relative Valuation Analysis" for **{ticker}**.

        **Raw Peer Data (from Screener.in):**
        {peer_markdown}

        **CRITICAL INSTRUCTIONS: SMART FILTERING & RISK CHECKS**
        
        1. **Identify Direct Competitors:** Select the 3-5 peers from the list that are the *closest* business match to {ticker}. Briefly explain your selection.
        
        2. **Discard Irrelevant Peers:** Explicitly discard 1-2 companies that are in the same sector but have different business models.
        
        3. **GOVERNANCE CHECK (Promoter Pledging):**
           - Find the column "Pledged percentage" (or similar).
           - **RED FLAG:** If Pledged % > 0%, flag this as a significant governance risk.
           - **POSITIVE:** If 0%, explicitly mention it as a clean balance sheet sign.

        4. **VALUATION METRICS (P/E, PEG, FCF):**
           - Create a comparison table for the *Selected Peers Only*. 
           - **Required Columns:** Name, CMP, P/E, PEG Ratio, ROCE %, FCF (Last Yr), FCF (Prec Yr).
           
           **Analysis Rules:**
           - **PEG Ratio:** < 2.0 is "Undervalued" (Growth at Reasonable Price). > 2.0 is likely "Overvalued".
           - **Free Cash Flow (FCF):** - Look at "Free cash flow last year" AND "Free cash flow preceding year".
             - **Positive (+FCF)** is preferred and warrants a premium.
             - **Negative (-FCF)** is a risk factor.
             - consistency (positive in both years) is the best signal.

        5. **Valuation Verdict:** - Combine P/E, PEG, and FCF data.
           - *Example:* High P/E but Low PEG + Strong FCF = "Fairly Valued" or "Undervalued" (Quality/Growth).
           - *Example:* High P/E + Negative FCF = "Overvalued".
           - Final Classification: "Undervalued", "Fairly Valued", or "Overvalued".
        
        Format your response in clean Markdown.
        """

        # 4. Call LLM
        logger.info(f"Calling Gemini ({model_name}) for valuation...")
        response = model.generate_content(prompt)
        logger.info("Valuation Analysis complete.")
        
        return {
            "content": response.text,
            "raw_peer_data": peer_df.to_dict() 
        }

    except Exception as e:
        logger.error(f"Valuation agent failed: {e}", exc_info=True)
        return {"content": f"Valuation analysis failed due to error: {e}"}