import time
import random
import pandas as pd
import io
import logging
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Configure Logger
logger = logging.getLogger('screener_handler')
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - 🚜 HARVESTER - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class ScreenerHandler:
    def __init__(self):
        # 1. SETUP OPTIONS
        self.options = uc.ChromeOptions()
        self.options.add_argument("--window-size=1920,1080")
        self.options.add_argument("--no-sandbox")
        self.options.add_argument("--disable-dev-shm-usage")
        
        my_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.options.add_argument(f'--user-agent={my_user_agent}')
        
        # Uncomment to run invisible
        self.options.add_argument("--headless=new")

    def _login(self, driver, email, password):
        """Performs login to ensure custom columns are visible."""
        try:
            logger.info("🔐 Logging in to access custom columns...")
            driver.get("https://www.screener.in/login/")
            wait = WebDriverWait(driver, 15)
            wait.until(EC.visibility_of_element_located((By.ID, "id_username"))).send_keys(email)
            wait.until(EC.visibility_of_element_located((By.ID, "id_password"))).send_keys(password)
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search for a company']")))
            logger.info("✅ Login Successful.")
            return True
        except Exception as e:
            logger.error(f"❌ Login Failed: {e}")
            return False

    def _clean_numeric(self, value):
        if isinstance(value, (int, float)): return float(value)
        if not isinstance(value, str): return 0.0
        value = value.strip()
        if value in ['-', '', 'Nan', 'NaN']: return 0.0
        clean_val = value.replace(',', '').replace('%', '').replace('Cr', '').strip()
        try:
            return float(clean_val)
        except ValueError:
            return 0.0

    def fetch_wrapper_data(self, start_url, email=None, password=None):
        """
        Harvests data and Maps Names to Ticker IDs robustly.
        """
        driver = None
        all_dfs = []
        page_num = 1
        
        logger.info(f"Starting Harvest: {start_url}")
        
        try:
            driver = uc.Chrome(options=self.options, use_subprocess=True, version_main=142)
            wait = WebDriverWait(driver, 20)
            
            if email and password:
                if not self._login(driver, email, password):
                    return pd.DataFrame(), "Login Failed."

            driver.get(start_url)
            time.sleep(3)

            # --- HEADER EXTRACTION ---
            try:
                header_element = driver.find_element(By.TAG_NAME, "h1")
                screen_name = header_element.text.strip()
                logger.info(f"🎯 PROCESSING TARGET: '{screen_name}'")
            except:
                logger.info("🎯 PROCESSING TARGET: Unknown (Header not found)")
            # -------------------------

            while True:
                try:
                    # 1. Parse HTML Source
                    source = driver.page_source
                    soup = BeautifulSoup(source, "html.parser")
                    
                    # 2. Extract Data via Pandas
                    tables = pd.read_html(io.StringIO(source))
                    if tables:
                        df = tables[0]
                        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
                        if 'S.No.' in df.columns: df = df.drop(columns=['S.No.'])
                        
                        # 3. ROBUST TICKER EXTRACTION (The Fix)
                        # Create a Dictionary Map: { "Company Name": "TickerID" }
                        name_to_id = {}
                        
                        # Find all rows in the table body
                        rows = soup.select("table tbody tr")
                        
                        for row in rows:
                            # Find the company link
                            link = row.select_one("a[href*='/company/']")
                            if link:
                                name_text = link.get_text(strip=True)
                                href = link['href']
                                # Extract ID from href (e.g., /company/531727/)
                                parts = href.split('/')
                                if len(parts) > 2:
                                    # parts[2] is the ID
                                    name_to_id[name_text] = parts[2]
                        
                        # Apply the map to the DataFrame
                        # We look up the Name in the dictionary. If not found, fallback to Name.
                        # df.iloc[:, 0] is assumed to be the Name column
                        df['TickerID'] = df.iloc[:, 0].apply(lambda x: name_to_id.get(str(x).strip(), x))
                            
                        all_dfs.append(df)
                        logger.info(f"   ✅ Page {page_num} scraped ({len(df)} rows)")
                    else:
                        logger.warning(f"   ⚠️ No table found on Page {page_num}")

                    # 4. Pagination
                    try:
                        next_btn = driver.find_element(By.XPATH, "//div[@class='pagination']//a[contains(text(), 'Next')]")
                        next_btn.click()
                        page_num += 1
                        time.sleep(random.uniform(2.0, 4.0))
                    except NoSuchElementException:
                        logger.info("   🛑 Reached last page.")
                        break
                        
                except Exception as e:
                    logger.error(f"   ⚠️ Error processing page {page_num}: {e}")
                    break
        
        except Exception as e:
            logger.error(f"Critical Harvest Error: {e}")
        finally:
            if driver:
                driver.quit()
        
        if not all_dfs:
            return pd.DataFrame(), "No data found."
            
        full_df = pd.concat(all_dfs, ignore_index=True)
        return full_df, None

    def filter_survivors(self, df):
        """
        Gatekeeper Logic: Applies Financial Filters + Market Cap > 500Cr
        """
        if df.empty: return df, "Empty Dataframe"

        # 1. Map Columns
        col_map = {}
        df.columns = [str(c).strip() for c in df.columns]
        
        for col in df.columns:
            c_low = col.lower()
            if 'pledge' in c_low: col_map['Pledge'] = col
            elif 'debt' in c_low and 'eq' in c_low: col_map['D/E'] = col
            elif 'roce' in c_low: col_map['ROCE'] = col
            elif 'peg' in c_low: col_map['PEG'] = col
            elif 'cash' in c_low and 'flow' in c_low: col_map['FCF'] = col
            elif 'name' in c_low and 'company' not in c_low: col_map['Name'] = col
            elif 'cmp' in c_low and '/' not in c_low: col_map['Price'] = col
            elif 'mar' in c_low and 'cap' in c_low: col_map['Market Cap'] = col
            elif 'tickerid' in c_low: col_map['TickerID'] = col

        required = ['Pledge', 'D/E', 'ROCE', 'PEG', 'TickerID', 'Market Cap']
        missing = [k for k in required if k not in col_map]
        
        if missing:
            return pd.DataFrame(), f"Missing Columns: {missing}. (Did you log in?)"

        # 2. Clean Data
        clean_df = df.copy()
        for key, orig in col_map.items():
            if key not in ['Name', 'TickerID']:
                clean_df[orig] = clean_df[orig].apply(self._clean_numeric)

        fcf_mask = (clean_df[col_map['FCF']] > 0) if 'FCF' in col_map else True

        # 3. Apply Filters
        mask = (
            (clean_df[col_map['Pledge']] <= 0.1) & 
            (clean_df[col_map['D/E']] < 0.3) & 
            (clean_df[col_map['ROCE']] > 15.0) & 
            (clean_df[col_map['PEG']] > 0.0) & 
            (clean_df[col_map['PEG']] < 2.0) & 
            (clean_df[col_map['Market Cap']] > 500.0) & 
            fcf_mask
        )
        
        survivors = clean_df[mask].copy()
        
        rename_dict = {v: k for k, v in col_map.items()}
        survivors = survivors.rename(columns=rename_dict)
        
        final_cols = ['Name', 'TickerID', 'Price', 'Market Cap', 'PEG', 'ROCE', 'D/E', 'Pledge', 'FCF']
        available = [c for c in final_cols if c in survivors.columns]
        
        return survivors[available], f"Found {len(survivors)} qualifiers."

    def get_company_description(self, ticker_name):
        driver = None
        try:
            driver = uc.Chrome(options=self.options, use_subprocess=True, version_main=142)
            slug = ticker_name.replace(' ', '-').replace('.', '').replace('(', '').replace(')', '').lower()
            url = f"https://www.screener.in/company/{slug}/"
            driver.get(url)
            time.sleep(2)
            try:
                about_div = driver.find_element(By.CLASS_NAME, 'about-company')
                return about_div.text[:400] + "..."
            except:
                return "Description unavailable."
        except:
            return "Description unavailable."
        finally:
            if driver: driver.quit()