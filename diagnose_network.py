import asyncio
import os
import sys
import websockets
import requests
from termcolor import colored
from dotenv import load_dotenv

load_dotenv()

# Force Windows Policy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

API_KEY = os.getenv("GOOGLE_API_KEY")

def print_status(test_name, status, message):
    color = "green" if status == "PASS" else "red"
    print(f"{test_name:<20} | {colored(status, color)} | {message}")

async def test_rest_api():
    """Test 1: Can we talk to Google at all via HTTP?"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print_status("REST API (HTTP)", "PASS", "Connection successful.")
            return True
        else:
            print_status("REST API (HTTP)", "FAIL", f"Status Code: {response.status_code}")
            return False
    except Exception as e:
        print_status("REST API (HTTP)", "FAIL", str(e))
        return False

async def test_public_websocket():
    """Test 2: Are WebSockets blocked globally on this machine?"""
    # We use a public echo server to test if your Firewall hates ALL WebSockets
    uri = "wss://echo.websocket.org" 
    try:
        async with websockets.connect(uri, timeout=10) as ws:
            await ws.send("test")
            response = await ws.recv()
            print_status("Public WS Test", "PASS", "Can connect to generic WebSockets.")
            return True
    except Exception as e:
        print_status("Public WS Test", "FAIL", f"Firewall/ISP likely blocking WSS: {e}")
        return False

async def test_google_websocket():
    """Test 3: Can we handshake with Google's Live Server?"""
    # This tries to open a raw socket to Google without the SDK logic
    host = "generativelanguage.googleapis.com"
    uri = f"wss://{host}/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={API_KEY}"
    
    try:
        # We just want to see if the HANDSHAKE completes. 
        # The connection will likely close immediately because we aren't sending valid data,
        # but if we get past the handshake, the network is fine.
        async with websockets.connect(uri, timeout=10) as ws:
            print_status("Google WS Handshake", "PASS", "Connected to Google Live Server!")
            return True
    except websockets.exceptions.InvalidStatusCode as e:
        # 400/404 is actually GOOD here. It means we connected, but sent bad data.
        # It proves the network path is open.
        print_status("Google WS Handshake", "PASS", "Network Path is OPEN (Server replied).")
        return True
    except Exception as e:
        print_status("Google WS Handshake", "FAIL", f"Blocked: {e}")
        return False

async def main():
    print(colored("--- STARTING NETWORK DIAGNOSTICS ---", "cyan"))
    
    # 1. Check Key
    if not API_KEY:
        print(colored("Error: GOOGLE_API_KEY is missing.", "red"))
        return

    # 2. Run Tests
    rest_ok = await asyncio.to_thread(test_rest_api)
    ws_public_ok = await test_public_websocket()
    ws_google_ok = await test_google_websocket()

    print(colored("\n--- DIAGNOSIS ---", "cyan"))
    if not rest_ok:
        print("❌ Your internet cannot reach Google API at all. Check VPN/DNS.")
    elif not ws_public_ok:
        print("❌ Your Firewall/Antivirus is blocking ALL WebSocket (wss://) traffic.")
    elif not ws_google_ok:
        print("❌ Google's WebSocket endpoint is specifically blocked or timing out.")
        print("   Try: disabling IPv6 or switching to a mobile hotspot.")
    else:
        print("✅ Network looks fine. The issue is likely inside the SDK configuration.")

if __name__ == "__main__":
    asyncio.run(main())