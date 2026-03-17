import json

# Parse proxies from the file content
proxies_text = """px711001.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px043006.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px1160303.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px1400403.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px022409.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px013304.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px390501.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px060301.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px014236.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px950403.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px340403.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px016008.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px1210303.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px173003.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px500401.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px710701.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px041202.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px040805.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px580801.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px510201.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px990502.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px043004.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px810503.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px031901.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px210404.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px100801.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px031901.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px730503.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px350401.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px130501.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px380101.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px090404.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px490401.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px220601.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px410701.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px013401.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px052001.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px016007.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px1390303.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px016007.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px121102.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px390501.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px220601.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px013302.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px480301.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px010702.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px490402.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px320702.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px260901.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px241102.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px051703.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px032002.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px410701.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px022409.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px051005.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px430403.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px012702.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px370505.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px430403.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px241104.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px016102.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px173007.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px121101.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px591203.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px490701.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px730503.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px1210303.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px520401.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px1160303.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px570201.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px440401.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px420602.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px016501.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px014004.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px013301.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px710701.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px700403.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px591201.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px013601.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px331101.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px121001.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px320705.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px870303.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px460101.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px600303.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px591701.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px460101.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px043005.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px490402.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px040706.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px022408.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px060301.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px280301.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px380101.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px251002.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px1330403.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px023004.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px480301.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px016006.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px580801.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px570201.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px510201.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px591801.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px300902.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px591801.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px023004.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px013403.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px500401.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px032004.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px040805.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px400408.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px1260302.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px591201.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px180801.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px150902.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px032002.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px040706.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px591701.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px022505.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px023005.pointtoserver.com:10780:ppurevpn0s12840722:vkgp6joz
px140801.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px440401.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz
px100801.pointtoserver.com:10780:purevpn0s12840722:vkgp6joz"""

# Parse unique proxies
proxies_list = []
seen = set()
for line in proxies_text.strip().split('\n'):
    line = line.strip()
    if line and line not in seen:
        proxies_list.append(line)
        seen.add(line)

# Load config
with open('shopify_config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Update proxies
config['proxies'] = proxies_list
config['active_proxies'] = proxies_list[:10]  # Start with first 10 as active
config['dead_proxies'] = []

# Save
with open('shopify_config.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)

print(f"✅ Proxies updated!")
print(f"📊 Total proxies: {len(proxies_list)}")
print(f"🟢 Active proxies: {len(config['active_proxies'])}")
print(f"💳 Available sites: {len(config['available_sites'])}")
