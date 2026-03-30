import requests
import time
import base64
import re
import os
import sys
import socket
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= GitHub Settings =================
REPO_OWNER = "none-person"
REPO_NAME = "-tmp-cache-7382748fv"
PROXY_WORKFLOW = "scraper.yml"
CONFIG_WORKFLOW = "configs.yml"

def get_github_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip().strip(' "\'')
    except FileNotFoundError:
        pass
    return None

GITHUB_TOKEN = get_github_token()
# ===================================================

# Chisel proxy settings
LOCAL_PROXY = {
    "http": "socks5h://127.0.0.1:1088",
    "https": "socks5h://127.0.0.1:1088"
}

if not GITHUB_TOKEN:
    print("[-] ERROR: GITHUB_TOKEN not found!")
    sys.exit(1)

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def trigger_workflow(workflow_filename):
    print(f"[*] Sending execution trigger for '{workflow_filename}' to GitHub server...")
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_filename}/dispatches"
    try:
        response = requests.post(url, headers=HEADERS, json={"ref": "main"}, proxies=LOCAL_PROXY, timeout=15)
        if response.status_code == 204:
            print("[+] Trigger sent successfully.")
            return True
        else:
            print(f"[-] Error sending trigger: {response.text}")
            return False
    except Exception as e:
        print(f"[-] Error connecting to tunnel: {e}")
        return False

def wait_for_workflow_completion(workflow_filename):
    print("[*] Waiting for the GitHub server to start the job...")
    time.sleep(10)
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_filename}/runs"
    
    while True:
        try:
            response = requests.get(url, headers=HEADERS, proxies=LOCAL_PROXY, timeout=15).json()
            if not response.get("workflow_runs"):
                time.sleep(5)
                continue
                
            latest_run = response["workflow_runs"][0]
            status = latest_run["status"]
            conclusion = latest_run["conclusion"]
            
            if status == "completed":
                if conclusion == "success":
                    print("[+] Action on GitHub completed successfully.")
                    return True
                else:
                    print("[-] GitHub action failed.")
                    return False
            else:
                print(f"[*] Server is working... Status: {status} (This may take a few minutes)")
                time.sleep(15)
        except Exception as e:
            print(f"[-] Communication error with GitHub (check tunnel): {e}")
            time.sleep(15)

def download_proxy_file():
    print("[*] Downloading collected proxies from GitHub...")
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/proxy.txt"
    try:
        response = requests.get(url, headers=HEADERS, proxies=LOCAL_PROXY, timeout=15)
        if response.status_code == 200:
            content = response.json()["content"]
            decoded_content = base64.b64decode(content).decode('utf-8')
            proxies = [line.strip() for line in decoded_content.splitlines() if line.strip()]
            print(f"[+] Downloaded {len(proxies)} proxies.")
            return proxies
        return []
    except Exception as e:
         print(f"[-] Error downloading file: {e}")
         return []

def download_configs():
    print("[*] Downloading collected configs from GitHub (configs folder)...")
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/configs"
    try:
        response = requests.get(url, headers=HEADERS, proxies=LOCAL_PROXY, timeout=15)
        if response.status_code == 200:
            files = response.json()
            os.makedirs("downloaded_configs", exist_ok=True)
            saved_files = []
            for file_info in files:
                if file_info["type"] == "file" and file_info["name"].endswith(".txt"):
                    file_name = file_info["name"]
                    download_url = file_info["download_url"]
                    res = requests.get(download_url, proxies=LOCAL_PROXY)
                    if res.status_code == 200:
                        filepath = os.path.join("downloaded_configs", file_name)
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(res.text)
                        saved_files.append(filepath)
            print(f"[+] Downloaded {len(saved_files)} config files to 'downloaded_configs' folder.")
            return saved_files
        else:
            print(f"[-] Error finding configs folder: {response.text}")
            return []
    except Exception as e:
         print(f"[-] Error downloading configs: {e}")
         return []

def local_test_proxy(proxy_link):
    match = re.match(r'^(?:tg://proxy|https://t\.me/proxy)\?server=([^&]+)&port=(\d+)&secret=.+$', proxy_link)
    if not match: return None
    server, port = match.groups()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.5) 
        result = sock.connect_ex((server, int(port)))
        sock.close()
        return proxy_link if result == 0 else None
    except Exception:
        return None

def main():
    print("="*40)
    print(" Welcome! Please select an option:")
    print(" 1. Get new proxies (Telegram MTProto)")
    print(" 2. Get & Merge VPN configs (For LiteSpeedTest)")
    print("="*40)
    
    choice = input("Your choice (1 or 2): ")
    
    if choice == '1':
        print("\n[*] Make sure your Chisel tunnel is running...")
        if trigger_workflow(PROXY_WORKFLOW):
            if wait_for_workflow_completion(PROXY_WORKFLOW):
                proxies = download_proxy_file()
                if proxies:
                    print(f"\n[*] Locally testing {len(proxies)} proxies using direct internet connection...")
                    working_proxies = []
                    with ThreadPoolExecutor(max_workers=50) as executor:
                        futures = [executor.submit(local_test_proxy, p) for p in proxies]
                        for future in as_completed(futures):
                            result = future.result()
                            if result:
                                working_proxies.append(result)
                                print(f"[✔] Proxy connected: {result[:50]}...")
                                
                    print(f"\n[+] Test finished! {len(working_proxies)} proxies are working with your direct internet.")
                    with open("local_working_proxies.txt", "w", encoding="utf-8") as f:
                        for wp in working_proxies:
                            f.write(wp + "\n")
                    print("[+] Working proxies have been saved to 'local_working_proxies.txt'.")

    elif choice == '2':
        print("\n[*] Make sure your Chisel tunnel is running...")
        if trigger_workflow(CONFIG_WORKFLOW):
            if wait_for_workflow_completion(CONFIG_WORKFLOW):
                saved_files = download_configs()
                if saved_files:
                    print("\n[*] Gathering and merging all config lines...")
                    all_configs = set()
                    for filepath in saved_files:
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                for line in f:
                                    config = line.strip()
                                    if config and (config.startswith('vmess://') or config.startswith('vless://') or 
                                                   config.startswith('ss://') or config.startswith('trojan://') or 
                                                   config.startswith('wireguard://')):
                                        all_configs.add(config)
                        except Exception:
                            pass
                    
                    configs_list = list(all_configs)
                    print(f"[*] Found {len(configs_list)} unique configs. Saving to 'all_configs.txt'...")
                    
                    # فقط ذخیره تمامی کانفیگ‌های بدون تکرار در یک فایل و اتمام کار اسکریپت
                    with open("all_configs.txt", "w", encoding="utf-8") as f:
                        for c in configs_list:
                            f.write(c + "\n")
                            
                    print("="*60)
                    print("[+] PERFECT! All configs have been downloaded and merged.")
                    print("[+] Now, open your terminal and run the following command to test them:")
                    print("\033[92m  ./lite -test all_configs.txt \033[0m")
                    print("="*60)

    else:
        print("Invalid choice!")

if __name__ == "__main__":
    main()
