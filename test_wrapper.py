import os
from dotenv import load_dotenv
from screener_handler import ScreenerHandler

# Load environment variables (for credentials)
load_dotenv()

target_url = "https://www.screener.in/market/IN06/" 

def run_test():
    print(f"🚀 Starting Test on: {target_url}\n")
    
    # GET CREDENTIALS
    email = os.getenv("SCREENER_EMAIL")
    password = os.getenv("SCREENER_PASSWORD")
    
    if not email or not password:
        print("❌ Error: SCREENER_EMAIL or SCREENER_PASSWORD not found in .env file.")
        return

    handler = ScreenerHandler()
    
    # 1. HARVEST (Now with Login!)
    print("... Logging in & Harvesting data...")
    raw_df, error_msg = handler.fetch_wrapper_data(target_url, email, password)
    
    if not raw_df.empty:
        print(f"✅ Harvest Success! Found {len(raw_df)} stocks.")
    else:
        print(f"❌ Harvest Failed: {error_msg}")
        return

    # 2. GATEKEEPER
    print("\n... Applying 5/5 Financial Filters...")
    survivors, status_msg = handler.filter_survivors(raw_df)
    
    print(f"📋 Status: {status_msg}")
    
    if not survivors.empty:
        print(f"\n🏆 QUALIFIED SURVIVORS ({len(survivors)}):")
        print(survivors.to_string(index=False))
    else:
        print("\n⚠️ No stocks passed the strict filters.")

if __name__ == "__main__":
    run_test()