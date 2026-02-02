import io
import os
import shutil
import time
from typing import Dict, Optional, Tuple, Any
import logging
import pandas as pd
import requests
import platform
import base64 

# --- IMPORTS ---
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, SessionNotCreatedException, StaleElementReferenceException

# --- LOGGER ---
logger = logging.getLogger('screener_download')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - ⚪ DOWNLOAD - %(message)s')
    handler.setFormatter(formatter)
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

def download_financial_data(
    ticker: str, 
    config: dict, 
    is_consolidated: bool = False,
    # --- New Flags for Phase 0.5 ---
    need_excel: bool = True,
    need_transcripts: bool = True,
    need_ppt: bool = True,
    need_credit_report: bool = True,
    need_peers: bool = True,
    # --- New Flag for SEBI MVP ---
    metadata_only: bool = False
) -> Tuple[Optional[str], Dict[str, Any], pd.DataFrame]:
    
    email = config["SCREENER_EMAIL"]
    password = config["SCREENER_PASSWORD"]
    
    logger.info(f"Starting download for {ticker} | Metadata Only={metadata_only}...")
    
    temp_download_dir = os.path.join(os.getcwd(), "temp_downloads")
    os.makedirs(temp_download_dir, exist_ok=True)

    # ... (Rest of chrome options logic remains identical) ...
    def get_chrome_options():
        opts = uc.ChromeOptions()
        prefs = {
            "download.default_directory": temp_download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "plugins.always_open_pdf_externally": True,
            "pdfjs.disabled": True,
            "plugins.plugins_list": [{"enabled": False, "name": "Chrome PDF Viewer"}],
            "download.extensions_to_open": "applications/pdf"
        }
        opts.add_experimental_option("prefs", prefs)

        if platform.system() == "Linux":
            opts.binary_location = "/usr/bin/chromium"
            opts.add_argument("--headless=new") 
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1920,1080")
        else:
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--headless=new") 
        
        return opts

    driver = None
    company_name = None
    file_buffers = {}
    peer_data = pd.DataFrame()

    try:
        logger.info("Initializing Chrome Driver...")
        target_version = 144  # Match Chrome version on Streamlit Cloud

        try:
            options = get_chrome_options()
            driver = uc.Chrome(options=options, use_subprocess=True, version_main=target_version)
            driver.execute_cdp_cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": temp_download_dir})
        except Exception as e:
            logger.warning(f"Standard uc.Chrome failed: {e}. Trying without subprocess...")
            try:
                retry_options = get_chrome_options()
                driver = uc.Chrome(options=retry_options, version_main=target_version)
            except Exception as e2:
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
        
        # --- SANITIZE USER AGENT ---
        raw_ua = driver.execute_script("return navigator.userAgent;")
        clean_ua = raw_ua.replace("HeadlessChrome", "Chrome") 
        
        session = requests.Session()
        session.headers.update({
            "User-Agent": clean_ua, 
            "Referer": url,
            "Accept-Language": "en-US,en;q=0.9",
        })
        for cookie in driver.get_cookies(): 
            session.cookies.set(cookie['name'], cookie['value'])
        # -----------------------------------

        try:
            # --- ALWAYS FETCH COMPANY NAME ---
            wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
            company_name = wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(@class, 'margin-0')]"))).text.strip()
            logger.info(f"✅ Company Identified: {company_name}")

            # --- SEBI MVP SHORT CIRCUIT ---
            if metadata_only:
                logger.info("🛑 Metadata Only Mode: Skipping heavy downloads.")
                driver.quit()
                return company_name, {}, pd.DataFrame()
            # ----------------------------

            # --- EXCEL ---
            if need_excel:
               # ... (Original Excel logic) ...
               pass 
            # (Rest of the function continues as is for full download logic)

            if need_excel:
                logger.info("Downloading Excel...")
                files_before = os.listdir(temp_download_dir)
                
                def click_excel_button(d):
                    try:
                        d.find_element(By.XPATH, "//button[.//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'export to excel')]]").click()
                        return True
                    except:
                        try:
                            excel_link = d.find_element(By.XPATH, "//a[contains(text(), 'Export to Excel')]").get_attribute('href')
                            d.get(excel_link)
                            return True
                        except: return False

                success = click_excel_button(driver)

                if not success and is_consolidated:
                    logger.warning("   ⚠️ Consolidated Excel not found/clickable. Falling back to Standalone...")
                    try:
                        driver.get(f"https://www.screener.in/company/{ticker}/")
                        wait.until(EC.presence_of_element_located((By.ID, "top-ratios")))
                        if click_excel_button(driver): logger.info("   ✅ Standalone Excel click successful.")
                    except Exception as e: logger.error(f"   ❌ Fallback navigation failed: {e}")

                new_filename = wait_for_new_file(temp_download_dir, files_before)
                if new_filename:
                    with open(os.path.join(temp_download_dir, new_filename), 'rb') as f:
                        file_buffers['excel'] = io.BytesIO(f.read())
                    logger.info(f"✅ Excel Downloaded: {new_filename}")
                else: logger.warning("❌ Excel file did not appear in download folder.")
            else:
                logger.info("⏭️ Skipped Excel.")

            # --- PEERS ---
            if need_peers and company_name:
                peer_data = scrape_peers_data(driver)
            else:
                logger.info("⏭️ Skipped Peers.")

            # --- PPT SEARCH ---
            if need_ppt:
                # ... (Original PPT Logic) ...
                logger.info("Scanning for Investor Presentation (PPT)...")
                # Ensure we are on the documents tab/hash if needed, though usually one page
                driver.get(f"https://www.screener.in/company/{ticker}/#documents")
                
                ppt_url = None
                ppt_xpaths = [
                    "//a[contains(@class, 'concall-link') and contains(text(), 'PPT')]",
                    "//ul[contains(@class, 'list-links')]//a[contains(text(), 'PPT')]",
                    "//div[contains(@class, 'documents')]//a[contains(text(), 'PPT')]"
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
                    download_headers = session.headers.copy()
                    if 'Referer' in download_headers: del download_headers['Referer']
                    download_headers.update({
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Upgrade-Insecure-Requests": "1"
                    })

                    try:
                        logger.info("   > Attempting download via Requests...")
                        r = session.get(ppt_url, headers=download_headers, stream=True, timeout=15)
                        r.raise_for_status()
                        file_buffers['investor_presentation'] = io.BytesIO(r.content)
                        logger.info(f"     ✅ PPT Downloaded via Requests ({len(r.content)/1024/1024:.2f} MB)")

                    except Exception as req_e:
                        logger.warning(f"     ⚠️ Requests blocked/timed out. Switching to 'Natural Click'...")

                        try:
                            files_before_ppt = os.listdir(temp_download_dir)
                            xpath = ppt_xpaths[0]
                            link_element = driver.find_element(By.XPATH, xpath)
                            driver.execute_script("arguments[0].removeAttribute('target');", link_element)
                            driver.execute_script("arguments[0].click();", link_element)
                            
                            ppt_filename = wait_for_new_file(temp_download_dir, files_before_ppt, timeout=60)
                            
                            if ppt_filename:
                                full_path = os.path.join(temp_download_dir, ppt_filename)
                                with open(full_path, 'rb') as f:
                                    file_buffers['investor_presentation'] = io.BytesIO(f.read())
                                logger.info(f"     ✅ PPT Downloaded to Disk: {ppt_filename}")
                                if driver.current_url != url: driver.back()
                            else:
                                logger.warning("     ⚠️ File not found on disk. Checking if browser is viewing the PDF...")
                                if getattr(driver, 'current_url', '').lower().endswith('.pdf'):
                                    logger.info("     > Browser is displaying PDF! Extracting data via JavaScript...")
                                    # --- JS INJECTION FALLBACK ---
                                    js_grab_pdf = """
                                        var uri = window.location.href;
                                        var callback = arguments[arguments.length - 1];
                                        fetch(uri, {credentials: 'include'})
                                            .then(resp => {
                                                if (!resp.ok) throw new Error('Network response was not ok');
                                                return resp.arrayBuffer();
                                            })
                                            .then(buffer => {
                                                var binary = '';
                                                var bytes = new Uint8Array(buffer);
                                                var len = bytes.byteLength;
                                                for (var i = 0; i < len; i++) {
                                                    binary += String.fromCharCode(bytes[i]);
                                                }
                                                callback(window.btoa(binary));
                                            })
                                            .catch(err => callback('ERROR: ' + err));
                                    """
                                    try:
                                        result_b64 = driver.execute_async_script(js_grab_pdf)
                                        if result_b64 and not result_b64.startswith('ERROR'):
                                            pdf_bytes = base64.b64decode(result_b64)
                                            file_buffers['investor_presentation'] = io.BytesIO(pdf_bytes)
                                            logger.info(f"     ✅ PPT Extracted via JS Injection ({len(pdf_bytes)/1024/1024:.2f} MB)")
                                        else:
                                            logger.error(f"     ❌ JS Extraction Failed: {result_b64}")
                                    except Exception as js_e:
                                        logger.error(f"     ❌ JS Extraction Crashed: {js_e}")
                                    driver.back()
                                else:
                                    logger.error(f"     ❌ Selenium Failed. Not on PDF URL.")
                                    if driver.current_url != url: driver.back()

                        except Exception as e: 
                            logger.error(f"     ❌ Selenium Critical Error: {e}")
                            if driver.current_url != url: driver.back()
                else:
                    logger.info("   > No PPT link found.")
            else:
                logger.info("⏭️ Skipped PPT.")

            # --- CREDIT RATINGS ---
            if need_credit_report:
                 # ... (Original Credit Logic) ...
                logger.info("Checking for Credit Ratings...")
                try:
                    if "documents" not in driver.current_url:
                         driver.get(f"https://www.screener.in/company/{ticker}/#documents")

                    header_xpath = "//h3[contains(text(), 'Credit ratings')]"
                    try:
                        wait.until(EC.presence_of_element_located((By.XPATH, header_xpath)))
                    except TimeoutException: pass

                    rating_links = driver.find_elements(By.XPATH, "//h3[contains(text(), 'Credit ratings')]/..//li//a")
                    if not rating_links:
                        rating_links = driver.find_elements(By.XPATH, "//section[@id='documents']//a[contains(text(), 'CRISIL') or contains(text(), 'ICRA') or contains(text(), 'CARE') or contains(text(), 'India Ratings')]")

                    if rating_links:
                        latest_rating = rating_links[0] 
                        rating_url = latest_rating.get_attribute('href')
                        
                        if rating_url.lower().endswith('.pdf'):
                            try:
                                r = session.get(rating_url, stream=True, timeout=15)
                                r.raise_for_status()
                                file_buffers['credit_rating_doc'] = io.BytesIO(r.content)
                                file_buffers['credit_rating_type'] = 'pdf'
                                logger.info("     ✅ Rating PDF Downloaded.")
                            except: pass
                        else:
                            if "icra.in" in rating_url:
                                files_before_rating = os.listdir(temp_download_dir)
                                driver.get(rating_url)
                                try:
                                    download_btn = wait.until(EC.element_to_be_clickable((By.ID, "DownloadRatingReport")))
                                    download_btn.click()
                                    rating_filename = wait_for_new_file(temp_download_dir, files_before_rating, timeout=20)
                                    if rating_filename:
                                        with open(os.path.join(temp_download_dir, rating_filename), 'rb') as f:
                                            file_buffers['credit_rating_doc'] = io.BytesIO(f.read())
                                        file_buffers['credit_rating_type'] = 'pdf'
                                        logger.info(f"     ✅ ICRA PDF Downloaded: {rating_filename}")
                                    driver.back()
                                except: driver.back()
                            else:
                                driver.get(rating_url)
                                time.sleep(2) 
                                try:
                                    page_text = driver.find_element(By.TAG_NAME, 'body').text
                                    file_buffers['credit_rating_doc'] = page_text
                                    file_buffers['credit_rating_type'] = 'html'
                                    logger.info(f"     ✅ Rating Text Scraped ({len(page_text)} chars).")
                                    driver.back() 
                                except: pass
                    else:
                        logger.info("   > No Credit Rating links found.")
                except Exception as e:
                    logger.warning(f"Error processing Credit Ratings: {e}")
            else:
                logger.info("⏭️ Skipped Credit Ratings.")

            # --- TRANSCRIPTS ---
            if need_transcripts:
                # ... (Original Transcript Logic) ...
                logger.info("Scanning for Concall Transcripts...")
                try:
                    if "documents" not in driver.current_url:
                        driver.get(f"https://www.screener.in/company/{ticker}/#documents")

                    transcripts_xpath = "//h3[normalize-space()='Concalls']/following::a[contains(@class, 'concall-link') and contains(text(), 'Transcript')]"
                    transcript_elements = driver.find_elements(By.XPATH, transcripts_xpath)
                    
                    transcript_urls = [elem.get_attribute('href') for elem in transcript_elements if elem]
                    
                    successful_downloads = 0
                    for i, pdf_url in enumerate(transcript_urls):
                        if successful_downloads >= 2: break
                        if not pdf_url: continue

                        try:
                            response = session.get(pdf_url, stream=True, timeout=15)
                            response.raise_for_status()
                            if 'application/pdf' in response.headers.get('Content-Type', ''):
                                key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                                file_buffers[key] = io.BytesIO(response.content)
                                successful_downloads += 1
                                continue 
                        except: pass

                        try:
                            files_before_pdf = os.listdir(temp_download_dir)
                            driver.get(pdf_url)
                            pdf_filename = wait_for_new_file(temp_download_dir, files_before_pdf, timeout=15)
                            if pdf_filename:
                                with open(os.path.join(temp_download_dir, pdf_filename), 'rb') as f:
                                    key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                                    file_buffers[key] = io.BytesIO(f.read())
                                successful_downloads += 1
                                driver.back() 
                            else:
                                driver.back()
                        except: pass

                except Exception as e:
                    logger.warning(f"Error processing Transcripts: {e}")
            else:
                logger.info("⏭️ Skipped Transcripts.")
            
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