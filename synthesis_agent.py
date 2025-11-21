import google.generativeai as genai
import logging
import time
from google.api_core import exceptions as google_exceptions

# --- CUSTOM LOGGER SETUP ---
# 1. Get a custom logger
logger = logging.getLogger('synthesis_agent')
logger.setLevel(logging.INFO)

# 2. Create a handler
handler = logging.StreamHandler()

# 3. Create a custom formatter and set it for the handler
formatter = logging.Formatter('%(asctime)s - 🔵 SYNTH - %(message)s')
handler.setFormatter(formatter)

# 4. Add the handler to the logger
if not logger.handlers:
    logger.addHandler(handler)

# 5. Stop logger from propagating to the root logger
logger.propagate = False
# --- END CUSTOM LOGGER SETUP ---


def generate_investment_summary(ticker: str, quantitative_analysis: str, qualitative_analysis: dict, agent_config: dict) -> str:
    """
    Generates a final, comprehensive investment summary using the Gemini model.
    Accepts an agent_config dictionary for API key and model names.
    """
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-flash") # Use lite model for summary

    if not api_key:
        msg = "Synthesis Agent Error: Google API Key is not configured."
        logger.error(msg)
        return msg

    # --- Existing logic for handling missing analysis ---
    if qualitative_analysis:
        qualitative_summary = f"""
        - Positives & Concerns (Latest Quarter): {qualitative_analysis.get('positives_and_concerns', 'N/A')}
        - Quarter-over-Quarter Comparison: {qualitative_analysis.get('qoq_comparison', 'N/A')}
        - Scuttlebutt Analysis (Management, Competition, Culture): {qualitative_analysis.get('scuttlebutt', 'N/A')}
        - SEBI Compliance Check: {qualitative_analysis.get('sebi_check', 'N/A')}
        """
    else:
        qualitative_summary = "Qualitative analysis was not performed or failed."
    
    if not quantitative_analysis:
        quantitative_analysis = "Quantitative analysis was not performed or failed."
    # --- End of existing logic ---

    prompt = f"""
    You are a senior investment analyst at a top-tier hedge fund. Your task is to synthesize the provided quantitative and qualitative analyses for the company with ticker **{ticker}** into a single, comprehensive, and actionable investment summary.

    The final report must be structured exactly as follows, using Markdown for formatting:

    ###  Investment Thesis
    Give an overall investment thesis here. Is it a buy, hold, or sell, and why?

    ## 1. Executive Summary
    A brief, high-level overview (3-4 sentences) summarizing the key findings. 

    ## 2. Quantitative Analysis Summary
    Summarize the key takeaways from the quantitative analysis. Do not just repeat the data. Interpret it. Focus on trends in revenue, profitability, debt, and cash flow.

    ## 3. Qualitative Analysis Summary
    Summarize the key insights from the qualitative analysis. Focus on management's tone, competitive advantages (moat), industry trends, and any red flags from the scuttlebutt or SEBI check.

    ## 4. SWOT Analysis
    Based on ALL the information provided, generate a SWOT analysis:
    - **Strengths:** Internal factors that give the company an edge (e.g., strong balance sheet, market leadership).
    - **Weaknesses:** Internal factors that are disadvantages (e.g., high debt, declining margins).
    - **Opportunities:** External factors the company can capitalize on (e.g., new markets, favorable regulations).
    - **Threats:** External factors that could harm the company (e.g., new competition, economic downturn).

    ## 5. Key Monitorables 
    Conclude with a bulleted list of 3-4 key metrics or factors that an investor should monitor in the upcoming quarters. 

    ---
    **Disclaimer:** This report is AI-generated and is for informational purposes only. It does not constitute financial advice. Please conduct your own due diligence before making any investment decisions.
    ---

    Here is the data you need to synthesize:

    ### Quantitative Analysis Report:
    ```
    {quantitative_analysis}
    ```

    ### Qualitative Analysis Report:
    ```
    {qualitative_summary}
    ```
    """

    logger.info(f"Generating final investment summary for {ticker}...")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # --- START NEW RETRY LOGIC ---
        max_retries = 3
        base_delay_seconds = 65 

        for attempt in range(max_retries):
            try:
                logger.info(f"Calling Gemini for synthesis of {ticker} (Attempt {attempt + 1})")
                response = model.generate_content(prompt)
                logger.info(f"Finished final analysis for {ticker}.")
                return response.text
            
            # Specific catch for 429 Resource Exhausted errors
            except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
                logger.warning(f"Rate limit hit for '{ticker}' synthesis: {e}. Waiting {base_delay_seconds}s to retry...")
                if attempt < max_retries - 1:
                    time.sleep(base_delay_seconds)
                else:
                    logger.error(f"Final attempt failed for '{ticker}' synthesis.")
                    return f"An error occurred during synthesis analysis for {ticker} after {max_retries} attempts. Rate limit exceeded. {str(e)}"
            
            # Catch for other errors (wrapped in the same loop)
            except Exception as e:
                # Check if it's a 429 wrapped in a generic exception
                if "429" in str(e):
                     logger.warning(f"Rate limit (429) detected for '{ticker}' synthesis: {e}. Waiting {base_delay_seconds}s to retry...")
                     if attempt < max_retries - 1:
                        time.sleep(base_delay_seconds)
                     else:
                        logger.error(f"Final attempt failed for '{ticker}' synthesis.")
                        return f"An error occurred during synthesis analysis for {ticker} after {max_retries} attempts. Rate limit exceeded. {str(e)}"
                else:
                    # This was a non-retryable error
                    error_msg = f"An error occurred during synthesis analysis for {ticker}: {e}"
                    logger.error(error_msg)
                    return error_msg
        
        # Fallback return (should be unreachable)
        return f"An error occurred during synthesis analysis for {ticker} after {max_retries} attempts."
        # --- END NEW RETRY LOGIC ---

    except Exception as e:
        # This outer try/except catches setup errors (e.g., genai.configure)
        error_msg = f"A setup error occurred during synthesis analysis for {ticker}: {e}"
        logger.error(error_msg)
        return error_msg