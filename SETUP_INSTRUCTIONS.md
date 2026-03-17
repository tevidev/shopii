# Shopify Auto Checkout System - Setup & Run Instructions

## 📋 Requirements
- Python 3.7+
- pip (Python package manager)

## 🔧 Setup (First Time Only)

### 1. Open Terminal/Command Prompt in VS Code
Press `Ctrl + ~` (Windows/Linux) or `` Cmd + ` `` (Mac)

### 2. Install Required Packages
Copy and paste this command:
```bash
pip install aiofiles beautifulsoup4 fake-useragent httpx python-telegram-bot requests telegram
```

Wait for installation to complete ✅

### 3. Verify Setup
```bash
python shopify_auto_checkout.py
```

## 🚀 How to Run

### Method 1: VS Code Terminal (Easiest)
1. Open Terminal in VS Code: `Ctrl + ~`
2. Type this command:
```bash
python shopify_auto_checkout.py
```

### Method 2: Command Line
```bash
cd /path/to/project
python shopify_auto_checkout.py
```

## 📊 System Features

✅ **4 Concurrent Workers** - Fast card checking
✅ **90 Active Sites** - Smart site rotation
✅ **67 Working Proxies** - All new PureVPN proxies
✅ **Permanent Site Banning** - Dead sites never reused
✅ **Real-Time File Output** - 6 categorized result files:
  - charged.txt (successfully charged)
  - live.txt (valid/approved)
  - declined.txt (declined cards)
  - challenge.txt (3D Secure/CAPTCHA required)
  - suspicious.txt (fraud detected)
  - errors.txt (system errors)

## 🔒 Proxy Configuration

**Current Proxy Status:**
- ✅ 67 new PureVPN proxies loaded
- ✅ Using proxy rotation with 4 workers
- ✅ Auto-fallback if proxy fails

**Proxies File:** `shopify_config.json` (active_proxies list)

## 💳 Input Format (Cards File)

Create a file with one card per line:
```
4017954195773040
5547300039598811
5547300429645958
```

Format: `CARDNUMBER` (no spaces, no dashes)

## 📝 Menu Options

When running, you'll see:
```
1. Single Card Check (/sx)
2. Mass Card Check (/msx)
3. Mass Site Check - Admin (/mssx)
4. Add Sites to Rotation - Admin (/addsx)
5. Add Proxies to Rotation - Admin (/addpp)
6. Show Statistics
7. Exit
```

## ✅ Verification Checklist

Before running, verify:
- ✅ Python 3 installed: `python --version`
- ✅ All packages installed: No import errors
- ✅ shopify_auto_checkout.py exists
- ✅ shopify_config.json exists with proxies
- ✅ 90 sites loaded
- ✅ 67 proxies loaded

## 🐛 Troubleshooting

**"Module not found" error:**
```bash
pip install [module_name]
```

**"Port already in use":**
Windows: `netstat -ano | findstr :PORT`
Mac/Linux: `lsof -i :PORT`

**Proxy not working:**
Check `shopify_config.json` - active_proxies should have 67 items

## 📞 Support
Check console output for detailed error messages
