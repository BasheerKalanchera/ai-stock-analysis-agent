# Screener_Download.py
import io
import os
import shutil
import time
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# webdriver-manager is only needed for local development
from webdriver_manager.chrome import ChromeDriverManager


def wait_for_new_file(download_path: str, files_before: list, timeout: int = 60) -> str | None:
    """Waits for a new file to appear in the download directory."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files_after = os.listdir(download_path)
        # Ignore temporary download files
        new_files = [f for f in files_after if f not in files_before and not f.endswith(('.crdownload', '.tmp'))]
        if new_files:
            print(f"  > SUCCESS: Downloading '{new_files[0]}'.")
            return new_files[0]
        time.sleep(1)
    return None


def download_financial_data(
    ticker: str,
    email: str,
    password: str,
    is_consolidated: bool = False
) -> Tuple[Optional[str], Dict[str, io.BytesIO]]:
    """
    Downloads financial data and returns it in memory.
    This function is environment-aware and works both locally and in Streamlit Cloud.
    Returns: Tuple of (company_name, dict of file buffers)
    """
    chrome_options = webdriver.ChromeOptions()
    
    temp_download_dir = os.path.join(os.getcwd(), "temp_downloads")
    os.makedirs(temp_download_dir, exist_ok=True)

    prefs = {
        "download.default_directory": temp_download_dir,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver = None
    company_name = None
    file_buffers = {}

    try:
        # --- DYNAMIC DRIVER INITIALIZATION ---
        if os.environ.get("STREAMLIT_SERVER_RUNNING_IN_CLOUD") == "true":
            print("Initializing Chrome Driver for Streamlit Cloud...")
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            # Set a common user agent to appear as a regular browser
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
            # Set a window size for headless mode
            chrome_options.add_argument("--window-size=1920,1080")
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            print("Initializing Chrome Driver for local machine...")
            # Add arguments for a better local debugging experience
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
            service = Service(executable_path=ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
        # --- END DYNAMIC INITIALIZATION ---

        wait = WebDriverWait(driver, 20)

        # Login process
        print("Logging into Screener.in...")
        driver.get("https://www.screener.in/login/")
        wait.until(EC.visibility_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.visibility_of_element_located((By.ID, "id_password"))).send_keys(password)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))).click()
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search for a company']")))
        print("Login successful.")

        # Navigate to company page
        url = f"https://www.screener.in/company/{ticker}/{'consolidated/' if is_consolidated else ''}"
        driver.get(url)

        try:
            # Download Excel
            print("Attempting to download Excel file...")
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            company_name_element = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]")))
            company_name = company_name_element.text.strip()

            files_before = os.listdir(temp_download_dir)
            export_button_xpath = "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]"
            export_button = wait.until(EC.element_to_be_clickable((By.XPATH, export_button_xpath)))
            driver.execute_script("arguments[0].click();", export_button)
            
            # Wait for download and store in memory
            new_filename = wait_for_new_file(temp_download_dir, files_before)
            if new_filename:
                excel_path = os.path.join(temp_download_dir, new_filename)
                time.sleep(1)
                with open(excel_path, 'rb') as f:
                    excel_buffer = io.BytesIO(f.read())
                file_buffers['excel'] = excel_buffer

            # Download Transcripts
            print("\nNavigating to Documents page...")
            driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
            transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"

            transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))
            # Initialize a counter specifically for this loop's downloads.
            successful_downloads = 0

            print(f"Found {len(transcript_elems)} transcript links. Attempting to download two valid ones.")

            for i in range(len(transcript_elems)):
                if successful_downloads == 2:
                    print("Successfully downloaded two transcripts. Stopping.")
                    break
                try:
                    current_transcript_link = driver.find_elements(By.XPATH, transcripts_xpath)[i]
                    files_before = os.listdir(temp_download_dir)
                    driver.execute_script("arguments[0].click();", current_transcript_link)

                    new_filename = wait_for_new_file(temp_download_dir, files_before, timeout=20)
                    if new_filename:
                        print(f"Success: Downloaded transcript from link #{i+1}.")
                        transcript_path = os.path.join(temp_download_dir, new_filename)
                        time.sleep(1)
                        with open(transcript_path, 'rb') as f:
                            transcript_buffer = io.BytesIO(f.read())
                        key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                        file_buffers[key] = transcript_buffer
                        successful_downloads += 1
                except Exception as e:
                    print(f"Error processing link #{i+1}: {e}. Trying next link.")
                    pass # Continue to the navigation part
                
                if successful_downloads < 2 and (i + 1) < len(transcript_elems):
                    driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
                    wait.until(EC.visibility_of_element_located((By.XPATH, "//h2[normalize-space()='Documents']")))

            # Final status update
            print(f"Loop finished. Total new transcripts downloaded: {successful_downloads}.")

        except TimeoutException as te:
            print(f"Timeout occurred on main page: {te}")

    except Exception as e:
        print(f"A critical error occurred: {e}")
    finally:
        if driver:
            driver.quit()
        if os.path.exists(temp_download_dir):
            shutil.rmtree(temp_download_dir, ignore_errors=True)
        print("\nBrowser closed and temp files cleaned up.")

    return company_name, file_buffers

