import json

# Read current config
with open('shopify_config.json', 'r') as f:
    config = json.load(f)

current_sites = set(config['available_sites'])
print(f"Current sites: {len(current_sites)}")

# Read the large sites file (19,557 sites)
try:
    with open('shopify_v40_19557_sites.txt', 'r') as f:
        for line in f:
            url = line.strip()
            if url and url.startswith('http'):
                current_sites.add(url)
except FileNotFoundError:
    print("⚠️ Large sites file not found yet")

# Save config with all sites
config['available_sites'] = sorted(list(current_sites))
config['unavailable_sites'] = []

with open('shopify_config.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)

print(f"✅ UPDATED! Total sites: {len(config['available_sites'])}")
print(f"📊 Available: {len(config['available_sites'])}")
print(f"🚫 Unavailable: {len(config['unavailable_sites'])}")
