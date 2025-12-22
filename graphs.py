from langgraph.graph import StateGraph, END
from state import StockAnalysisState
import nodes

# ==============================================================================
# 1. FULL WORKFLOW GRAPH
# ==============================================================================
full_workflow = StateGraph(StockAnalysisState)
full_workflow.add_node("fetch_data", nodes.fetch_data_node)
full_workflow.add_node("quantitative_analysis", nodes.quantitative_analysis_node)
full_workflow.add_node("delay_before_strategy", nodes.delay_node)
full_workflow.add_node("strategy_analysis", nodes.strategy_analysis_node)
full_workflow.add_node("delay_before_risk", nodes.delay_node)
full_workflow.add_node("risk_analysis", nodes.risk_analysis_node)
full_workflow.add_node("qualitative_analysis", nodes.qualitative_analysis_node)
full_workflow.add_node("valuation_analysis", nodes.valuation_analysis_node)
full_workflow.add_node("synthesis", nodes.synthesis_node)
full_workflow.add_node("generate_report", nodes.generate_report_node)

full_workflow.set_entry_point("fetch_data")
full_workflow.add_edge("fetch_data", "quantitative_analysis")
full_workflow.add_edge("quantitative_analysis", "strategy_analysis")
full_workflow.add_edge("strategy_analysis", "risk_analysis")
full_workflow.add_edge("risk_analysis", "qualitative_analysis")
full_workflow.add_edge("qualitative_analysis", "valuation_analysis")
full_workflow.add_edge("valuation_analysis", "synthesis")
full_workflow.add_edge("synthesis", "generate_report")
full_workflow.add_edge("generate_report", END)
app_graph = full_workflow.compile()

# ==============================================================================
# 2. RISK ONLY GRAPH
# ==============================================================================
risk_workflow = StateGraph(StockAnalysisState)
risk_workflow.add_node("screener_for_risk", nodes.screener_for_risk_node)
risk_workflow.add_node("isolated_risk", nodes.isolated_risk_node)
risk_workflow.set_entry_point("screener_for_risk")
risk_workflow.add_edge("screener_for_risk", "isolated_risk")
risk_workflow.add_edge("isolated_risk", END)
risk_only_graph = risk_workflow.compile()

# ==============================================================================
# 3. SEBI MVP GRAPH
# ==============================================================================
sebi_workflow_def = StateGraph(StockAnalysisState)
sebi_workflow_def.add_node("screener_metadata", nodes.screener_metadata_node)
sebi_workflow_def.add_node("sebi_check", nodes.sebi_check_node)
sebi_workflow_def.set_entry_point("screener_metadata")
sebi_workflow_def.add_edge("screener_metadata", "sebi_check")
sebi_workflow_def.add_edge("sebi_check", END)
sebi_workflow = sebi_workflow_def.compile()

# ==============================================================================
# 4. EARNINGS DECODER GRAPH
# ==============================================================================
earnings_workflow_def = StateGraph(StockAnalysisState)
earnings_workflow_def.add_node("fetch_latest", nodes.screener_latest_transcript_node)
earnings_workflow_def.add_node("analyze_latest", nodes.analyze_latest_transcript_node)
earnings_workflow_def.set_entry_point("fetch_latest")
earnings_workflow_def.add_edge("fetch_latest", "analyze_latest")
earnings_workflow_def.add_edge("analyze_latest", END)
earnings_graph = earnings_workflow_def.compile()

# ==============================================================================
# 5. STRATEGIC SHIFT GRAPH
# ==============================================================================
strategy_shift_workflow_def = StateGraph(StockAnalysisState)
strategy_shift_workflow_def.add_node("fetch_both", nodes.screener_both_transcripts_node)
strategy_shift_workflow_def.add_node("analyze_both", nodes.analyze_both_transcripts_node)
strategy_shift_workflow_def.add_node("compare_quarters", nodes.compare_quarters_node)

strategy_shift_workflow_def.set_entry_point("fetch_both")
strategy_shift_workflow_def.add_edge("fetch_both", "analyze_both")
strategy_shift_workflow_def.add_edge("analyze_both", "compare_quarters")
strategy_shift_workflow_def.add_edge("compare_quarters", END)
strategy_shift_graph = strategy_shift_workflow_def.compile()

# ==============================================================================
# 6. SCUTTLEBUTT GRAPH
# ==============================================================================
# Includes Strategy and Risk nodes as prerequisites for inputs
scuttlebutt_workflow_def = StateGraph(StockAnalysisState)
scuttlebutt_workflow_def.add_node("fetch_data", nodes.fetch_data_node) 
scuttlebutt_workflow_def.add_node("strategy_analysis", nodes.strategy_analysis_node)
scuttlebutt_workflow_def.add_node("risk_analysis", nodes.risk_analysis_node)
scuttlebutt_workflow_def.add_node("scuttlebutt_analysis", nodes.scuttlebutt_analysis_node)

scuttlebutt_workflow_def.set_entry_point("fetch_data")
scuttlebutt_workflow_def.add_edge("fetch_data", "strategy_analysis")
scuttlebutt_workflow_def.add_edge("strategy_analysis", "risk_analysis")
scuttlebutt_workflow_def.add_edge("risk_analysis", "scuttlebutt_analysis")
scuttlebutt_workflow_def.add_edge("scuttlebutt_analysis", END)

scuttlebutt_graph = scuttlebutt_workflow_def.compile()

# ==============================================================================
# 7. QUANTITATIVE DEEP-DIVE GRAPH
# ==============================================================================
quant_workflow_def = StateGraph(StockAnalysisState)
quant_workflow_def.add_node("screener_for_quant", nodes.screener_for_quant_node)
quant_workflow_def.add_node("isolated_quant", nodes.isolated_quantitative_node)

quant_workflow_def.set_entry_point("screener_for_quant")
quant_workflow_def.add_edge("screener_for_quant", "isolated_quant")
quant_workflow_def.add_edge("isolated_quant", END)

quant_only_graph = quant_workflow_def.compile()

# ==============================================================================
# 8. VALUATION DEEP-DIVE GRAPH
# ==============================================================================
val_workflow_def = StateGraph(StockAnalysisState)
val_workflow_def.add_node("screener_for_valuation", nodes.screener_for_valuation_node)
val_workflow_def.add_node("isolated_valuation", nodes.isolated_valuation_node)

val_workflow_def.set_entry_point("screener_for_valuation")
val_workflow_def.add_edge("screener_for_valuation", "isolated_valuation")
val_workflow_def.add_edge("isolated_valuation", END)

valuation_only_graph = val_workflow_def.compile()

# ==============================================================================
# 9. STRATEGY DEEP-DIVE GRAPH
# ==============================================================================
strat_workflow_def = StateGraph(StockAnalysisState)
strat_workflow_def.add_node("screener_for_strategy", nodes.screener_for_strategy_node)
strat_workflow_def.add_node("isolated_strategy", nodes.isolated_strategy_node)

strat_workflow_def.set_entry_point("screener_for_strategy")
strat_workflow_def.add_edge("screener_for_strategy", "isolated_strategy")
strat_workflow_def.add_edge("isolated_strategy", END)

strategy_only_graph = strat_workflow_def.compile()