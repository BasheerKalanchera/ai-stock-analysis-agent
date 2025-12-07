import io
import os
import shutil
import time
from typing import Dict, Optional, Tuple, Any
import logging
import pandas as pd
import requests
import platform

# --- IMPORTS ---
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, SessionNotCreatedException, StaleElementReferenceException

# --- LOGGER ---
logger = logging.getLogger('screener_download')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - ⚪ DOWNLOAD - %(message)s')
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)
logger.propagate = False

def wait_for_new_file(download_path: str, files_before: list, timeout: int = 60) -> str | None:
    start_time = time.time()
    while time.time() - start_time < timeout:
        files_after = os.listdir(download_path)
        new_files = [f for f in files_after if f not in files_before and not f.endswith(('.crdownload', '.tmp')) and not f.startswith('.')]
        if new_files:
            return new_files[0]
        time.sleep(1)
    return None

def scrape_peers_data(driver) -> pd.DataFrame:
    try:
        logger.info("Attempting to scrape Peers table...")
        wait = WebDriverWait(driver, 10)
        target_id = "peers-table-placeholder"
        try:
            container = wait.until(EC.presence_of_element_located((By.ID, target_id)))
            driver.execute_script("arguments[0].scrollIntoView();", container)
        except TimeoutException:
            container = wait.until(EC.presence_of_element_located((By.ID, "peers")))
            driver.execute_script("arguments[0].scrollIntoView();", container)

        table_selector = f"#{target_id} table"
        table_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, table_selector)))
        
        html = table_element.get_attribute('outerHTML')
        dfs = pd.read_html(io.StringIO(html))
        
        if dfs:
            peer_df = dfs[0]
            if "S.No." in peer_df.columns: peer_df = peer_df.drop(columns=["S.No."])
            peer_df = peer_df.loc[:, ~peer_df.columns.str.contains('^Unnamed', case=False)]
            logger.info(f"✅ SUCCESS: Scraped Peer Data Table ({len(peer_df)} rows).")
            return peer_df
    except Exception as e:
        logger.warning(f"Could not scrape Peers table: {e}")
        return pd.DataFrame()
    return pd.DataFrame()

