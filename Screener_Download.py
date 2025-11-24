import io
import os
import shutil
import time
from typing import Dict, Optional, Tuple
import logging
import pandas as pd
import requests

# --- UPDATED IMPORTS ---
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, InvalidSelectorException

# --- CUSTOM LOGGER SETUP ---
logger = logging.getLogger('screener_download')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
# Using ⚪ (White Circle) for the Downloader Agent
formatter = logging.Formatter('%(asctime)s - ⚪ DOWNLOAD - %(message)s')
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False
# ---------------------------

def wait_for_new_file(download_path: str, files_before: list, timeout: int = 60) -> str | None:
    """Waits for a new file to appear in the download directory."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files_after = os.listdir(download_path)
        new_files = [f for f in files_after if f not in files_before and not f.endswith(('.crdownload', '.tmp')) and not f.startswith('.')]
        if new_files:
            logger.info(f"  > SUCCESS: Downloading '{new_files[0]}'.")
            return new_files[0]
        time.sleep(1)
    return None

def scrape_peers_data(driver) -> pd.DataFrame:
    """Scrapes the Peers table from the Screener page."""
    try:
        logger.info("Attempting to scrape Peers table...")
        
        wait = WebDriverWait(driver, 10)
        target_id = "peers-table-placeholder"
        
        try:
            # 1. Scroll to the placeholder
            container = wait.until(EC.presence_of_element_located((By.ID, target_id)))
            driver.execute_script("arguments[0].scrollIntoView();", container)
        except TimeoutException:
            logger.info(f"#{target_id} not found, falling back to generic #peers section...")
            container = wait.until(EC.presence_of_element_located((By.ID, "peers")))
            driver.execute_script("arguments[0].scrollIntoView();", container)

        # 2. Find the table
        table_selector = f"#{target_id} table"
        table_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, table_selector)))
        
        # 3. Extract and Parse
        html = table_element.get_attribute('outerHTML')
        
        # Wrap html string in StringIO to suppress FutureWarning
        dfs = pd.read_html(io.StringIO(html))
        
        if dfs:
            peer_df = dfs[0]
            
            # Cleanup
            if "S.No." in peer_df.columns:
                peer_df = peer_df.drop(columns=["S.No."])
            peer_df = peer_df.loc[:, ~peer_df.columns.str.contains('^Unnamed', case=False)]
            #peer_df = peer_df.fillna("")
            
            # --- LOGGING SUCCESS ---
            logger.info(f"✅ SUCCESS: Scraped Peer Data Table ({len(peer_df)} rows found).")
            return peer_df
            
    except Exception as e:
        logger.warning(f"Could not scrape Peers table: {e}")
        if "lxml" in str(e):
            logger.error("HINT: You are missing the 'lxml' library. Run: pip install lxml")
        return pd.DataFrame()
    
    return pd.DataFrame()

def download_financial_data(
    ticker: str,
    config: dict,
    is_consolidated: bool = False
) -> Tuple[Optional[str], Dict[str, io.BytesIO], pd.DataFrame]:
    """
    Downloads financial data using Hybrid Method (Selenium for Login + Requests for Files).
    """
    email = config["SCREENER_EMAIL"]
    password = config["SCREENER_PASSWORD"]
    
    logger.info("Starting financial data download process (Stealth Mode)...")
    
    options = uc.ChromeOptions()
    temp_download_dir = os.path.join(os.getcwd(), "temp_downloads")
    os.makedirs(temp_download_dir, exist_ok=True)

    # Basic Prefs (We rely less on these now, but good to keep for Excel)
    prefs = {
        "download.default_directory": temp_download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--headless=new") 
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = None
    company_name = None
    file_buffers = {}
    peer_data = pd.DataFrame()

    try:
        logger.info("Initializing Undetected Chrome Driver...")
        driver = uc.Chrome(options=options, use_subprocess=True)
        wait = WebDriverWait(driver, 20)

        # 1. LOGIN
        logger.info("Logging into Screener.in...")
        driver.get("https://www.screener.in/login/")
        time.sleep(2)
        
        wait.until(EC.visibility_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.visibility_of_element_located((By.ID, "id_password"))).send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search for a company']")))
        logger.info("Login successful.")

        # 2. PREPARE REQUESTS SESSION (Cookie Handoff)
        # This allows us to download files directly without using the browser's download manager
        session = requests.Session()
        # Transfer user-agent to avoid detection
        selenium_user_agent = driver.execute_script("return navigator.userAgent;")
        session.headers.update({"User-Agent": selenium_user_agent})
        # Transfer cookies
        for cookie in driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])

        # 3. NAVIGATE TO COMPANY
        url = f"https://www.screener.in/company/{ticker}/{'consolidated/' if is_consolidated else ''}"
        driver.get(url)

        try:
            # --- EXCEL DOWNLOAD (Keep using Selenium for this as it's a dynamic button) ---
            logger.info("Attempting to download Excel file...")
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            company_name = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]"))).text.strip()

            files_before = os.listdir(temp_download_dir)
            export_xpath = "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]"
            
            try:
                 driver.find_element(By.XPATH, export_xpath).click()
            except:
                 # Fallback to link if button fails
                 export_link = driver.find_element(By.XPATH, "//a[contains(text(), 'Export to Excel')]")
                 driver.get(export_link.get_attribute('href'))

            new_filename = wait_for_new_file(temp_download_dir, files_before)
            if new_filename:
                with open(os.path.join(temp_download_dir, new_filename), 'rb') as f:
                    file_buffers['excel'] = io.BytesIO(f.read())
                logger.info(f"✅ Excel Downloaded: {new_filename}")

            # --- SCRAPE PEERS ---
            if company_name:
                 peer_data = scrape_peers_data(driver)

            # --- TRANSCRIPT DOWNLOADS (Using Requests) ---
            logger.info("Navigating to Documents for Transcripts...")
            driver.get(f"https://www.screener.in/company/{ticker}/#documents/")
            transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
            
            transcript_links = driver.find_elements(By.XPATH, transcripts_xpath)
            logger.info(f"Found {len(transcript_links)} transcript links. Downloading latest 2 directly...")

            successful_downloads = 0
            for i, link_elem in enumerate(transcript_links):
                if successful_downloads >= 2: break
                
                try:
                    pdf_url = link_elem.get_attribute('href')
                    logger.info(f"   > Downloading Transcript #{i+1} via Requests...")
                    
                    # DIRECT DOWNLOAD (No browser waiting)
                    response = session.get(pdf_url, stream=True)
                    
                    if response.status_code == 200 and 'application/pdf' in response.headers.get('Content-Type', ''):
                        pdf_buffer = io.BytesIO(response.content)
                        key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                        file_buffers[key] = pdf_buffer
                        logger.info(f"     ✅ Success (Size: {len(response.content)/1024:.2f} KB)")
                        successful_downloads += 1
                    else:
                        logger.warning(f"     ❌ Failed: Status {response.status_code} or not a PDF")

                except Exception as e:
                    logger.warning(f"     ⚠️ Error downloading PDF: {e}")

        except TimeoutException as te:
            logger.warning(f"Timeout on company page: {te}")

    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
    finally:
        if driver:
            try:
                driver.quit()
            except OSError:
                pass
        if os.path.exists(temp_download_dir):
            shutil.rmtree(temp_download_dir, ignore_errors=True)
        logger.info("Cleanup complete.")

    return company_name, file_buffers, peer_data