import io
import fitz
import asyncio
import google.generativeai as genai
from typing import Optional, Dict, List
from functools import lru_cache
import logging
import time 
import re       
import random   
import json
from google.api_core import exceptions as google_exceptions
import nest_asyncio
nest_asyncio.apply() # <--- CRITICAL FIX: Allows nested event loops

# --- TOOL IMPORTS ---
try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

# --- CUSTOM LOGGER SETUP ---
logger = logging.getLogger('qualitative_agent')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter(f'%(asctime)s - 🟡 QUAL - %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False
# --- END CUSTOM LOGGER SETUP ---

# --- HELPER FUNCTIONS ---

def _parse_retry_delay(error_message: str) -> int:
    try:
        match = re.search(r'retry_delay.*seconds:\s*(\d+)', error_message, re.DOTALL | re.IGNORECASE)
        if match: return int(match.group(1))
    except: pass
    return 0

def _log_rate_limit(analysis_type: str, attempt: int, wait_time: float, is_generic_429: bool = False):
    error_type = "generic 429" if is_generic_429 else "rate limit"
    logger.warning(f"'{analysis_type}' (Attempt {attempt}) encountered {error_type} - retry after {wait_time:.1f} seconds.")

def _chunk_text(text: str, chunk_size: int = 25000) -> list[str]:
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

# --- TOOL COMPONENTS ---

def _search_tool(query: str, api_key: str = None, required_keywords: List[str] = None) -> str:
    """
    Component 1: The Robust Search Tool with PYTHON-LEVEL FILTERING
    """
    raw_results = []
    source_name = "Unknown"

    # 1. Fetch from Tavily or DDG
    if TavilyClient and api_key and api_key.startswith("tvly-"):
        try:
            logger.info(f"🔎 Executing TAVILY Search: {query}")
            client = TavilyClient(api_key=api_key)
            # Fetch MORE results (10) because the filter will delete some
            response = client.search(query, search_depth="advanced", max_results=20)
            raw_results = response.get("results", [])
            source_name = "Tavily"
        except Exception as e:
            logger.error(f"Tavily Search failed: {e}. Falling back to DuckDuckGo...")

    if not raw_results and DDGS:
        try:
            logger.info(f"🔎 Executing DDG Fallback Search: {query}")
            with DDGS() as ddgs:
                # Fetch MORE results (15) for filtering buffer
                raw_results = list(ddgs.text(query, region='in-en', safesearch='off', max_results=15))
            source_name = "DuckDuckGo"
        except Exception as e:
            logger.error(f"DDG Search error: {e}")

    if not raw_results:
        return "No results found."

    # 2. THE FIREWALL: Python-Level Filtering
    filtered_results = []
    
    if required_keywords:
        logger.info(f"   🛡️ Applying Keyword Firewall: {required_keywords}")
        for r in raw_results:
            # Combine all text fields
            # Tavily uses 'content', DDG uses 'body'
            text_blob = (r.get('title', '') + " " + r.get('content', '') + " " + r.get('body', '') + " " + r.get('snippet', '')).lower()
            
            # CHECK: Does the text contain at least one of the required keywords?
            if any(k.lower() in text_blob for k in required_keywords):
                filtered_results.append(r)
            else:
                # Irrelevant result dropped here
                pass
    else:
        filtered_results = raw_results

    # 3. Format Output
    if not filtered_results:
        return f"No results found regarding {required_keywords} specifically."

    output = f"Search Results (Source: {source_name}, Filtered for {required_keywords}):\n"
    # Limit to top 7 AFTER filtering to keep context size manageable
    for i, r in enumerate(filtered_results[:7], 1):
        url = r.get('url') or r.get('href', 'N/A')
        content = r.get('content') or r.get('body') or r.get('snippet', 'N/A')
        output += f"{i}. Title: {r.get('title')}\n   URL: {url}\n   Content: {content}\n\n"
    
    return output

# --- CORE FUNCTIONS ---

def _extract_text_from_pdf_buffer(pdf_buffer: io.BytesIO | None) -> str:
    logger.info("Starting PDF text extraction...")
    if not pdf_buffer: return ""
    try:
        with fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        logger.info("Finished PDF text extraction.")
        return full_text
    except Exception as e:
        logger.error(f"Error reading PDF from buffer: {e}")
        return ""

@lru_cache(maxsize=32)
def _analyze_with_gemini(prompt: str, analysis_type: str, model_name: str, api_key: str, max_retries: int = 6) -> str:
    if not api_key: return f"Analysis skipped for '{analysis_type}': Google API Key is not configured."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    base_delay_seconds = 30 
    for attempt in range(max_retries):
        try:
            logger.info(f"Calling Gemini for '{analysis_type}' analysis... (Attempt {attempt + 1}/{max_retries})")
            response = model.generate_content(prompt)
            logger.info(f"Finished '{analysis_type}' analysis.")
            return response.text
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
            wait = _parse_retry_delay(str(e)) or (base_delay_seconds + random.uniform(0, 2))
            if attempt < max_retries - 1:
                _log_rate_limit(analysis_type, attempt + 1, wait, is_generic_429=False)
                time.sleep(wait)
            else: return f"Rate limit exceeded after retries. {str(e)}"
        except Exception as e:
            if "429" in str(e):
                 wait = base_delay_seconds + random.uniform(0, 2)
                 if attempt < max_retries - 1:
                    _log_rate_limit(analysis_type, attempt + 1, wait, is_generic_429=True)
                    time.sleep(wait)
                 else: return f"Rate limit exceeded. {str(e)}"
            else: return f"Analysis Error: {e}"
    return "Analysis failed."

# --- MANUAL REACT LOOP FOR GEMMA ---
def _manual_react_loop(prompt: str, analysis_type: str, model_name: str, tavily_key: str = None, filter_keywords: List[str] = None) -> str:
    logger.info(f"Initiating Manual ReAct Loop for '{analysis_type}' (Model: {model_name})...")
    model = genai.GenerativeModel(model_name)
    chat = model.start_chat(history=[])
    
    system_instruction = """
    You are a forensic financial investigator. You have access to a Search Tool.
    To use the tool, you MUST output a JSON object in this EXACT format:
    ```json
    {"tool": "search", "query": "your search query here"}
    ```
    After you receive the search results (Observation), you will generate the Final Answer.
    If you have enough information, just provide the Final Answer directly without JSON.
    """
    
    full_prompt = f"{system_instruction}\n\nTask: {prompt}"
    max_turns = 10
    current_input = full_prompt

    for i in range(max_turns):
        retry_count = 0
        while retry_count < 3:
            try:
                response = chat.send_message(current_input)
                break 
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    retry_count += 1
                    wait = _parse_retry_delay(str(e)) or 15
                    logger.warning(f"   [ReAct Turn {i+1}] Rate limit. Retrying in {wait}s...")
                    time.sleep(wait + 5)
                else: return f"Analysis failed: {str(e)}"
        
        if not response: return "Analysis failed due to rate limits."

        try:
            response_text = response.text
            json_match = re.search(r'```json\s*({.*?})\s*```', response_text, re.DOTALL) or \
                         re.search(r'({.*"tool":\s*"search".*})', response_text, re.DOTALL)

            if json_match:
                try:
                    tool_data = json.loads(json_match.group(1))
                    if tool_data.get("tool") == "search":
                        query = tool_data.get("query")
                        logger.info(f"   [ReAct Turn {i+1}] Model requested search: '{query}'")
                        
                        # EXECUTE TOOL WITH FILTERING
                        observation = _search_tool(query, api_key=tavily_key, required_keywords=filter_keywords)
                        
                        current_input = f"Observation: {observation}\n\nBased on this, please provide the Final Answer or another search query."
                        continue 
                except: pass
            
            logger.info(f"   [ReAct Turn {i+1}] Model provided final answer.")
            # FIX: Escape dollar signs to prevent Streamlit/Markdown from treating them as LaTeX
            safe_response_text = response_text.replace("$", "\\$")

            return safe_response_text            
        except Exception as e: return f"Analysis failed: {str(e)}"
            
    return "Analysis timed out."

def _analyze_with_tools(prompt: str, analysis_type: str, model_name: str, agent_config: dict, filter_keywords: List[str] = None) -> str:
    api_key = agent_config.get("GOOGLE_API_KEY")
    tavily_key = agent_config.get("TAVILY_API_KEY") 
    if not api_key: return "Missing Google API Key."
    genai.configure(api_key=api_key)
    is_gemma = "gemma" in model_name.lower()
    
    if is_gemma:
        return _manual_react_loop(prompt, analysis_type, model_name, tavily_key=tavily_key, filter_keywords=filter_keywords)
    else:
        # Native tool wrapper with filtering
        def search_tool_wrapper(query: str): 
            return _search_tool(query, api_key=tavily_key, required_keywords=filter_keywords)
            
        model = genai.GenerativeModel(model_name, tools=[search_tool_wrapper])
        try:
            logger.info(f"Initiating Native Tool-Enabled Chat for '{analysis_type}'...")
            chat = model.start_chat(enable_automatic_function_calling=True)
            response = chat.send_message(prompt)
            logger.info(f"Finished Tool-Enabled '{analysis_type}'.")
            return response.text
        except Exception as e:
            logger.error(f"Tool Analysis Failed: {e}")
            return f"Tool analysis failed: {str(e)}"

# --- ANALYSIS FUNCTIONS ---

def _compare_transcripts(latest_analysis: str, previous_analysis: str, agent_config: dict) -> str:
    prompt = f"""
    You are an expert financial analyst. Your task is to compare the company's performance based on the provided **analysis summaries** of the last two quarters.
    **CRITICAL INSTRUCTION:** You **must** generate your response as a single, valid JSON array of objects. Do not include any text, code blocks, or explanations before or after the JSON.
    The JSON array must contain objects with these exact keys:
    1.  "Metric"
    2.  "Latest Quarter Analysis"
    3.  "Previous Quarter Analysis"
    **FORMATTING:** For the analysis values, use a single string. Inside that string, use Markdown bullets (`* `).
    **IMPORTANT:** All newlines inside the JSON strings **MUST be escaped as `\\n`**. Do not use literal newlines.
    **JSON STRUCTURE EXAMPLE (Note the `\\n`):**
    [
      {{
        "Metric": "Overall Sentiment Shift",
        "Latest Quarter Analysis": "* The tone is cautious.\\n* Focus on cost cutting.",
        "Previous Quarter Analysis": "* The tone was optimistic.\\n* Focus on expansion."
      }}
    ]
    **You must include rows for at least the following metrics:**
    * Overall Sentiment Shift
    * Financial & Operational Highlights
    * Segment Performance
    * Outlook & Guidance
    * Key Concerns / New Issues
    **Latest Quarter Analysis Summary:**
    ---
    {latest_analysis}
    ---
    **Previous Quarter Analysis Summary:**
    ---
    {previous_analysis}
    ---
    **Your Output (VALID JSON array only):**
    """
    return _analyze_with_gemini(prompt, "Quarter-over-Quarter Comparison",
                                agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"),
                                agent_config.get("GOOGLE_API_KEY"))

def _analyze_positives_and_concerns(transcript_text: str, agent_config: dict) -> str:
    logger.info(f"Attempting Direct Analysis of transcript ({len(transcript_text)} chars)...")
    prompt = f"""
    Based ONLY on the provided earnings conference call transcript, identify the key positives and areas of concern.
    Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    Under each heading, use bullet points to list the key takeaways.
    Directly quote relevant phrases or sentences from the transcript to support each point.
    **Transcript:**
    ---
    {transcript_text}
    """
    direct_result = _analyze_with_gemini(prompt, "Positives & Concerns (Direct)", agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), agent_config.get("GOOGLE_API_KEY"), max_retries=2)
    if "Could not generate" not in direct_result and "Rate limit exceeded" not in direct_result: return direct_result
    
    logger.warning("Direct Analysis failed or hit limits. Switching to Map-Reduce Fallback Strategy...")
    chunks = _chunk_text(transcript_text, chunk_size=24000)
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing Fallback Map Chunk {i+1}/{len(chunks)}...")
        chunk_prompt = f"""
        Analyze this PARTIAL SECTION of an earnings call transcript.
        Extract any key "Positives" (Growth, wins, margin expansion) and "Areas of Concern" (Headwinds, cost pressure, delays).
        Be concise. If no significant points are found in this section, reply with "No key points".
        **Transcript Part {i+1}:**
        ---
        {chunk}
        """
        summary = _analyze_with_gemini(chunk_prompt, f"Positives Map Chunk {i+1}", agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), agent_config.get("GOOGLE_API_KEY"), max_retries=6)
        chunk_summaries.append(summary)
        if i < len(chunks) - 1: time.sleep(5) 

    combined_summaries = "\n\n".join(chunk_summaries)
    final_prompt = f"""
    You are an expert financial analyst. Below are summaries extracted from different parts of an earnings call transcript.
    Your task is to consolidate these partial points into one final, coherent report.
    1. Remove duplicates.
    2. Merge related points.
    3. Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    4. Use bullet points.
    **Combined Summaries:**
    ---
    {combined_summaries}
    """
    return _analyze_with_gemini(final_prompt, "Positives & Concerns (Reduce Step)", agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), agent_config.get("GOOGLE_API_KEY"))

