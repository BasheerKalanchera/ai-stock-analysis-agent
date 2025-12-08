import logging
import time
import random
import re  # Added for parsing error messages
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from pypdf import PdfReader

# Setup Logger
logger = logging.getLogger('strategy_agent')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - 🔵 STRATEGY AGENT - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

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

def strategy_analyst_agent(file_buffers, api_key, model_name):
    """
    Analyzes PPT + Credit Report to produce a 'Universal Alpha' Investment Memo.
    """
    logger.info(f"Strategy Agent (Universal Mode) started using model: {model_name}")
    
    if 'investor_presentation' not in file_buffers:
        return "### Strategic Outlook\n\n*No Investor Presentation found. Cannot generate strategic insights.*"

    ppt_buffer = file_buffers['investor_presentation']
    ppt_text = ""
    try:
        reader = PdfReader(ppt_buffer)
        for i, page in enumerate(reader.pages): 
            text = page.extract_text()
            if text: ppt_text += f"\n[PPT SLIDE {i+1}]\n{text}"
    except Exception as e:
        logger.error(f"PPT Extraction failed: {e}")

    credit_text = ""
    if 'credit_rating_doc' in file_buffers:
        try:
            doc = file_buffers['credit_rating_doc']
            if isinstance(doc, str):
                credit_text = f"\n[CREDIT REPORT]\n{doc}"
            else:
                reader = PdfReader(doc)
                for page in reader.pages:
                    credit_text += f"\n[CREDIT REPORT]\n{page.extract_text()}"
        except Exception as e:
            logger.warning(f"Credit Rating extraction failed: {e}")

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name) 

        prompt = f"""
        You are a Chief Investment Officer (CIO) at a multi-strategy Hedge Fund.
        Your job is to identify the "Alpha" (Hidden Value) in a company by analyzing its Investor Presentation (The Pitch) and Credit Report (The Reality).

        **PHASE 1: DIAGNOSIS**
        First, determine the **Investment Category** of this company based on the documents:
        1. **The Compounder:** Dominant market leader, high ROCE, consistent growth (e.g., Nestle, TCS).
        2. **The Aggressor:** High growth, burning cash, land-grabbing market share (e.g., Zomato, New-age Tech).
        3. **The Turnaround:** Recovering from bad debt/losses, margin expansion story (e.g., Tata Motors 2020).
        4. **The Special Situation:** Demerger, IPO, Restructuring, Regulatory change (e.g., Gabriel India, ITC Hotels).

        **PHASE 2: EXTRACTION (Apply the Lens)**
        Based on the category, extract the specific "Golden Nuggets" of information:
        - If **Compounder**: Look for "Premiumization" (Mix shift), "Pricing Power," and "New Adjacencies."
        - If **Aggressor**: Look for "Unit Economics," "CAC reduction," and "Path to Profitability."
        - If **Turnaround**: Look for "De-leveraging" (Debt reduction), "Cost cutting," and "Asset Monetization."
        - If **Special Situation**: Look for "Value Unlocking," "Swap Ratios," and "Synergies."

        *CRITICAL STEP: EXTRACT THE SALES PITCH*
        Scan the Investor Presentation specifically for the "Dream Scenario." Identify the "Optimized Metrics" (Adjusted EBITDA, Market Share) and the "Visual Centerpieces" (Photos of new plants, maps of expansion) that management uses to sell the growth story.

        **PHASE 3: SYNTHESIS (The Report)**
        Write a High-Conviction Investment Memo in strict Markdown.

        **Inputs:**
        **The Pitch (PPT):** {ppt_text[:60000]} 

        ---

        **OUTPUT FORMAT:**

        ### 1. The Narrative Diagnosis
        **Verdict:** [State the Category: Compounder / Aggressor / Turnaround / Special Situation]
        **The "Elevator Pitch":** [1-2 sentences explaining *why* this company fits that category. E.g., "This is a classic Special Situation driven by a complex three-way demerger..."]

        ### 2. The Sales Pitch (The Highlight Reel)
        *[Adopt the persona of an enthusiastic Growth Investor for this section only. Summarize the story management WANTS us to believe.]*
        * **The "Hook":** [The one big idea or theme they are selling. e.g., "From Regional Player to National Behemoth"]
        * **The Visual Centerpiece:** [Identify the biggest physical changes showcased in the PPT (e.g., New factories, capacity expansion). How is this framed as the engine for future volume?]
        * **"Optimized" Metrics:** [What numbers are they highlighting most aggressively? Are they focusing on "Adjusted EBITDA," "Market Share," or "Core Revenue"? Ignore statutory accounting here; look for their preferred metrics.]

        ### 3. The "Alpha" Drivers (The Reality Check)
        *[Switch back to skeptical CIO persona. Identify 2-3 specific, non-obvious drivers of future value. Do NOT just list revenue growth. Look for:]*
        * **Mix Shift:** Is high-margin revenue growing faster than low-margin revenue? (e.g., "Sunroofs growing 2x faster than Shocks")
        * **Capex Efficiency:** Is a big capex cycle finishing? (This means Free Cash Flow is about to explode).
        * **Hidden Assets:** Land, brands, or patents that the market ignores.

        ### 4. Strategic Pivot & Future Roadmap
        [What is the *single biggest* change coming in the next 3 years? (e.g., "Entry into EV components" or "Doubling Export capacity"). Use the PPT's "Future Strategy" slides.]

        ### 5. Final Investment Verdict
        * **Bull Case:** [The most optimistic outcome if the strategy works.]
        * **Bear Case:** [The biggest structural risk identified.]
        """

        response = generate_with_retry(model, prompt)
        logger.info("Analysis complete.")
        return response.text

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}")
        return f"### Error\nFailed to generate strategy profile: {str(e)}"