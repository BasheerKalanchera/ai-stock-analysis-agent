import os
import google.generativeai as genai
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()

# --- Google API Configuration ---
API_KEY_CONFIGURED = False
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in .env file.")
    genai.configure(api_key=api_key)
    print("Synthesis Agent: Google API Key configured successfully.")
    API_KEY_CONFIGURED = True
except (ValueError, Exception) as e:
    print(f"Synthesis Agent Error: Could not configure Google API Key. {e}")

def generate_investment_summary(ticker: str, quantitative_analysis: str, qualitative_analysis: dict) -> str:
    """
    Generates a final, comprehensive investment summary using the Gemini model.
    """
    if not API_KEY_CONFIGURED:
        return "Synthesis Agent Error: Google API Key is not configured."

    # --- KEY CHANGE START ---
    # Check if qualitative_analysis is None and provide a default message if it is.
    if qualitative_analysis:
        qualitative_summary = f"""
        - Positives & Concerns (Latest Quarter): {qualitative_analysis.get('positives_and_concerns', 'N/A')}
        - Quarter-over-Quarter Comparison: {qualitative_analysis.get('qoq_comparison', 'N/A')}
        - Scuttlebutt Analysis (Management, Competition, Culture): {qualitative_analysis.get('scuttlebutt', 'N/A')}
        - SEBI Compliance Check: {qualitative_analysis.get('sebi_check', 'N/A')}
        """
    else:
        qualitative_summary = "Qualitative analysis was not performed or failed."
    
    # Also handle the case where quantitative_analysis might be None
    if not quantitative_analysis:
        quantitative_analysis = "Quantitative analysis was not performed or failed."
    # --- KEY CHANGE END ---


    prompt = f"""
    You are a senior investment analyst at a top-tier hedge fund. Your task is to synthesize the provided quantitative and qualitative analyses for the company with ticker **{ticker}** into a single, comprehensive, and actionable investment summary.

    The final report must be structured exactly as follows, using Markdown for formatting:

    ## 1. Executive Summary
    A brief, high-level overview (3-4 sentences) summarizing the key findings. State the overall investment thesis. Is it a buy, hold, or sell, and why?

    ## 2. Financial Performance (Quantitative Analysis)
    Summarize the key takeaways from the quantitative analysis. Do not just repeat the data. Interpret it. Focus on trends in revenue, profitability, debt, and cash flow.

    ## 3. Business & Management Commentary (Qualitative Analysis)
    Summarize the key insights from the qualitative analysis. Focus on management's tone, competitive advantages (moat), industry trends, and any red flags from the scuttlebutt or SEBI check.

    ## 4. SWOT Analysis
    Based on ALL the information provided, generate a SWOT analysis:
    - **Strengths:** Internal factors that give the company an edge (e.g., strong balance sheet, market leadership).
    - **Weaknesses:** Internal factors that are disadvantages (e.g., high debt, declining margins).
    - **Opportunities:** External factors the company can capitalize on (e.g., new markets, favorable regulations).
    - **Threats:** External factors that could harm the company (e.g., new competition, economic downturn).

    ## 5. Key Monitorables & Investment Thesis
    Conclude with a bulleted list of 3-4 key metrics or factors that an investor should monitor in the upcoming quarters. Reiterate the core investment thesis.

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

    print("Synthesis Agent: Generating final investment summary...")
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        print("Synthesis Agent: Finished final analysis.")
        return response.text
    except Exception as e:
        error_msg = f"An error occurred during synthesis analysis: {e}"
        print(error_msg)
        return error_msg