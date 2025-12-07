import google.generativeai as genai
import os
from dotenv import load_dotenv  # <--- Add this

# Load environment variables from .env file
load_dotenv()  # <--- Add this

# Now Python can see the key
try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    
    print(f"{'Model Name':<40} | {'Supported Methods'}")
    print("-" * 80)

    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"{m.name:<40} | {m.supported_generation_methods}")

except KeyError:
    print("Error: GOOGLE_API_KEY is still not found. Check your .env file format.")
except Exception as e:
    print(f"An error occurred: {e}")