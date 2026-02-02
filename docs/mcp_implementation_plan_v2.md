# MCP Integration Implementation Plan (Simplified - 2 Servers)

## Goal

Integrate Model Context Protocol (MCP) into the existing multi-agent stock analysis system using a **simplified 2-server approach** (Screener + Search only) to standardize external resource access, improve maintainability, and create a more modular architecture.

## Benefits

- **Standardized interfaces** for Screener.in and Tavily search
- **Easier testing** through mockable MCP servers
- **Better error handling** with built-in retry logic
- **Flexibility** to swap data sources without changing agent code
- **Clean separation** between orchestration (LangGraph), agents, and data access (MCP)
- **Agents keep their intelligence** - PDF processing, calculations, AI analysis remain in agents

---

## Architecture Overview

![MCP Architecture - Simplified 2-Server Approach](../../../.gemini/antigravity/brain/17370893-6bc2-4515-9821-977f66b0c318/mcp_architecture_final_clean_1768011944222.png)

**Key Points:**
- **2 MCP Servers Only**: Screener (data fetching) + Search (web search)
- **All 5 agents** use Screener MCP Server for their specific data needs
- **Only Qualitative Agent** uses Search MCP Server for scuttlebutt research  
- **Agents handle internally**: PDF processing (PyMuPDF)

, Financial calculations (pandas), AI analysis (Gemini direct calls), Chart generation (matplotlib)

---

## Implementation Phases

### Phase 1: Infrastructure Setup (2-3 hours)

Set up MCP dependencies and create the foundation.

#### Step 1.1: Install MCP Dependencies

```bash
pip install mcp
```

Update `requirements.txt`:
```txt
# Add MCP support
mcp>=1.0.0
```

#### Step 1.2: Create MCP Directory Structure

```
ai-stock-analysis-agent/
├── mcp_servers/
│   ├── __init__.py
│   ├── base.py              # Base MCP server utilities
│   ├── screener_server.py   # Screener.in MCP server
│   └── search_server.py     # Tavily/search MCP server
├── mcp_clients/
│   ├── __init__.py
│   └── client_manager.py    # MCP client management
```

#### Step 1.3: Create Base MCP Utilities

Create `mcp_servers/base.py` with common functionality:
- Error handling
- Logging
- Connection management
- Retry logic

---

### Phase 2: Screener MCP Server (2-3 days) **HIGH PRIORITY**

Create MCP server to standardize all Screener.in interactions.

#### Step 2.1: Design Resource URIs

Define standardized resource URIs:
```
screener://companies/{ticker}/profile
screener://companies/{ticker}/financials?consolidated=true
screener://companies/{ticker}/peers
screener://companies/{ticker}/excel
screener://companies/{ticker}/presentations/latest
screener://companies/{ticker}/transcripts/latest
screener://companies/{ticker}/transcripts/history?count=2
screener://companies/{ticker}/credit
```

#### Step 2.2: Implement Screener MCP Server

Create `mcp_servers/screener_server.py`:

**Resources to implement:**
- `get_company_profile()` - Basic company info
- `get_financials()` - Financial statements
- `get_peers()` - Peer comparison data
- `get_excel_data()` - Raw Excel files
- `get_presentations()` - Investor presentations
- `get_transcripts()` - Earnings call transcripts
- `get_credit_data()` - Credit ratings

**Tools to implement:**
- `search_company()` - Find company by name/ticker
- `download_documents()` - Batch download documents

#### Step 2.3: Refactor screener_handler.py

Move logic from `screener_handler.py` into MCP server.

---

### Phase 3: Search MCP Server (1 day) **HIGH PRIORITY**

Create MCP server for Tavily web search capabilities.

#### Step 3.1: Design Search Resources

**Resources:**
```
search://news?company={name}&days=30
search://regulatory?company={name}&type=sebi
search://forums?company={name}&platform=valuepickr
```

**Tools:**
- `search_news()` - Recent news articles
- `search_regulatory()` - SEBI orders, filings
- `search_forums()` - Investment forums
- `search_management()` - Management background

#### Step 3.2: Implement Search MCP Server

Create `mcp_servers/search_server.py`:

Move Tavily integration from `qualitative_analysis_agent.py`.

#### Step 3.3: Add Rate Limiting

Implement rate limiting for Tavily API to prevent quota exhaustion.

---

### Phase 4: MCP Client Management (2-3 hours)

Create client utilities for agents to use MCP servers.

#### Step 4.1: Implement Client Manager

Create `mcp_clients/client_manager.py`:

```python
class MCPClientManager:
    def __init__(self, config):
        self.screener = MCPClient("screener")
        self.search = MCPClient("search")
    
    async def initialize(self):
        # Connect to both MCP servers
        await self.screener.connect()
        await self.search.connect()
    
    async def shutdown(self):
        # Clean up connections
        await self.screener.disconnect()
        await self.search.disconnect()
    
    def get_clients(self):
        return {
            'screener': self.screener,
            'search': self.search
        }
```

#### Step 4.2: Update Agent Config

Modify `state.py` to include MCP clients:

```python
class StockAnalysisState(TypedDict):
    # ... existing fields ...
    mcp_clients: Dict[str, Any] | None  # MCP client instances
```

---

### Phase 5: Refactor Agents (2 days)

Update agents to use MCP for data fetching only (keep PDF processing, calculations, AI analysis in agents).

#### Step 5.1: Update Data Fetching

**All agents** - Replace direct Screener.in calls with MCP:

