import pandas as pd
import os
import warnings
import sys
import google.generativeai as genai
from dotenv import load_dotenv

# Suppress openpyxl style warnings which are not relevant for data extraction
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

def format_headers(df_headers):
    """Formats headers to 'Mon-YY' format if they are dates."""
    formatted_headers = []
    for header in df_headers:
        try:
            formatted_headers.append(pd.to_datetime(str(header)).strftime('%b-%y'))
        except (ValueError, TypeError):
            formatted_headers.append(str(header))
    return ['Narration'] + formatted_headers[1:]

def read_and_parse_data_sheet(excel_path: str):
    """
    Reads the 'Data Sheet' and returns the separated financial statements.
    """
    try:
        df = pd.read_excel(excel_path, sheet_name='Data Sheet', header=None, engine='openpyxl')

        # Find all 'Report Date' rows. The first is for annual, the second for quarterly.
        report_date_indices = df[df.iloc[:, 0].astype(str).str.contains('Report Date', na=False)].index
        if len(report_date_indices) < 2:
            print("Error: Could not find both annual and quarterly 'Report Date' rows.")
            return None, None, None
        
        annual_headers_row_index = report_date_indices[0]
        quarterly_headers_row_index = report_date_indices[1]

        # Extract and format headers.
        annual_headers = format_headers(df.iloc[annual_headers_row_index, :].tolist())
        
        # Find the start and end rows for each financial statement section.
        pnl_start_row = df[df.iloc[:, 0].astype(str).str.contains('PROFIT & LOSS', na=False)].index[0]
        balance_sheet_start_row = df[df.iloc[:, 0].astype(str).str.contains('BALANCE SHEET', na=False)].index[0]
        cash_flow_start_row = df[df.iloc[:, 0].astype(str).str.contains('CASH FLOW', na=False)].index[0]
        price_row_index = df[df.iloc[:, 0].astype(str).str.contains('PRICE:', na=False)].index[0]

        # Extract the dataframes for each statement with corrected slicing.
        annual_pnl_df = df.iloc[pnl_start_row + 2 : quarterly_headers_row_index, :].copy()
        balance_sheet_df = df.iloc[balance_sheet_start_row + 2 : cash_flow_start_row - 1, :].copy()
        cash_flow_df = df.iloc[cash_flow_start_row + 2 : price_row_index, :].copy()

        # Apply headers and set index for each dataframe.
        def process_df(dataframe, headers):
            dataframe.columns = headers[:len(dataframe.columns)]
            dataframe.set_index('Narration', inplace=True)
            dataframe.dropna(how='all', inplace=True)
            return dataframe

        annual_pnl_df = process_df(annual_pnl_df, annual_headers)
        balance_sheet_df = process_df(balance_sheet_df, annual_headers)
        cash_flow_df = process_df(cash_flow_df, annual_headers)

        return annual_pnl_df, balance_sheet_df, cash_flow_df

    except Exception as e:
        print(f"Error parsing 'Data Sheet': {e}")
        return None, None, None

def call_gemini_api(pnl_data: str, balance_sheet_data: str, cash_flow_data: str, ticker: str):
    """
    Sends the financial data to the Gemini API and returns the analysis.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Error: GOOGLE_API_KEY not found in .env file."

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""
        You are an expert quantitative financial analyst. Your task is to provide a detailed analysis of the provided financial statements for the company with ticker: {ticker}.

        Here is the financial data:

        --- ANNUAL PROFIT & LOSS ---
        {pnl_data}

        --- ANNUAL BALANCE SHEET ---
        {balance_sheet_data}

        --- ANNUAL CASH FLOW ---
        {cash_flow_data}

        ---

        Based on the data provided, please perform the following analysis:

        1.  **Revenue and Profitability Analysis:**
            * Calculate the Year-on-Year (YoY) sales growth for the last 3 available years.
            * Analyze the trend in Net Profit over the last 5 years. Is it consistent?
            * Comment on the trend of the Operating Profit Margin (OPM). You will need to calculate this (Operating Profit / Sales).

        2.  **Balance Sheet Analysis:**
            * Analyze the company's debt situation. Look at the 'Borrowings' line. Is debt increasing or decreasing?
            * Comment on the trend in 'Reserves'.

        3.  **Cash Flow Analysis:**
            * Analyze the 'Cash from Operating Activity'. Is the company generating consistent cash from its core business?
            * Compare the 'Cash from Operating Activity' to the 'Net Profit'. Are they aligned? A healthy company's operating cash flow is typically close to or higher than its net profit.

        4.  **Overall Summary:**
            * Provide a brief summary of the company's financial health based on your analysis.
            * List 2-3 key positive highlights and 2-3 potential red flags or areas to monitor.

        Present your analysis in a clear, structured format using markdown.
        """
        
        response = model.generate_content(prompt)
        
        return response.text

    except Exception as e:
        return f"An error occurred while calling the Gemini API: {e}"


def analyze_financials(excel_path: str, ticker: str):
    """
    Reads, parses, and sends financial data for AI analysis.
    This function is now designed to be called by other scripts (like a Streamlit app).
    """
    try:
        annual_pnl_df, balance_sheet_df, cash_flow_df = read_and_parse_data_sheet(excel_path)

        if annual_pnl_df is None or balance_sheet_df is None or cash_flow_df is None:
            error_message = "Could not parse one or more essential financial statements. Aborting analysis."
            print(error_message)
            return error_message

        # --- Call the Gemini API with the parsed data ---
        analysis_result = call_gemini_api(
            annual_pnl_df.to_string(),
            balance_sheet_df.to_string(),
            cash_flow_df.to_string(),
            ticker
        )

        # --- THIS IS THE KEY CHANGE ---
        # Instead of printing, we return the result for the app to display.
        return analysis_result

    except FileNotFoundError:
        error_message = f"Error: The file was not found at {excel_path}"
        print(error_message)
        return error_message
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        print(error_message)
        return error_message


if __name__ == '__main__':
    """
    This block allows the script to be run directly for testing.
    It checks for command-line arguments first.
    If two arguments are provided (file_path and ticker), it uses them.
    Otherwise, it falls back to hardcoded default values.
    """
    load_dotenv()
    
    # Check if command-line arguments are provided
    if len(sys.argv) == 3:
        file_path = sys.argv[1]
        TICKER = sys.argv[2]
        print(f"Using command-line arguments: File Path='{file_path}', Ticker='{TICKER}'")
    else:
        # Fallback to hardcoded values for direct testing without arguments
        print("No command-line arguments provided. Falling back to default values.")
        TICKER = "CUPID"
        DOWNLOAD_FOLDER = "downloads"
        file_path = os.path.join(os.getcwd(), DOWNLOAD_FOLDER, f"{TICKER}.xlsx")
    
    # Run the analysis and print the report
    report = analyze_financials(file_path, TICKER)
    print("\n--- QUANTITATIVE ANALYSIS REPORT ---")
    print(report)
