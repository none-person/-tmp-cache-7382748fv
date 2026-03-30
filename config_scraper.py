import asyncio
import aiohttp
import json
import re
import logging
from bs4 import BeautifulSoup
import os
import shutil
import base64
from urllib.parse import parse_qs, unquote

# === اصلاح مسیرها به صورت مطلق ===
BASE_DIR = os.getcwd()


URLS_FILE = os.path.join(BASE_DIR, 'Files', 'urls.txt')

KEYWORDS_FILE = os.path.join(BASE_DIR, 'Files', 'key.json')

OUTPUT_DIR = os.path.join(BASE_DIR, 'configs')

# ==================================

REQUEST_TIMEOUT = 15
CONCURRENT_REQUESTS = 10
MAX_CONFIG_LENGTH = 1500
MIN_PERCENT25_COUNT = 15

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

PROTOCOL_CATEGORIES = [
    "Vmess", "Vless", "Trojan", "ShadowSocks", "ShadowSocksR",
    "Tuic", "Hysteria2", "WireGuard"
]

def decode_base64(data):
    try:
        data = data.replace('_', '/').replace('-', '+')
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data).decode('utf-8')
    except Exception:
        return None

def get_vmess_name(vmess_link):
    if not vmess_link.startswith("vmess://"): return None
    try:
        b64_part = vmess_link[8:]
        decoded_str = decode_base64(b64_part)
        if decoded_str:
            return json.loads(decoded_str).get('ps')
    except Exception:
        pass
    return None

def get_ssr_name(ssr_link):
    if not ssr_link.startswith("ssr://"): return None
    try:
        b64_part = ssr_link[6:]
        decoded_str = decode_base64(b64_part)
        if not decoded_str: return None
        parts = decoded_str.split('/?')
        if len(parts) < 2: return None
        params = parse_qs(parts[1])
        if 'remarks' in params and params['remarks']:
            return decode_base64(params['remarks'][0])
    except Exception:
        pass
    return None

def should_filter_config(config):
    if 'i_love_' in config.lower(): return True
    if config.count('%25') >= MIN_PERCENT25_COUNT: return True
    if len(config) >= MAX_CONFIG_LENGTH: return True
    if '%2525' in config: return True
    return False

async def fetch_url(session, url):
    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            text_content = ""
            for element in soup.find_all(['pre', 'code', 'p', 'div', 'li', 'span', 'td']):
                text_content += element.get_text(separator='\n', strip=True) + "\n"
            if not text_content:
                text_content = soup.get_text(separator=' ', strip=True)
            logging.info(f"Successfully fetched: {url}")
            return url, text_content
    except Exception as e:
        logging.warning(f"Failed to fetch {url}: {e}")
        return url, None

def find_matches(text, categories_data):
    matches = {category: set() for category in categories_data}
    for category, patterns in categories_data.items():
        for pattern_str in patterns:
            if not isinstance(pattern_str, str): continue
            try:
                is_protocol_pattern = any(proto_prefix in pattern_str for proto_prefix in [p.lower() + "://" for p in PROTOCOL_CATEGORIES])
                if category in PROTOCOL_CATEGORIES or is_protocol_pattern:
                    pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
                    found = pattern.findall(text)
                    if found:
                        matches[category].update({item.strip() for item in found if item.strip()})
            except re.error:
                continue
    return {k: v for k, v in matches.items() if v}

def save_to_file(directory, category_name, items_set):
    if not items_set: return False, 0
    file_path = os.path.join(directory, f"{category_name}.txt")
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            for item in sorted(list(items_set)):
                f.write(f"{item}\n")
        logging.info(f"Saved {len(items_set)} items to {file_path}")
        return True, len(items_set)
    except Exception as e:
        logging.error(f"Failed to write file {file_path}: {e}")
        return False, 0

async def main():
    if not os.path.exists(URLS_FILE) or not os.path.exists(KEYWORDS_FILE):
        logging.critical(f"Input files not found ({URLS_FILE} or {KEYWORDS_FILE}).")
        return

    with open(URLS_FILE, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
        categories_data = json.load(f)

    protocol_patterns = {cat: pat for cat, pat in categories_data.items() if cat in PROTOCOL_CATEGORIES}
    country_keywords = {cat: pat for cat, pat in categories_data.items() if cat not in PROTOCOL_CATEGORIES}
    
    logging.info(f"Loaded {len(urls)} URLs.")

    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    async def fetch_with_sem(session, url_to_fetch):
        async with sem:
            return await fetch_url(session, url_to_fetch)

    async with aiohttp.ClientSession() as session:
        fetched_pages = await asyncio.gather(*[fetch_with_sem(session, u) for u in urls])

    final_configs_by_country = {cat: set() for cat in country_keywords.keys()}
    final_all_protocols = {cat: set() for cat in PROTOCOL_CATEGORIES}

    logging.info("Processing extracted configs...")
    for url, text in fetched_pages:
        if not text: continue

        page_protocol_matches = find_matches(text, protocol_patterns)
        for protocol_cat_name, configs_found in page_protocol_matches.items():
            if protocol_cat_name in PROTOCOL_CATEGORIES:
                for config in configs_found:
                    if should_filter_config(config): continue
                    
                    final_all_protocols[protocol_cat_name].add(config)

                    # Extract name for country matching
                    name_to_check = None
                    if '#' in config:
                        try:
                            name_to_check = unquote(config.split('#', 1)[1]).strip()
                        except IndexError: pass
                    
                    if not name_to_check:
                        if config.startswith('ssr://'): name_to_check = get_ssr_name(config)
                        elif config.startswith('vmess://'): name_to_check = get_vmess_name(config)

                    if name_to_check and isinstance(name_to_check, str):
                        for country_name, keywords in country_keywords.items():
                            match_found = False
                            for keyword in keywords:
                                if not isinstance(keyword, str): continue
                                is_abbr = (len(keyword) in [2, 3]) and re.match(r'^[A-Z]+$', keyword)
                                if is_abbr:
                                    if re.search(r'\b' + re.escape(keyword) + r'\b', name_to_check, re.IGNORECASE):
                                        match_found = True
                                else:
                                    if keyword.lower() in name_to_check.lower():
                                        match_found = True
                                
                                if match_found:
                                    final_configs_by_country[country_name].add(config)
                                    break
                            if match_found: break

    # Save logic
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for category, items in final_all_protocols.items():
        save_to_file(OUTPUT_DIR, category, items)
    for category, items in final_configs_by_country.items():
        save_to_file(OUTPUT_DIR, category, items)

    logging.info("--- Scraper Finished ---")

if __name__ == "__main__":
    asyncio.run(main())