```python
# OLD (direct call)
from screener_handler import download_excel
excel_data = download_excel(ticker)

# NEW (via MCP)
financial_data = await mcp_clients['screener'].read_resource(
    f"screener://companies/{ticker}/financials"
)
```

#### Step 5.2: Update Qualitative Agent

Add Search MCP Server for web search:

```python
# OLD (direct Tavily call)
from tavily import TavilyClient
results = tavily_client.search(query)

# NEW (via MCP)
results = await mcp_clients['search'].call_tool(
    "search_news",
    {"company": company_name, "days": 30}
)
```

#### Step 5.3: Keep Agent Logic Intact

**DO NOT move these to MCP** (keep in agents):
- PDF text extraction (PyMuPDF)
- Financial ratio calculations (pandas/numpy)
- Chart generation (matplotlib)
- AI analysis (Gemini direct calls)

---

### Phase 6: Update Orchestration Layer (1 day)

#### Step 6.1: Update nodes.py

Modify `nodes.py`:

```python
async def fetch_data_node(state: StockAnalysisState):
    mcp_clients = state['mcp_clients']
    ticker = state['ticker']
    
    # Fetch via MCP
    profile = await mcp_clients['screener'].read_resource(
        f"screener://companies/{ticker}/profile"
    )
    
    return {
        "company_name": profile['name'],
        # ... other data ...
    }
```

#### Step 6.2: Update app.py

Initialize MCP clients in `app.py`:

```python
async def run_analysis_for_ticker(ticker, config, status_container):
    # Initialize MCP clients
    mcp_manager = MCPClientManager(config)
    await mcp_manager.initialize()
    
    inputs = {
        "ticker": ticker,
        "mcp_clients": mcp_manager.get_clients(),
        # ... other state ...
    }
    
    # Run workflow
    result = await target_graph.arun(inputs)
    
    await mcp_manager.shutdown()
    return result
```

---

### Phase 7: Testing (1-2 days)

#### Step 7.1: Unit Tests for MCP Servers

Create `tests/test_mcp_servers.py`:
- Test Screener resource endpoints
- Test Search tool endpoints
- Test error handling
- Test rate limiting

#### Step 7.2: Mock MCP Servers

Create mock servers for testing:
```python
class MockScreenerMCP:
    async def read_resource(self, uri):
        return MOCK_DATA[uri]

class MockSearchMCP:
    async def call_tool(self, tool, params):
        return MOCK_RESULTS[tool]
```

#### Step 7.3: Integration Tests

- End-to-end analysis for known ticker
- Verify all 10 workflow modes still work
- Performance benchmarking

---

### Phase 8: Documentation & Deployment (1 day)

#### Step 8.1: Update Documentation

- Document MCP server URIs and tools
- Create deployment guide
- Update README

#### Step 8.2: Configuration

Update `.env`:
```
MCP_SCREENER_URL=http://localhost:8001
MCP_SEARCH_URL=http://localhost:8002
USE_MCP=false  # Feature flag for gradual rollout
```

#### Step 8.3: Deployment Strategy

**Recommended: Embedded Servers**
- MCP servers run as part of main application
- Start when Streamlit starts
- Simpler for single-machine deployment

---

## Migration Strategy

### Feature Flag Approach (Recommended)

```python
USE_MCP = os.getenv('USE_MCP', 'false').lower() == 'true'

if USE_MCP:
    # New MCP path
    data = await mcp_client.read_resource(uri)
else:
    # Legacy path
    data = screener_handler.download(ticker)
```

### Incremental Rollout

1. **Phase 1-2**: Build Screener MCP Server
2. **Test**: Verify with one agent (Quantitative)
3. **Phase 3**: Build Search MCP Server  
4. **Phase 4-5**: Refactor all agents
5. **Phase 6**: Update orchestration
6. **Phase 7**: Full testing
7. **Phase 8**: Deploy with feature flag
8. **Enable**: Set `USE_MCP=true` when confident

---

## Timeline Estimate (Simplified)

| Phase | Effort | Duration |
|-------|--------|----------|
| Phase 1: Infrastructure | Small | 2-3 hours |
| Phase 2: Screener Server | Medium | 2-3 days |
| Phase 3: Search Server | Small | 1 day |
| Phase 4: Client Manager | Small | 2-3 hours |
| Phase 5: Agent Refactoring | Medium | 2 days |
| Phase 6: Orchestration Updates | Small | 1 day |
| Phase 7: Testing | Medium | 1-2 days |
| Phase 8: Documentation | Small | 1 day |
| **Total** | **~5-7 days** | **~1 week** |

**Reduced from 1.5-2 weeks (4-server approach) to ~1 week!**

---

## What We're NOT Building

To keep this simple and focused:

❌ **Financial Analysis MCP Server** - Agents handle calculations directly  
❌ **Document Processing MCP Server** - Agents use PyMuPDF directly  
❌ **Gemini MCP Server** - Agents call Gemini API directly  

These can be added later if needed, but starting with just 2 servers gives us 80% of the value with 40% of the complexity.

---

## Success Metrics

- ✅ All 10 workflow modes working with MCP
- ✅ Screener data fetching centralized
- ✅ Search functionality centralized
- ✅ Zero data loss or corruption
- ✅ Performance within 10% of baseline
- ✅ Easy to add new data sources in future

---

## Next Steps

1. ✅ **Review this simplified plan** 
2. **Decision on deployment** - Embedded vs standalone servers
3. **Start with Phase 1** - Set up infrastructure (2-3 hours)
4. **Build Screener Server** - Prove concept (2-3 days)
5. **Iterate** - Refine based on learnings

**Ready to proceed with Phase 1?**
