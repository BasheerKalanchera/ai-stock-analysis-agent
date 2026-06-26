"""
Screener_Download.py
====================
Downloads financial data from screener.in for a given stock ticker using
Playwright browser automation. Supports downloading Excel financials,
Peer comparison tables, Investor Presentations (PPT), Credit Rating reports
(CRISIL, ICRA, CARE, etc.), and Concall Transcripts. Transfers browser
cookies to a requests.Session for direct PDF downloads where possible.

CHANGE LOG
----------
[2026-03-09] Sector Scraping for Dynamic Valuation
  - Updated `scrape_peers_data` to also scrape the company's sector from the 
    investor peers breadcrumb trail structure.
  - The sector is now extracted and stored in `file_buffers['sector']`.

[2026-03-08] Add keyword-based transcript filtering
  - After downloading each transcript PDF, extract first-page text using pypdf
    and check for special event keywords (investor day, analyst meet, AGM, etc.).
  - If detected as a non-earnings transcript, skip it and try the next link.
  - Ensures the qualitative agent always analyzes actual quarterly earnings calls.

[2026-03-04] Fix ICRA credit rating downloads & transcript selectors
  - Refactored credit ratings to loop through ALL rating links instead of
    only checking the first one. If a link fails, it moves to the next.
  - Added "NO FILE TO VIEW" detection for broken ICRA report pages.
  - Extracted credit rating publication date from Screener HTML link text
    and stored it in file_buffers['credit_rating_date'] for the Risk Agent.
  - Fixed transcript CSS selector from brittle h3 sibling combinator to
    '.documents.concalls a.concall-link[title="Raw Transcript"]' which
    correctly handles deeply nested DOM structures (e.g., HCLTECH).

[2026-02-28] Selenium → Playwright migration
  - Replaced Selenium (undetected-chromedriver) with Playwright async API.
  - Removed wait_for_new_file() polling — replaced with page.expect_download().
  - Removed JS injection fallback for in-browser PDFs — replaced with native
    Playwright download handling.
  - Added public sync wrapper download_financial_data() that runs the async
    implementation in a dedicated Thread with ProactorEventLoop (fixes
    Streamlit's SelectorEventLoop on Windows which can't create subprocesses).
  - Cookie transfer: browser cookies are now extracted from Playwright context
    and injected into a requests.Session for direct PDF downloads.
  - On Linux (Streamlit Cloud), uses system Chromium from packages.txt.
    On Windows (local dev), uses Playwright's bundled Chromium.
"""
import asyncio
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

# --- PLAYWRIGHT IMPORTS ---
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from pypdf import PdfReader

# --- LOGGER ---
logger = logging.getLogger('screener_download')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - ⚪ DOWNLOAD - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.propagate = False

# --- EARNINGS CALL DETECTION ---
# Instead of trying to detect special events (too many false positives),
# we detect POSITIVE indicators of a quarterly earnings call.
# Every earnings call transcript prominently mentions quarter identifiers
# on the first page. If none are found, it's likely a special event.
EARNINGS_CALL_INDICATORS = [
    # Quarter identifiers (most reliable)
    " q1 ", " q2 ", " q3 ", " q4 ",
    " q1-", " q2-", " q3-", " q4-",
    "q1 fy", "q2 fy", "q3 fy", "q4 fy",
    "q1fy", "q2fy", "q3fy", "q4fy",
    "quarter 1", "quarter 2", "quarter 3", "quarter 4",
    "first quarter", "second quarter", "third quarter", "fourth quarter",
    "1st quarter", "2nd quarter", "3rd quarter", "4th quarter",
    # Earnings-specific phrases
    "earnings call", "earnings conference",
    "earning call", "earning conference",
    "results conference", "results call",
    "quarterly results", "financial results",
    "quarterly earnings",
]


