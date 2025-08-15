import os
import time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def download_financial_data(ticker: str, email: str, password: str, download_path: str):
    """
    Downloads Excel and PDF, waits for them to be fully downloaded and renamed,
    and then returns their final, stable paths.
    
    Returns:
        A tuple (excel_path, pdf_path), or (None, None) on failure.
    """
    chrome_options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": download_path,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20)
        
        # Login
        driver.get("https://www.screener.in/login/")
        wait.until(EC.presence_of_element_located((By.ID, "id_username"))).send_keys(email)
        wait.until(EC.presence_of_element_located((By.ID, "id_password"))).send_keys(password)
        wait.until(EC.presence_of_element_located((By.XPATH, "//button[@type='submit']"))).click()
        time.sleep(3)

        # Navigate and Initiate Downloads
        company_url = f"https://www.screener.in/company/{ticker}/consolidated/"
        driver.get(company_url)
        files_before = set(os.listdir(download_path))
        
        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(), 'Export to Excel')]]"))).click()
        print("Initiating Excel download...")
        
        wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Documents"))).click()
        wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Annual reports']/following-sibling::div[1]//a[1]"))).click()
        print("Initiating Annual Report PDF download...")

        # Robust Wait, Rename, and Path Return Logic
        wait_time = 60
        final_excel_path, final_pdf_path = None, None
        for i in range(wait_time):
            new_files = set(os.listdir(download_path)) - files_before
            temp_excel = next((f for f in new_files if f.endswith('.xlsx') and not f.endswith('.crdownload')), None)
            temp_pdf = next((f for f in new_files if f.endswith('.pdf') and not f.endswith('.crdownload')), None)

            if temp_excel and not final_excel_path:
                final_excel_path = os.path.join(download_path, f"{ticker}.xlsx")
                if os.path.exists(final_excel_path): os.remove(final_excel_path)
                os.rename(os.path.join(download_path, temp_excel), final_excel_path)
                print(f"SUCCESS: Excel file download confirmed and renamed to: {final_excel_path}")
            
            if temp_pdf and not final_pdf_path:
                final_pdf_path = os.path.join(download_path, f"{ticker}_Annual_Report.pdf")
                if os.path.exists(final_pdf_path): os.remove(final_pdf_path)
                os.rename(os.path.join(download_path, temp_pdf), final_pdf_path)
                print(f"SUCCESS: PDF file download confirmed and renamed to: {final_pdf_path}")

            if final_excel_path and final_pdf_path:
                time.sleep(2) # Final small buffer before closing browser
                driver.quit()
                return final_excel_path, final_pdf_path
            
            time.sleep(1)

        print("Error: Download timed out for one or both files.")
        driver.quit()
        return None, None

    except Exception as e:
        print(f"An unexpected error occurred during download: {e}")
        if driver:
            driver.quit()
        return None, None