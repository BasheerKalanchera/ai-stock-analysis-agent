# Screener_Download.py
import os
import time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException

def wait_for_new_file(download_path: str, files_before: list, timeout: int = 60) -> str | None:
    """Waits for a new file to appear in the download directory."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files_after = os.listdir(download_path)
        # --- THE FIX: Ignore both .crdownload and .tmp files ---
        new_files = [f for f in files_after if f not in files_before and not f.endswith(('.crdownload', '.tmp'))]
        if new_files:
            print(f"  > SUCCESS: Downloading '{new_files[0]}'.")
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
    # Re-enable headless mode for deployment, comment out for local debugging
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
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
        # Correctly finds the search bar by its placeholder text instead of ID
        # wait.until(EC.visibility_of_element_located((By.ID, "search-input")))
        #wait.until(EC.visibility_of_element_located((By.XPATH, "//input[@placeholder='Search for a company']")))
        # Correctly waits for the element to be present in the HTML
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search for a company']")))
        print("Login successful.")

        if is_consolidated:
            driver.get(f"https://www.screener.in/company/{ticker}/consolidated/")
        else:
            driver.get(f"https://www.screener.in/company/{ticker}/")

        try:
            print("Attempting to download from the current page...")
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            company_name_element = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]")))
            company_name = company_name_element.text.strip()
            
            files_before = os.listdir(download_path)
            export_button_xpath = "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]"
            
            export_button = wait.until(EC.element_to_be_clickable((By.XPATH, export_button_xpath)))
            driver.execute_script("arguments[0].click();", export_button)
            print("SUCCESS: 'Export to Excel' button clicked.")

        except TimeoutException:
            print("WARNING: 'Export to Excel' button not found on the initial page.")
            print(f"Falling back to the standalone page for {ticker} and retrying...")
            driver.get(f"https://www.screener.in/company/{ticker}/")
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            company_name_element = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]")))
            company_name = company_name_element.text.strip()
            files_before = os.listdir(download_path)
            export_button_xpath = "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]"
            export_button = wait.until(EC.element_to_be_clickable((By.XPATH, export_button_xpath)))
            driver.execute_script("arguments[0].click();", export_button)
            print("SUCCESS: 'Export to Excel' button clicked on standalone page.")
        # --- END OF CHANGE 2 ---

        new_filename = wait_for_new_file(download_path, files_before)
        if new_filename:
            source_path = os.path.join(download_path, new_filename)
            final_excel_path = os.path.join(download_path, f"{ticker}.xlsx")
            if os.path.exists(final_excel_path): os.remove(final_excel_path)
            os.rename(source_path, final_excel_path)
            print(f"SUCCESS: Excel file saved to: {final_excel_path}")
        else:
            print("ERROR: Excel download timed out.")

        # --- NEW ROBUST TRANSCRIPT DOWNLOAD LOGIC ---
        print("\nNavigating to the Documents page to find transcripts...")
        driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
        
        transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
        
        try:
            transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))
            print(f"Found {len(transcript_elems)} transcript links. Attempting to download the two most recent valid ones.")

            for i in range(len(transcript_elems)):
                if final_latest_transcript_path and final_previous_transcript_path:
                    break

                print(f"Attempting download from transcript link #{i+1}...")
                files_before = os.listdir(download_path)
                
                # Re-find elements each time to prevent stale element errors
                current_transcript_link = driver.find_elements(By.XPATH, transcripts_xpath)[i]
                driver.execute_script("arguments[0].click();", current_transcript_link)
                
                new_filename = wait_for_new_file(download_path, files_before, timeout=20)

                if new_filename:
                    # print(f"  > SUCCESS: Downloading '{new_filename}'.")
                    _, ext = os.path.splitext(new_filename)
                    
                    # --- THE FIX: ADD A PAUSE AFTER A SUCCESSFUL DOWNLOAD ---
                    # print("Pausing for 2 seconds to ensure file is downloaded fully")

                    # time.sleep(2)
                    if not final_latest_transcript_path:
                        final_latest_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Latest{ext}")
                        if os.path.exists(final_latest_transcript_path): os.remove(final_latest_transcript_path)
                        os.rename(os.path.join(download_path, new_filename), final_latest_transcript_path)
                        print(f"  > Saved as: {final_latest_transcript_path}")
                    elif not final_previous_transcript_path:
                        final_previous_transcript_path = os.path.join(download_path, f"{ticker}_Concall_Transcript_Previous{ext}")
                        if os.path.exists(final_previous_transcript_path): os.remove(final_previous_transcript_path)
                        os.rename(os.path.join(download_path, new_filename), final_previous_transcript_path)
                        print(f"  > Saved as: {final_previous_transcript_path}")
                    
                    
                    # Navigate back to the documents page to continue the loop
                    driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
                    # Wait for the 'Documents' heading to be visible to confirm the page is ready
                    wait.until(EC.visibility_of_element_located((By.XPATH, "//h2[normalize-space()='Documents']")))
                else:
                    print(f"  > WARNING: Download failed for link #{i+1}. It might be a broken link. Trying next one.")
                    # If the link was broken, the browser is on an error page. Go back.
                    driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
                    # Wait for the 'Documents' heading to be visible to confirm the page is ready
                    wait.until(EC.visibility_of_element_located((By.XPATH, "//h2[normalize-space()='Documents']")))

        except TimeoutException:
            print("WARNING: No concall transcript links were found on the Documents page.")
        # --- END OF NEW LOGIC ---

    except Exception as e:
        print(f"An error occurred during the download process: {e}")
    finally:
        if driver:
            driver.quit()
        print("\nBrowser closed.")

    return company_name, final_excel_path, final_pdf_path, final_latest_transcript_path, final_previous_transcript_path