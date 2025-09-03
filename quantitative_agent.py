import pandas as pd
import os
import warnings
import sys
import google.generativeai as genai
from dotenv import load_dotenv
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# --- CHARTING FUNCTIONS ---

def create_sales_profit_chart(df, ticker):
    """Generates a bar chart for Sales and Net Profit."""
    try:
        data = df.loc[['Sales', 'Net profit']].copy()
        for col in data.columns:
            data[col] = pd.to_numeric(data[col], errors='coerce')
        
        data.T.plot(kind='bar', figsize=(12, 7), grid=True)
        plt.title(f'{ticker} - Annual Sales and Net Profit', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.legend(title='Metric')
        plt.tight_layout()
        
        filename = f"{ticker}_1_sales_profit.png"
        plt.savefig(filename)
        plt.close()
        print(f"Chart saved as {filename}")
        return filename
    except Exception as e:
        print(f"Could not generate Sales/Profit chart: {e}")
        return None

def create_borrowings_chart(df, ticker):
    """Generates a bar chart for Borrowings (Debt)."""
    try:
        data = df.loc[['Borrowings']].copy()
        for col in data.columns:
            data[col] = pd.to_numeric(data[col], errors='coerce')

        data.T.plot(kind='bar', figsize=(10, 6), grid=True, legend=False)
        plt.title(f'{ticker} - Borrowings Over Time', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()

        filename = f"{ticker}_2_borrowings.png"
        plt.savefig(filename)
        plt.close()
        print(f"Chart saved as {filename}")
        return filename
    except Exception as e:
        print(f"Could not generate Borrowings chart: {e}")
        return None

def create_cashflow_vs_profit_chart(cashflow_df, pnl_df, ticker):
    """Generates a chart comparing Cash from Ops to Net Profit."""
    try:
        # Ensure we're working with copies to avoid SettingWithCopyWarning
        cf_data = cashflow_df.loc[['Cash from Operating Activity']].copy()
        profit_data = pnl_df.loc[['Net profit']].copy()

        # Combine the two series into one DataFrame
        combined_data = pd.concat([cf_data, profit_data])
        for col in combined_data.columns:
            combined_data[col] = pd.to_numeric(combined_data[col], errors='coerce')
        
        combined_data.T.plot(kind='bar', figsize=(12, 7), grid=True)
        plt.title(f'{ticker} - Net Profit vs. Cash from Operating Activity', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.legend(title='Metric')
        plt.tight_layout()

        filename = f"{ticker}_3_cashflow_vs_profit.png"
        plt.savefig(filename)
        plt.close()
        print(f"Chart saved as {filename}")
        return filename
    except Exception as e:
        print(f"Could not generate Cashflow vs Profit chart: {e}")
        return None


# --- DATA PARSING (Updated to return all 3 statements) ---

def read_and_parse_data_sheet(excel_path: str):
    """Reads the 'Data Sheet' and returns P&L, Balance Sheet, and Cash Flow."""
    try:
        df = pd.read_excel(excel_path, sheet_name='Data Sheet', header=None, engine='openpyxl')

        report_date_indices = df[df.iloc[:, 0].astype(str).str.contains('Report Date', na=False)].index
        annual_headers_row_index = report_date_indices[0]
        quarterly_headers_row_index = report_date_indices[1]
        annual_headers = [str(h) for h in df.iloc[annual_headers_row_index, :].tolist()]
        annual_headers[0] = 'Narration'
        
        pnl_start = df[df.iloc[:, 0].astype(str).str.contains('PROFIT & LOSS', na=False)].index[0]
        bs_start = df[df.iloc[:, 0].astype(str).str.contains('BALANCE SHEET', na=False)].index[0]
        cf_start = df[df.iloc[:, 0].astype(str).str.contains('CASH FLOW', na=False)].index[0]
        price_row = df[df.iloc[:, 0].astype(str).str.contains('PRICE:', na=False)].index[0]

        pnl_df = df.iloc[pnl_start + 2 : bs_start - 1].copy()
        bs_df = df.iloc[bs_start + 2 : cf_start - 1].copy()
        cf_df = df.iloc[cf_start + 2 : price_row].copy()

        def process_df(dataframe):
            dataframe.columns = annual_headers[:len(dataframe.columns)]
            dataframe.set_index('Narration', inplace=True)
            dataframe.dropna(how='all', inplace=True)
            return dataframe

        return process_df(pnl_df), process_df(bs_df), process_df(cf_df)

    except Exception as e:
        print(f"Error parsing 'Data Sheet': {e}")
        return None, None, None


# --- MAIN ANALYSIS FUNCTION (Updated to call all chart functions) ---

def analyze_financials(excel_path: str, ticker: str):
    """
    Main function to analyze data, generate text and all charts,
    and return a structured list.
    """
    USE_MOCK_DATA = True
    MOCK_DATA_PATH = "mock_quant_report.txt"

    try:
        annual_pnl_df, balance_sheet_df, cash_flow_df = read_and_parse_data_sheet(excel_path)
        if annual_pnl_df is None:
            return [{"type": "text", "content": "Could not parse financial statements."}]

        # --- Get Text Analysis (Mock or Live) ---
        analysis_result_text = ""
        if USE_MOCK_DATA:
            print("--- Using Mock Quantitative Report ---")
            with open(MOCK_DATA_PATH, 'r', encoding='utf-8') as f:
                analysis_result_text = f.read()
        else:
            # Note: The live prompt should be updated to analyze all 3 statements
            print("--- Calling Live Gemini API ---")
            # analysis_result_text = call_gemini_api(...)
            analysis_result_text = "Live API call disabled in this example."

        # --- Generate All Charts ---
        chart1 = create_sales_profit_chart(annual_pnl_df, ticker)
        chart2 = create_borrowings_chart(balance_sheet_df, ticker)
        chart3 = create_cashflow_vs_profit_chart(cash_flow_df, annual_pnl_df, ticker)
        
        # --- Assemble the Structured Output ---
        report_content = []
        if analysis_result_text:
            report_content.append({"type": "text", "content": analysis_result_text})
        
        # Add charts to the content list if they were created successfully
        for chart_path in [chart1, chart2, chart3]:
            if chart_path:
                report_content.append({"type": "chart", "content": chart_path})
        
        return report_content

    except Exception as e:
        return [{"type": "text", "content": f"An unexpected error occurred: {e}"}]

# --- Main execution block for testing ---
if __name__ == '__main__':
    if len(sys.argv) == 3:
        file_path, TICKER = sys.argv[1], sys.argv[2]
    else:
        TICKER = "RSYSTEMS"
        # Assuming the sample CSVs are converted to a single Excel file
        # For testing, you'll need an .xlsx file named RSYSTEMS.xlsx
        file_path = f"{TICKER}.xlsx" 

    final_content = analyze_financials(file_path, TICKER)
    
    print("\n--- STRUCTURED OUTPUT ---")
    import json
    print(json.dumps(final_content, indent=2))