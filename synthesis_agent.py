import google.generativeai as genai
import logging
import time
import random
import re
from google.api_core import exceptions as google_exceptions

# --- CUSTOM LOGGER SETUP ---
logger = logging.getLogger('synthesis_agent')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - 🔵 SYNTH - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.propagate = False
# --- END CUSTOM LOGGER SETUP ---

def generate_with_retry(model, prompt, max_retries=3, base_delay=30):
    """
    Helper to retry Gemini generation on rate limit errors.
    Defaults to a 30s wait, but prioritizes the actual wait time requested by the API.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt)
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
            retry_seconds = base_delay 
            # Try to extract specific wait time from the error message
            try:
                match = re.search(r'retry_delay.*seconds:\s*(\d+)', str(e), re.DOTALL | re.IGNORECASE)
                if match:
                    retry_seconds = int(match.group(1)) + 5 # Add a small buffer
            except:
                pass

            # If no specific time found, add jitter to base delay
            if retry_seconds == base_delay:
                retry_seconds = base_delay + random.uniform(1, 5)

            logger.warning(f"Generation (Attempt {attempt + 1}/{max_retries}) encountered rate limit - retry after {retry_seconds:.1f} seconds.")
            time.sleep(retry_seconds)
            
        except Exception as e:
            # Handle generic 429s that might not match the specific Google exception types
            if "429" in str(e):
                retry_seconds = base_delay + random.uniform(1, 5)
                logger.warning(f"Generation (Attempt {attempt + 1}/{max_retries}) encountered generic 429 - retry after {retry_seconds:.1f} seconds.")
                time.sleep(retry_seconds)
            else:
                raise e
                
    raise Exception(f"Max retries ({max_retries}) exceeded. The API is too busy.")

def generate_investment_summary(
    ticker: str, 
    quantitative_analysis: str, 
    qualitative_analysis: dict, 
    valuation_analysis: dict,
    risk_analysis: str,      
    strategy_analysis: str,  
    agent_config: dict
) -> str:
    """
    Generates a final, comprehensive investment summary using the Gemini model.
    Now includes Risk and Strategy agent outputs and smart retry logic.
    """
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-flash") 

    if not api_key:
        msg = "Synthesis Agent Error: Google API Key is not configured."
        logger.error(msg)
        return msg

    # --- 1. Prepare Qualitative Summary ---
    if qualitative_analysis:
        qualitative_summary = f"""
        - Positives & Concerns (Latest Quarter): {qualitative_analysis.get('positives_and_concerns', 'N/A')}
        - Quarter-over-Quarter Comparison: {qualitative_analysis.get('qoq_comparison', 'N/A')}
        - Scuttlebutt Analysis (Management, Competition, Culture): {qualitative_analysis.get('scuttlebutt', 'N/A')}
        - SEBI Compliance Check: {qualitative_analysis.get('sebi_check', 'N/A')}
        """
    else:
        qualitative_summary = "Qualitative analysis was not performed or failed."
    
    # --- 2. Prepare Quantitative Summary ---
    if not quantitative_analysis:
        quantitative_analysis = "Quantitative analysis was not performed or failed."

    # --- 3. Prepare Valuation Summary ---
    if valuation_analysis:
        val_content = valuation_analysis.get('content', 'Valuation analysis content missing.')
    else:
        val_content = "Valuation analysis was not performed."

    # --- 4. Prepare Risk & Strategy Summaries ---
    risk_text = risk_analysis if risk_analysis else "Risk analysis not performed."
    strategy_text = strategy_analysis if strategy_analysis else "Strategy analysis not performed."

    # --- 5. Construct Prompt ---
    prompt = f"""
    You are a senior investment analyst at a top-tier hedge fund. Your task is to synthesize the provided multi-agent analysis for **{ticker}** into a single, comprehensive, and actionable investment summary.

    The final report must be structured exactly as follows, using Markdown:

    ### Investment Thesis
    **Critical Conclusion:** Buy, Sell, or Hold.
    * Synthesize the *Strategy* (The Dream), *Reality* (The Numbers), and *Risk* (The Downside).
    * Does the strategic pivot justify the valuation? Are the credit risks too high?

    ## 1. Executive Summary
    A brief, high-level overview (3-4 sentences) summarizing key findings across Strategy, Financials, and Risk.

    ## 2. Strategic Outlook (The "Alpha")
    * Summarize the Company's Investment Category (Compounder, Aggressor, Turnaround, etc.).
    * Highlight the management's "Sales Pitch" vs. the "Reality Check".
    * What is the major strategic roadmap for the next 3 years?

    ## 3. Quantitative Analysis
    * Key trends in revenue, profitability, debt, and cash flow.

    ## 4. Qualitative & Management Analysis
    * Insights on management tone, competitive advantages (moat), and industry trends.
    * Any red flags from scuttlebutt?

    ## 5. Credit & Risk Profile
    * **Credit Rating:** Mention the rating and outlook.
    * **Structural Risks:** Highlight promoter pledges, working capital traps, or cyclicality.
    * **Liquidity:** Is the balance sheet safe?

    ## 6. Valuation & Governance
    * Is the stock cheap, fair, or expensive?
    * **Verdict on PEG Ratio and Promoter Pledges.**

    ## 7. SWOT Analysis
    * **Strengths:** (e.g., Moat, Strong Margins)
    * **Weaknesses:** (e.g., High Debt, Poor Governance)
    * **Opportunities:** (e.g., Strategic Pivot, Market Expansion)
    * **Threats:** (e.g., Credit Downgrades, Competition)

    ## 8. Key Monitorables 
    * 3-4 specific metrics to watch in the next 2 quarters.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the data to synthesize:

    ### Strategy & Universal Alpha Report:
    ```
    {strategy_text}
    ```

    ### Quantitative Analysis Report:
    ```
    {quantitative_analysis}
    ```

    ### Qualitative Analysis Report:
    ```
    {qualitative_summary}
    ```

    ### Risk & Credit Profile:
    ```
    {risk_text}
    ```

    ### Valuation Analysis Report:
    ```
    {val_content}
    ```
    """

    logger.info(f"Generating final investment summary for {ticker}...")
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # Use the smart retry helper
        response = generate_with_retry(model, prompt)
        
        logger.info(f"Finished final analysis for {ticker}.")
        return response.text

    except Exception as e:
        error_msg = f"Synthesis failed for {ticker}: {str(e)}"
        logger.error(error_msg)
        return error_msg