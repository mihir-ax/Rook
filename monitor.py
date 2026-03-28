import os
import time
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from threading import Thread

app = Flask(__name__)

# 🌍 ENVIRONMENT VARIABLES
NEXUS_API_URL = os.getenv("NEXUS_API_URL", "https://nexus-lemon-beta.vercel.app/api/uptime")
ALERIFY_API_URL = os.getenv("ALERIFY_API_URL", "https://rapid-x-chi.vercel.app/send")

# Trackers
consecutive_failures = {}
last_db_log_time = {}   # Har 2 min me DB update track karne ke liye
last_heartbeats = {}    # URLs se aane wali requests track karne ke liye

def fetch_targets():
    """Fetch live URLs to monitor directly from Nexus Database"""
    try:
        res = requests.get(f"{NEXUS_API_URL}?type=targets", timeout=10)
        if res.status_code == 200:
            return res.json().get('data', [])
    except Exception as e:
        print(f"Error fetching targets from Nexus: {e}")
    return []

def send_alert(target_name, target_url, error_msg):
    """Trigger Alerify if site is DOWN for 3 consecutive checks"""
    print(f"🚨 ALERT! {target_name} IS DOWN FOR 3 CONSECUTIVE CHECKS! Triggering Alerify...")
    
    html_msg = f"""
    <h3>🔴 UPTIME ALERT: SERVICE DOWN</h3>
    <p><b>Service:</b> {target_name}</p>
    <p><b>URL:</b> <a href='{target_url}'>{target_url}</a></p>
    <p><b>Error:</b> {error_msg}</p>
    <p><b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><b>Note:</b> Alert triggered after 3 consecutive failed checks</p>
    """
    
    payload = {
        "subject": f"🔴 DOWN ALERT: {target_name}",
        "tg_html_message": html_msg,
        "email_html_message": html_msg
    }
    
    try:
        requests.post(ALERIFY_API_URL, json=payload, timeout=10)
        print(f"✅ Alert sent for {target_name}")
    except Exception as e:
        print(f"Failed to trigger Alerify: {e}")

def run_radar_sweep():
    global consecutive_failures, last_db_log_time
    targets = fetch_targets()
    if not targets:
        print(f"[{datetime.now()}] No targets found in Nexus. Sleeping...")
        return

    print(f"[{datetime.now()}] Initiating Radar Sweep for {len(targets)} targets... (Ping checking)")
    
    for target in targets:
        start_time = time.time()
        status = "UP"
        latency = 0
        target_name = target["name"]
        target_url = target["url"]
        
        try:
            # 1. PING THE URL (Runs every 30 seconds)
            res = requests.get(target_url, timeout=15)
            latency = int((time.time() - start_time) * 1000)
            
            if res.status_code != 200:
                status = "DOWN"
                consecutive_failures[target_name] = consecutive_failures.get(target_name, 0) + 1
                print(f"⚠️ {target_name} DOWN #{consecutive_failures[target_name]} | Status: {res.status_code}")
                
                if consecutive_failures[target_name] >= 3:
                    send_alert(target_name, target_url, f"HTTP Status {res.status_code}")
                    consecutive_failures[target_name] = 0
            else:
                if consecutive_failures.get(target_name, 0) > 0:
                    print(f"✅ {target_name} is back UP! Resetting failure counter")
                consecutive_failures[target_name] = 0
                
        except requests.exceptions.RequestException as e:
            latency = 9999
            status = "DOWN"
            consecutive_failures[target_name] = consecutive_failures.get(target_name, 0) + 1
            print(f"⚠️ {target_name} DOWN #{consecutive_failures[target_name]} | Error: {str(e)}")
            
            if consecutive_failures[target_name] >= 3:
                send_alert(target_name, target_url, str(e))
                consecutive_failures[target_name] = 0

        # 2. SEND LOG BACK TO NEXUS (Strictly Every 2 Minutes / 120 Seconds)
        current_time = time.time()
        last_log = last_db_log_time.get(target_name, 0)
        
        if current_time - last_log >= 120:  # 120 seconds = 2 minutes
            try:
                payload = {
                    "action": "log_ping",
                    "targetName": target_name,
                    "status": status,
                    "latency": latency
                }
                requests.post(NEXUS_API_URL, json=payload, timeout=5)
                print(f"💾 Logged to DB: {target_name} | Status: {status} | Latency: {latency}ms")
                # Update the last log time
                last_db_log_time[target_name] = current_time
            except Exception as e:
                print(f"❌ Failed to send log to Nexus DB: {e}")

def background_worker():
    """Background thread to run radar sweeps continuously"""
    print("🤖 NEXUS Python Worker Node Started!")
    while True:
        run_radar_sweep()
        # Sleep for 30 Seconds only
        time.sleep(30)


# --- FLASK ENDPOINTS ---

@app.route('/heartbeat/<target_name>', methods=['GET', 'POST'])
def receive_heartbeat(target_name):
    """Endpoint for monitored URLs to ping us back (Reverse Check)"""
    last_heartbeats[target_name] = datetime.now().isoformat()
    print(f"💓 Heartbeat received from {target_name} at {last_heartbeats[target_name]}")
    return jsonify({"status": "success", "message": f"Heartbeat for {target_name} logged."}), 200

@app.route('/')
def health_check():
    """Root endpoint to verify service is alive and see who is hitting us back"""
    return jsonify({
        "status": "I AM ALIVE",
        "message": "Nexus Uptime Monitor Worker is running",
        "timestamp": datetime.now().isoformat(),
        "monitored_targets": len(consecutive_failures),
        "active_alerts": {k: v for k, v in consecutive_failures.items() if v > 0},
        "incoming_heartbeats": last_heartbeats  # Yaha dikhega ki kis kis URL ne is app ko ping kiya hai
    }), 200

@app.route('/ping')
def ping():
    return jsonify({"status": "success", "message": "pong", "timestamp": datetime.now().isoformat()}), 200

if __name__ == "__main__":
    worker_thread = Thread(target=background_worker, daemon=True)
    worker_thread.start()
    
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 Web service running on port {port}")
    app.run(host='0.0.0.0', port=port)