def _is_earnings_call_transcript(pdf_bytes_io: io.BytesIO) -> bool:
    """
    Checks whether a downloaded transcript PDF is a quarterly earnings call
    (returns True) or a special event like Investor Day/AGM (returns False).
    Uses POSITIVE detection: looks for quarter identifiers (Q1/Q2/Q3/Q4)
    and earnings-related phrases on the first 2 pages. If none are found,
    the transcript is classified as a non-earnings special event.

    Why 2 pages? Indian concall PDFs typically have a BSE/NSE regulatory
    cover letter on page 1 that may not always contain "earnings conference".
    The actual transcript title page (with Q1/Q2/Q3/Q4 identifiers) is
    usually on page 2.
    """
    try:
        pdf_bytes_io.seek(0)
        reader = PdfReader(pdf_bytes_io)
        if not reader.pages:
            return True  # Can't determine — assume earnings call

        # Extract text from the first 2 pages (cover letter + title page)
        combined_text = ""
        for i in range(min(2, len(reader.pages))):
            combined_text += (reader.pages[i].extract_text() or "") + " "
        
        # If the PDF is a scanned image, extract_text() will return nothing.
        # It's better to assume it's valid than to aggressively skip it.
        if len(combined_text.strip()) < 50:
            logger.info("     🔍 Extracted text is empty (likely scanned PDF). Assuming earnings call.")
            pdf_bytes_io.seek(0)
            return True

        # Normalize all whitespace (newlines, tabs, multiple spaces) into single spaces
        normalized_text = f" {' '.join(combined_text.lower().split())} "

        for indicator in EARNINGS_CALL_INDICATORS:
            if indicator in normalized_text:
                pdf_bytes_io.seek(0)
                return True  # Confirmed earnings call

        # No earnings indicators found — likely a special event
        logger.info(f"     🔍 No earnings call indicators found on first 2 pages. Classifying as special event.")
        pdf_bytes_io.seek(0)
        return False
    except Exception as e:
        logger.warning(f"     ⚠️ Could not classify transcript: {e}. Assuming earnings call.")
        pdf_bytes_io.seek(0)
        return True  # On error, assume earnings call to avoid skipping valid data


async def scrape_peers_data(page) -> tuple:
    """Scrapes the Peers table and sector breadcrumb from the current company page.
    Returns (peer_df: pd.DataFrame, sector: str).
    """
    sector = "Unknown"
    try:
        logger.info("Attempting to scrape Peers table...")
        target_id = "peers-table-placeholder"

        try:
            container = await page.wait_for_selector(f"#{target_id}", timeout=10000)
        except PlaywrightTimeoutError:
            container = await page.wait_for_selector("#peers", timeout=10000)

        await container.scroll_into_view_if_needed()

        # --- SECTOR BREADCRUMB SCRAPE ---
        try:
            breadcrumb_els = await page.locator(
                "#peers a[href*='/market/'], "
                "#peers-table-placeholder a[href*='/market/']"
            ).all()
            if breadcrumb_els:
                texts = []
                for el in breadcrumb_els:
                    t = (await el.inner_text()).strip()
                    if t:
                        texts.append(t)
                # Use second-to-last for broader industry grouping, or last if only one
                sector = texts[-2] if len(texts) >= 2 else texts[-1] if texts else "Unknown"
                logger.info(f"✅ Sector Identified: {sector} (breadcrumb: {' > '.join(texts)})")
            else:
                logger.warning("Sector breadcrumb not found in Peers section.")
        except Exception as e:
            logger.warning(f"Could not scrape sector breadcrumb: {e}")

        # --- PEERS TABLE SCRAPE ---
        table_selector = f"#{target_id} table"
        try:
            table_element = await page.wait_for_selector(table_selector, timeout=10000)
        except PlaywrightTimeoutError:
            # Fallback: try direct #peers table
            table_element = await page.wait_for_selector("#peers table", timeout=5000)

        html = await table_element.inner_html()
        dfs = pd.read_html(io.StringIO(f"<table>{html}</table>"))

        if dfs:
            peer_df = dfs[0]
            if "S.No." in peer_df.columns:
                peer_df = peer_df.drop(columns=["S.No."])
            peer_df = peer_df.loc[:, ~peer_df.columns.str.contains('^Unnamed', case=False)]
            logger.info(f"✅ SUCCESS: Scraped Peer Data Table ({len(peer_df)} rows).")
            return peer_df, sector
    except Exception as e:
        logger.warning(f"Could not scrape Peers table: {e}")
    return pd.DataFrame(), sector


