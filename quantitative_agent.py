import pandas as pd
import os
import warnings

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

def read_financial_statements(excel_path: str):
    """
    Reads financial statements and supplemental information from the 'Data Sheet' of an Excel file.
    This version is adapted for the specific structure of the provided 'CUPID.xlsx' file.
    """
    try:
        print(f"Reading Excel file from: {excel_path}")

        # Read the 'Data Sheet' to get the full data.
        df = pd.read_excel(excel_path, sheet_name='Data Sheet', header=None)

        # Find all 'Report Date' rows. The first is for annual, the second for quarterly.
        report_date_indices = df[df.iloc[:, 0].astype(str).str.contains('Report Date', na=False)].index
        if len(report_date_indices) < 2:
            print("Error: Could not find both annual and quarterly 'Report Date' rows.")
            return

        annual_headers_row_index = report_date_indices[0]
        quarterly_headers_row_index = report_date_indices[1]

        # Extract and format headers.
        annual_headers = format_headers(df.iloc[annual_headers_row_index, :].tolist())
        quarterly_headers = format_headers(df.iloc[quarterly_headers_row_index, :].tolist())

        # Find the start and end rows for each financial statement section.
        pnl_start_row = df[df.iloc[:, 0].astype(str).str.contains('PROFIT & LOSS', na=False)].index[0]
        balance_sheet_start_row = df[df.iloc[:, 0].astype(str).str.contains('BALANCE SHEET', na=False)].index[0]
        cash_flow_start_row = df[df.iloc[:, 0].astype(str).str.contains('CASH FLOW', na=False)].index[0]
        price_row_index = df[df.iloc[:, 0].astype(str).str.contains('PRICE:', na=False)].index[0]

        # Extract the dataframes for each statement with corrected slicing.
        # Annual P&L: between 'PROFIT & LOSS' and the quarterly headers row.
        annual_pnl_df = df.iloc[pnl_start_row + 2 : quarterly_headers_row_index, :].copy()
        # Quarterly P&L: between the quarterly headers row and the 'BALANCE SHEET' header.
        quarterly_pnl_df = df.iloc[quarterly_headers_row_index + 1 : balance_sheet_start_row - 1, :].copy()
        # Balance Sheet: between 'BALANCE SHEET' and 'CASH FLOW' headers.
        balance_sheet_df = df.iloc[balance_sheet_start_row + 2 : cash_flow_start_row - 1, :].copy()
        # Cash Flow: between 'CASH FLOW' and 'PRICE:' headers.
        cash_flow_df = df.iloc[cash_flow_start_row + 2 : price_row_index, :].copy()
        # Supplemental Info: from 'PRICE:' to the end.
        supplemental_df = df.iloc[price_row_index:, :].copy()

        # Apply the corrected headers to the extracted dataframes.
        annual_pnl_df.columns = annual_headers[:len(annual_pnl_df.columns)]
        quarterly_pnl_df.columns = quarterly_headers[:len(quarterly_pnl_df.columns)]
        balance_sheet_df.columns = annual_headers[:len(balance_sheet_df.columns)]
        cash_flow_df.columns = annual_headers[:len(cash_flow_df.columns)]
        supplemental_df.columns = annual_headers[:len(supplemental_df.columns)]

        # Set 'Narration' as the index.
        annual_pnl_df.set_index('Narration', inplace=True)
        quarterly_pnl_df.set_index('Narration', inplace=True)
        balance_sheet_df.set_index('Narration', inplace=True)
        cash_flow_df.set_index('Narration', inplace=True)
        supplemental_df.set_index('Narration', inplace=True)

        # Clean and print the dataframes.
        def clean_and_print(df, name):
            print(f"\n--- {name} ---")
            df.dropna(how='all', inplace=True)
            # Use ffill to fill NaN values in the index.
            df.index = df.index.to_series().ffill()
            print(df.to_string())

        print("\n" + "="*50)
        print("PARSED FINANCIAL STATEMENTS")
        print("="*50)

        clean_and_print(annual_pnl_df, "ANNUAL PROFIT & LOSS")
        clean_and_print(quarterly_pnl_df, "QUARTERLY PROFIT & LOSS")
        clean_and_print(balance_sheet_df, "BALANCE SHEET")
        clean_and_print(cash_flow_df, "CASH FLOW")
        clean_and_print(supplemental_df, "SUPPLEMENTAL INFORMATION")

    except FileNotFoundError:
        print(f"Error: The file was not found at {excel_path}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

# The main execution block
if __name__ == "__main__":
    # Get the directory of the script and construct the file path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "downloads", "CUPID.xlsx")
    read_financial_statements(file_path)