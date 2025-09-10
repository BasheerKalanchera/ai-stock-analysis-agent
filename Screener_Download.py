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
from urllib.parse import urlparse

def wait_for_new_file(download_path: str, files_before: list, timeout: int = 60) -> str | None:
    """Waits for a new file to appear in the download directory."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files_after = os.listdir(download_path)
        new_files = [f for f in files_after if f not in files_before and not f.endswith('.crdownload')]
        if new_files:
            return new_files[0]
        time.sleep(1)
    return None

def download_financial_data(ticker: str, email: str, password: str, download_path: str, is_consolidated: bool = False):
    """
    Downloads Excel and the two most recent Concall Transcripts.
    Also scrapes and returns the company name.
    """
    chrome_options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": download_path,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    # **NOTE**: Headless mode is disabled for debugging. 
    # To run in the background, remove the '#' from the line below.
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--start-maximized")
    driver = None

    company_name = None
    final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path = None, None, None, None

    try:
        print("Initializing Chrome Driver...")
        service = ChromeService(executable_path=ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20)

        print("Logging into Screener.in...")
        driver.get("https://www.screener.in/login/")
        wait.until(EC.visibility_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.visibility_of_element_located((By.ID, "id_password"))).send_keys(password)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))).click()
        time.sleep(3) # A short pause to ensure the login session is fully established.
        print("Login successful.")

        # --- MODIFIED: Robustly handle consolidated vs. standalone URLs ---
        if is_consolidated:
            print(f"Attempting to navigate to the consolidated page for {ticker}...")
            company_url = f"https://www.screener.in/company/{ticker}/consolidated/"
            driver.get(company_url)
            
            # Check if the URL still contains the consolidated path after navigation.
            # Screener.in often redirects to the standalone page if consolidated data isn't available.
            if "/consolidated/" not in driver.current_url:
                print("Consolidated page not found. Falling back to Standalone data.")
                company_url = f"https://www.screener.in/company/{ticker}/"
                driver.get(company_url)
            else:
                print("Successfully navigated to the consolidated page.")
        else:
            print(f"Navigating to the standalone page for {ticker}...")
            company_url = f"https://www.screener.in/company/{ticker}/"
            driver.get(company_url)
        # --- END MODIFIED ---

        print("Waiting for company dashboard to load...")
        wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
        print("Dashboard loaded.")

        company_name_element = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]")))
        company_name = company_name_element.text.strip()
        print(f"SUCCESS: Scraped company name: {company_name}")
        
        files_before = os.listdir(download_path)
        export_button_xpath = "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]"
        
        # NEW FAST CODE
        print("Locating and clicking the 'Export to Excel' button...")
        # 1. Wait for the button to simply be present in the page's HTML. This is much faster.
        export_button = wait.until(EC.presence_of_element_located((By.XPATH, export_button_xpath)))

        # 2. Use a brief, targeted pause to ensure any button-enabling JS has run.
        time.sleep(1) 

        # 3. Use the robust JavaScript click, which works even if the button is slightly obscured.
        driver.execute_script("arguments[0].click();", export_button)
        
        # --- FIX FOR INTERMITTENT CORRUPTED FILES ---
        # Add a definitive pause AFTER clicking the download button. This gives the
        # browser enough time to fully receive the file from the server before
        # our script starts looking for it in the download folder, preventing a race condition.
        print("Waiting for 3 seconds for the download to complete...")
        time.sleep(3)
        # --- END OF FIX ---

        new_filename = wait_for_new_file(download_path, files_before)
        if new_filename:
            source_path = os.path.join(download_path, new_filename)
            final_excel_path = os.path.join(download_path, f"{ticker}.xlsx")
            if os.path.exists(final_excel_path): os.remove(final_excel_path)
            os.rename(source_path, final_excel_path)
            print(f"SUCCESS: Excel file saved to: {final_excel_path}")
        else:
            print("ERROR: Excel download timed out.")

        print("\nNavigating to the Documents page...")
        wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Documents"))).click()
        
        transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
        transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))

        if transcript_elems:
            # Download latest transcript
            files_before = os.listdir(download_path)
            driver.execute_script("arguments[0].click();", transcript_elems[0])
            print("Initiating Latest Concall Transcript download and Waiting for 2 seconds for the download to complete...")
            time.sleep(2)
            new_filename = wait_for_new_file(download_path, files_before)
            if new_filename:
                _, ext = os.path.splitext(new_filename)
                final_latest_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Latest{ext}")
                if os.path.exists(final_latest_transcript_path): os.remove(final_latest_transcript_path)
                os.rename(os.path.join(download_path, new_filename), final_latest_transcript_path)
                print(f"SUCCESS: Latest Concall Transcript saved to: {final_latest_transcript_path}")

            # Download previous transcript
            if len(transcript_elems) > 1:
                time.sleep(2) # Give browser a moment before next click
                files_before = os.listdir(download_path)
                transcript_elems = driver.find_elements(By.XPATH, transcripts_xpath) # Re-find to avoid stale element
                driver.execute_script("arguments[0].click();", transcript_elems[1])
                print("Initiating Previous Concall Transcript download and Waiting for 2 seconds for the download to complete...")
                time.sleep(2)
                new_filename = wait_for_new_file(download_path, files_before)
                if new_filename:
                    _, ext = os.path.splitext(new_filename)
                    final_previous_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Previous{ext}")
                    if os.path.exists(final_previous_transcript_path): os.remove(final_previous_transcript_path)
                    os.rename(os.path.join(download_path, new_filename), final_previous_transcript_path)
                    print(f"SUCCESS: Previous Concall Transcript saved to: {final_previous_transcript_path}")

    except Exception as e:
        print(f"An error occurred during the download process: {e}")
    finally:
        if driver:
            driver.quit()
        print("\nBrowser closed.")

    return company_name, final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path