async def _download_financial_data_async(
    ticker: str,
    config: dict,
    is_consolidated: bool = False,
    need_excel: bool = True,
    need_transcripts: bool = True,
    need_ppt: bool = True,
    need_credit_report: bool = True,
    need_peers: bool = True,
    metadata_only: bool = False
) -> Tuple[Optional[str], Dict[str, Any], pd.DataFrame]:
    """
    Internal async implementation. Uses Playwright to log into screener.in
    and download all requested financial documents for a ticker.
    """
    email = config["SCREENER_EMAIL"]
    password = config["SCREENER_PASSWORD"]

    logger.info(f"Starting download for {ticker} | Metadata Only={metadata_only}...")

    company_name = None
    file_buffers = {}
    peer_data = pd.DataFrame()

    async with async_playwright() as p:
        # --- BROWSER LAUNCH ---
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1920,1080",
        ]
        # On Linux (Streamlit Cloud), use the system Chromium installed via packages.txt.
        # On Windows (local), use Playwright's own downloaded Chromium.
        executable_path = "/usr/bin/chromium" if platform.system() == "Linux" else None
        browser = await p.chromium.launch(
            headless=True,
            args=launch_args,
            executable_path=executable_path,
        )

        # Create context with download support
        context = await browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            # --- 1. LOGIN ---
            logger.info("Initializing browser and logging in...")
            await page.goto("https://www.screener.in/login/", wait_until="domcontentloaded")
            await page.wait_for_selector("#id_username", timeout=15000)
            await page.fill("#id_username", email)
            await page.fill("#id_password", password)
            await page.click("button[type='submit']")
            # Wait for redirect away from the login page (URL will no longer contain '/login/')
            await page.wait_for_url(lambda url: "/login/" not in url, timeout=20000)
            await page.wait_for_load_state("domcontentloaded")
            logger.info("Login successful.")

            # --- 2. NAVIGATE TO COMPANY PAGE ---
            url = f"https://www.screener.in/company/{ticker}/{'consolidated/' if is_consolidated else ''}"
            await page.goto(url, wait_until="domcontentloaded")

            # --- BUILD REQUESTS SESSION (transfer cookies) ---
            cookies = await context.cookies()
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": url,
                "Accept-Language": "en-US,en;q=0.9",
            })
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'])

            # --- 3. FETCH COMPANY NAME ---
            try:
                await page.wait_for_selector("#top-ratios", timeout=15000)
                company_name_el = await page.wait_for_selector("h1.margin-0", timeout=10000)
                company_name = (await company_name_el.inner_text()).strip()
                logger.info(f"✅ Company Identified: {company_name}")
            except PlaywrightTimeoutError:
                logger.warning("Could not find company name element.")

            # --- SEBI MVP SHORT CIRCUIT ---
            if metadata_only:
                logger.info("🛑 Metadata Only Mode: Skipping heavy downloads.")
                return company_name, {}, pd.DataFrame()

            # --- 4. EXCEL ---
            if need_excel:
                logger.info("Downloading Excel with validation...")
                excel_downloaded = False

                for attempt in range(3):
                    try:
                        click_success = False

                        # Try button click first
                        try:
                            btn = page.locator("button:has-text('Export to Excel'), button:has-text('export to excel')")
                            count = await btn.count()
                            if count > 0:
                                async with page.expect_download(timeout=20000) as download_info:
                                    await btn.first.click()
                                download = await download_info.value
                                dl_path = await download.path()
                                with open(dl_path, 'rb') as f:
                                    excel_bytes = f.read()
                                click_success = True
                            else:
                                raise Exception("Button not found")
                        except Exception:
                            # Fallback: try href link
                            try:
                                link = page.locator("a:has-text('Export to Excel')")
                                href = await link.get_attribute('href')
                                if href:
                                    async with page.expect_download(timeout=20000) as download_info:
                                        await page.goto(href)
                                    download = await download_info.value
                                    dl_path = await download.path()
                                    with open(dl_path, 'rb') as f:
                                        excel_bytes = f.read()
                                    click_success = True
                            except Exception:
                                pass

                        # Fallback to standalone if consolidated link missing
                        if not click_success and is_consolidated:
                            logger.warning(f"   ⚠️ Consolidated Excel missing (Attempt {attempt+1}). Switching to Standalone...")
                            try:
                                await page.goto(f"https://www.screener.in/company/{ticker}/", wait_until="domcontentloaded")
                                await page.wait_for_selector("#top-ratios", timeout=10000)
                                try:
                                    btn = page.locator("button:has-text('Export to Excel'), button:has-text('export to excel')")
                                    if await btn.count() > 0:
                                        async with page.expect_download(timeout=20000) as download_info:
                                            await btn.first.click()
                                        download = await download_info.value
                                        dl_path = await download.path()
                                        with open(dl_path, 'rb') as f:
                                            excel_bytes = f.read()
                                        click_success = True
                                except Exception:
                                    pass
                            except Exception as e:
                                logger.error(f"   ❌ Fallback navigation failed: {e}")

                        if click_success:
                            # Validate magic bytes (ZIP/XLSX = PK, Legacy XLS = D0CF11E0)
                            is_valid = excel_bytes[:2] == b'PK' or excel_bytes[:4] == b'\xd0\xcf\x11\xe0'
                            if is_valid:
                                file_buffers['excel'] = io.BytesIO(excel_bytes)
                                logger.info("✅ Excel Downloaded & Validated.")
                                excel_downloaded = True
                                break
                            else:
                                logger.warning(f"❌ Invalid file (HTML/Corrupt) on attempt {attempt+1}. Retrying...")
                                await page.goto(url, wait_until="domcontentloaded")
                                await page.wait_for_selector("#top-ratios", timeout=10000)
                        else:
                            logger.warning(f"❌ Failed to find/click Excel export (Attempt {attempt+1}).")

                    except Exception as e:
                        logger.warning(f"⚠️ Error during Excel attempt {attempt+1}: {e}")

                    await asyncio.sleep(2)

                if not excel_downloaded:
                    logger.error("❌ Failed to download valid Excel after 3 attempts.")
            else:
                logger.info("⏭️ Skipped Excel.")

            # --- 5. PEERS ---
            if need_peers and company_name:
                peer_data, scraped_sector = await scrape_peers_data(page)
                file_buffers['sector'] = scraped_sector
            else:
                logger.info("⏭️ Skipped Peers.")

            # --- 6. PPT ---
            if need_ppt:
                logger.info("Scanning for Investor Presentation (PPT)...")
                await page.goto(f"https://www.screener.in/company/{ticker}/#documents", wait_until="domcontentloaded")

                ppt_url = None
                ppt_selectors = [
                    "a.concall-link:has-text('PPT')",
                    "ul.list-links a:has-text('PPT')",
                    "div.documents a:has-text('PPT')",
                ]

                for sel in ppt_selectors:
                    try:
                        el = page.locator(sel)
                        if await el.count() > 0:
                            ppt_url = await el.first.get_attribute('href')
                            logger.info(f"   > Found PPT via selector: {sel}")
                            break
                    except Exception:
                        continue

                if ppt_url:
                    # Attempt 1: requests download
                    try:
                        logger.info("   > Attempting PPT download via Requests...")
                        r = session.get(ppt_url, stream=True, timeout=15)
                        r.raise_for_status()
                        file_buffers['investor_presentation'] = io.BytesIO(r.content)
                        logger.info(f"     ✅ PPT Downloaded via Requests ({len(r.content)/1024/1024:.2f} MB)")
                    except Exception:
                        # Attempt 2: Playwright natural click download
                        logger.warning("     ⚠️ Requests blocked. Switching to Natural Click...")
                        try:
                            sel = ppt_selectors[0]
                            link_el = page.locator(sel).first
                            # Remove target="_blank" so download happens in same context
                            await link_el.evaluate("el => el.removeAttribute('target')")
                            async with page.expect_download(timeout=60000) as dl_info:
                                await link_el.click()
                            dl = await dl_info.value
                            dl_path = await dl.path()
                            with open(dl_path, 'rb') as f:
                                ppt_bytes = f.read()
                            file_buffers['investor_presentation'] = io.BytesIO(ppt_bytes)
                            logger.info(f"     ✅ PPT Downloaded via Click ({len(ppt_bytes)/1024/1024:.2f} MB)")
                        except Exception as e:
                            logger.error(f"     ❌ PPT Download Failed: {e}")
                else:
                    logger.info("   > No PPT link found.")
            else:
                logger.info("⏭️ Skipped PPT.")

            # --- 7. CREDIT RATINGS ---
            if need_credit_report:
                logger.info("Checking for Credit Ratings...")
                try:
                    if "documents" not in page.url:
                        await page.goto(f"https://www.screener.in/company/{ticker}/#documents", wait_until="domcontentloaded")

                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except PlaywrightTimeoutError:
                        logger.warning("   > networkidle timeout (non-fatal). Continuing...")

                    # Wait for credit ratings heading to confirm section is rendered
                    try:
                        await page.wait_for_selector("h3:has-text('Credit ratings')", timeout=8000)
                    except PlaywrightTimeoutError:
                        logger.warning("   > 'Credit ratings' heading not found on page.")

                    # Use XPath — identical to the original working Selenium implementation.
                    # Goes UP to the parent of the h3, then finds all li > a descendants.
                    rating_links = await page.locator(
                        "xpath=//h3[contains(text(), 'Credit ratings')]/..//li//a"
                    ).all()
                    logger.info(f"   > XPath primary: found {len(rating_links)} rating link(s).")

                    if not rating_links:
                        # Fallback: any link in documents section with Rating-related text
                        rating_links = await page.locator(
                            "xpath=//section[@id='documents']//a["
                            "contains(text(), 'CRISIL') or contains(text(), 'ICRA') or "
                            "contains(text(), 'CARE') or contains(text(), 'India Ratings') or "
                            "contains(text(), 'Rating')]"
                        ).all()
                        logger.info(f"   > XPath fallback: found {len(rating_links)} rating link(s).")

                    if rating_links:
                        for rating_link in rating_links:
                            rating_url = await rating_link.get_attribute('href')
                            if not rating_url:
                                continue
                            
                            logger.info(f"   > Trying Rating URL: {rating_url}")
                            
                            # Extract the date text from the link (e.g. "Rating update\n7 Oct 2025 from icra")
                            try:
                                link_text = await rating_link.inner_text()
                                date_text = link_text.split('\n')[-1].strip() if '\n' in link_text else link_text.strip()
                            except Exception:
                                date_text = "Unknown Date"

                            if rating_url.lower().endswith('.pdf'):
                                try:
                                    r = session.get(rating_url, stream=True, timeout=15)
                                    r.raise_for_status()
                                    file_buffers['credit_rating_doc'] = io.BytesIO(r.content)
                                    file_buffers['credit_rating_type'] = 'pdf'
                                    file_buffers['credit_rating_date'] = date_text
                                    logger.info(f"     ✅ Rating PDF Downloaded directly ({date_text}).")
                                    break # Success, stop looking
                                except Exception as e:
                                    logger.error(f"     ❌ Direct PDF download failed: {e}")
                            
                            elif "icra.in" in rating_url:
                                await page.goto(rating_url, wait_until="domcontentloaded")
                                try:
                                    # Check if the page explicitly says there's no file
                                    page_text = await page.locator('body').inner_text()
                                    if "NO FILE TO VIEW" in page_text.upper():
                                        logger.warning("     ⚠️ ICRA reports 'NO FILE TO VIEW'. Skipping to next link...")
                                        await page.go_back()
                                        continue

                                    download_btn = page.locator("#DownloadRatingReport")
                                    await download_btn.wait_for(timeout=10000)
                                    async with page.expect_download(timeout=15000) as dl_info:
                                        await download_btn.click()
                                    dl = await dl_info.value
                                    dl_path = await dl.path()
                                    with open(dl_path, 'rb') as f:
                                        rating_bytes = f.read()
                                    file_buffers['credit_rating_doc'] = io.BytesIO(rating_bytes)
                                    file_buffers['credit_rating_type'] = 'pdf'
                                    file_buffers['credit_rating_date'] = date_text
                                    logger.info(f"     ✅ ICRA PDF Downloaded via button ({date_text}).")
                                    await page.go_back()
                                    break # Success, stop looking
                                except PlaywrightTimeoutError:
                                    logger.warning("     ⚠️ ICRA button timeout. Skipping to next link...")
                                    await page.go_back()
                                except Exception as e:
                                    logger.warning(f"     ⚠️ ICRA download failed: {e}. Skipping...")
                                    await page.go_back()
                            
                            else:
                                logger.info(f"   > Navigating to rating page: {rating_url}")
                                await page.goto(rating_url, wait_until="domcontentloaded")
                                await asyncio.sleep(2)
                                try:
                                    page_text = await page.locator('body').inner_text()
                                    if len(page_text) > 200:
                                        file_buffers['credit_rating_doc'] = page_text
                                        file_buffers['credit_rating_type'] = 'html'
                                        file_buffers['credit_rating_date'] = date_text
                                        logger.info(f"     ✅ Rating Text Scraped ({len(page_text)} chars) ({date_text}).")
                                        await page.go_back()
                                        break # Success, stop looking
                                    else:
                                        logger.warning("     ⚠️ Page text too short, skipping...")
                                        await page.go_back()
                                except Exception as e:
                                    logger.error(f"     ❌ Page text scrape failed: {e}")
                                    await page.go_back()
                    else:
                        logger.info("   > No Credit Rating links found.")
                except Exception as e:
                    logger.warning(f"Error processing Credit Ratings: {e}")
            else:
                logger.info("⏭️ Skipped Credit Ratings.")

            # --- 8. TRANSCRIPTS ---
            if need_transcripts:
                logger.info("Scanning for Concall Transcripts...")
                try:
                    if "documents" not in page.url:
                        await page.goto(f"https://www.screener.in/company/{ticker}/#documents", wait_until="domcontentloaded")

                    # Target the specific concalls section container, then find transcript links within it
                    transcript_elements = await page.locator(
                        ".documents.concalls a.concall-link[title='Raw Transcript'], "
                        ".documents.concalls a.concall-link:has-text('Transcript')"
                    ).all()

                    transcript_urls = []
                    for el in transcript_elements:
                        href = await el.get_attribute('href')
                        if href:
                            transcript_urls.append(href)

                    successful_downloads = 0
                    skipped_special_events = 0
                    for i, pdf_url in enumerate(transcript_urls):
                        if successful_downloads >= 2:
                            break
                        if not pdf_url:
                            continue

                        key = 'latest_transcript' if successful_downloads == 0 else 'previous_transcript'
                        pdf_bytes_io = None

                        # Try requests first
                        try:
                            response = session.get(pdf_url, stream=True, timeout=15)
                            response.raise_for_status()
                            if 'application/pdf' in response.headers.get('Content-Type', ''):
                                pdf_bytes_io = io.BytesIO(response.content)
                        except Exception:
                            pass

                        # Fallback: Playwright download
                        if pdf_bytes_io is None:
                            try:
                                async with page.expect_download(timeout=15000) as dl_info:
                                    await page.goto(pdf_url)
                                dl = await dl_info.value
                                dl_path = await dl.path()
                                with open(dl_path, 'rb') as f:
                                    transcript_bytes = f.read()
                                pdf_bytes_io = io.BytesIO(transcript_bytes)
                                await page.go_back()
                            except Exception:
                                pass

                        if pdf_bytes_io is None:
                            continue

                        # --- KEYWORD FILTER: Skip non-earnings-call transcripts ---
                        if not _is_earnings_call_transcript(pdf_bytes_io):
                            skipped_special_events += 1
                            logger.info(f"     ⏭️ Transcript {i+1} skipped (Special Event, not quarterly earnings).")
                            continue

                        file_buffers[key] = pdf_bytes_io
                        successful_downloads += 1
                        logger.info(f"     ✅ Transcript {i+1} Downloaded (Earnings Call confirmed).")

                    if skipped_special_events > 0:
                        logger.info(f"   > Skipped {skipped_special_events} non-earnings transcript(s).")

                except Exception as e:
                    logger.warning(f"Error processing Transcripts: {e}")
            else:
                logger.info("⏭️ Skipped Transcripts.")

        except PlaywrightTimeoutError as te:
            logger.warning(f"Timeout during scraping: {te}")
        except Exception as e:
            logger.error(f"Critical error: {e}", exc_info=True)
        finally:
            await context.close()
            await browser.close()
            logger.info("Browser closed. Cleanup complete.")

    return company_name, file_buffers, peer_data


