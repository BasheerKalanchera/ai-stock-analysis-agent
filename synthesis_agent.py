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
    agent_config: dict,
    workflow_mode: str = None
) -> str:
    """
    Generates a final, comprehensive investment summary using the Gemini model.
    Supports full multi-agent synthesis as well as specialized, mode-specific
    synthesis for individual agent loops (e.g., QoQ Concall Analysis, Risk, Quant, etc.).
    """
    api_key = agent_config.get("GOOGLE_API_KEY")
    model_name = agent_config.get("HEAVY_MODEL_NAME", "gemini-1.5-flash") 

    if not api_key:
        msg = "Synthesis Agent Error: Google API Key is not configured."
        logger.error(msg)
        return msg

    qualitative_analysis = qualitative_analysis or {}
    valuation_analysis = valuation_analysis or {}

    # --- Mode-Specific Synthesis Prompts for Individual Agent Loops ---

    if workflow_mode == "QoQ Concall Analysis":
        qoq_comp = qualitative_analysis.get('qoq_comparison', 'N/A')
        latest_txt = qualitative_analysis.get('latest_analysis', 'N/A')
        prev_txt = qualitative_analysis.get('previous_analysis', 'N/A')

        prompt = f"""
    You are a senior equity research analyst specializing in Indian corporate earnings calls.
    Your task is to synthesize the Quarter-over-Quarter (QoQ) earnings call comparison for **{ticker}** into a sharp, actionable executive briefing.

    Structure your markdown report exactly as follows:

    ### Strategic Shift Executive Summary
    **Trajectory Verdict:** [Accelerating / Steady / Pivoting / Deteriorating / Cautious]
    Provide a 2-3 sentence core takeaway comparing the latest quarter with the prior quarter. What is the single biggest strategic message or shift from management?

    ## 1. Key Strategic Pivots & Forward Guidance
    * Major shifts in corporate strategy, capacity expansion (capex), or new market/product entries.
    * Guidance updates: Did management upgrade, maintain, or temper growth expectations?

    ## 2. Demand, Pricing & Operational Realities
    * Demand environment across key segments, domestic vs. export trends.
    * Margin trajectory, raw material/input cost pressures, and pricing power.

    ## 3. Emerging Red Flags & Guidance Discrepancies
    * Any missed commitments, slipped timelines, or changes in tone from the previous quarter.
    * Tough questions from analysts and areas where management was evasive or cautious.

    ## 4. Key Monitorables for Next Quarter
    * 3-4 specific milestones, margin thresholds, or volume targets to watch closely in upcoming earnings.

    ---
    **Disclaimer:** AI-generated analysis based on quarterly conference call transcripts for informational purposes only.
    ---

    Here is the underlying concall comparison data:

    ### QoQ Comparison Matrix:
    ```json
    {qoq_comp}
    ```

    ### Latest Quarter Analysis:
    ```
    {latest_txt}
    ```

    ### Previous Quarter Analysis:
    ```
    {prev_txt}
    ```
    """

    elif workflow_mode == "Latest Concall Analysis":
        latest_txt = qualitative_analysis.get('latest_analysis', 'N/A')

        prompt = f"""
    You are a senior equity research analyst specializing in corporate earnings calls.
    Your task is to synthesize the latest quarterly conference call analysis for **{ticker}** into an executive concall debrief.

    Structure your markdown report exactly as follows:

    ### Earnings Concall Executive Summary
    **Management Sentiment Verdict:** [Bullish / Confident / Neutral / Defensive / Cautious]
    A 2-3 sentence core takeaway on operational performance and management tone.

    ## 1. Core Operational & Financial Highlights
    * Revenue drivers, capacity utilization, order book, and volume growth.
    * Margin trends, cost pressures, and profitability drivers.

    ## 2. Growth Drivers, Capex & Long-Term Pipeline
    * Ongoing and planned capital expenditures, capacity additions, and execution timelines.
    * New market initiatives, product launches, or export diversification.

    ## 3. Analyst Q&A Highlights & Critical Nuances
    * The most telling questions asked by institutional analysts and how management responded.
    * Subtle nuances or unaddressed concerns in the Q&A session.

    ## 4. Key Near-Term Monitorables
    * 3-4 critical metrics or milestones to track over the next 1-2 quarters.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the earnings call analysis data:
    ```
    {latest_txt}
    ```
    """

    elif workflow_mode == "Quantitative Deep-Dive":
        prompt = f"""
    You are a senior financial analyst and forensic accountant.
    Your task is to synthesize the quantitative financial performance and trends for **{ticker}** into a rigorous executive financial review.

    Structure your markdown report exactly as follows:

    ### Financial Health Executive Summary
    **Earnings Quality Verdict:** [High Quality / Moderate / Low Quality / Stressed]
    A 2-3 sentence synthesis of revenue sustainability, margin resilience, and balance sheet leverage.

    ## 1. Revenue Trajectory & Profitability Margins
    * Historical growth consistency, cyclicality, and revenue momentum.
    * Operating (EBITDA) and net profit margin expansion or contraction drivers.

    ## 2. Balance Sheet Strength & Leverage
    * Debt levels, debt-to-equity trajectory, and interest coverage safety buffer.
    * Working capital cycle (debtor days, inventory turnover, payable days) and cash conversion.

    ## 3. Capital Efficiency & Return Ratios
    * Quality of ROCE and ROE trends over the analyzed period.
    * Evidence of reinvestment rate vs. capital return efficiency.

    ## 4. Cash Flow Realities vs Accounting Profits
    * Operating Cash Flow (OCF) vs. Net Profit (PAT) conversion.
    * Free Cash Flow (FCF) generation after accounting for capital expenditure.

    ## 5. Key Financial Monitorables
    * 3-4 specific financial ratios or red-flag areas to monitor.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the quantitative analysis data:
    ```
    {quantitative_analysis}
    ```
    """

    elif workflow_mode == "Risk Analysis Only":
        risk_text = risk_analysis if risk_analysis else "Risk analysis not performed."

        prompt = f"""
    You are a chief risk officer (CRO) and credit analyst.
    Your task is to synthesize the credit rating documentation and structural risk profile for **{ticker}** into a concise executive risk dossier.

    Structure your markdown report exactly as follows:

    ### Downside Risk Executive Summary
    **Overall Risk Rating:** [Low Risk / Moderate Risk / Elevated Risk / High Distress Risk]
    A 2-3 sentence verdict on the company's creditworthiness, structural stability, and margin of safety.

    ## 1. Credit Rating Agency Assessment & Rating Trajectory
    * Agency ratings, rationale, outlook (Positive/Stable/Negative), and recent upgrades/downgrades.
    * Bank facilities, debt covenants, and credit headroom.

    ## 2. Structural & Balance Sheet Vulnerabilities
    * Promoter share pledge levels, debt maturity profile, and refinancing risk.
    * Contingent liabilities, off-balance sheet exposures, and customer/vendor concentration.

    ## 3. Working Capital & Liquidity Buffer
    * Liquidity cushion, cash & liquid investments vs. short-term debt obligations.
    * Sensitivity to industry cyclicality or raw material price volatility.

    ## 4. Key Downside Triggers & Stress Scenarios
    * 3-4 specific warning signs or triggers that would warrant an immediate risk downgrade.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the risk analysis data:
    ```
    {risk_text}
    ```
    """

    elif workflow_mode == "Strategy Deep Dive":
        strategy_text = strategy_analysis if strategy_analysis else "Strategy analysis not performed."

        prompt = f"""
    You are a strategy consultant and corporate development director.
    Your task is to synthesize the strategic vision and growth roadmap for **{ticker}** (extracted from the Investor Presentation) into an executive strategy brief.

    Structure your markdown report exactly as follows:

    ### Strategic Outlook Executive Summary
    **Strategic Execution Verdict:** [Visionary & Achievable / Aggressive / Status Quo / High Execution Risk]
    A 2-3 sentence overview of corporate ambitions and strategic direction.

    ## 1. Long-Term Vision & Growth Pillars
    * Core strategic pillars driving the 3-5 year corporate vision.
    * Market share targets, new customer segments, or geographic expansions.

    ## 2. Strategic Initiatives & Capex Commitments
    * Specific projects, capacity additions, digital/automation transformations, or greenfield/brownfield investments.

    ## 3. Management "Sales Pitch" vs. Reality Check
    * Where does management's narrative sound overly optimistic or promotional?
    * Practical friction points and execution bottlenecks in the stated roadmap.

    ## 4. Strategic Risks & Key Execution Milestones
    * 3-4 specific milestones that will prove whether the strategy is succeeding or stumbling.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the strategy analysis data:
    ```
    {strategy_text}
    ```
    """

    elif workflow_mode == "Valuation & Governance Deep-Dive":
        val_content = valuation_analysis.get('content', 'Valuation analysis content missing.') if isinstance(valuation_analysis, dict) else str(valuation_analysis)

        prompt = f"""
    You are a senior valuation specialist and portfolio manager.
    Your task is to synthesize the valuation metrics and peer group comparison for **{ticker}** into an executive valuation verdict.

    Structure your markdown report exactly as follows:

    ### Valuation & Governance Executive Summary
    **Valuation Verdict:** [Significantly Undervalued / Fairly Valued / Premium/Expensive / Speculative Bubble]
    A 2-3 sentence verdict on price vs. intrinsic value, incorporating governance quality.

    ## 1. Relative Valuation vs. Sector Peers
    * Comparison against industry peers across P/E, EV/EBITDA, P/B, and PEG ratios.
    * Is any premium or discount justified by ROCE, growth, or moat?

    ## 2. Margin of Safety & Historical Range
    * Current valuation multiple relative to the company's 3-year and 5-year historical median.
    * Margin of safety assessment under conservative assumptions.

    ## 3. Corporate Governance & Quality Discount
    * Evaluation of promoter holding, pledges, related-party transactions, and board independence.
    * Necessary governance discount or premium applied to the valuation.

    ## 4. Target Valuation Scenarios & Key Triggers
    * Bull, Base, and Bear case valuation multiples and key catalysts to realize value.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the valuation data:
    ```
    {val_content}
    ```
    """

    elif workflow_mode == "SEBI Violations Check (MVP)":
        sebi_res = qualitative_analysis.get('sebi_check', 'N/A')

        prompt = f"""
    You are a legal and regulatory compliance expert in Indian capital markets.
    Your task is to synthesize the SEBI regulatory verification findings for **{ticker}** into an executive regulatory compliance brief.

    Structure your markdown report exactly as follows:

    ### Regulatory Compliance Executive Summary
    **Compliance Standing:** [Clean Record / Minor Inquiries / Cautionary / Severe Regulatory Action]
    A 2-3 sentence synthesis of regulatory standing and compliance hygiene.

    ## 1. Findings from Regulatory Records & Filings
    * Specific SEBI orders, adjudication proceedings, inquiries, or settlements identified.
    * Scope and timeline of regulatory scrutiny (promoters, key managerial personnel, or entity level).

    ## 2. Governance & Market Impact Assessment
    * Materiality of findings on current day-to-day business operations.
    * Reputational risk, trading restrictions, or penalty exposures.

    ## 3. Recommendations & Compliance Monitorables
    * Specific ongoing legal/regulatory matters to track.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the SEBI check data:
    ```
    {sebi_res}
    ```
    """

    elif workflow_mode == "Scuttlebutt Research":
        scuttle_res = qualitative_analysis.get('scuttlebutt', 'N/A')
        strat_txt = strategy_analysis or 'N/A'
        risk_txt = risk_analysis or 'N/A'

        prompt = f"""
    You are an investigative equity research analyst.
    Your task is to synthesize the Scuttlebutt research (industry forums, employee reviews, news, customer feedback) for **{ticker}** into an executive ground-intelligence dossier.

    Structure your markdown report exactly as follows:

    ### Scuttlebutt Intelligence Executive Summary
    **Ground-Truth Verdict:** [Strong Moat & High Morale / Steady Operations / Mixed Signals / Under-the-Radar Red Flags]
    A 2-3 sentence synthesis of how real-world stakeholder sentiment compares against management's official narrative.

    ## 1. Customer & Channel Partner Sentiment
    * Product quality, customer loyalty, pricing acceptance, and dealer/distributor relationships.

    ## 2. Workplace Culture & Employee Perceptions
    * Glassdoor/AmbitionBox feedback: Leadership perception, work culture, attrition trends, and operational bottlenecks.

    ## 3. Industry & Competitor Dynamics
    * Industry insider perspectives, threat from existing or new competitors, and technological disruption.

    ## 4. Hidden Risks or Emerging Positives
    * 3-4 specific grassroots insights that traditional financial statements fail to capture.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the Scuttlebutt intelligence data:
    ```
    {scuttle_res}
    ```
    Context:
    Strategy: {strat_txt}
    Risk: {risk_txt}
    """

    elif workflow_mode == "Qualitative Deep-Dive":
        qual_summary = f"""
        - Positives & Concerns: {qualitative_analysis.get('positives_and_concerns', 'N/A')}
        - QoQ Comparison: {qualitative_analysis.get('qoq_comparison', 'N/A')}
        - Scuttlebutt: {qualitative_analysis.get('scuttlebutt', 'N/A')}
        - SEBI Check: {qualitative_analysis.get('sebi_check', 'N/A')}
        """
        strat_txt = strategy_analysis or 'N/A'
        risk_txt = risk_analysis or 'N/A'

        prompt = f"""
    You are a senior qualitative equity analyst and competitive strategist.
    Your task is to synthesize the comprehensive qualitative deep-dive for **{ticker}** into an executive moat and management evaluation.

    Structure your markdown report exactly as follows:

    ### Qualitative & Moat Executive Summary
    **Moat Rating:** [Wide Moat / Narrow Moat / None / Declining Moat]
    **Management Rating:** [Exemplary / Capable & Aligned / Questionable / Promotional]
    A 2-3 sentence verdict on the company's sustainable competitive advantage and management execution capability.

    ## 1. Competitive Moat & Industry Structure
    * Barriers to entry, pricing power, brand equity, network effects, or cost advantages.
    * Industry profit pool dynamics and structural tailwinds/headwinds.

    ## 2. Management Execution & Capital Allocation Integrity
    * Alignment with minority shareholders, honesty in earnings calls, and track record of delivering on promises.

    ## 3. Scuttlebutt & Stakeholder Realities
    * Grassroots perceptions from customers, employees, and channel partners vs. corporate claims.

    ## 4. Regulatory, Governance & Compliance Health
    * SEBI standing and corporate governance posture.

    ## 5. Critical Qualitative Monitorables
    * 3-4 qualitative signals to watch over the next 2-4 quarters.

    ---
    **Disclaimer:** AI-generated for informational purposes only.
    ---

    Here is the qualitative data:
    {qual_summary}
    Context Strategy: {strat_txt}
    Context Risk: {risk_txt}
    """

    else:
        # Default: Full Multi-Agent Workflow Synthesis
        qualitative_summary = f"""
        - Positives & Concerns (Latest Quarter): {qualitative_analysis.get('positives_and_concerns', 'N/A')}
        - Quarter-over-Quarter Comparison: {qualitative_analysis.get('qoq_comparison', 'N/A')}
        - Scuttlebutt Analysis (Management, Competition, Culture): {qualitative_analysis.get('scuttlebutt', 'N/A')}
        - SEBI Compliance Check: {qualitative_analysis.get('sebi_check', 'N/A')}
        """ if qualitative_analysis else "Qualitative analysis was not performed or failed."

        quant_summary = quantitative_analysis if quantitative_analysis else "Quantitative analysis was not performed or failed."
        val_content = valuation_analysis.get('content', 'Valuation analysis content missing.') if isinstance(valuation_analysis, dict) else (str(valuation_analysis) if valuation_analysis else "Valuation analysis was not performed.")
        risk_text = risk_analysis if risk_analysis else "Risk analysis not performed."
        strategy_text = strategy_analysis if strategy_analysis else "Strategy analysis not performed."

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
    {quant_summary}
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

    logger.info(f"Generating synthesis summary for {ticker} (Mode: {workflow_mode or 'Full'})...")
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # Use the smart retry helper
        response = generate_with_retry(model, prompt)
        
        logger.info(f"Finished synthesis for {ticker} (Mode: {workflow_mode or 'Full'}).")
        return response.text

    except Exception as e:
        error_msg = f"Synthesis failed for {ticker}: {str(e)}"
        logger.error(error_msg)
        return error_msg