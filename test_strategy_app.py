import streamlit as st
import os
import logging
from dotenv import load_dotenv
from Screener_Download import download_financial_data
from strategy_agent import strategy_analyst_agent

# Load environment variables
load_dotenv()

# Configure Streamlit
st.set_page_config(page_title="Strategy Agent Test Harness", layout="wide")

st.title("🚀 Strategy Agent Test Harness")
st.markdown("""
This harness isolates the **Download (PPT) -> Strategy Agent** workflow.
It fetches the latest Investor Presentation and extracts strategic insights.
""")

# Sidebar: Configuration
st.sidebar.header("Configuration")

default_email = os.getenv("SCREENER_EMAIL", "")
default_pass = os.getenv("SCREENER_PASSWORD", "")
default_key = os.getenv("GOOGLE_API_KEY", "")
default_model = os.getenv("LITE_MODEL_NAME", "gemini-2.5-flash-lite")

screener_email = st.sidebar.text_input("Screener Email", value=default_email)
screener_pass = st.sidebar.text_input("Screener Password", value=default_pass, type="password")
gemini_key = st.sidebar.text_input("Gemini API Key", value=default_key, type="password")
gemini_model = st.sidebar.text_input("Gemini Model", value=default_model)

# Main Input
ticker = st.text_input("Enter Ticker (e.g., TATASTEEL)", value="").upper()

if st.button("Run Strategy Analysis"):
    if not (screener_email and screener_pass and gemini_key and ticker):
        st.error("Please provide all credentials and a ticker.")
    else:
        config = {
            "SCREENER_EMAIL": screener_email,
            "SCREENER_PASSWORD": screener_pass
        }

        # Step 1: Download
        with st.status("Running Screener Downloader...", expanded=True) as status:
            st.write("Initializing Stealth Driver...")
            
            company, file_buffers, _ = download_financial_data(ticker, config)
            
            if 'investor_presentation' in file_buffers:
                ppt_size = file_buffers['investor_presentation'].getbuffer().nbytes
                st.success(f"Found Investor Presentation! ({ppt_size / 1024 / 1024:.2f} MB)")
            else:
                st.warning("No Investor Presentation (PPT) found on Screener.")
            
            status.update(label="Download Complete", state="complete", expanded=False)

        # Step 2: Agent Execution
        if 'investor_presentation' in file_buffers:
            st.subheader(f"Strategy Profile: {company}")
            
            with st.spinner(f"Agent is reading PPT slides using {gemini_model}..."):
                report = strategy_analyst_agent(file_buffers, gemini_key, gemini_model)
            
            # Step 3: Display
            st.markdown("---")
            st.markdown(report)
            st.markdown("---")
            
            with st.expander("Debug: Raw Data Info"):
                 st.write(f"Files extracted: {list(file_buffers.keys())}")
        else:
            st.error("Cannot run Agent: No PPT available.")