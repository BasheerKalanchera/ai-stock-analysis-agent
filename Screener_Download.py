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
    Logs into screener.in, downloads the Excel data sheet, and then downloads
    the latest Annual Report PDF.

    Args:
        ticker (str): The stock ticker of the company (e.g., "CUPID").
        email (str): Your screener.in login email.
        password (str): Your screener.in login password.
        download_path (str): The absolute local folder path to save the downloaded files.
    """
    # --- Setup Chrome options ---
    chrome_options = webdriver.ChromeOptions()
    
    # --- THIS IS THE FIX ---
    # Add prefs to disable the PDF viewer and force downloads.
    prefs = {
        "download.default_directory": download_path,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")

    # --- Initialize WebDriver ---
    driver = None
    try:
        print("Setting up Chrome WebDriver (Headless Mode)...")
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20)

        # --- 1. Login ---
        print("Navigating to login page...")
        driver.get("https://www.screener.in/login/")
        
        username_field = wait.until(EC.presence_of_element_located((By.ID, "id_username")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "id_password")))
        login_button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[@type='submit']")))

        print(f"Attempting to log in as {email}...")
        username_field.send_keys(email)
        password_field.send_keys(password)
        login_button.click()
        time.sleep(3) # Pause for post-login redirect

        # --- 2. Navigate to Company Page ---
        company_url = f"https://www.screener.in/company/{ticker}/consolidated/"
        print(f"Navigating to {ticker}'s consolidated page...")
        driver.get(company_url)

        # --- 3. Initiate Excel Download ---
        print("Locating 'Export to Excel' button...")
        export_button_locator = (By.XPATH, "//button[.//span[contains(text(), 'Export to Excel')]]")
        export_button = wait.until(EC.element_to_be_clickable(export_button_locator))
        
        files_before = set(os.listdir(download_path))
        print("Initiating Excel download...")
        driver.execute_script("arguments[0].click();", export_button)
        time.sleep(2) # Short pause to ensure download is initiated

        # --- 4. Initiate Annual Report PDF Download ---
        print("Navigating to 'Documents' tab...")
        documents_tab_locator = (By.LINK_TEXT, "Documents")
        documents_tab = wait.until(EC.element_to_be_clickable(documents_tab_locator))
        driver.execute_script("arguments[0].click();", documents_tab)

        print("Locating latest Annual Report link...")
        # This XPath finds the H3 tag for "Annual reports", then finds the first link in the first div that follows it.
        annual_report_link_locator = (By.XPATH, "//h3[text()='Annual reports']/following-sibling::div[1]//a[1]")
        annual_report_link = wait.until(EC.element_to_be_clickable(annual_report_link_locator))
        
        print("Initiating Annual Report PDF download...")
        driver.execute_script("arguments[0].click();", annual_report_link)

        # --- 5. Wait for Both Downloads to Complete ---
        print("Waiting for both downloads to complete...")
        wait_time = 60
        excel_file_path = None
        pdf_file_path = None

        for i in range(wait_time):
            files_after = set(os.listdir(download_path))
            new_files = files_after - files_before

            for file in new_files:
                # Check for completed Excel file
                if file.endswith('.xlsx') and not file.endswith('.crdownload') and not excel_file_path:
                    temp_path = os.path.join(download_path, file)
                    excel_file_path = os.path.join(download_path, f"{ticker}.xlsx")
                    if os.path.exists(excel_file_path):
                        os.remove(excel_file_path)
                    os.rename(temp_path, excel_file_path)
                    print(f"SUCCESS: Excel file saved as: {excel_file_path}")

                # Check for completed PDF file
                if (file.endswith('.pdf') or file.endswith('.PDF')) and not file.endswith('.crdownload') and not pdf_file_path:
                    temp_path = os.path.join(download_path, file)
                    pdf_file_path = os.path.join(download_path, f"{ticker}_Annual_Report.pdf")
                    if os.path.exists(pdf_file_path):
                        os.remove(pdf_file_path)
                    os.rename(temp_path, pdf_file_path)
                    print(f"SUCCESS: PDF file saved as: {pdf_file_path}")
            
            if excel_file_path and pdf_file_path:
                print("All downloads complete!")
                break
            
            time.sleep(1)

        if not excel_file_path:
            print(f"ERROR: Excel download failed after {wait_time} seconds.")
        if not pdf_file_path:
            print(f"ERROR: PDF download failed after {wait_time} seconds.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if driver:
            print("Closing the browser.")
            driver.quit()

if __name__ == '__main__':
    load_dotenv()
    SCREENER_EMAIL = os.getenv("SCREENER_EMAIL")
    SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")
    COMPANY_TICKER = "CUPID"
    DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "downloads")
    
    if not os.path.exists(DOWNLOAD_DIRECTORY):
        os.makedirs(DOWNLOAD_DIRECTORY)

    if not SCREENER_EMAIL or not SCREENER_PASSWORD:
        print("="*60)
        print("!!! ERROR: Credentials not found in .env file. !!!")
        print("Please create a .env file with SCREENER_EMAIL and SCREENER_PASSWORD.")
        print("="*60)
    else:
        download_financial_data(COMPANY_TICKER, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY)