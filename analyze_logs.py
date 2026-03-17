import re

# Read the log file
with open('attached_assets/Pasted--Error-on-page-10-407-Proxy-Authentication-Required-con_1766652950040.txt', 'r') as f:
    content = f.read()

lines = content.split('\n')

errors = {}
sites = {}
status_codes = {}
cards = []

for i, line in enumerate(lines, 1):
    # Find all errors
    if '❌' in line or '⚠️' in line:
        error_type = 'ERROR' if '❌' in line else 'WARNING'
        if error_type not in errors:
            errors[error_type] = []
        errors[error_type].append(line.strip())
    
    # Find all sites
    if 'https://' in line:
        sites_found = re.findall(r'https://[^\s/]+(?:/[^\s]*)?', line)
        for site in sites_found:
            if site not in sites:
                sites[site] = 0
            sites[site] += 1
    
    # Find all status codes
    if re.search(r'\d{3}(?:\s|:)', line):
        codes = re.findall(r'(\d{3})', line)
        for code in codes:
            if code not in status_codes:
                status_codes[code] = 0
            status_codes[code] += 1
    
    # Find all cards
    if '💳 Card:' in line:
        card = re.search(r'Card: ([0-9\s]+)', line)
        if card:
            cards.append(card.group(1))

print("=" * 60)
print("COMPLETE LOG ANALYSIS - WORD BY WORD")
print("=" * 60)

print("\n🔴 CRITICAL FINDINGS:")
print(f"Total Lines: {len(lines)}")
print(f"Total Errors (❌): {len(errors.get('ERROR', []))}")
print(f"Total Warnings (⚠️): {len(errors.get('WARNING', []))}")

print("\n⚠️ ALL WARNINGS FOUND:")
for i, warn in enumerate(errors.get('WARNING', [])[:20], 1):
    print(f"{i}. {warn[:100]}")

print("\n❌ ALL ERRORS FOUND:")
for i, err in enumerate(errors.get('ERROR', [])[:20], 1):
    print(f"{i}. {err[:100]}")

print("\n📊 STATUS CODES:")
for code, count in sorted(status_codes.items()):
    print(f"   {code}: {count} times")

print(f"\n🌐 UNIQUE SITES ACCESSED: {len(sites)}")
for site, count in sorted(sites.items(), key=lambda x: -x[1])[:15]:
    print(f"   {site}: {count} attempts")

print(f"\n💳 CARDS PROCESSED: {len(set(cards))}")
for card in set(cards)[:5]:
    print(f"   {card}")

print("\n🔍 CRITICAL ISSUE: 407 Proxy Authentication Required")
proxy_errors = [l for l in errors.get('WARNING', []) if '407' in l]
print(f"   407 Errors found: {len(proxy_errors)}")
print("   ⚠️ ALL PROXIES FAILED - causing sites to be marked dead!")
