import pandas as pd
import warnings
import re
import google.generativeai as genai
import matplotlib.pyplot as plt
import datetime
import io
from typing import List, Dict, Any

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# --- CHARTING FUNCTIONS (No changes needed) ---
def format_year_ticks(ax):
    """Helper function to format x-axis ticks to show only years"""
    labels = [label.get_text()[:4] for label in ax.get_xticklabels()]
    ax.set_xticklabels(labels, rotation=45, ha='right')

def create_sales_profit_chart(df, ticker):
    try:
        data = df.loc[['Sales', 'Net profit']].copy()
        data.columns = pd.to_datetime(data.columns)
        data = data.sort_index(axis=1)
        
        for col in data.columns: 
            data[col] = pd.to_numeric(data[col], errors='coerce')
        ax = data.T.plot(kind='bar', figsize=(12, 7), grid=True)
        plt.title(f'{ticker} - Annual Sales and Net Profit', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        format_year_ticks(ax)
        plt.legend(title='Metric')
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        print(f"Sales vs Net Profit Chart for {ticker} created in memory.")
        return buf
    except Exception as e:
        print(f"Could not generate Sales/Profit chart: {e}")
        return None

def create_borrowings_chart(df, ticker):
    try:
        data = df.loc[['Borrowings']].copy()
        data.columns = pd.to_datetime(data.columns)
        data = data.sort_index(axis=1)
        
        for col in data.columns: 
            data[col] = pd.to_numeric(data[col], errors='coerce')
        ax = data.T.plot(kind='bar', figsize=(10, 6), grid=True, legend=False)
        plt.title(f'{ticker} - Borrowings Over Time', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        format_year_ticks(ax)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        print(f"Borrowings Chart for {ticker} created in memory.")
        return buf
    except Exception as e:
        print(f"Could not generate Borrowings chart: {e}")
        return None

def create_cashflow_vs_profit_chart(cashflow_df, pnl_df, ticker):
    try:
        cf_data = cashflow_df.loc[['Cash from Operating Activity']].copy()
        profit_data = pnl_df.loc[['Net profit']].copy()
        combined_data = pd.concat([cf_data, profit_data])
        
        combined_data.columns = pd.to_datetime(combined_data.columns)
        combined_data = combined_data.sort_index(axis=1)
        
        for col in combined_data.columns:
            combined_data[col] = pd.to_numeric(combined_data[col], errors='coerce')
            
        ax = combined_data.T.plot(kind='bar', figsize=(12, 7), grid=True)
        plt.title(f'{ticker} - Net Profit vs. Cash from Operating Activity', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        format_year_ticks(ax)
        plt.legend(title='Metric')
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        print(f"Cashflow vs Net Profit Chart for {ticker} created in memory.")
        return buf
    except Exception as e:
        print(f"Could not generate Cashflow vs Profit chart: {e}")
        return None
    
def create_opm_chart(opm_df: pd.DataFrame, ticker: str):
    """Generates a bar chart for OPM Trend from a pre-processed DataFrame."""
    try:
        opm_df_for_plotting = opm_df.drop('Operating Profit (Cr)').T
        
        opm_df_for_plotting.index = pd.to_datetime(opm_df_for_plotting.index)
        opm_df_for_plotting = opm_df_for_plotting.sort_index()
        
        opm_df_for_plotting['OPM %'] = pd.to_numeric(opm_df_for_plotting['OPM %'], errors='coerce')
        ax = opm_df_for_plotting.plot(y='OPM %', kind='bar', figsize=(10, 6), grid=True, legend=False, color='red')
        plt.title(f'{ticker} - Operating Profit Margin (OPM) Trend', fontsize=16)
        plt.ylabel('OPM (%)', fontsize=12)
        plt.xlabel('Year')
        format_year_ticks(ax)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        print(f"OPM Chart for {ticker} created in memory.")
        return buf
    except Exception as e:
        print(f"Could not generate OPM chart from DataFrame: {e}")
        return None

def create_reserves_chart(df, ticker):
    try:
        data = df.loc[['Reserves']].copy()
        data.columns = pd.to_datetime(data.columns)
        data = data.sort_index(axis=1)
        
        for col in data.columns: 
            data[col] = pd.to_numeric(data[col], errors='coerce')
        ax = data.T.plot(kind='bar', figsize=(10, 6), grid=True, legend=False, color='green')
        plt.title(f'{ticker} - Reserves Growth Over Time', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        format_year_ticks(ax)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        print(f"Reserves Chart for {ticker} created in memory.")
        return buf
    except Exception as e:
        print(f"Could not generate Reserves chart: {e}")
        return None

def create_cfo_chart(df, ticker):
    try:
        data = df.loc[['Cash from Operating Activity']].copy()
        data.columns = pd.to_datetime(data.columns)
        data = data.sort_index(axis=1)
        
        for col in data.columns: 
            data[col] = pd.to_numeric(data[col], errors='coerce')
        ax = data.T.plot(kind='bar', figsize=(10, 6), grid=True, legend=False, color='purple')
        plt.title(f'{ticker} - Cash from Operating Activity (CFO) Trend', fontsize=16)
        plt.ylabel('Amount (in Crores)', fontsize=12)
        format_year_ticks(ax)
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        print(f"CFO Chart for {ticker} created in memory.")
        return buf
    except Exception as e:
        print(f"Could not generate CFO chart: {e}")
        return None

# --- HEADER CLEANING HELPER (No changes needed) ---
def clean_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Drop bad headers, duplicate columns, and normalize names to string."""
    df = df.loc[:, df.columns.notna()]
    df = df.loc[:, df.columns.astype(str).str.lower() != 'nan']
    df = df.dropna(axis=1, how='all')
    df = df.loc[:, ~df.columns.duplicated(keep='first')]
    df.columns = df.columns.map(str)
    return df

# --- DATA PARSING (No changes needed) ---
def read_and_parse_data_sheet(excel_buffer: io.BytesIO):
    """Parse financial data from Excel buffer."""
    try:
        df = pd.read_excel(excel_buffer, sheet_name='Data Sheet', header=None, engine='openpyxl')
        excel_buffer.seek(0)
        report_date_indices = df[df.iloc[:, 0].astype(str).str.contains('Report Date', na=False)].index
        annual_headers_row_index = report_date_indices[0]
        annual_headers = [h.strftime('%Y-%m-%d') if isinstance(h, datetime.datetime) else str(h) for h in df.iloc[annual_headers_row_index, :].tolist()]
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
            dataframe.set_index('Narration', inplace=True); dataframe.dropna(how='all', inplace=True)
            return dataframe[~dataframe.index.duplicated(keep='first')]

        pnl = process_df(pnl_df)
        bs = process_df(bs_df)
        cf = process_df(cf_df)

        pnl = clean_headers(pnl)
        bs = clean_headers(bs)
        cf = clean_headers(cf)
       
        return pnl, bs, cf

    except Exception as e:
        print(f"Error parsing 'Data Sheet': {e}"); return None, None, None

def calculate_opm_from_data_sheet(excel_buffer: io.BytesIO):
    """Calculate OPM from Excel buffer."""
    try:
        df = pd.read_excel(excel_buffer, sheet_name='Data Sheet', header=None, engine='openpyxl')
        excel_buffer.seek(0)
        
        header_row_index = df[df[0] == 'Report Date'].index[0]
        header_values = df.iloc[header_row_index]
        data_start_index = header_row_index + 1
        bs_start_index = df[df[0] == 'BALANCE SHEET'].index[0]
        pnl_data = df.iloc[data_start_index:bs_start_index].copy()
        pnl_data.columns = header_values
        pnl_data.set_index('Report Date', inplace=True)
        pnl_data.index.name = "Narration"
        
        pnl_data = pnl_data[~pnl_data.index.duplicated(keep='first')]
        pnl_data.index = pnl_data.index.str.strip()
        
        pnl_data = pnl_data.apply(pd.to_numeric, errors='coerce').fillna(0)

        opex_group_items = ['Raw Material Cost', 'Power and Fuel', 'Other Mfr. Exp', 'Employee Cost', 'Selling and admin', 'Other Expenses']
        opex_group_sum = pnl_data.loc[pnl_data.index.intersection(opex_group_items)].sum(axis=0)
        inventory_series = pnl_data.loc['Change in Inventory'] if 'Change in Inventory' in pnl_data.index else pd.Series(0, index=pnl_data.columns)
        total_expenses = opex_group_sum - inventory_series
        sales_series = pnl_data.loc['Sales']
        operating_profit = sales_series - total_expenses
        opm_percent = (operating_profit / sales_series) * 100

        opm_df = pd.DataFrame({'Operating Profit (Cr)': operating_profit, 'OPM %': opm_percent.round(2)}).T
        opm_df.columns = [col.strftime('%Y-%m-%d') if isinstance(col, datetime.datetime) else col for col in opm_df.columns]
        opm_df.rename(columns={col: col.strftime('%Y-%m-%d') if isinstance(col, datetime.datetime) else col for col in opm_df.columns}, inplace=True)
        opm_df = clean_headers(opm_df)
        return opm_df

    except Exception as e:
        print(f"Could not calculate OPM data from 'Data Sheet': {e}")
        return None

# --- LLM ANALYSIS FUNCTION ---
def get_analysis_from_gemini(pnl_df, bs_df, cf_df, ticker, opm_table_string, agent_config: dict):
    """Sends financial data to Gemini and gets back a quantitative analysis report."""
    api_key = agent_config.get("GOOGLE_API_KEY")
    # Using 'LITE_MODEL_NAME' for consistency, but you can change this if needed
    model_name = agent_config.get("LITE_MODEL_NAME", "gemini-1.5-flash")

    if not api_key:
        return "ERROR: Google API Key not configured."

    try:
        genai.configure(api_key=api_key)
        
        generation_config = {"temperature": 0.2, "top_p": 1, "top_k": 1, "max_output_tokens": 8192}
        model = genai.GenerativeModel(model_name=model_name, generation_config=generation_config)

        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 2000)

        pnl_string = pnl_df.to_string()
        bs_string = bs_df.to_string()
        cf_string = cf_df.to_string()

        prompt = f"""
        You are an expert financial analyst. Your task is to provide a detailed quantitative analysis of a company based on its financial statements.
        Analyze the data for ticker "{ticker}":

        **Profit & Loss Statement (Annual):**
        ```{pnl_string}```
        **OPM (Annual):**
        ```{opm_table_string}```
        **Balance Sheet (Annual):**
        ```{bs_string}```
        **Cash Flow Statement (Annual):**
        ```{cf_string}```

        Please perform the following analysis and structure your response in Markdown:

        ### 1. Revenue and Profitability Analysis
        - **Year-on-Year (YoY) Sales and Net Profit Growth:** Analyze YoY sales and Net Profit growth for the data provided
        - **Analysis:** Comment on the trend.
        - **Operating Profit Margin (OPM) Trend:** Analyze the trend of OPM for the data provided
        - **Analysis:** Comment on the OPM trend based on the data provided above.

        ### 2. Balance Sheet Analysis
        - **Company's Debt Situation (Borrowings):** Analyze the trend of 'Borrowings' for the data provided.
        - **Analysis:** Comment on the debt trend.
        - **Trend in 'Reserves':** Analyze the trend of 'Reserves' for the data provided.
        - **Analysis:** Comment on the reserves trend.

        ### 3. Cash Flow Analysis
        - **Comparison of 'Cash from Operating Activity' to 'Net Profit' (Annual):** Compare CFO and Net Profit annually and calculate the CFO/NP Ratio.
        - **Analysis:** Comment on the CFO trend and CFO vs Net Profit comparison.
        - **Cumulative 'Cash from Operating Activity' vs. 'Net Profit':** Calculate the cumulative CFO and cumulative Net Profit over the entire period available and provide the ratio.
        - **Analysis:** Comment on the cumulative data.

        ### 4. Overall Summary
        - **Key Findings:** Summarize your key findings.
        - **Key Positive Highlights:** List 2-3 positive highlights.
        - **Potential Red Flags / Areas to Monitor:** List 2-3 red flags.
        
        Provide a professional, data-driven analysis. Do not include investment advice.
        """
        
        print("--- Calling Gemini for Quantitative Analysis ---")
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        print(f"An error occurred while calling the Gemini API: {e}")
        return f"ERROR: Failed to get analysis from Gemini. {e}"


def safe_extract_section(text, start_marker, end_marker=None):
    try:
        pattern = f"({re.escape(start_marker)}.*?)(?={re.escape(end_marker)})" if end_marker else f"({re.escape(start_marker)}.*)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except re.error as e:
        print(f"Regex error for marker '{start_marker}': {e}"); return ""

# --- MAIN ANALYSIS FUNCTION ---
def analyze_financials(excel_buffer: io.BytesIO, ticker: str, agent_config: dict) -> List[Dict[str, Any]]:
    """
    Analyzes financial data from Excel file stored in memory.
    Accepts an agent_config dictionary for API key and model names.
    """
    print("--- Starting Quantitative Analysis ---")
    try:
        # Parse Excel data from buffer
        annual_pnl_df, balance_sheet_df, cash_flow_df = read_and_parse_data_sheet(excel_buffer)
        if annual_pnl_df is None: 
            return [{"type": "text", "content": "Could not parse financial statements."}]

        # Calculate OPM using the same buffer
        opm_df = calculate_opm_from_data_sheet(excel_buffer)
        opm_table_string = opm_df.to_markdown() if opm_df is not None else "OPM data could not be extracted from the 'Data Sheet'."
            
        # Get analysis from Gemini, passing the config dictionary
        analysis_result_text = get_analysis_from_gemini(
            annual_pnl_df, balance_sheet_df, cash_flow_df, ticker, opm_table_string, agent_config
        )
        if "ERROR:" in analysis_result_text: 
            return [{"type": "text", "content": analysis_result_text}]

        # Create charts using the parsed DataFrames
        chart1_sales_profit = create_sales_profit_chart(annual_pnl_df, ticker)
        chart2_borrowings = create_borrowings_chart(balance_sheet_df, ticker)
        chart3_cf_vs_profit = create_cashflow_vs_profit_chart(cash_flow_df, annual_pnl_df, ticker)
        chart4_opm = create_opm_chart(opm_df, ticker) if opm_df is not None else None
        chart5_reserves = create_reserves_chart(balance_sheet_df, ticker)
        chart6_cfo = create_cfo_chart(cash_flow_df, ticker)
        
        report_content = []
        
        # Defining markers for splitting (No changes needed)
        markers = {
            "rev_profit": "1. Revenue and Profitability Analysis",
            "balance_sheet": "2. Balance Sheet Analysis",
            "cash_flow": "3. Cash Flow Analysis",
            "summary": "4. Overall Summary"
        }
        
        text_rev_profit = safe_extract_section(analysis_result_text, "### " + markers['rev_profit'], "### " + markers['balance_sheet'])
        text_balance_sheet = safe_extract_section(analysis_result_text, "### " + markers['balance_sheet'], "### " + markers['cash_flow'])
        text_cash_flow = safe_extract_section(analysis_result_text, "### " + markers['cash_flow'], "### " + markers['summary'])
        text_summary = safe_extract_section(analysis_result_text, "### " + markers['summary'])
        
        def remove_first_line(text):
            return text.split('\n', 1)[1] if '\n' in text else text

        # Report generation logic (No changes needed here)
        if text_rev_profit:
            opm_marker = "**Operating Profit Margin (OPM) Trend:**"
            text_to_process = remove_first_line(text_rev_profit)
            if "Operating Profit Margin (OPM) Trend:" in text_to_process:
                part1, part2 = text_to_process.split("Operating Profit Margin (OPM) Trend:", 1)
                report_content.append({"type": "text", "content": "**" + markers['rev_profit'] + "**"})
                if chart1_sales_profit: report_content.append({"type": "chart", "content": chart1_sales_profit})
                report_content.append({"type": "text", "content": part1.strip()})
                report_content.append({"type": "text", "content": opm_marker})
                if chart4_opm: report_content.append({"type": "chart", "content": chart4_opm})
                report_content.append({"type": "text", "content": part2.strip()})
            else:
                report_content.append({"type": "text", "content": "**" + markers['rev_profit'] + "**"})
                if chart1_sales_profit: report_content.append({"type": "chart", "content": chart1_sales_profit})
                report_content.append({"type": "text", "content": text_to_process})

        if text_balance_sheet:
            reserves_marker = "**Trend in 'Reserves':**"
            text_to_process = remove_first_line(text_balance_sheet)
            if "Trend in 'Reserves':" in text_to_process:
                part1, part2 = text_to_process.split("Trend in 'Reserves':", 1)
                report_content.append({"type": "text", "content": "**" + markers['balance_sheet'] + "**"})
                if chart2_borrowings: report_content.append({"type": "chart", "content": chart2_borrowings})
                report_content.append({"type": "text", "content": part1.strip()})
                report_content.append({"type": "text", "content": reserves_marker})
                if chart5_reserves: report_content.append({"type": "chart", "content": chart5_reserves})
                report_content.append({"type": "text", "content": part2.strip()})
            else:
                report_content.append({"type": "text", "content": "**" + markers['balance_sheet'] + "**"})
                if chart2_borrowings: report_content.append({"type": "chart", "content": chart2_borrowings})
                report_content.append({"type": "text", "content": text_to_process})

        if text_cash_flow:
            cfo_vs_np_marker = "**Comparison of 'Cash from Operating Activity' to 'Net Profit' (Annual):**"
            cumulative_marker = "**Cumulative 'Cash from Operating Activity' vs. 'Net Profit':**"
            text_to_process = remove_first_line(text_cash_flow)
            report_content.append({"type": "text", "content": "**" + markers['cash_flow'] + "**"})
            if chart6_cfo: report_content.append({"type": "chart", "content": chart6_cfo})
            if "Comparison of 'Cash from Operating Activity' to 'Net Profit' (Annual):" in text_to_process:
                part1, remainder = text_to_process.split("Comparison of 'Cash from Operating Activity' to 'Net Profit' (Annual):", 1)
                report_content.append({"type": "text", "content": part1.strip()})
                report_content.append({"type": "text", "content": cfo_vs_np_marker})
                if chart3_cf_vs_profit: report_content.append({"type": "chart", "content": chart3_cf_vs_profit})
                if "Cumulative 'Cash from Operating Activity' vs. 'Net Profit':" in remainder:
                    part2, part3 = remainder.split("Cumulative 'Cash from Operating Activity' vs. 'Net Profit':", 1)
                    report_content.append({"type": "text", "content": part2.strip()})
                    report_content.append({"type": "text", "content": cumulative_marker})
                    report_content.append({"type": "text", "content": part3.strip()})
                else: report_content.append({"type": "text", "content": remainder.strip()})
            else: report_content.append({"type": "text", "content": text_to_process})
        
        if text_summary: report_content.append({"type": "text", "content": text_summary})
        if not report_content: return [{"type": "text", "content": analysis_result_text}]
        print("--- Finished Quantitative Analysis ---")
        return report_content
        
    except Exception as e:
        return [{"type": "text", "content": f"An unexpected error in quantitative_agent: {e.__class__.__name__} {e}"}]