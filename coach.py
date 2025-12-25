import os
import sys
import socket # Add this

# --- 1. NETWORK PATCH: FORCE IPv4 ---
# This fixes WinError 10060 by forcing Python to ignore IPv6
def patch_socket_ipv4():
    real_getaddrinfo = socket.getaddrinfo
    def new_getaddrinfo(*args, **kwargs):
        responses = real_getaddrinfo(*args, **kwargs)
        # Filter out IPv6 (AF_INET6) results, keep only IPv4 (AF_INET)
        return [res for res in responses if res[0] == socket.AF_INET]
    socket.getaddrinfo = new_getaddrinfo

patch_socket_ipv4()
# ------------------------------------

import time
import json
import pyaudio
import wave
from termcolor import colored
from dotenv import load_dotenv
import google.generativeai as genai

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

# Force REST transport just to be safe
genai.configure(api_key=API_KEY, transport='rest')

# We use 2.5 Flash Preview because it supports File Uploads (REST) 
# whereas 'native-audio-preview' is WebSocket ONLY.
MODEL_ID = "gemini-3-flash-preview" 

# Audio Settings
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
OUTPUT_FILENAME = "session_practice.wav"

SYSTEM_PROMPT = """
You are PitchPerfect, an expert presentation coach. 
Listen to the attached audio file of a user practicing a presentation.

Analyze the speech and output a JSON object with these fields:
- "confidence_score": (Integer 1-10)
- "filler_word_count": (Integer)
- "pacing_analysis": (String, e.g., "Too fast", "Good")
- "key_feedback_points": (List of strings)
- "summary": (String)

Do NOT use Markdown formatting (like ```json). Just output the raw JSON.
"""

def record_audio():
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    
    print(colored("\n🎤 RECORDING... (Press Ctrl+C to stop and analyze)", "green", attrs=['bold']))
    
    frames = []
    try:
        while True:
            data = stream.read(CHUNK)
            frames.append(data)
            # Simple visualizer
            if len(frames) % 10 == 0:
                sys.stdout.write(".")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print(colored("\n\n🛑 Recording Stopped.", "yellow"))
    
    stream.stop_stream()
    stream.close()
    p.terminate()

    # Save to file
    wf = wave.open(OUTPUT_FILENAME, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    return OUTPUT_FILENAME

def analyze_audio(file_path):
    print(colored(f"🚀 Uploading {file_path} to Gemini...", "cyan"))
    
    # 1. Upload File (REST API)
    audio_file = genai.upload_file(file_path, mime_type="audio/wav")
    
    # 2. Wait for processing (Usually instant for audio)
    while audio_file.state.name == "PROCESSING":
        print("Processing...")
        time.sleep(1)
        audio_file = genai.get_file(audio_file.name)

    # 3. Generate Content
    print(colored("🧠 Analyzing with Gemini 2.5 Flash...", "cyan"))
    model = genai.GenerativeModel(
        model_name=MODEL_ID,
        system_instruction=SYSTEM_PROMPT
    )
    
    response = model.generate_content([audio_file, "Generate the report."])
    
    # 4. Cleanup
    audio_file.delete()
    
    return response.text

if __name__ == "__main__":
    try:
        # Step 1: Record
        audio_path = record_audio()
        
        # Step 2: Analyze
        json_report = analyze_audio(audio_path)
        
        # Step 3: Report
        print(colored("\n" + "="*40, "green"))
        print(colored("     PITCH PERFECT REPORT     ", "green", attrs=['bold']))
        print(colored("="*40, "green"))
        print(json_report)
        
        # Save to file
        with open("final_report.json", "w") as f:
            f.write(json_report)
            
    except Exception as e:
        print(colored(f"Error: {e}", "red"))