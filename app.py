import streamlit as st
import os
from dotenv import load_dotenv

# Import Agent Functions
from Screener_Download import download_financial_data
from qualitative_agent import process_annual_report, answer_qualitative_question

st.set_page_config(page_title="AI Stock Analysis Agent", page_icon="🤖", layout="wide")
load_dotenv()

st.title("🤖 AI Stock Analysis Crew")
st.markdown("Enter a stock ticker to analyze its Annual Report.")

# --- Session State Initialization ---
if 'ticker' not in st.session_state:
    st.session_state.ticker = ""
if 'report_data' not in st.session_state:
    st.session_state.report_data = None
# NEW: Initialize chat history
if 'messages' not in st.session_state:
    st.session_state.messages = []

# --- Sidebar Controls ---
st.sidebar.header("Controls")
ticker_input = st.sidebar.text_input("Enter Stock Ticker", value="DOMS")

if st.sidebar.button("Analyze Stock", type="primary"):
    st.session_state.ticker = ticker_input
    # Clear previous analysis and chat history
    st.session_state.report_data = None
    st.session_state.messages = []
    
    if not st.session_state.ticker:
        st.error("Please enter a stock ticker.")
    else:
        # --- Run Analysis Pipeline ---
        SCREENER_EMAIL = os.getenv("SCREENER_EMAIL")
        SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")
        DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")

        if not os.path.exists(DOWNLOAD_DIRECTORY): os.makedirs(DOWNLOAD_DIRECTORY)

        with st.spinner(f"Agent 1 (Data Fetcher): Securing data for {st.session_state.ticker}..."):
            excel_path, pdf_path = download_financial_data(
                st.session_state.ticker, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY
            )

        if pdf_path:
            st.success("Data Fetcher Agent: PDF secured.")
            with st.spinner("The Qualitative Agent is reading the Annual Report..."):
                st.session_state.report_data = process_annual_report(pdf_path)
            if not st.session_state.report_data:
                st.error("Qualitative Agent failed: Could not process the PDF document.")
        else:
            st.error("Data Fetcher Agent failed: Could not secure the PDF file.")

# --- Main Chat Interface ---
st.header(f"Qualitative Analysis for {st.session_state.ticker.upper()}")

# NEW: Display chat history
chat_container = st.container()
with chat_container:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# Only show the chat input if the report has been processed
if st.session_state.report_data:
    if prompt := st.chat_input("Ask a question about the annual report..."):
        # Add user message to history
        st.session_state.messages.append({"role": "user", "content": prompt})
        # Display user message
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

        # Generate and display AI response
        with st.spinner("The Qualitative Agent is analyzing..."):
            response = answer_qualitative_question(st.session_state.report_data, prompt)
            with chat_container:
                 with st.chat_message("assistant"):
                    st.markdown(response)
            # Add AI response to history
            st.session_state.messages.append({"role": "assistant", "content": response})
else:
    st.info("Click 'Analyze Stock' to begin the analysis.")