def _scuttlebutt_sync(company_name: str, context_text: str, agent_config: dict) -> str:
    logger.info("Starting scuttlebutt analysis...")
    context_instruction = ""
    if context_text and len(context_text) > 10:
        context_instruction = f"**COMPANY BACKGROUND & CONTEXT:**\nUse the following summary to GROUND your research.\n{context_text}"
    prompt = f"""
    As a world-class financial analyst following Philip Fisher's "Scuttlebutt" method, conduct a deep investigation into the company: **{company_name}**.
    {context_instruction}
    Your goal is to gather qualitative insights that are not typically found in financial statements. Search for and synthesize the most up-to-date information available as of **September 2025** from a wide range of sources including:
    - Recent news articles, focusing on the period from **late 2024 to the present day**
    - The latest industry reports and forum discussions
    - Employee reviews (e.g., Glassdoor) posted within the last year
    - Recent customer feedback and reviews
    - Management interviews or public statements from **2025**
    - Any recent supply chain or partner commentary
    **Synthesize your findings into a concise report covering these key areas:**
    1.  **Competitive Landscape:** How is the company positioned against its main competitors? What are its key competitive advantages (moat)?
    2.  **Management Quality & Culture:** What is the reputation of the CEO and the senior management team? What is the overall employee morale and company culture like?
    3.  **Customer & Product Perception:** How do customers perceive the company's products or services? Are they seen as innovative, reliable, or a leader in their category?
    4.  **Industry Trends & Headwinds:** What are the major tailwinds (positive trends) and headwinds (challenges) facing the industry and the company?
    5.  **Red Flags:** Are there any potential issues, controversies, or risks that an investor should be aware of?
    Provide a final summary of your overall impression. Use Markdown for formatting.
    """
    return _analyze_with_gemini(prompt, "Scuttlebutt Analysis", agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro"), agent_config.get("GOOGLE_API_KEY"))

def _sebi_sync(company_name: str, agent_config: dict) -> str:
    """
    Component 3: The Holistic Regulatory Check (STRICT AUDITOR PERSONA + BOILERPLATE CHECK)
    """
    logger.info("Starting holistic regulatory analysis (Live Check)...")
    
    clean_name = company_name.replace("Limited", "").replace("Ltd", "").replace("India", "").strip()
    filter_keywords = [clean_name]
    logger.info(f"   🛡️ Generated Filter Keywords: {filter_keywords}")

    prompt = f"""
    You are a **STRICT Regulatory Compliance Auditor**. Your task is to verify if **{company_name}** (the specific Indian listed entity) has any confirmed regulatory violations.
    
    **Action:**
    Perform ONE comprehensive search using a query like: 
    > "{company_name} India regulatory violations SEBI RBI tax penalty lawsuit litigation fraud verdict"
    
    **AUDIT RULES (ZERO TOLERANCE FOR IRRELEVANCE):**
    1.  **EXACT MATCH ONLY:** You must ONLY report findings where **{company_name}** is explicitly the accused party.
    2.  **IGNORE VENDOR NEWS:** If the company is mentioned as a **service provider, vendor, or technology partner** to a regulator (e.g., "TCS wins SEBI contract", "Infosys builds MCA portal"), **DELETE IT**.
    3.  **REJECT CONTEXT:** If a search result discusses a fraud at a *different* company (e.g., Satyam, Ricoh, Mishtann), **DELETE IT**.
    4.  **REJECT GENERALITIES:** If a result says "SEBI tightened rules for all brokers," **DELETE IT**.
    5.  **IGNORE LEGAL DEFINITIONS:** If terms like "Fraudulent Borrower" or "Wilful Defaulter" appear ONLY in a 'Definitions' or 'Declarations' section of a document (like a DRHP/Prospectus), **DELETE IT**. Only report if the company is affirmatively identified as one.
    6.  **IGNORE AUDITOR BOILERPLATE:** Phrases like "nothing has come to our attention that causes us to believe that the statement contains material misstatement" are standard **CLEAN** reports. Do NOT flag these as violations. Only flag if the auditor explicitly uses terms like **"Qualified Opinion"**, **"Adverse Opinion"**, or **"Basis for Qualified Conclusion"**.
    7.  **INCLUDE TAX/LEGAL:** Report material GST/Customs penalties, Income Tax raids, and major foreign litigation.
    8.  **NO NEUTRAL FILLER (CRITICAL):** Do **NOT** list routine corporate events like "Board Meeting Outcomes", "Annual Reports", "IPO Filings", "Name Changes", or "Award Wins". If a search result is just a neutral document or announcement, **IGNORE IT**.
    9.  **CLEAN VERDICT:** If the search results contain no direct violations for **{company_name}**, your output must be:
        "Status: CLEAN. No significant regulatory violations found in recent public records for {company_name}."
    
    **Output Format:**
    Strictly follow this layout. Ensure there is a blank line between each section.
    
    **Status:** [CLEAN / WARNING / CRITICAL]
    
    **Executive Summary:**
    (1-2 sentences. Direct facts only. No fluff.)
    
    **Key Findings:**
    (Bullet points with Dates and Source Snippets. **Sort by Newest First.**)

    **CRITICAL SORTING & FORMATTING INSTRUCTION:**
    1. **STANDARDIZE DATES:** Start EVERY bullet point with the date in **YYYY-MM-DD** format. If the exact day is unknown, use YYYY-MM-01.
    2. **REVERSE CHRONOLOGICAL:** You **MUST** order the list so the most recent date (e.g., 2025-12-01) is at the TOP, and the oldest date (e.g., 2021-01-01) is at the BOTTOM.
    3. **Example Format:**
       * **2025-08-15:** [Details of violation...] (Source: ...)
       * **2024-11-20:** [Details of violation...] (Source: ...)
    """
    
    return _analyze_with_tools(
        prompt, 
        "Regulatory & Fraud Check (Live)",
        agent_config.get("LITE_MODEL_NAME", "gemma-3-27b-it"), 
        agent_config,
        filter_keywords=filter_keywords 
    )

# --- Async Orchestrator ---
async def run_qualitative_analysis_async(
    company_name: str, latest_transcript_buffer: io.BytesIO | None, previous_transcript_buffer: io.BytesIO | None,
    agent_config: dict, strategy_context: str = "", risk_context: str = ""
) -> Dict[str, Optional[str]]:
    logger.info(f"--- Starting Qualitative Analysis for {company_name} ---")
    results = {"positives_and_concerns": None, "qoq_comparison": None, "scuttlebutt": None, "sebi_check": None}
    combined_context = f"Strategy: {strategy_context}\nRisk: {risk_context}"

    if company_name:
        scuttlebutt_future = asyncio.create_task(asyncio.to_thread(_scuttlebutt_sync, company_name, combined_context, agent_config))
        sebi_future = asyncio.create_task(asyncio.to_thread(_sebi_sync, company_name, agent_config))
    
    latest_text, previous_text = None, None
    if latest_transcript_buffer:
        latest_text = await asyncio.to_thread(_extract_text_from_pdf_buffer, latest_transcript_buffer)
    if previous_transcript_buffer:
        previous_text = await asyncio.to_thread(_extract_text_from_pdf_buffer, previous_transcript_buffer)

    lat_res, prev_res = None, None
    if latest_text:
        time.sleep(15) 
        lat_res = await asyncio.to_thread(_analyze_positives_and_concerns, latest_text, agent_config)
        results["positives_and_concerns"] = lat_res
    if previous_text:
        time.sleep(15)
        prev_res = await asyncio.to_thread(_analyze_positives_and_concerns, previous_text, agent_config)

    if lat_res and prev_res:
        time.sleep(15)
        results["qoq_comparison"] = await asyncio.to_thread(_compare_transcripts, lat_res, prev_res, agent_config)
    
    if company_name:
        results["scuttlebutt"] = await scuttlebutt_future
        results["sebi_check"] = await sebi_future

    logger.info(f"--- Finished Qualitative Analysis for {company_name} ---")
    return results

def run_qualitative_analysis(company_name, latest, previous, config, strat="", risk=""):
    """
    Robust Synchronous Wrapper for Async Agent
    Creates a fresh, isolated event loop for every run to prevent Streamlit deadlocks.
    """
    import asyncio
    
    # 1. Create a completely new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 2. Apply nest_asyncio specifically to this new loop to allow re-entrancy
    import nest_asyncio
    nest_asyncio.apply(loop)
    
    try:
        logger.info(f"🟡 QUAL - Wrapper initialized. Starting async execution for {company_name}...")
        
        # 3. Run the async function until completion
        results = loop.run_until_complete(
            run_qualitative_analysis_async(company_name, latest, previous, config, strat, risk)
        )
        return results
        
    except Exception as e:
        logger.error(f"❌ QUAL - Critical Async Failure: {e}")
        # Return a partial result so the pipeline doesn't crash completely
        return {
            "positives_and_concerns": f"Error: {str(e)}", 
            "qoq_comparison": None, 
            "scuttlebutt": None, 
            "sebi_check": None
        }
        
    finally:
        # 4. Clean up the loop to free resources
        try:
            # Cancel any pending tasks (if it crashed)
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            
            # Close the loop
            loop.close()
            logger.info("🟡 QUAL - Event loop closed.")
        except Exception as cleanup_error:
            logger.warning(f"Loop cleanup warning: {cleanup_error}")

def run_isolated_sebi_check(company_name, agent_config):
    return _sebi_sync(company_name, agent_config)