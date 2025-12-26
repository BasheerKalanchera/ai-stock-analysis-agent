import requests
import json

# REPLACE WITH YOUR ACTUAL API KEY
API_KEY = "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"

def dump_full_json(api_key):
    url = "https://api.tavily.com/usage"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            # Parse JSON and print it with indentation for readability
            data = response.json()
            print("\n--- 📥 RAW JSON RESPONSE ---")
            print(json.dumps(data, indent=4))
        else:
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    dump_full_json(API_KEY)