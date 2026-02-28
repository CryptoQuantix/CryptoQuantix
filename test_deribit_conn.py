
import requests
import time

def test_deribit():
    print("Testing Deribit Connection...")
    try:
        start = time.time()
        resp = requests.get("https://www.deribit.com/api/v2/public/test", timeout=10)
        resp.raise_for_status()
        latency = (time.time() - start) * 1000
        print(f"Success! Latency: {latency:.2f}ms")
        print(f"Response: {resp.json()}")
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    test_deribit()
