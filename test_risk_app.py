import streamlit as st
import os
import logging
from dotenv import load_dotenv
from Screener_Download import download_financial_data
from risk_agent import risk_analyst_agent

# Load environment variables
load_dotenv()

# Configure Streamlit
st.set_page_config(page_title="Risk Agent Test Harness", layout="wide")

st.title("🧪 Risk Agent Test Harness")
st.markdown("""
This harness isolates the **Download -> Risk Agent** workflow.
It skips valuation models and full report generation to allow rapid iteration on the Risk Agent prompt.
""")

# Sidebar: Configuration
st.sidebar.header("Configuration")

# Load defaults from .env
default_email = os.getenv("SCREENER_EMAIL", "")
default_pass = os.getenv("SCREENER_PASSWORD", "")
default_key = os.getenv("GOOGLE_API_KEY", "")
default_model = os.getenv("LITE_MODEL_NAME", "gemini-2.5-flash-lite") # Fallback if .env missing

screener_email = st.sidebar.text_input("Screener Email", value=default_email)
screener_pass = st.sidebar.text_input("Screener Password", value=default_pass, type="password")
gemini_key = st.sidebar.text_input("Gemini API Key", value=default_key, type="password")
gemini_model = st.sidebar.text_input("Gemini Model", value=default_model)

# Main Input
ticker = st.text_input("Enter Ticker (e.g., TATASTEEL)", value="").upper()

if st.button("Run Risk Analysis"):
    if not (screener_email and screener_pass and gemini_key and ticker):
        st.error("Please provide all credentials and a ticker.")
    else:
        # Create Config Dict
        config = {
            "SCREENER_EMAIL": screener_email,
            "SCREENER_PASSWORD": screener_pass
        }

        # Step 1: Download
        with st.status("Running Screener Downloader...", expanded=True) as status:
            st.write("Initializing Stealth Driver...")
            
            # Run the updated downloader
            # Note: We don't need consolidated for risk usually, default False is fine
            company, file_buffers, _ = download_financial_data(ticker, config)
            
            if 'credit_rating_doc' in file_buffers:
                doc_type = file_buffers['credit_rating_type']
                st.success(f"Found Credit Rating ({doc_type})!")
            else:
                st.warning("No Credit Rating found on Screener.")
            
            status.update(label="Download Complete", state="complete", expanded=False)

        # Step 2: Agent Execution
        st.subheader(f"Risk Profile: {company}")
        
        with st.spinner(f"Agent is analyzing credit documents using {gemini_model}..."):
            # Pass the model name explicitly
            report = risk_analyst_agent(file_buffers, gemini_key, gemini_model)
        
        # Step 3: Display
        st.markdown("---")
        st.markdown(report)
        st.markdown("---")
        
        # Debug: Show raw data info
        with st.expander("Debug: Raw Data Info"):
            st.write(f"Files extracted: {list(file_buffers.keys())}")
            if 'credit_rating_doc' in file_buffers:
                content = file_buffers['credit_rating_doc']
                st.write(f"Rating Content Type: {type(content)}")
                if isinstance(content, str):
                    st.write(f"Length: {len(content)} chars")