import io
import fitz
import google.generativeai as genai
from typing import Optional, Dict, List
from functools import lru_cache
import logging
import time 
import re       
import random   
import json
from urllib.parse import urlparse
from google.api_core import exceptions as google_exceptions

# --- TOOL IMPORTS ---
try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

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

def _extract_text_from_pdf_buffer(pdf_buffer: io.BytesIO | None) -> str:
    logger.info("Starting PDF text extraction...")
    if not pdf_buffer: return ""
    try:
        with fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        logger.info(f"Finished PDF text extraction. ({len(full_text)} chars)")
        return full_text
    except Exception as e:
        logger.error(f"Error reading PDF from buffer: {e}")
        return ""

# --- TOOL COMPONENTS ---

def _search_tool(query: str, api_key: str = None, required_keywords: List[str] = None) -> str:
    """
    Standard Search Tool (Tavily Only - DDG Removed)
    """
    raw_results = []
    source_name = "Unknown"

    if TavilyClient and api_key and api_key.startswith("tvly-"):
        try:
            logger.info(f"🔎 Executing TAVILY Search: {query}")
            client = TavilyClient(api_key=api_key)
            response = client.search(query, search_depth="advanced", max_results=20)
            raw_results = response.get("results", [])
            source_name = "Tavily"
        except Exception as e:
            logger.error(f"Tavily Search failed: {e}.")
    else:
        if not TavilyClient:
            logger.error("TavilyClient not imported. Install via 'pip install tavily-python'.")

    if not raw_results:
        return "No results found."

    filtered_results = []
    if required_keywords:
        logger.info(f"   🛡️ Applying Keyword Firewall: {required_keywords}")
        for r in raw_results:
            text_blob = (r.get('title', '') + " " + r.get('content', '') + " " + r.get('body', '') + " " + r.get('snippet', '')).lower()
            if any(k.lower() in text_blob for k in required_keywords):
                filtered_results.append(r)
    else:
        filtered_results = raw_results

    if not filtered_results:
        return f"No results found regarding {required_keywords} specifically."

    output = f"Search Results (Source: {source_name}, Filtered for {required_keywords}):\n"
    for i, r in enumerate(filtered_results[:7], 1):
        url = r.get('url') or r.get('href', 'N/A')
        content = r.get('content') or r.get('body') or r.get('snippet', 'N/A')
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except:
            domain = "web"
        output += f"{i}. Source: {r.get('title')} ({domain})\n   URL: {url}\n   Content: {content}\n\n"
    
    return output

def _perform_scuttlebutt_search(company_name: str, api_key: str) -> str:
    """
    Deep Dive Search Helper (Preserved Detailed Queries)
    """
    if not api_key:
        return "Warning: TAVILY_API_KEY not found. Search skipped."

    try:
        tavily = TavilyClient(api_key=api_key)
        # PRESERVED: Specific Investigative Queries
        queries = [
            f"{company_name} management interview transcripts outlook 2025 key takeaways",
            f"{company_name} channel checks dealers distributors complaints margins vs competitors",
            f"{company_name} forensic accounting red flags short seller report fraud allegations",
            f"{company_name} employee culture toxicity attrition Glassdoor reviews 2024 2025",
            f"{company_name} market share loss vs competitors India industry report"
        ]
        
        aggregated_context = "### EXTERNAL LIVE SEARCH RESULTS (GROUNDING DATA):\n"
        
        for q in queries:
            logger.info(f"🔎 Deep-Dive Query: {q}")
            time.sleep(1.0) # Small politeness delay for API
            response = tavily.search(query=q, search_depth="advanced", max_results=5)
            results = response.get('results', [])
            
            for res in results:
                try:
                    domain = urlparse(res['url']).netloc.replace("www.", "")
                    if res['title'].strip().lower() in ["pdf", "document", "untitled"]:
                        clean_title = f"Document/Filing from {domain}"
                    else:
                        clean_title = f"{res['title']} ({domain})"
                except:
                    clean_title = res['title']
                aggregated_context += f"- Source: {clean_title}\n  URL: {res['url']}\n  Content: {res['content']}\n\n"
        
        return aggregated_context

    except Exception as e:
        logger.error(f"Scuttlebutt Search Failed: {e}")
        return f"Search failed due to error: {str(e)}"