def download_financial_data(
    ticker: str,
    config: dict,
    is_consolidated: bool = False,
    need_excel: bool = True,
    need_transcripts: bool = True,
    need_ppt: bool = True,
    need_credit_report: bool = True,
    need_peers: bool = True,
    metadata_only: bool = False
) -> Tuple[Optional[str], Dict[str, Any], pd.DataFrame]:
    """
    Public synchronous wrapper around the async Playwright implementation.
    Runs Playwright in a dedicated thread with its own event loop to avoid
    conflicts with Streamlit's background thread event loop on Windows.
    """
    import threading

    result_container = [None]
    exception_container = [None]

    def run_in_thread():
        # On Windows, SelectorEventLoop (used in threads) doesn't support
        # subprocess creation. ProactorEventLoop does.
        if platform.system() == "Windows":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_container[0] = loop.run_until_complete(
                _download_financial_data_async(
                    ticker=ticker,
                    config=config,
                    is_consolidated=is_consolidated,
                    need_excel=need_excel,
                    need_transcripts=need_transcripts,
                    need_ppt=need_ppt,
                    need_credit_report=need_credit_report,
                    need_peers=need_peers,
                    metadata_only=metadata_only,
                )
            )
        except Exception as e:
            exception_container[0] = e
        finally:
            loop.close()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    thread.join()

    if exception_container[0]:
        raise exception_container[0]

    return result_container[0]
