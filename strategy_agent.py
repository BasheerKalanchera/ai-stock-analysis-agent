import logging
import time
import random
import re
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

def _chunk_text(text, chunk_size=20000):
    """Splits text into manageable chunks for the LLM."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

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
                
    raise Exception(f"Max retries ({max_retries}) exceeded.")

def _map_reduce_strategy(model, ppt_text, credit_text):
    """
    Fallback method: Processes PPT in chunks to extract key insights, then synthesizes.
    """
    logger.info("⚠️ ACTIVATING FALLBACK: Map-Reduce Strategy (PPT too large for one-shot).")
    
    chunks = _chunk_text(ppt_text)
    extracted_notes = []

    # --- MAP PHASE: Extract value from chunks ---
    map_prompt_template = """
    You are a Data Miner for a Hedge Fund. 
    Analyze this section of an Investor Presentation. Extract ONLY the following (be concise):
    1. **The "Sales Pitch":** Key marketing slogans, "Optimized Metrics" (Adjusted EBITDA, etc.), and Visual highlights (photos of new plants).
    2. **Strategic Claims:** Future roadmap, capacity expansion plans, and new product launches.
    
    If nothing relevant is found, output "No key data."
    
    **PPT Section:**
    {chunk}
    """

    for i, chunk in enumerate(chunks):
        logger.info(f"   > Processing Map Chunk {i+1}/{len(chunks)}...")
        try:
            # We use a lower retry count for chunks to fail fast if needed
            response = generate_with_retry(model, map_prompt_template.format(chunk=chunk), max_retries=2, base_delay=10)
            extracted_notes.append(response.text)
            
            # [ADDED LOG] Confirm chunk completion
            logger.info(f"   > ✅ Chunk {i+1}/{len(chunks)} extracted successfully.")
            
        except Exception as e:
            logger.warning(f"   > Chunk {i+1} failed: {e}. Skipping.")
            continue
        time.sleep(2) # Cooldown between chunks

    combined_notes = "\n".join(extracted_notes)
    
    # --- REDUCE PHASE: Final Synthesis ---
    logger.info("   > Starting Reduce Phase (Synthesis)...")
    
    reduce_prompt = f"""
    You are a Chief Investment Officer (CIO) at a multi-strategy Hedge Fund.
    Your job is to identify the "Alpha" (Hidden Value) in a company.
    
    We have extracted the key notes from the Investor Presentation (The Pitch) and have the full Credit Report (The Reality).

    **PHASE 1: DIAGNOSIS**
    First, determine the **Investment Category** (Compounder, Aggressor, Turnaround, Special Situation).

    **PHASE 2: SYNTHESIS**
    Write a High-Conviction Investment Memo in strict Markdown based on these inputs.

    **Inputs:**
    **Extracted Strategy Notes (from PPT):** {combined_notes[:50000]} 

    **The Reality (Credit Report):** {credit_text}

    ---

    **OUTPUT FORMAT:**

    ### 1. The Narrative Diagnosis
    **Verdict:** [Category]
    **The "Elevator Pitch":** [1-2 sentences on why it fits.]

    ### 2. The Sales Pitch (The Highlight Reel)
    *[Adopt enthusiastic Growth Investor persona]*
    * **The "Hook":** [Key theme from extracted notes]
    * **The Visual Centerpiece:** [Physical expansions described]
    * **"Optimized" Metrics:** [Non-GAAP numbers highlighted]

    ### 3. The "Alpha" Drivers (The Reality Check)
    *[Adopt skeptical CIO persona. Use the Credit Report to ground the PPT claims]*
    * **Mix Shift:** High-margin vs low-margin growth.
    * **Capex Efficiency:** Is FCF about to explode?
    * **Hidden Assets:** Land/Brands/Patents.

    ### 4. Strategic Pivot & Future Roadmap
    [Single biggest change in next 3 years based on extracted notes.]

    ### 5. Final Investment Verdict
    * **Bull Case:**
    * **Bear Case:**
    """
    
    final_response = generate_with_retry(model, reduce_prompt, max_retries=3, base_delay=30)
    
    # [ADDED LOG] Confirm Reduce completion
    logger.info("   > ✅ Reduce Phase (Synthesis) complete.")
    
    return final_response.text

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

        # --- ATTEMPT 1: ONE-SHOT (Preferred for coherence) ---
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
        **The Reality (Credit Report):** {credit_text}

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
        logger.info("One-Shot Analysis complete.")
        return response.text

    except Exception as e:
        # Check if the error is related to retries/overload
        if "Max retries" in str(e) or "429" in str(e) or "ResourceExhausted" in str(e):
            logger.warning(f"One-Shot failed due to limits. Switching to Map-Reduce strategy... (Error: {str(e)})")
            try:
                # --- ATTEMPT 2: MAP-REDUCE FALLBACK ---
                return _map_reduce_strategy(model, ppt_text, credit_text)
            except Exception as map_e:
                logger.error(f"Map-Reduce Strategy also failed: {map_e}")
                return f"### Error\nFailed to generate strategy profile (both One-Shot and Map-Reduce failed): {str(map_e)}"
        else:
            logger.error(f"LLM Generation failed: {e}")
            return f"### Error\nFailed to generate strategy profile: {str(e)}"