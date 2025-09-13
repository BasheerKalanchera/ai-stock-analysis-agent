# Screener_Download.py
import io 
from typing import Tuple, Dict, Optional
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

#Modified function to return file buffers instead of file paths
#
#Changed return type to Tuple[Optional[str], Dict[str, io.BytesIO]]
#Created temporary download directory that gets cleaned up
#Store files in BytesIO buffers instead of saving to disk
#Removed file path parameters and returns
#Added cleanup of temporary files
#Returns a dictionary of file buffers with keys:
#'excel': Excel financial data
#'latest_transcript': Most recent concall transcript
#'previous_transcript': Previous concall transcript
# The function now works without persistent storage, making it suitable for Streamlit Cloud deployment.
    

def download_financial_data(
    ticker: str, 
    email: str, 
    password: str, 
    is_consolidated: bool = False
) -> Tuple[Optional[str], Dict[str, io.BytesIO]]:
    """
    Downloads financial data and returns it in memory.
    Returns: Tuple of (company_name, dict of file buffers)
    """
    chrome_options = webdriver.ChromeOptions()
    # Create a temporary download directory
    temp_download_dir = os.path.join(os.getcwd(), "temp_downloads")
    os.makedirs(temp_download_dir, exist_ok=True)
    
    prefs = {
        "download.default_directory": temp_download_dir,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = None
    company_name = None
    file_buffers = {}

    try:
        print("Initializing Chrome Driver...")
        service = ChromeService(executable_path=ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
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
            print("Attempting to download from the current page...")
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
                with open(excel_path, 'rb') as f:
                    excel_buffer = io.BytesIO(f.read())
                file_buffers['excel'] = excel_buffer
                os.remove(excel_path)  # Clean up temp file

            # Download Transcripts
            print("\nNavigating to Documents page...")
            driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
            transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
            
            transcript_elems = wait.until(EC.presence_of_all_elements_located((By.XPATH, transcripts_xpath)))
            print(f"Found {len(transcript_elems)} transcript links.")

            for i, _ in enumerate(transcript_elems[:2]):  # Get only first two transcripts
                files_before = os.listdir(temp_download_dir)
                current_transcript_link = driver.find_elements(By.XPATH, transcripts_xpath)[i]
                driver.execute_script("arguments[0].click();", current_transcript_link)
                
                new_filename = wait_for_new_file(temp_download_dir, files_before, timeout=20)
                if new_filename:
                    transcript_path = os.path.join(temp_download_dir, new_filename)
                    with open(transcript_path, 'rb') as f:
                        transcript_buffer = io.BytesIO(f.read())
                    
                    key = 'latest_transcript' if i == 0 else 'previous_transcript'
                    file_buffers[key] = transcript_buffer
                    os.remove(transcript_path)  # Clean up temp file
                    
                    driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
                    wait.until(EC.visibility_of_element_located((By.XPATH, "//h2[normalize-space()='Documents']")))

        except TimeoutException as te:
            print(f"Timeout occurred: {te}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if driver:
            driver.quit()
        # Clean up temp directory
        if os.path.exists(temp_download_dir):
            for file in os.listdir(temp_download_dir):
                os.remove(os.path.join(temp_download_dir, file))
            os.rmdir(temp_download_dir)
        print("\nBrowser closed and temp files cleaned up.")

    return company_name, file_buffers