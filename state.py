"""
state.py
========
Defines the main TypedDict state representation used throughout LangGraph workflows.

CHANGE LOG
----------
[2026-03-09] Dynamic Sector-Specific Valuation
  - Added `sector: str | None` property to `StockAnalysisState` to route scraped sector values.
"""

import io
from typing import TypedDict, Dict, Any, List, Annotated
import pandas as pd

# Define the shared state structure
class StockAnalysisState(TypedDict):
    ticker: str
    company_name: str | None
    sector: str | None
    file_data: Dict[str, io.BytesIO]
    peer_data: pd.DataFrame | None
    quant_results_structured: List[Dict[str, Any]] | None
    quant_text_for_synthesis: str | None
    strategy_results: str | None
    risk_results: str | None
    qualitative_results: Dict[str, Any] | None
    valuation_results: Dict[str, Any] | None
    final_report: str | None
    log_file_content: Annotated[str, lambda x, y: x + y]  # Reducer for appending logs
    pdf_report_bytes: bytes | None
    is_consolidated: bool | None
    agent_config: Dict[str, Any]
    workflow_mode: str | None  # Track which mode was run