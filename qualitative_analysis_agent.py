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
    if not pdf_buffer: return ""
    try:
        logger.info("Extracting text from PDF...")
        with fitz.open(stream=pdf_buffer.getvalue(), filetype="pdf") as doc:
            full_text = "".join(page.get_text() for page in doc)
        logger.info(f"PDF Extraction Complete. Length: {len(full_text)} chars")
        return full_text
    except Exception as e:
        logger.error(f"Error reading PDF from buffer: {e}")
        return ""

# --- TOOL COMPONENTS ---

def _search_tool(query: str, api_key: str = None, required_keywords: List[str] = None) -> str:
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
    if not api_key:
        return "Warning: TAVILY_API_KEY not found. Search skipped."

    try:
        tavily = TavilyClient(api_key=api_key)
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
            time.sleep(1.5) 
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
    """
    Hybrid Tool Executor:
    - Uses Manual ReAct Loop for 'gemma' models (more reliable for lightweight models)
    - Uses Native Tool Calling for 'gemini' models (better integration)
    """
    api_key = agent_config.get("GOOGLE_API_KEY")
    tavily_key = agent_config.get("TAVILY_API_KEY") 
    if not api_key: return "Missing Google API Key."
    genai.configure(api_key=api_key)
    
    is_gemma = "gemma" in model_name.lower()
    
    if is_gemma:
        return _manual_react_loop(prompt, analysis_type, model_name, tavily_key=tavily_key, filter_keywords=filter_keywords)
    else:
        # NATIVE TOOL USE RESTORED
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

# --- ANALYSIS SUB-AGENTS ---

def _sebi_sync(company_name: str, agent_config: dict) -> str:
    logger.info("Starting SEBI/Regulatory analysis...")
    clean_name = company_name.replace("Limited", "").replace("Ltd", "").replace("India", "").strip()
    filter_keywords = [clean_name]

    prompt = f"""
    You are a **STRICT Regulatory Compliance Auditor**. Check for violations for **{company_name}**.
    
    **Action:**
    Perform ONE comprehensive search: "{company_name} India regulatory violations SEBI RBI tax penalty lawsuit litigation fraud verdict"
    
    **AUDIT RULES:**
    1. **EXACT MATCH ONLY:** Ignore vendors, partners, or general industry news.
    2. **IGNORE BOILERPLATE:** "Nothing has come to our attention" is CLEAN.
    3. **OUTPUT:**
       **Status:** [CLEAN / WARNING / CRITICAL]
       **Executive Summary:** (1-2 sentences)
       **Key Findings:** (Bullet points with YYYY-MM-DD dates, Newest First)
       
       If no violations: "Status: CLEAN. No significant regulatory violations found."
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
    Use bullet points and quote relevant phrases.
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
    
    # 3. Fallback: Map-Reduce (Restored)
    logger.warning("Direct Analysis failed or hit limits. Switching to Map-Reduce Fallback Strategy...")
    chunks = _chunk_text(transcript_text, chunk_size=24000)
    chunk_summaries = []
    
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing Fallback Map Chunk {i+1}/{len(chunks)}...")
        chunk_prompt = f"""
        Analyze this PARTIAL SECTION of an earnings call transcript.
        Extract any key "Positives" and "Areas of Concern".
        Be concise.
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
    Consolidate these partial points into one final report.
    1. Remove duplicates.
    2. Structure: "Positives" and "Areas of Concern".
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
    prompt = f"""
    Compare the company's performance based on these two summaries.
    **CRITICAL:** Output a SINGLE valid JSON array. No markdown.
    Keys: "Metric", "Latest Quarter Analysis", "Previous Quarter Analysis".
    Escape newlines as \\n.
    
    **Latest:** {latest_analysis[:10000]}
    **Previous:** {previous_analysis[:10000]}
    """
    return _analyze_with_gemini(prompt, "QoQ Comparison", agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash"), agent_config.get("GOOGLE_API_KEY"))

def _scuttlebutt_sync(company_name: str, context_text: str, agent_config: dict) -> str:
    logger.info("Starting Scuttlebutt analysis...")
    
    tavily_key = agent_config.get("TAVILY_API_KEY")
    search_context = ""
    if tavily_key:
        search_context = _perform_scuttlebutt_search(company_name, tavily_key)
    else:
        search_context = "No live search results available."

    combined_context = f"{search_context}\n\n### INTERNAL NOTES:\n{context_text}"
    
    prompt = f"""
    You are a forensic financial investigator (Philip Fisher style) for: **{company_name}**.
    Use the provided search results and internal notes.
    
    **GOALS:**
    1. Channel Checks (Dealers, distributors, margin pressure?)
    2. Management Integrity (Raids, SEBI orders?)
    3. Brand Perception (Glassdoor, Consumer forums?)
    4. Strategic Reality Check (Promises vs Delivery?)
    
    **FORMAT:** Markdown report. Cite sources like [Mint], [Glassdoor].
    
    **CONTEXT:**
    {combined_context[:50000]}
    """
    return _analyze_with_gemini(prompt, "Scuttlebutt Analysis", agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-pro"), agent_config.get("GOOGLE_API_KEY"))

# --- MAIN ORCHESTRATOR (SEQUENTIAL) ---

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