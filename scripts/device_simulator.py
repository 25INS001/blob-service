import requests
import json
import time
import random
import datetime

# Configuration
API_URL = "https://api.robogenic.site/blob/device/heartbeat" 
TOKEN = "YOUR_JWT_TOKEN_HERE" 
DEVICE_ID = "simulated-device-001"

# Global state for network counters to simulate accumulation
net_state = {
    "bytes_sent": 10000000,
    "bytes_recv": 50000000
}

def get_stats():
    """Generates random system stats matching the user's psutil structure."""
    
    # Simulate accumulating network traffic
    net_state["bytes_sent"] += random.randint(100000, 5000000) # +100KB to +5MB
    net_state["bytes_recv"] += random.randint(200000, 8000000) # +200KB to +8MB

    return {
        'cpu': {
            'total': round(random.uniform(5, 50), 1),
            'cores': [round(random.uniform(0, 60), 1) for _ in range(12)],
            'count': 12,
            'name': "AMD Ryzen 5 5500",
            'freq_current': 3200 + random.randint(-100, 100), # MHz
            'freq_max': 4200
        },
        'memory': {
            'total': 32 * 1024**3, # Bytes
            'available': int(random.uniform(10, 20) * 1024**3),
            'percent': round(random.uniform(30, 70), 1),
            'used': int(random.uniform(10, 20) * 1024**3)
        },
        'swap': {
            'total': 2 * 1024**3, # Bytes
            'used': 0,
            'percent': 0.0
        },
        'disks': [
            {
                'device': '/dev/nvme0n1p2',
                'mountpoint': '/',
                'total': 400 * 1024**3, # Bytes
                'used': 330 * 1024**3,
                'percent': 82.5
            },
            {
                'device': '/dev/sda1',
                'mountpoint': '/home/ashu/space',
                'total': 500 * 1024**3,
                'used': 50 * 1024**3,
                'percent': 10.0
            }
        ],
        'network': {
            'enp9s0': {
                'bytes_sent': net_state["bytes_sent"],
                'bytes_recv': net_state["bytes_recv"]
            }
        },
        'gpus': [{
            'name': "NVIDIA GeForce RTX 3050",
            'load': round(random.uniform(0, 100), 1),
            'memory_used': random.randint(1000, 5000), # MB
            'memory_total': 6144, # MB
            'temperature': round(random.uniform(30, 80), 1)
        }],
        'system': {
            'boot_time': "2026-02-07 06:07:38",
            'time': datetime.datetime.now().strftime("%H:%M:%S"),
            'date': datetime.datetime.now().strftime("%Y-%m-%d"),
            'temperatures': {
                'k10temp': [{'label': 'Tdie', 'current': round(random.uniform(35, 65), 1)}]
            }
        }
    }

def send_heartbeat():
    payload = {
        "device_id": DEVICE_ID,
        "status": "online",
        "version": "1.0.2",
        "device_type": "compute_node",
        "stats": get_stats()
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"Sending heartbeat to {API_URL}...")
        response = requests.post(API_URL, json=payload, headers=headers)
        
        if response.status_code == 200:
            print(f"[{response.status_code}] Success")
        else:
            print(f"[{response.status_code}] Failed: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print(f"Starting heartbeat simulation for {DEVICE_ID}")
    while True:
        send_heartbeat()
        time.sleep(5) # Faster for testing network rates
