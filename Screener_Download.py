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
    # To run without opening a browser window, uncomment the following lines
    # chrome_options.add_argument("--headless")
    # chrome_options.add_argument("--window-size=1920,1080")

    # --- Initialize WebDriver ---
    driver = None
    try:
        print("Setting up Chrome WebDriver...")
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # --- 1. Navigate to login page ---
        print("Navigating to login page...")
        driver.get("https://www.screener.in/login/")

        # --- 2. Wait for the login form, then enter credentials and submit ---
        print("Waiting for the login form to be ready...")
        wait = WebDriverWait(driver, 20) # Increased wait time
        
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

        # --- 4. Navigate directly to the company page ---
        company_url = f"https://www.screener.in/company/{ticker}/"
        print(f"Navigating to {ticker}'s page...")
        driver.get(company_url)

        # --- 5. Wait for the 'Export to Excel' button to be visible and clickable ---
        print("Waiting for the 'Export to Excel' button to be visible and clickable...")

        export_button_locator = (
            By.XPATH, "//button[.//span[contains(text(), 'Export to Excel')]]"
        )

        export_button = wait.until(
            EC.element_to_be_clickable(export_button_locator)
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", export_button)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", export_button)
        
        print("Login successful and page ready! Found 'Export to Excel' button.")
        
        # --- 6. Scroll the button into view ---
        print("Scrolling the button into view...")
        driver.execute_script("arguments[0].scrollIntoView(true);", export_button)
        time.sleep(1) # Add a small pause after scrolling

        # --- 7. Use a JavaScript click for maximum reliability ---
        print("Clicking to download using JavaScript...")
        driver.execute_script("arguments[0].click();", export_button)

        # --- 8. Robust wait for the download to complete ---
        print(f"Waiting for download to start and complete...")
        expected_filename = f"{ticker}.xlsx"
        downloaded_file_path = os.path.join(download_path, expected_filename)
        
        wait_time = 30  # Max wait time in seconds
        download_complete = False
        for i in range(wait_time):
            if os.path.exists(downloaded_file_path):
                initial_size = os.path.getsize(downloaded_file_path)
                if initial_size > 0:
                    time.sleep(2) 
                    final_size = os.path.getsize(downloaded_file_path)
                    if initial_size == final_size:
                        print(f"Download complete! File saved at: {downloaded_file_path}")
                        download_complete = True
                        break 
            time.sleep(1)
        
        if not download_complete:
            print(f"Download failed. File not found or did not finish downloading after {wait_time} seconds.")


    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if driver:
            print("Closing the browser.")
            driver.quit()

if __name__ == '__main__':
    # --- Load environment variables from .env file ---
    load_dotenv()

    # --- Get credentials from environment variables ---
    SCREENER_EMAIL = os.getenv("SCREENER_EMAIL")
    SCREENER_PASSWORD = os.getenv("SCREENER_PASSWORD")
    
    # --- Company to download ---
    COMPANY_TICKER = "CUPID"
    
    # --- Set an absolute path for the download directory ---
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