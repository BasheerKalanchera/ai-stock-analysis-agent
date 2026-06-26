import io
import requests
from pypdf import PdfReader

def test_bse_pdf():
    # URL from user's logs
    url = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/9958b16b-6858-4523-b61f-48fc2c0c5f82.pdf"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.screener.in/",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    print(f"Downloading {url} with headers...")
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    content_type = response.headers.get('Content-Type', '')
    print(f"Content-Type: {content_type}")
    
    pdf_bytes_io = io.BytesIO(response.content)
    
    try:
        reader = PdfReader(pdf_bytes_io)
        print(f"Successfully loaded PDF. Number of pages: {len(reader.pages)}")
        
        first_page_text = reader.pages[0].extract_text() or ""
        print(f"Extracted length of first page: {len(first_page_text)} chars")
        print("--- FIRST 500 CHARS ---")
        print(first_page_text[:500])
        print("-----------------------")
        print(f"Is it less than 50 chars? {len(first_page_text.strip()) < 50}")
        
    except Exception as e:
        print(f"Failed to read PDF: {e}")

if __name__ == "__main__":
    test_bse_pdf()
