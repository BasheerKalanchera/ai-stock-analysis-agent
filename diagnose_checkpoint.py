"""
Standalone Neon/checkpointer diagnostic.
Run: python diagnose_checkpoint.py
This does NOT import Streamlit or graphs — pure timing test.
"""
import os, time, socket
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("❌ DATABASE_URL not found in .env"); exit(1)

print(f"DB URL (masked): ...{db_url[-40:]}\n")

# ── Step 1: Raw TCP ping to Neon host ───────────────────────────────────────
import urllib.parse
parsed = urllib.parse.urlparse(db_url)
host = parsed.hostname
port = parsed.port or 5432
print(f"Step 1 — TCP connect to {host}:{port}")
t = time.time()
try:
    sock = socket.create_connection((host, port), timeout=10)
    sock.close()
    print(f"  ✅ TCP OK in {time.time()-t:.2f}s\n")
except Exception as e:
    print(f"  ❌ TCP FAILED in {time.time()-t:.2f}s: {e}\n")

# ── Step 2: psycopg.connect (no query) ──────────────────────────────────────
print("Step 2 — psycopg.connect (autocommit, connect_timeout=10)")
t = time.time()
try:
    import psycopg
    conn = psycopg.connect(db_url, autocommit=True, connect_timeout=10)
    print(f"  ✅ Connected in {time.time()-t:.2f}s")
    conn.close()
    print()
except Exception as e:
    print(f"  ❌ FAILED in {time.time()-t:.2f}s: {e}\n"); exit(1)

# ── Step 3: PostgresSaver.setup() ───────────────────────────────────────────
print("Step 3 — PostgresSaver(conn).setup()  [creates/checks tables]")
t = time.time()
try:
    from langgraph.checkpoint.postgres import PostgresSaver
    with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as setup_conn:
        PostgresSaver(setup_conn).setup()
    print(f"  ✅ setup() done in {time.time()-t:.2f}s\n")
except Exception as e:
    print(f"  ❌ FAILED in {time.time()-t:.2f}s: {e}\n"); exit(1)

# ── Step 4: ConnectionPool creation ─────────────────────────────────────────
print("Step 4 — ConnectionPool.open(wait=True, timeout=10)")
t = time.time()
try:
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(
        conninfo=db_url,
        min_size=0, max_size=2,
        kwargs={"autocommit": True, "connect_timeout": 10},
        open=False,
        check=ConnectionPool.check_connection,
    )
    pool.open(wait=True, timeout=10)
    print(f"  ✅ Pool opened in {time.time()-t:.2f}s")
    pool.close()
    print()
except Exception as e:
    print(f"  ❌ FAILED in {time.time()-t:.2f}s: {e}\n"); exit(1)

# ── Step 5: Graph recompilation ─────────────────────────────────────────────
print("Step 5 — graphs.recompile_with_checkpointer()  [8 LangGraph graphs]")
t = time.time()
try:
    import graphs
    from checkpointer_serde import StockAnalysisSerializer

    # Build a dummy pool just for timing the recompile step
    pool2 = ConnectionPool(
        conninfo=db_url,
        min_size=0, max_size=1,
        kwargs={"autocommit": True, "connect_timeout": 10},
        open=False,
    )
    pool2.open(wait=True, timeout=10)
    serde = StockAnalysisSerializer()
    cp = PostgresSaver(conn=pool2, serde=serde)
    graphs.recompile_with_checkpointer(cp)
    print(f"  ✅ Recompile done in {time.time()-t:.2f}s\n")
    pool2.close()
except Exception as e:
    print(f"  ❌ FAILED in {time.time()-t:.2f}s: {e}\n"); exit(1)

print("=" * 50)
print("✅ All steps passed. Checkpointer should work fine.")
print("   If Streamlit still fails, the 25s thread timeout may still be\n"
      "   too short — check the individual step times above.\n")
