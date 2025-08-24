import os
import time
import argparse
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def wait_for_new_file(download_path: str, files_before: list, timeout: int = 30) -> str | None:
    """Waits for a new file to appear in the download directory."""
    for _ in range(timeout):
        files_after = os.listdir(download_path)
        new_files = [f for f in files_after if f not in files_before and not f.endswith('.crdownload')]
        if new_files:
            return new_files[0] # Return the first new file found
        time.sleep(1)
    return None

def download_financial_data(ticker: str, email: str, password: str, download_path: str):
    """
    Downloads Excel and the two most recent Concall Transcripts.
    The Annual Report download has been disabled.
    
    Returns:
        A tuple (excel_path, pdf_path, latest_transcript_path, previous_transcript_path).
        pdf_path will be None. Other paths will be None if a download failed.
    """
    chrome_options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": download_path,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    # Comment out the next line to see the browser in action
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--window-size=1920,1080")
    driver = None
    
    final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path = None, None, None, None

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20)
        
        # Login
        print("Logging into Screener.in...")
        driver.get("https://www.screener.in/login/")
        wait.until(EC.presence_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.presence_of_element_located((By.ID, "id_password"))).send_keys(password)
        wait.until(EC.presence_of_element_located((By.XPATH, "//button[@type='submit']"))).click()
        time.sleep(3)
        print("Login successful.")

        # --- 1. Download Excel File ---
        try:
            print("Navigating to the main company page for Excel download...")
            company_url = f"https://www.screener.in/company/{ticker}/consolidated/"
            driver.get(company_url)
            
            files_before = os.listdir(download_path)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(), 'Export to Excel')]]"))).click()
            print("Initiating Excel download...")
            
            new_filename = wait_for_new_file(download_path, files_before)
            if new_filename:
                final_excel_path = os.path.join(download_path, f"{ticker}.xlsx")
                if os.path.exists(final_excel_path): os.remove(final_excel_path)
                os.rename(os.path.join(download_path, new_filename), final_excel_path)
                print(f"SUCCESS: Excel file saved to: {final_excel_path}")
            else:
                print("ERROR: Excel download timed out.")
        except Exception as e:
            print(f"ERROR: Could not download the Excel report. Skipping. Reason: {e}")

        # --- 2. Download Documents (Transcripts) ---
        print("\nNavigating to the Documents page...")
        wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Documents"))).click()
        time.sleep(2) # Allow documents section to load

        # --- Download Annual Report PDF (DISABLED) ---
        # try:
        #     files_before = os.listdir(download_path)
        #     wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Annual reports']/following-sibling::div[1]//a[1]"))).click()
        #     print("Initiating Annual Report PDF download...")
            
        #     new_filename = wait_for_new_file(download_path, files_before)
        #     if new_filename:
        #         final_pdf_path = os.path.join(download_path, f"{ticker}_Annual_Report.pdf")
        #         if os.path.exists(final_pdf_path): os.remove(final_pdf_path)
        #         os.rename(os.path.join(download_path, new_filename), final_pdf_path)
        #         print(f"SUCCESS: Annual Report saved to: {final_pdf_path}")
        #     else:
        #         print("ERROR: Annual Report download timed out.")
        # except Exception as e:
        #     print(f"INFO: Annual Report download skipped as requested. Reason: {e}")
            
        # --- Download Concall Transcripts ---
        try:
            # Find ALL transcript links under the "Concalls" section
            transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
            transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))
    
            if not transcript_elems:
                print("INFO: No concall transcripts found.")
            else:
                # --- Download Latest transcript (first one) ---
                files_before = os.listdir(download_path)
                transcript_elems[0].click()
                print("Initiating Latest Concall Transcript download...")
                new_filename = wait_for_new_file(download_path, files_before)
                if new_filename:
                    _, extension = os.path.splitext(new_filename)
                    final_latest_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Latest{extension}")
                    if os.path.exists(final_latest_transcript_path): os.remove(final_latest_transcript_path)
                    os.rename(os.path.join(download_path, new_filename), final_latest_transcript_path)
                    print(f"SUCCESS: Latest Concall Transcript saved to: {final_latest_transcript_path}")
                else:
                    print("ERROR: Latest Concall Transcript download timed out.")

                # --- Download Previous transcript (second one, if available) ---
                if len(transcript_elems) > 1:
                    transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))
                    files_before = os.listdir(download_path)
                    transcript_elems[1].click()
                    print("Initiating Previous Concall Transcript download...")
                    new_filename = wait_for_new_file(download_path, files_before)
                    if new_filename:
                        _, extension = os.path.splitext(new_filename)
                        final_previous_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Previous{extension}")
                        if os.path.exists(final_previous_transcript_path): os.remove(final_previous_transcript_path)
                        os.rename(os.path.join(download_path, new_filename), final_previous_transcript_path)
                        print(f"SUCCESS: Previous Concall Transcript saved to: {final_previous_transcript_path}")
                    else:
                        print("ERROR: Previous Concall Transcript download timed out.")
        except Exception as e:
            print(f"INFO: Concall Transcript(s) not found or an error occurred. Skipping. Reason: {e}")

        return final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path

    finally:
        if driver:
            driver.quit()
        print("\nBrowser closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download financial data from Screener.in for a given stock ticker.")
    parser.add_argument("ticker", type=str, help="The stock ticker symbol (e.g., DOMS, RELIANCE).")
    args = parser.parse_args()

    load_dotenv()
    SCREENER_EMAIL = os.getenv("SCREENER_EMAIL")
    SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")

    if not SCREENER_EMAIL or not SCREENER_PASSWORD:
        print("Error: Make sure SCREENER_EMAIL and SCREENER_PASSWORD are set in your .env file.")
    else:
        DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")
        if not os.path.exists(DOWNLOAD_DIRECTORY):
            os.makedirs(DOWNLOAD_DIRECTORY)

        print(f"--- Starting Download for Ticker: {args.ticker} ---")
        excel_path, pdf_path, latest_transcript, previous_transcript = download_financial_data(
            args.ticker, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY
        )

        print("\n--- Download Summary ---")
        print(f"Excel Report: {excel_path or 'FAILED'}")
        print(f"Annual Report: SKIPPED")
        print(f"Latest Transcript: {latest_transcript or 'FAILED / NOT FOUND'}")
        print(f"Previous Transcript: {previous_transcript or 'FAILED / NOT FOUND'}")
        print("------------------------")
