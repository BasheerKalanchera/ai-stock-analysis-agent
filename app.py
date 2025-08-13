import streamlit as st
import os
from dotenv import load_dotenv

# --- Import Functions from Your Agent Scripts ---
# We assume these files are in the same directory
from Screener_Download import download_screener_excel
from quantitative_agent import analyze_financials

# --- Page Configuration ---
st.set_page_config(
    page_title="AI Stock Analysis Agent",
    page_icon="🤖",
    layout="wide"
)

# --- Load Environment Variables ---
load_dotenv()

# --- Main App Interface ---
st.title("🤖 AI Stock Analysis Agent")
st.markdown("This app uses a team of AI agents to perform a quantitative analysis of a stock.")

# --- User Input ---
st.sidebar.header("Controls")
ticker = st.sidebar.text_input("Enter Stock Ticker (e.g., CUPID, RELIANCE)", value="CUPID")
analyze_button = st.sidebar.button("Analyze Stock", type="primary")

# --- Main Logic ---
if analyze_button:
    # --- Validate Inputs ---
    if not ticker:
        st.error("Please enter a stock ticker.")
    else:
        # --- Setup Paths and Credentials ---
        SCREENER_EMAIL = os.getenv("SCREENER_EMAIL")
        SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")
        GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
        DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")
        
        if not os.path.exists(DOWNLOAD_DIRECTORY):
            os.makedirs(DOWNLOAD_DIRECTORY)

        # --- Check for Credentials ---
        if not SCREENER_EMAIL or not SCREENER_PASSWORD or not GOOGLE_API_KEY:
            st.error("One or more required credentials (SCREENER_EMAIL, SCREENER_PASSWORD, GOOGLE_API_KEY) are missing from your .env file.")
        else:
            # --- Agent 1: Data Fetcher ---
            st.info(f"Agent 1: Fetching financial data for {ticker} from Screener.in...")
            with st.spinner("The Data Fetcher agent is running. This may take a moment..."):
                try:
                    # Call the download function
                    download_screener_excel(ticker, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY)
                    excel_path = os.path.join(DOWNLOAD_DIRECTORY, f"{ticker}.xlsx")
                    
                    if os.path.exists(excel_path):
                        st.success(f"Agent 1: Successfully downloaded data to {excel_path}")
                        
                        # --- Agent 2: Quantitative Analyst ---
                        st.info(f"Agent 2: Performing quantitative analysis for {ticker}...")
                        with st.spinner("The Quantitative Analyst agent is processing the data and calling the Gemini API..."):
                            try:
                                # Call the analysis function, which now returns the report
                                analysis_report = analyze_financials(excel_path, ticker)
                                
                                st.success("Agent 2: Analysis complete!")
                                
                                # --- Display the Final Report ---
                                st.markdown("---")
                                st.header(f"Quantitative Analysis Report for {ticker.upper()}")
                                st.markdown(analysis_report)

                            except Exception as e:
                                st.error(f"An error occurred during analysis: {e}")

                    else:
                        st.error(f"Agent 1: Failed to download the data file for {ticker}. Please check the console for errors.")
                
                except Exception as e:
                    st.error(f"An error occurred during data download: {e}")

else:
    st.info("Enter a stock ticker in the sidebar and click 'Analyze Stock' to begin.")


