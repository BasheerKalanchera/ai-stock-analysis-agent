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
            return new_files[0]
        time.sleep(1)
    return None

def download_financial_data(ticker: str, email: str, password: str, download_path: str):
    """
    Downloads Excel and the two most recent Concall Transcripts.
    Also scrapes and returns the company name.

    Returns:
        A tuple (company_name, excel_path, pdf_path, latest_transcript_path, previous_transcript_path).
    """
    chrome_options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": download_path,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    # chrome_options.add_argument("--headless") # Keep this commented out for debugging if needed
    chrome_options.add_argument("--window-size=1920,1080")
    driver = None

    company_name = None
    final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path = None, None, None, None

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20)

        print("Logging into Screener.in...")
        driver.get("https://www.screener.in/login/")
        wait.until(EC.presence_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.presence_of_element_located((By.ID, "id_password"))).send_keys(password)
        wait.until(EC.presence_of_element_located((By.XPATH, "//button[@type='submit']"))).click()
        time.sleep(3)
        print("Login successful.")

        try:
            print("Navigating to the main company page...")
            if ticker.isdigit():
                company_url = f"https://www.screener.in/company/{ticker}/"
            else:
                company_url = f"https://www.screener.in/company/{ticker}/consolidated/"

            driver.get(company_url)

            print("Waiting for company dashboard to load...")
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            print("Dashboard loaded.")

            try:
                company_name_xpath = "//h1[contains(@class, 'margin-0')]"
                company_name_element = driver.find_element(By.XPATH, company_name_xpath)
                company_name = company_name_element.text.strip()
                print(f"SUCCESS: Scraped company name: {company_name}")
            except Exception as e:
                print(f"ERROR: Could not scrape company name after page load. Reason: {e}")
                company_name = ticker

            try:
                print("Expanding columns to show maximum data...")
                columns_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'COLUMNS')]")))
                columns_button.click()
                max_columns_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'options-body')]//button[text()='12']")))
                max_columns_button.click()
                time.sleep(3)
                print("Columns expanded successfully.")
            except Exception as e:
                print(f"INFO: Could not expand columns, downloading with default view. Reason: {e}")

            files_before = os.listdir(download_path)
            
            # --- FIX #1: ROBUST BUTTON CLICKING LOGIC ---
            # Use a case-insensitive XPath to handle text variations ("Export to Excel" vs "EXPORT TO EXCEL")
            export_button_xpath = "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]"
            
            # Wait for the button to be present in the HTML
            print("Locating the 'Export to Excel' button...")
            export_button = wait.until(EC.presence_of_element_located((By.XPATH, export_button_xpath)))

            # Click using JavaScript to bypass potential overlays (e.g., side menus)
            print("Initiating Excel download via JavaScript click...")
            driver.execute_script("arguments[0].click();", export_button)
            time.sleep(3)
            
            new_filename = wait_for_new_file(download_path, files_before)
            if new_filename:
                # --- FIX #2: SAFE FILE RENAME LOGIC ---
                # This logic prevents accidentally deleting the downloaded file on case-insensitive
                # systems like Windows when the downloaded filename only differs by case.
                source_path = os.path.join(download_path, new_filename)
                final_excel_path = os.path.join(download_path, f"{ticker}.xlsx")

                if os.path.exists(final_excel_path) and os.path.normcase(source_path) != os.path.normcase(final_excel_path):
                    os.remove(final_excel_path)

                os.rename(source_path, final_excel_path)
                print(f"SUCCESS: Excel file saved to: {final_excel_path}")
            else:
                print("ERROR: Excel download timed out.")
        except Exception as e:
            print(f"ERROR: Could not navigate to company page or download Excel. Reason: {e}")

        try:
            print("\nNavigating to the Documents page...")
            wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Documents"))).click()
            time.sleep(2)

            transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
            transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))

            if transcript_elems:
                files_before = os.listdir(download_path)
                driver.execute_script("arguments[0].click();", transcript_elems[0])
                print("Initiating Latest Concall Transcript download...")
                new_filename = wait_for_new_file(download_path, files_before)
                if new_filename:
                    _, extension = os.path.splitext(new_filename)
                    final_latest_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Latest{extension}")
                    if os.path.exists(final_latest_transcript_path): os.remove(final_latest_transcript_path)
                    os.rename(os.path.join(download_path, new_filename), final_latest_transcript_path)
                    print(f"SUCCESS: Latest Concall Transcript saved to: {final_latest_transcript_path}")

                if len(transcript_elems) > 1:
                    time.sleep(2)
                    transcript_elems = driver.find_elements(By.XPATH, transcripts_xpath)
                    files_before = os.listdir(download_path)
                    driver.execute_script("arguments[0].click();", transcript_elems[1])
                    print("Initiating Previous Concall Transcript download...")
                    new_filename = wait_for_new_file(download_path, files_before)
                    if new_filename:
                        _, extension = os.path.splitext(new_filename)
                        final_previous_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Previous{extension}")
                        if os.path.exists(final_previous_transcript_path): os.remove(final_previous_transcript_path)
                        os.rename(os.path.join(download_path, new_filename), final_previous_transcript_path)
                        print(f"SUCCESS: Previous Concall Transcript saved to: {final_previous_transcript_path}")
        except Exception as e:
            print(f"INFO: Concall Transcript(s) not found or an error occurred. Skipping. Reason: {e}")

        return company_name, final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path

    finally:
        if driver:
            driver.quit()
        print("\nBrowser closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download financial data from Screener.in for a given stock ticker.")
    parser.add_argument("ticker", type=str, help="The stock ticker symbol (e.g., DOMS, 543963).")
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
        company, excel_path, _, latest_transcript, previous_transcript = download_financial_data(
            args.ticker, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY
        )

        print("\n--- Download Summary ---")
        print(f"Company Name: {company or 'FAILED'}")
        print(f"Excel Report: {excel_path or 'FAILED'}")
        print(f"Latest Transcript: {latest_transcript or 'FAILED / NOT FOUND'}")
        print(f"Previous Transcript: {previous_transcript or 'FAILED / NOT FOUND'}")
        print("------------------------")