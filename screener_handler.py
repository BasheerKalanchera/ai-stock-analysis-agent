import asyncio
import io
import time
import random
import logging
import platform
import threading
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

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
        # Playwright setup happens directly in async contexts
        pass

    async def _login_async(self, page, email, password):
        """Performs login to ensure custom columns are visible."""
        try:
            logger.info("🔐 Logging in to access custom columns...")
            await page.goto("https://www.screener.in/login/", wait_until="domcontentloaded")
            await page.wait_for_selector("#id_username", timeout=15000)
            await page.fill("#id_username", email)
            await page.fill("#id_password", password)
            await page.click("button[type='submit']")
            await page.wait_for_url(lambda url: "/login/" not in url, timeout=20000)
            await page.wait_for_load_state("domcontentloaded")
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

    async def _fetch_wrapper_data_async(self, start_url, email=None, password=None):
        logger.info(f"Starting Harvest: {start_url}")
        all_dfs = []
        page_num = 1
        
        async with async_playwright() as p:
            launch_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ]
            executable_path = "/usr/bin/chromium" if platform.system() == "Linux" else None
            browser = await p.chromium.launch(
                headless=True,
                args=launch_args,
                executable_path=executable_path,
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            try:
                if email and password:
                    success = await self._login_async(page, email, password)
                    if not success:
                        return pd.DataFrame(), "Login Failed."

                await page.goto(start_url, wait_until="domcontentloaded")
                await asyncio.sleep(1)

                # --- HEADER EXTRACTION ---
                try:
                    header_element = page.locator("h1").first
                    screen_name = (await header_element.inner_text()).strip()
                    logger.info(f"🎯 PROCESSING TARGET: '{screen_name}'")
                except:
                    logger.info("🎯 PROCESSING TARGET: Unknown (Header not found)")
                # -------------------------

                while True:
                    try:
                        # 1. Parse HTML Source
                        source = await page.content()
                        soup = BeautifulSoup(source, "html.parser")
                        
                        # 2. Extract Data via Pandas
                        tables = pd.read_html(io.StringIO(source))
                        if tables:
                            df = tables[0]
                            df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
                            if 'S.No.' in df.columns: df = df.drop(columns=['S.No.'])
                            
                            # 3. ROBUST TICKER EXTRACTION
                            name_to_id = {}
                            rows = soup.select("table tbody tr")
                            for row in rows:
                                link = row.select_one("a[href*='/company/']")
                                if link:
                                    name_text = link.get_text(strip=True)
                                    href = link['href']
                                    parts = href.split('/')
                                    if len(parts) > 2:
                                        name_to_id[name_text] = parts[2]
                            
                            df['TickerID'] = df.iloc[:, 0].apply(lambda x: name_to_id.get(str(x).strip(), x))
                                
                            all_dfs.append(df)
                            logger.info(f"   ✅ Page {page_num} scraped ({len(df)} rows)")
                        else:
                            logger.warning(f"   ⚠️ No table found on Page {page_num}")

                        # 4. Pagination
                        try:
                            next_btn = page.locator("div.pagination a:has-text('Next')")
                            if await next_btn.count() > 0:
                                await next_btn.first.click()
                                await page.wait_for_load_state("domcontentloaded")
                                page_num += 1
                                await asyncio.sleep(random.uniform(1.0, 2.5))
                            else:
                                logger.info("   🛑 Reached last page.")
                                break
                        except Exception:
                            logger.info("   🛑 Reached last page (error clicking next).")
                            break
                            
                    except Exception as e:
                        logger.error(f"   ⚠️ Error processing page {page_num}: {e}")
                        break
            
            except Exception as e:
                logger.error(f"Critical Harvest Error: {e}")
            finally:
                await context.close()
                await browser.close()
            
        if not all_dfs:
            return pd.DataFrame(), "No data found."
            
        full_df = pd.concat(all_dfs, ignore_index=True)
        return full_df, None

    def fetch_wrapper_data(self, start_url, email=None, password=None):
        """Synchronous wrapper to run async Playwright safely in Streamlit/Windows."""
        result_container = [None, None]
        exception_container = [None]

        def run_in_thread():
            if platform.system() == "Windows":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                out_df, msg = loop.run_until_complete(self._fetch_wrapper_data_async(start_url, email, password))
                result_container[0] = out_df
                result_container[1] = msg
            except Exception as e:
                exception_container[0] = e
            finally:
                loop.close()

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        thread.join()

        if exception_container[0]:
            logger.error(f"Thread Error: {exception_container[0]}")
            return pd.DataFrame(), str(exception_container[0])

        return result_container[0], result_container[1]

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
            elif 'opm' in c_low: col_map['OPM'] = col

        required = ['Pledge', 'D/E', 'ROCE', 'PEG', 'TickerID', 'Market Cap', 'OPM', 'FCF']
        missing = [k for k in required if k not in col_map]
        
        if missing:
            return pd.DataFrame(), f"Missing Columns: {missing}. (Did you log in?)"

        # 2. Clean Data
        clean_df = df.copy()
        for key, orig in col_map.items():
            if key not in ['Name', 'TickerID']:
                clean_df[orig] = clean_df[orig].apply(self._clean_numeric)

        # 3. Apply Filters
        mask = (
            (clean_df[col_map['Pledge']] <= 0.1) & 
            (clean_df[col_map['D/E']] < 0.3) & 
            (clean_df[col_map['ROCE']] > 15.0) & 
            (clean_df[col_map['PEG']] > 0.0) & 
            (clean_df[col_map['PEG']] < 2.0) & 
            (clean_df[col_map['Market Cap']] > 1000.0) & 
#            (clean_df[col_map['OPM']] > 15.0) &
            (clean_df[col_map['FCF']] > 0)
 #           (clean_df[col_map['FCF']] > 0) &
 #           (clean_df[col_map['Market Cap']] < 20 * clean_df[col_map['FCF']])
        )
        
        survivors = clean_df[mask].copy()
        
        rename_dict = {v: k for k, v in col_map.items()}
        survivors = survivors.rename(columns=rename_dict)
        
        final_cols = ['Name', 'TickerID', 'Price', 'Market Cap', 'PEG', 'ROCE', 'D/E', 'Pledge', 'OPM', 'FCF']
        available = [c for c in final_cols if c in survivors.columns]
        
        return survivors[available], f"Found {len(survivors)} qualifiers."

    async def _get_company_description_async(self, ticker_name):
        async with async_playwright() as p:
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1920,1080"]
            executable_path = "/usr/bin/chromium" if platform.system() == "Linux" else None
            browser = await p.chromium.launch(headless=True, args=launch_args, executable_path=executable_path)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                slug = ticker_name.replace(' ', '-').replace('.', '').replace('(', '').replace(')', '').lower()
                url = f"https://www.screener.in/company/{slug}/"
                await page.goto(url, wait_until="domcontentloaded")
                about_div = page.locator('.about-company')
                if await about_div.count() > 0:
                    text = await about_div.first.inner_text()
                    return text[:400] + "..."
                return "Description unavailable."
            except:
                return "Description unavailable."
            finally:
                await context.close()
                await browser.close()

    def get_company_description(self, ticker_name):
        """Synchronous wrapper to run async Playwright safely in Streamlit/Windows."""
        result_container = ["Description unavailable."]
        def run_in_thread():
            if platform.system() == "Windows":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                desc = loop.run_until_complete(self._get_company_description_async(ticker_name))
                result_container[0] = desc
            except:
                pass
            finally:
                loop.close()
        
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        thread.join()
        return result_container[0]
