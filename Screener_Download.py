import os
import time
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def download_screener_excel(ticker: str, email: str, password: str, download_path: str):
    """
    Logs into screener.in using Selenium and downloads the financial data Excel file.

    Args:
        ticker (str): The stock ticker of the company (e.g., "CUPID").
        email (str): Your screener.in login email.
        password (str): Your screener.in login password.
        download_path (str): The absolute local folder path to save the downloaded file.
    """
    # --- Setup Chrome options to specify download folder ---
    chrome_options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": download_path}
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")

    # --- Initialize WebDriver ---
    driver = None
    try:
        print("Setting up Chrome WebDriver (Headless Mode)...")
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # --- 1. Navigate to login page ---
        print("Navigating to login page...")
        driver.get("https://www.screener.in/login/")

        # --- 2. Wait for the login form, then enter credentials and submit ---
        print("Waiting for the login form to be ready...")
        wait = WebDriverWait(driver, 20)
        
        username_field = wait.until(EC.presence_of_element_located((By.ID, "id_username")))
        password_field = wait.until(EC.presence_of_element_located((By.ID, "id_password")))
        login_button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[@type='submit']")))

        print(f"Login form ready. Attempting to log in as {email}...")
        username_field.send_keys(email)
        password_field.send_keys(password)
        login_button.click()
        
        # --- 3. Add a short pause to allow the post-login redirect to complete ---
        print("Pausing for 3 seconds to allow dashboard to load...")
        time.sleep(3)

        # --- 4. THIS IS THE FIX: Navigate directly to the CONSOLIDATED company page ---
        company_url = f"https://www.screener.in/company/{ticker}/consolidated/"
        print(f"Navigating to {ticker}'s consolidated page...")
        driver.get(company_url)

        # --- 5. Wait for the 'Export to Excel' button to be present ---
        print("Waiting for the 'Export to Excel' button to be present on the page...")
        export_button_locator = (By.XPATH, "//button[.//span[contains(text(), 'Export to Excel')]]")
        
        export_button = wait.until(EC.presence_of_element_located(export_button_locator))
        
        print("Login successful and page ready! Found 'Export to Excel' button.")
        
        # --- 6. Scroll the button into view ---
        print("Scrolling the button into view...")
        driver.execute_script("arguments[0].scrollIntoView(true);", export_button)
        time.sleep(1)

        # --- 7. FINAL ROBUST DOWNLOAD LOGIC ---
        files_before = set(os.listdir(download_path))
        
        print("Clicking to download using JavaScript...")
        driver.execute_script("arguments[0].click();", export_button)

        print(f"Waiting for download to complete...")
        wait_time = 30
        download_complete = False
        for i in range(wait_time):
            files_after = set(os.listdir(download_path))
            new_files = files_after - files_before
            
            # Find the new file that is a completed excel file
            final_files = [f for f in new_files if f.endswith('.xlsx')]

            if final_files:
                downloaded_file = final_files[0]
                downloaded_file_path = os.path.join(download_path, downloaded_file)
                
                # Wait a moment to ensure the file is fully written
                time.sleep(2)
                
                # Rename the file to the expected ticker name for consistency
                new_file_path = os.path.join(download_path, f"{ticker}.xlsx")
                if os.path.exists(new_file_path):
                    os.remove(new_file_path)
                os.rename(downloaded_file_path, new_file_path)
                
                print(f"Download complete! File saved as: {new_file_path}")
                download_complete = True
                break
            
            time.sleep(1)
        
        if not download_complete:
            print(f"Download failed. No new .xlsx file detected after {wait_time} seconds.")

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
        download_screener_excel(COMPANY_TICKER, SCREENER_EMAIL, SCREENER_PASSWORD, DOWNLOAD_DIRECTORY)