# --- GEMINI CORE FUNCTIONS ---

@lru_cache(maxsize=32)
def _analyze_with_gemini(prompt: str, analysis_type: str, model_name: str, api_key: str, max_retries: int = 6) -> str:
    if not api_key: return f"Analysis skipped for '{analysis_type}': Google API Key is not configured."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    base_delay_seconds = 30 
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Calling Gemini for '{analysis_type}'... (Attempt {attempt + 1}/{max_retries})")
            response = model.generate_content(prompt)
            logger.info(f"Finished '{analysis_type}'.")
            return response.text
        except (google_exceptions.ResourceExhausted, google_exceptions.TooManyRequests) as e:
            wait = _parse_retry_delay(str(e)) or (base_delay_seconds + random.uniform(2, 5))
            if attempt < max_retries - 1:
                _log_rate_limit(analysis_type, attempt + 1, wait, is_generic_429=False)
                time.sleep(wait)
            else: return f"Rate limit exceeded after retries. {str(e)}"
        except Exception as e:
            if "429" in str(e):
                 wait = base_delay_seconds + random.uniform(2, 5)
                 if attempt < max_retries - 1:
                    _log_rate_limit(analysis_type, attempt + 1, wait, is_generic_429=True)
                    time.sleep(wait)
                 else: return f"Rate limit exceeded. {str(e)}"
            else: return f"Analysis Error: {e}"
    return "Analysis failed."

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
                    wait = _parse_retry_delay(str(e)) or 20
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
                        observation = _search_tool(query, api_key=tavily_key, required_keywords=filter_keywords)
                        current_input = f"Observation: {observation}\n\nBased on this, please provide the Final Answer or another search query."
                        continue 
                except: pass
            
            logger.info(f"   [ReAct Turn {i+1}] Model provided final answer.")
            return response_text.replace("$", "\\$")            
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
        # Native Tool Use
        def search_tool_wrapper(query: str): 
            return _search_tool(query, api_key=tavily_key, required_keywords=filter_keywords)
            
        model = genai.GenerativeModel(model_name, tools=[search_tool_wrapper])
        try:
            logger.info(f"Initiating Native Tool-Enabled Chat for '{analysis_type}' (Model: {model_name})...")
            chat = model.start_chat(enable_automatic_function_calling=True)
            response = chat.send_message(prompt)
            logger.info(f"Finished Tool-Enabled '{analysis_type}'.")
            return response.text
        except Exception as e:
            logger.error(f"Tool Analysis Failed: {e}")
            return f"Tool analysis failed: {str(e)}"

# --- ANALYSIS SUB-AGENTS (PRESERVED DETAILED PROMPTS) ---

def _sebi_sync(company_name: str, agent_config: dict) -> str:
    logger.info("Starting SEBI/Regulatory analysis (Detailed Check)...")
    clean_name = company_name.replace("Limited", "").replace("Ltd", "").replace("India", "").strip()
    filter_keywords = [clean_name]

    # PRESERVED: The Detailed 9-Rule Prompt
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

def _analyze_positives_and_concerns(transcript_text: str, agent_config: dict) -> str:
    """
    Analyzes earnings transcript.
    Includes MAP-REDUCE FALLBACK for large files.
    """
    logger.info(f"Analyzing transcript ({len(transcript_text)} chars)...")
    prompt = f"""
    Based ONLY on the provided earnings conference call transcript, identify the key positives and areas of concern.
    Structure your answer with two clear headings: "Positives" and "Areas of Concern".
    Under each heading, use bullet points to list the key takeaways.
    Directly quote relevant phrases or sentences from the transcript to support each point.
    **Transcript:**
    ---
    {transcript_text}
    """
    
    # 1. Try Direct Analysis
    direct_result = _analyze_with_gemini(
        prompt, "Positives & Concerns (Direct)", 
        agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), 
        agent_config.get("GOOGLE_API_KEY"), 
        max_retries=2
    )

    # 2. Check for Failures/Limits
    if "Could not generate" not in direct_result and "Rate limit exceeded" not in direct_result: 
        return direct_result
    
    # 3. Fallback: Map-Reduce
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
        summary = _analyze_with_gemini(
            chunk_prompt, f"Positives Map Chunk {i+1}", 
            agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), 
            agent_config.get("GOOGLE_API_KEY"), 
            max_retries=6
        )
        chunk_summaries.append(summary)
        # Internal delay for map-reduce
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
    return _analyze_with_gemini(
        final_prompt, "Positives & Concerns (Reduce Step)", 
        agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), 
        agent_config.get("GOOGLE_API_KEY")
    )

def _compare_transcripts(latest_analysis: str, previous_analysis: str, agent_config: dict) -> str:
    # PRESERVED: Detailed JSON Comparison Prompt
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
    return _analyze_with_gemini(prompt, "Quarter-over-Quarter Comparison", agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), agent_config.get("GOOGLE_API_KEY"))

def _scuttlebutt_sync(company_name: str, context_text: str, agent_config: dict) -> str:
    logger.info("Starting Scuttlebutt analysis...")
    
    tavily_key = agent_config.get("TAVILY_API_KEY")
    search_context = ""
    if tavily_key:
        search_context = _perform_scuttlebutt_search(company_name, tavily_key)
    else:
        search_context = "No live search results available."

    combined_context = f"{search_context}\n\n### INTERNAL NOTES:\n{context_text}"
    
    # PRESERVED: Detailed Scuttlebutt Prompt
    prompt = f"""
    You are a forensic financial investigator executing Philip Fisher's "Scuttlebutt" methodology for: **{company_name}**.

    ### INPUT CONTEXT (GROUND TRUTH)
    The following are **real-time search results** and analysis notes. 
    **CRITICAL INSTRUCTION:** You must answer the questions using **ONLY** this information. 
    Do NOT invent names, dates, or figures.
    If the search results say the CEO is "X", do not say it is "Y".
    If a source is labeled "PDF" or "Document", use the domain name provided in the source description for clarity (e.g., "BSE Filing", "Broker Report").

    {combined_context[:50000]}

    ### ANALYSIS GOALS (DEEP DIVE)
    Synthesize the findings into a **Detailed Investigative Report**. Avoid generic statements; look for specific anecdotes, numbers, and dates.
    
    1.  **Channel Checks & Competitive Position:** * Do not just say "competitive market". Identifying specific complaints from dealers or distributors? 
        * Are margins being squeezed? Who is taking market share?
    2.  **Management Integrity & Governance:** * Look for details on recent tax raids, SEBI orders, or whistle-blower complaints. 
        * Verify the names of Key Managerial Personnel against the search text.
    3.  **Real-World Brand Perception:** * Go beyond "good brand". What are the specific recurring complaints on Glassdoor or Consumer Forums?
    4.  **Strategic Shift & Outlook:** * What did management specifically promise in the latest interview vs what are they delivering?
    5.  **Red Flags:** * Highlight any forensic risks, frequent auditor resignations, or related party transactions found in the text.

    ### FORMAT
    Return the response in Markdown. 
    **CITATION RULE:** Cite the specific source (e.g., [Mint Article], [BSE Filing]) for every major claim. Do not just use [PDF].
    """
    return _analyze_with_gemini(prompt, "Scuttlebutt Analysis", agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro"), agent_config.get("GOOGLE_API_KEY"))

# --- MAIN ORCHESTRATOR (SEQUENTIAL RESTORED) ---

def run_qualitative_analysis(
    company_name: str, latest_transcript_buffer: io.BytesIO | None, previous_transcript_buffer: io.BytesIO | None,
    agent_config: dict, strategy_context: str = "", risk_context: str = ""
) -> Dict[str, Optional[str]]:
    """
    STRICTLY SEQUENTIAL ORCHESTRATOR.
    Executes agents one by one with cool-down periods to prevent 'Thundering Herd' rate limits.
    """
    logger.info(f"--- 🟢 Starting Sequential Qualitative Analysis for {company_name} ---")
    
    results = {
        "sebi_check": None,
        "positives_and_concerns": None,
        "qoq_comparison": None,
        "scuttlebutt": None
    }
    
    # Global cooldown setting
    STEP_DELAY = 10 

    # STEP 1: SEBI / REGULATORY CHECK
    try:
        if company_name:
            results["sebi_check"] = _sebi_sync(company_name, agent_config)
            logger.info("✅ Step 1 (SEBI) Complete.")
    except Exception as e:
        logger.error(f"❌ Step 1 (SEBI) Failed: {e}")
        results["sebi_check"] = f"Error: {str(e)}"
    
    time.sleep(STEP_DELAY)

    # STEP 2: LATEST TRANSCRIPT ANALYSIS
    lat_res = None
    try:
        if latest_transcript_buffer:
            text = _extract_text_from_pdf_buffer(latest_transcript_buffer)
            if text:
                lat_res = _analyze_positives_and_concerns(text, agent_config)
                results["positives_and_concerns"] = lat_res
                logger.info("✅ Step 2 (Latest Earnings) Complete.")
            else:
                logger.warning("Step 2 Skipped: Empty text extracted.")
        else:
            logger.info("Step 2 Skipped: No latest transcript.")
    except Exception as e:
        logger.error(f"❌ Step 2 (Latest Earnings) Failed: {e}")

    time.sleep(STEP_DELAY)

    # STEP 3: PREVIOUS TRANSCRIPT ANALYSIS
    prev_res = None
    try:
        if previous_transcript_buffer:
            text = _extract_text_from_pdf_buffer(previous_transcript_buffer)
            if text:
                prev_res = _analyze_positives_and_concerns(text, agent_config)
                logger.info("✅ Step 3 (Previous Earnings) Complete.")
            else:
                logger.warning("Step 3 Skipped: Empty text extracted.")
        else:
            logger.info("Step 3 Skipped: No previous transcript.")
    except Exception as e:
        logger.error(f"❌ Step 3 (Previous Earnings) Failed: {e}")

    time.sleep(STEP_DELAY)

    # STEP 4: QOQ COMPARISON
    try:
        if lat_res and prev_res and "Error" not in lat_res and "Error" not in prev_res:
            results["qoq_comparison"] = _compare_transcripts(lat_res, prev_res, agent_config)
            logger.info("✅ Step 4 (QoQ Comparison) Complete.")
        else:
            logger.info("Step 4 Skipped: Insufficient data for comparison.")
    except Exception as e:
        logger.error(f"❌ Step 4 (Comparison) Failed: {e}")

    time.sleep(STEP_DELAY)

    # STEP 5: SCUTTLEBUTT
    try:
        if company_name:
            combined_context = f"Strategy: {strategy_context}\nRisk: {risk_context}"
            results["scuttlebutt"] = _scuttlebutt_sync(company_name, combined_context, agent_config)
            logger.info("✅ Step 5 (Scuttlebutt) Complete.")
    except Exception as e:
        logger.error(f"❌ Step 5 (Scuttlebutt) Failed: {e}")
        results["scuttlebutt"] = f"Error: {str(e)}"

    logger.info(f"--- 🏁 Finished Sequential Analysis for {company_name} ---")
    return results

# --- WRAPPERS FOR STANDALONE MODES ---

def run_isolated_sebi_check(company_name, agent_config):
    return _sebi_sync(company_name, agent_config)

def run_earnings_analysis_standalone(company_name, transcript_buffer, config, quarter_label="Generic"):
    text = _extract_text_from_pdf_buffer(transcript_buffer)
    if not text: return "Failed to extract text."
    return _analyze_positives_and_concerns(text, config)

def run_comparison_standalone(latest_analysis_text: str, previous_analysis_text: str, config: dict) -> str:
    return _compare_transcripts(latest_analysis_text, previous_analysis_text, config)

def run_scuttlebutt_standalone(company_name: str, config: dict, strat: str = "", risk: str = "") -> str:
    context = f"STRATEGY: {strat}\nRISK: {risk}"
    return _scuttlebutt_sync(company_name, context, config)