def download_financial_data(ticker: str, config: dict, is_consolidated: bool = False) -> Tuple[Optional[str], Dict[str, Any], pd.DataFrame]:
    email = config["SCREENER_EMAIL"]
    password = config["SCREENER_PASSWORD"]
    
    logger.info("Starting financial data download process...")
    
    options = uc.ChromeOptions()
    temp_download_dir = os.path.join(os.getcwd(), "temp_downloads")
    os.makedirs(temp_download_dir, exist_ok=True)

    prefs = {
        "download.default_directory": temp_download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        # --- NEW SETTINGS TO FORCE PDF DOWNLOAD ---
        "plugins.always_open_pdf_externally": True,
        "pdfjs.disabled": True,
        "plugins.plugins_list": [{"enabled": False, "name": "Chrome PDF Viewer"}],
        "download.extensions_to_open": "applications/pdf"
    }
    options.add_experimental_option("prefs", prefs)

    # --- CLOUD / LINUX COMPATIBILITY FIX ---
    # Check if running on Streamlit Cloud (Linux) or Local
    if platform.system() == "Linux":
        logger.info("Detected Linux environment (likely Streamlit Cloud). Setting up Headless Chromium...")
        options.binary_location = "/usr/bin/chromium" # Default path on Streamlit Cloud
        options.add_argument("--headless=new") 
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
    else:
        # Local (Windows/Mac) settings
        options.add_argument("--headless=new") 
        options.add_argument("--window-size=1920,1080")

    driver = None
    company_name = None
    file_buffers = {}
    peer_data = pd.DataFrame()

    try:
        logger.info("Initializing Chrome Driver...")
        
        # --- ROBUST DRIVER INITIALIZATION ---
        # On Cloud, we do NOT use version_main because we can't control the installed chromium version.
        try:
            driver = uc.Chrome(options=options, use_subprocess=True)
        except Exception as e:
            logger.warning(f"Standard uc.Chrome failed: {e}. Trying without subprocess...")
            try:
                driver = uc.Chrome(options=options)
            except Exception as e2:
                # FALLBACK: If undetected-chromedriver fails entirely on cloud, 
                # you might need to swap to standard Selenium here.
                logger.error(f"Critical Driver Error: {e2}")
                raise e2

        wait = WebDriverWait(driver, 20)

        # 1. LOGIN
        driver.get("https://www.screener.in/login/")
        wait.until(EC.visibility_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.visibility_of_element_located((By.ID, "id_password"))).send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search for a company']")))
        logger.info("Login successful.")

        # 2. NAVIGATE
        url = f"https://www.screener.in/company/{ticker}/{'consolidated/' if is_consolidated else ''}"
        driver.get(url)
        
        session = requests.Session()
        session.headers.update({"User-Agent": driver.execute_script("return navigator.userAgent;"), "Referer": url})
        for cookie in driver.get_cookies(): session.cookies.set(cookie['name'], cookie['value'])

        try:
            # --- EXCEL ---
            logger.info("Downloading Excel...")
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            company_name = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]"))).text.strip()

            files_before = os.listdir(temp_download_dir)
            
            # Helper function to attempt click
            def click_excel_button(d):
                try:
                    # Method 1: Button with specific span
                    d.find_element(By.XPATH, "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]").click()
                    return True
                except:
                    try:
                        # Method 2: Link with text
                        excel_link = d.find_element(By.XPATH, "//a[contains(text(), 'Export to Excel')]").get_attribute('href')
                        d.get(excel_link)
                        return True
                    except:
                        return False

            # 1. Attempt Download on Current Page (Consolidated or Standalone)
            success = click_excel_button(driver)

            # 2. Fallback Logic: If failed AND we are on Consolidated, try Standalone
            if not success and is_consolidated:
                logger.warning("   ⚠️ Consolidated Excel not found/clickable. Falling back to Standalone...")
                try:
                    # Navigate to Standalone URL
                    driver.get(f"https://www.screener.in/company/{ticker}/")
                    wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
                    
                    # Retry Download
                    if click_excel_button(driver):
                        logger.info("   ✅ Standalone Excel click successful.")
                    else:
                        logger.error("   ❌ Standalone Excel also failed.")
                except Exception as e:
                    logger.error(f"   ❌ Fallback navigation failed: {e}")

            # 3. Wait for file to appear
            new_filename = wait_for_new_file(temp_download_dir, files_before)
            if new_filename:
                with open(os.path.join(temp_download_dir, new_filename), 'rb') as f:
                    file_buffers['excel'] = io.BytesIO(f.read())
                logger.info(f"✅ Excel Downloaded: {new_filename}")
            else:
                logger.warning("❌ Excel file did not appear in download folder.")

            if company_name: peer_data = scrape_peers_data(driver)

            # --- PPT SEARCH (FIXED) ---
            logger.info("Scanning for Investor Presentation (PPT)...")
            driver.get(f"https://www.screener.in/company/{ticker}/#documents")
            
            ppt_url = None
            # Updated XPaths based on your screenshot
            ppt_xpaths = [
                "//a[contains(@class, 'concall-link') and contains(text(), 'PPT')]",  # Specific class match
                "//ul[contains(@class, 'list-links')]//a[contains(text(), 'PPT')]",   # Hierarchy match
                "//div[contains(@class, 'documents')]//a[contains(text(), 'PPT')]"    # Loose container match
            ]

            for xpath in ppt_xpaths:
                try:
                    ppt_elements = driver.find_elements(By.XPATH, xpath)
                    if ppt_elements:
                        ppt_url = ppt_elements[0].get_attribute('href')
                        logger.info(f"   > Found PPT via XPath: {xpath}")
                        break
                except: continue

            if ppt_url:
                # --- FIX: CREATE CLEAN HEADERS FOR DOWNLOAD ---
                # 1. Copy current session headers (which have the User-Agent)
                download_headers = session.headers.copy()
                
                # 2. REMOVE the 'Referer' header. 
                # This tells the server "I pasted this URL directly," bypassing hotlink blocking.
                if 'Referer' in download_headers:
                    del download_headers['Referer']

                # 3. ADD standard browser 'Accept' headers.
                # NSE and Corporate sites often reject requests without these.
                download_headers.update({
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1"
                })

                try:
                    logger.info("   > Downloading PPT (with sanitized headers)...")
                    # (Your existing requests code here...)
                    r = requests.get(ppt_url, headers=download_headers, stream=True, timeout=45)
                    r.raise_for_status()
                    file_buffers['investor_presentation'] = io.BytesIO(r.content)
                    logger.info(f"     ✅ PPT Downloaded via Requests ({len(r.content)/1024/1024:.2f} MB)")
                    
                except Exception as req_e:
                    logger.warning(f"     ⚠️ Requests failed ({req_e}). Retrying via Selenium...")
                    
                    try:
                        files_before_ppt = os.listdir(temp_download_dir)
                        
                        # Trigger navigation
                        driver.get(ppt_url)
                        
                        # Wait up to 90 seconds for the file to appear
                        ppt_filename = wait_for_new_file(temp_download_dir, files_before_ppt, timeout=90)
                        
                        if ppt_filename:
                            with open(os.path.join(temp_download_dir, ppt_filename), 'rb') as f:
                                file_buffers['investor_presentation'] = io.BytesIO(f.read())
                            logger.info(f"     ✅ PPT Downloaded via Selenium: {ppt_filename}")
                        else:
                            # --- THIS IS THE MISSING ERROR LOG ---
                            logger.error("     ❌ Selenium Timeout: PDF did not download within 90s (likely opened in viewer).")
                        
                        # Cleanup: Go back to prevent getting stuck on the PDF URL
                        try:
                             driver.back()
                        except: pass
                            
                    except Exception as e: 
                        logger.error(f"     ❌ Selenium Critical Error: {e}")
            else:
                logger.info("   > No PPT link found.")

            # --- CREDIT RATINGS LOGIC ---
            logger.info("Checking for Credit Ratings...")
            try:
                header_xpath = "//h3[contains(text(), 'Credit ratings')]"
                try:
                    wait.until(EC.presence_of_element_located((By.XPATH, header_xpath)))
                except TimeoutException:
                    logger.warning("   > 'Credit ratings' header not found within timeout.")

                rating_links = driver.find_elements(By.XPATH, "//h3[contains(text(), 'Credit ratings')]/..//li//a")
                
                if not rating_links:
                    logger.info("   > Header lookup failed. Trying Agency Keyword Search...")
                    rating_links = driver.find_elements(By.XPATH, "//section[@id='documents']//a[contains(text(), 'CRISIL') or contains(text(), 'ICRA') or contains(text(), 'CARE') or contains(text(), 'India Ratings')]")

                if rating_links:
                    latest_rating = rating_links[0] 
                    rating_url = latest_rating.get_attribute('href')
                    rating_text = latest_rating.text
                    logger.info(f"Found Rating Link: {rating_text}")

                    if rating_url.lower().endswith('.pdf'):
                        logger.info("   > Rating is a PDF. Downloading stream...")
                        try:
                            r = session.get(rating_url, stream=True, timeout=15)
                            r.raise_for_status()
                            file_buffers['credit_rating_doc'] = io.BytesIO(r.content)
                            file_buffers['credit_rating_type'] = 'pdf'
                            logger.info("     ✅ Rating PDF Downloaded.")
                        except Exception as e:
                            logger.error(f"Failed to download rating PDF: {e}")
                    else:
                        logger.info("   > Rating is a Webpage. Detecting agency...")
                        
                        # --- ICRA SPECIAL HANDLING ---
                        if "icra.in" in rating_url:
                            logger.info("   > Detected ICRA Page. Attempting to click 'Download' button...")
                            files_before_rating = os.listdir(temp_download_dir)
                            driver.get(rating_url)
                            try:
                                # Wait for the specific Download Button ID found in screenshot
                                download_btn = wait.until(EC.element_to_be_clickable((By.ID, "DownloadRatingReport")))
                                download_btn.click()
                                
                                # Wait for PDF to download
                                rating_filename = wait_for_new_file(temp_download_dir, files_before_rating, timeout=20)
                                if rating_filename:
                                    with open(os.path.join(temp_download_dir, rating_filename), 'rb') as f:
                                        file_buffers['credit_rating_doc'] = io.BytesIO(f.read())
                                    file_buffers['credit_rating_type'] = 'pdf'
                                    logger.info(f"     ✅ ICRA PDF Downloaded: {rating_filename}")
                                else:
                                    logger.warning("     ❌ ICRA Download Clicked but no file received.")
                                driver.back()
                            except Exception as icra_e:
                                logger.warning(f"     ⚠️ ICRA Download Failed: {icra_e}")
                                driver.back()
                        else:
                            # --- GENERIC WEBPAGE SCRAPE (CRISIL/Others) ---
                            driver.get(rating_url)
                            time.sleep(2) 
                            try:
                                page_text = driver.find_element(By.TAG_NAME, 'body').text
                                file_buffers['credit_rating_doc'] = page_text
                                file_buffers['credit_rating_type'] = 'html'
                                logger.info(f"     ✅ Rating Text Scraped ({len(page_text)} chars).")
                                driver.back() 
                            except Exception as e:
                                logger.error(f"Failed to scrape rating page: {e}")
                else:
                    logger.info("   > No Credit Rating links found.")

            except Exception as e:
                logger.warning(f"Error processing Credit Ratings: {e}")

            # --- TRANSCRIPTS LOGIC ---
            logger.info("Scanning for Concall Transcripts...")
            try:
                transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(),'Transcript')]"
                transcript_elements = driver.find_elements(By.XPATH, transcripts_xpath)
                
                transcript_urls = []
                for elem in transcript_elements:
                    try:
                        transcript_urls.append(elem.get_attribute('href'))
                    except StaleElementReferenceException:
                        continue
                
                logger.info(f"Found {len(transcript_urls)} transcript links. Downloading latest 2...")

                successful_downloads = 0
                for i, pdf_url in enumerate(transcript_urls):
                    if successful_downloads >= 2: break
                    if not pdf_url: continue

                    logger.info(f"   > Downloading Transcript #{i+1}...")
                    
                    try:
                        response = session.get(pdf_url, stream=True, timeout=15)
                        response.raise_for_status()
                        
                        if 'application/pdf' in response.headers.get('Content-Type', ''):
                            pdf_buffer = io.BytesIO(response.content)
                            key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                            file_buffers[key] = pdf_buffer
                            logger.info(f"     ✅ Success via Requests (Size: {len(response.content)/1024:.2f} KB)")
                            successful_downloads += 1
                            continue 
                    except Exception as req_e:
                        logger.warning(f"     ⚠️ Requests failed ({req_e}). Retrying via Selenium...")

                    try:
                        files_before_pdf = os.listdir(temp_download_dir)
                        driver.get(pdf_url)
                        pdf_filename = wait_for_new_file(temp_download_dir, files_before_pdf, timeout=15)
                        
                        if pdf_filename:
                            with open(os.path.join(temp_download_dir, pdf_filename), 'rb') as f:
                                pdf_buffer = io.BytesIO(f.read())
                            key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                            file_buffers[key] = pdf_buffer
                            logger.info(f"     ✅ Success via Selenium Fallback: {pdf_filename}")
                            successful_downloads += 1
                            driver.back() 
                        else:
                            logger.warning("     ❌ Failed via Selenium too.")
                            driver.back()
                    except Exception as e:
                         logger.warning(f"     ⚠️ Selenium download error: {e}")

            except Exception as e:
                logger.warning(f"Error processing Transcripts: {e}")
            
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