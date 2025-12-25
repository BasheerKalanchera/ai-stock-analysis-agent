import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

try:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    
    print(f"{'Model Name':<55} | {'Capabilities'}")
    print("-" * 110)

    for m in genai.list_models():
        # Check if the model supports the WebSocket protocol (Live API)
        is_live_model = 'bidiGenerateContent' in m.supported_generation_methods
        
        if is_live_model:
            # Highlight Live models in GREEN (if your terminal supports it) or just mark them
            print(f"🎙️  {m.name:<51} | [LIVE AUDIO SUPPORTED]")
        else:
            # Print standard models normally
            print(f"   {m.name:<51} | {m.supported_generation_methods}")

except Exception as e:
    print(f"An error occurred: {e}")