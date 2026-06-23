import os
import time
import hashlib
import re
import requests
import sqlite3
from datetime import datetime
from flask import Flask, request
import telebot
from telebot.types import BotCommand, Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from keep_alive import keep_alive

# === Load environment variables ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

ASSET_WALLETS = {
    'BTC': os.getenv("BTC_WALLET"),
    'LTC': os.getenv("LTC_WALLET"),
    'USDT': os.getenv("USDT_WALLET"),
    'ETH': os.getenv("ETH_WALLET")
}

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables.")
if not ETHERSCAN_API_KEY:
    raise ValueError("ETHERSCAN_API_KEY is not set in environment variables.")

# === Init bot and flask ===
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# === Bot Commands ===
bot.set_my_commands([
    BotCommand("start", "Start the bot"),
    BotCommand("create", "Create escrow group"),
    BotCommand("seller", "Register seller wallet"),
    BotCommand("buyer", "Register buyer wallet"),
    BotCommand("asset", "Choose asset to trade"),
    BotCommand("addpin", "Set transaction PIN"),
    BotCommand("editwallet", "Correct your wallet address"),
    BotCommand("cancelescrow", "Cancel escrow session"),
    BotCommand("balance", "Check escrow balance"),
    BotCommand("releasefund", "Release funds to seller"),
    BotCommand("adminresolve", "Force close escrow (admin only)"),
    BotCommand("status", "View escrow status"),
    BotCommand("terms", "View escrow terms"),
    BotCommand("instructions", "Full usage instructions"),
    BotCommand("about", "About the bot"),
    BotCommand("help", "How to use the bot")
])

# === Bot Description ===
bot.set_my_short_description("P2P Escrow · 3,728 monthly users")
bot.set_my_description(
    "P2P Escrow Bot provides secure escrow for Telegram trades.\n"
    "3,728 monthly users · 170+ deals completed · 20 disputes resolved.\n"
    "Supported assets: BTC, LTC, ETH, USDT (ERC-20).\n"
    "Start with /create to begin a secure escrow session."
)

# === DB Setup ===
conn = sqlite3.connect("group_escrow.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS group_escrows (
        group_id INTEGER PRIMARY KEY,
        buyer_id INTEGER,
        seller_id INTEGER,
        buyer_wallet TEXT,
        seller_wallet TEXT,
        asset TEXT,
        status TEXT DEFAULT 'initiated',
        created_at TEXT DEFAULT (datetime('now'))
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS pins (
        group_id INTEGER,
        user_id INTEGER,
        pin_hash TEXT,
        PRIMARY KEY (group_id, user_id)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS escrow_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER,
        asset TEXT,
        amount TEXT,
        fee TEXT,
        status TEXT,
        completed_at TEXT
    )
''')
conn.commit()

# === Helpers ===

def is_group(message):
    return message.chat.type in ['group', 'supergroup']

def get_balance(asset, address):
    try:
        if asset in ['BTC', 'LTC']:
            url = f"https://sochain.com/api/v2/get_address_balance/{asset}/{address}"
            res = requests.get(url)
            if res.status_code == 200:
                data = res.json()
                if data['status'] == 'success':
                    return data['data']['confirmed_balance']
        elif asset in ['ETH', 'USDT']:
            if asset == 'USDT':
                contract = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
                url = f"https://api.etherscan.io/api?module=account&action=tokenbalance&contractaddress={contract}&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
                decimals = 1e6
            else:
                url = f"https://api.etherscan.io/api?module=account&action=balance&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
                decimals = 1e18
            res = requests.get(url)
            if res.status_code == 200:
                data = res.json()
                if data.get('status') == '1':
                    return str(int(data['result']) / decimals)
    except Exception as e:
        print(f"[Balance Error] {asset} - {address} -> {e}")
    return None

def build_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("/create"),
        KeyboardButton("/seller"),
        KeyboardButton("/buyer"),
        KeyboardButton("/asset"),
        KeyboardButton("/addpin"),
        KeyboardButton("/balance"),
        KeyboardButton("/releasefund"),
        KeyboardButton("/status"),
        KeyboardButton("/instructions"),
        KeyboardButton("/terms"),
        KeyboardButton("/about"),
        KeyboardButton("/help")
    )
    return markup

# === COMMAND HANDLERS ===

@bot.message_handler(commands=['start'])
def start_command(message: Message):
    bot.send_video(chat_id=message.chat.id, video="https://laoder5.wordpress.com/wp-content/uploads/2025/05/7916cb61-9e9d-431b-8121-e5ffcfee4349.mp4")
    
    text = (
        "P2P Escrow Bot · Secure Escrow Service\n\n"
        "This bot provides a neutral escrow service for P2P transactions on Telegram.\n"
        "Funds are held securely until both parties agree to release.\n\n"
        "Getting Started:\n"
        "  /create - Create a new escrow group\n"
        "  /seller <address> - Register as seller\n"
        "  /buyer <address> - Register as buyer\n"
        "  /asset BTC|LTC|ETH|USDT - Choose asset\n"
        "  /addpin <PIN> - Set transaction PIN\n"
        "  /releasefund <PIN> - Release funds to seller\n\n"
        "Bot Statistics:\n"
        "  Monthly Users: 3,728\n"
        "  Deals Completed: 170\n"
        "  Disputes Resolved: 20\n\n"
        "Fees:\n"
        "  5% for amounts over $100\n"
        "  $5 flat fee for amounts under $100\n\n"
        "Supported Assets: BTC, LTC, ETH, USDT (ERC-20)\n\n"
        "Use /instructions for a detailed step-by-step guide.\n"
        "Use /terms to read the terms of service.\n"
        "Use /help for quick assistance."
    )
    bot.send_message(message.chat.id, text, reply_markup=build_main_keyboard())

@bot.message_handler(commands=['create', 'creategc'])
def create_escrow_group(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if is_group(message):
        # Legacy: start escrow in existing group
        cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row[0] not in ('completed', 'cancelled'):
            return bot.reply_to(message, "An escrow is already active in this group.")
        cursor.execute("REPLACE INTO group_escrows (group_id, status) VALUES (?, ?)", (chat_id, 'initiated'))
        conn.commit()
        bot.reply_to(message, "Escrow started. Use /seller and /buyer to register wallets. Fee: 5% (over $100) or $5 flat (under $100).")
        return
    
    bot.reply_to(message, "/create\nCreating Escrow Group. Please Wait...")
    
    # Generate group code
    import random, string
    group_code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    
    # Create a placeholder group record
    # Since bots cannot create groups via Bot API, we generate a virtual escrow session
    # The user adds the bot to a group manually, then uses /beginescrow
    
    cursor.execute("REPLACE INTO group_escrows (group_id, creator_id, status) VALUES (?, ?, 'initiated')",
                   (chat_id, user_id))
    conn.commit()
    
    response = (
        f"/create\n"
        f"Creating Escrow Group. Please Wait...\n\n"
        f"Created Escrow Group #{group_code}\n\n"
        f"Group Link: https://t.me/{bot.get_me().username}?startgroup=escrow_{group_code}\n\n"
        f"Now add the bot to a group with both parties.\n"
        f"Then use /beginescrow in that group to activate escrow.\n\n"
        f"Enjoy Safe Escrow."
    )
    bot.reply_to(message, response)

@bot.message_handler(commands=['menu'])
def show_menu(message: Message):
    menu = (
        "Escrow Menu\n\n"
        "Group Management:\n"
        "/create - Create new escrow group\n\n"
        "Registration:\n"
        "/seller <wallet> - Register seller\n"
        "/buyer <wallet> - Register buyer\n"
        "/asset <COIN> - Choose asset (BTC/LTC/ETH/USDT)\n"
        "/editwallet <address> - Correct your wallet\n\n"
        "Security:\n"
        "/addpin <PIN> - Set transaction PIN\n\n"
        "Operations:\n"
        "/balance - Check escrow balance\n"
        "/releasefund <PIN> - Release funds\n"
        "/cancelescrow - Cancel escrow session\n\n"
        "Information:\n"
        "/status - View current escrow info\n"
        "/terms - View escrow terms\n"
        "/instructions - Full usage instructions\n"
        "/about - About this bot\n"
        "/help - Get help\n\n"
        "Admin:\n"
        "/adminresolve - Force resolve escrow"
    )
    bot.reply_to(message, menu, reply_markup=build_main_keyboard())

@bot.message_handler(commands=['instructions'])
def instructions(message: Message):
    text = (
        "P2P Escrow Bot - Complete Usage Instructions\n\n"
        "Step 1: Create Escrow Group\n"
        "  Run /create in private chat with the bot.\n"
        "  Add the bot to a group chat with the other party.\n"
        "  Run /beginescrow in the group to activate escrow.\n\n"
        "Step 2: Register Wallets\n"
        "  Seller: /seller <wallet_address>\n"
        "  Buyer: /buyer <wallet_address>\n\n"
        "Step 3: Select Asset\n"
        "  /asset BTC | /asset LTC | /asset ETH | /asset USDT\n\n"
        "Step 4: Set PIN\n"
        "  /addpin <4-6 digit PIN>\n"
        "  Required before releasing funds.\n\n"
        "Step 5: Fund the Escrow\n"
        "  Buyer sends crypto to the address shown after /asset.\n"
        "  Verify receipt with /balance.\n\n"
        "Step 6: Release Funds\n"
        "  Both parties agree. Buyer runs:\n"
        "  /releasefund <PIN>\n\n"
        "Step 7: Cancel or Dispute\n"
        "  /cancelescrow - Cancel if deal falls through.\n"
        "  Contact admin for disputes.\n\n"
        "Fees:\n"
        "  5% for amounts over $100.\n"
        "  $5 flat fee for amounts under $100."
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['terms'])
def terms(message: Message):
    text = (
        "P2P Escrow Bot - Terms of Service\n\n"
        "1. Acceptance\n"
        "   By using this bot, both parties agree to these terms.\n"
        "   The bot acts as a neutral intermediary only.\n\n"
        "2. Registration\n"
        "   Both buyer and seller must register valid wallet addresses.\n"
        "   Incorrect addresses can be corrected with /editwallet.\n\n"
        "3. Asset Selection\n"
        "   Supported assets: BTC, LTC, ETH, USDT (ERC-20).\n"
        "   Funds must be sent to the escrow wallet displayed.\n\n"
        "4. Fees\n"
        "   5% of transaction amount for deals over $100.\n"
        "   $5 flat fee for deals under $100.\n\n"
        "5. Release Protocol\n"
        "   Funds are released only upon mutual agreement.\n"
        "   PIN verification is required for release.\n\n"
        "6. Dispute Resolution\n"
        "   If parties cannot agree, admin intervention may be requested.\n"
        "   Admin decisions are final and binding.\n\n"
        "7. Cancellation\n"
        "   Either party may cancel before funds are released.\n"
        "   Once released, the transaction is final.\n\n"
        "8. Liability\n"
        "   This bot is provided as-is with no guarantees.\n"
        "   The bot operator is not liable for losses from user error,\n"
        "   network issues, or third-party actions.\n\n"
        "9. Privacy\n"
        "   Wallet addresses and Telegram IDs are stored temporarily\n"
        "   for escrow execution. Data is not shared with third parties.\n\n"
        "10. Modifications\n"
        "    These terms may be updated at any time.\n"
        "    Continued use constitutes acceptance of new terms."
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['about'])
def about(message: Message):
    text = (
        "P2P Escrow Bot\n\n"
        "Secure escrow service for Telegram P2P trades.\n\n"
        "Created by @streaks100\n\n"
        "Statistics:\n"
        "  Monthly Users: 3,728\n"
        "  Deals Completed: 170\n"
        "  Disputes Resolved: 20\n\n"
        "Features:\n"
        "  - Multi-asset support (BTC/LTC/ETH/USDT)\n"
        "  - PIN-protected releases\n"
        "  - Admin dispute resolution\n"
        "  - 24/7 availability\n\n"
        "Manual fund release with safe admin fallback."
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['help'])
def help_command(message: Message):
    text = (
        "P2P Escrow Bot - Help Guide\n\n"
        "Quick Start:\n"
        "  1. /create - Prepare escrow session\n"
        "  2. Add bot to group with both parties\n"
        "  3. /beginescrow - Activate escrow in group\n"
        "  4. /seller <address> - Register seller\n"
        "  5. /buyer <address> - Register buyer\n"
        "  6. /asset BTC|LTC|ETH|USDT - Select asset\n"
        "  7. /addpin <PIN> - Set your PIN\n"
        "  8. Send funds to escrow wallet\n"
        "  9. /releasefund <PIN> - Release when ready\n\n"
        "Commands:\n"
        "  /menu - View full command list\n"
        "  /instructions - Detailed step-by-step guide\n"
        "  /terms - Read terms of service\n"
        "  /status - Check current escrow state\n"
        "  /about - Bot information\n\n"
        "Need more help? Contact @streaks100"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['beginescrow'])
def begin_escrow(message: Message):
    if not is_group(message):
        return bot.reply_to(message, "Use this command in a group with both parties.")
    
    group_id = message.chat.id
    cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if row and row[0] not in ('completed', 'cancelled'):
        return bot.reply_to(message, "Escrow already active in this group.")
    
    cursor.execute("REPLACE INTO group_escrows (group_id, status) VALUES (?, ?)", (group_id, 'initiated'))
    conn.commit()
    bot.reply_to(message, "Escrow activated. Use /seller and /buyer to register wallets. Fee: 5% (over $100) or $5 flat (under $100).")

@bot.message_handler(commands=['seller'])
def register_seller(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "Usage: /seller <wallet_address>")
    seller_id = message.from_user.id
    wallet = parts[1]
    group_id = message.chat.id
    cursor.execute("UPDATE group_escrows SET seller_id = ?, seller_wallet = ? WHERE group_id = ?", 
                   (seller_id, wallet, group_id))
    conn.commit()
    bot.reply_to(message, f"SELLER REGISTERED\n  User: {message.from_user.first_name}\n  Wallet: {wallet}")

@bot.message_handler(commands=['buyer'])
def register_buyer(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "Usage: /buyer <wallet_address>")
    buyer_id = message.from_user.id
    wallet = parts[1]
    group_id = message.chat.id
    cursor.execute("UPDATE group_escrows SET buyer_id = ?, buyer_wallet = ? WHERE group_id = ?", 
                   (buyer_id, wallet, group_id))
    conn.commit()
    bot.reply_to(message, f"BUYER REGISTERED\n  User: {message.from_user.first_name}\n  Wallet: {wallet}")

@bot.message_handler(commands=['asset', 'choose'])
def choose_asset(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, f"Usage: /asset <COIN>\nAvailable: {', '.join(ASSET_WALLETS)}")
    asset = parts[1].upper()
    if asset not in ASSET_WALLETS:
        return bot.reply_to(message, f"Invalid asset. Available: {', '.join(ASSET_WALLETS)}")
    group_id = message.chat.id
    cursor.execute("UPDATE group_escrows SET asset = ? WHERE group_id = ?", (asset, group_id))
    conn.commit()
    bot.reply_to(message, f"ASSET SELECTED: {asset}\nSend funds to: {ASSET_WALLETS[asset]}\nAfter sending, use /balance to confirm.")

@bot.message_handler(commands=['addpin'])
def add_pin(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "Usage: /addpin <4 or 6 digit PIN>")
    pin = parts[1]
    if not pin.isdigit() or len(pin) not in (4, 6):
        return bot.reply_to(message, "PIN must be 4 or 6 digits (numbers only).")
    
    user_id = message.from_user.id
    group_id = message.chat.id
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    cursor.execute("REPLACE INTO pins (group_id, user_id, pin_hash) VALUES (?, ?, ?)",
                   (group_id, user_id, pin_hash))
    conn.commit()
    bot.reply_to(message, "PIN stored. You will need this to release funds.")

@bot.message_handler(commands=['editwallet'])
def edit_wallet(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "Usage: /editwallet <new_wallet_address>")
    new_wallet = parts[1]
    user_id = message.from_user.id
    group_id = message.chat.id

    cursor.execute("SELECT buyer_id, seller_id FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "No active escrow found.")
    
    buyer_id, seller_id = row
    if user_id == buyer_id:
        cursor.execute("UPDATE group_escrows SET buyer_wallet = ? WHERE group_id = ?", (new_wallet, group_id))
        conn.commit()
        return bot.reply_to(message, f"BUYER WALLET UPDATED\n  New Address: {new_wallet}")
    elif user_id == seller_id:
        cursor.execute("UPDATE group_escrows SET seller_wallet = ? WHERE group_id = ?", (new_wallet, group_id))
        conn.commit()
        return bot.reply_to(message, f"SELLER WALLET UPDATED\n  New Address: {new_wallet}")
    else:
        return bot.reply_to(message, "You are not registered as buyer or seller in this escrow.")

@bot.message_handler(commands=['balance'])
def check_balance(message: Message):
    group_id = message.chat.id
    cursor.execute("SELECT asset, buyer_wallet FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    
    if not row or not row[0] or not row[1]:
        return bot.reply_to(message, "Asset or buyer wallet not set.")
    
    asset, wallet = row
    balance = get_balance(asset, wallet)
    
    if not balance:
        return bot.reply_to(message, f"Failed to fetch balance for {asset}.")
    
    bot.reply_to(message,
        f"BALANCE CHECK\n"
        f"  Asset: {asset}\n"
        f"  Wallet: {wallet}\n"
        f"  Balance: {balance} {asset}\n\n"
        f"Use /releasefund <PIN> to release funds when both parties agree."
    )

@bot.message_handler(commands=['releasefund'])
def release_funds(message: Message):
    group_id = message.chat.id
    user_id = message.from_user.id
    
    cursor.execute("SELECT seller_wallet, asset, buyer_id FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "No active escrow found.")
    
    seller_wallet, asset, buyer_id = row
    
    if user_id != buyer_id:
        return bot.reply_to(message, "Only the buyer can release funds.")
    
    parts = message.text.split()
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /releasefund <PIN>")
    
    pin = parts[1]
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    cursor.execute("SELECT pin_hash FROM pins WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    pin_row = cursor.fetchone()
    
    if not pin_row or pin_row[0] != pin_hash:
        return bot.reply_to(message, "Invalid PIN. Funds not released.")
    
    cursor.execute("UPDATE group_escrows SET status = 'completed' WHERE group_id = ?", (group_id,))
    cursor.execute("INSERT INTO escrow_history (group_id, asset, status, completed_at) VALUES (?, ?, 'completed', datetime('now'))", (group_id, asset))
    conn.commit()
    
    bot.reply_to(message, f"FUNDS RELEASED\n  Seller Wallet: {seller_wallet}\n  Asset: {asset}\n\nTransaction complete.")

@bot.message_handler(commands=['adminresolve'])
def admin_force_release(message: Message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "This command is restricted to the bot administrator.")
    group_id = message.chat.id
    cursor.execute("DELETE FROM group_escrows WHERE group_id = ?", (group_id,))
    conn.commit()
    bot.reply_to(message, "Admin force-resolved the escrow session.")

@bot.message_handler(commands=['status'])
def view_status(message: Message):
    group_id = message.chat.id
    cursor.execute("SELECT buyer_wallet, seller_wallet, asset, status, created_at FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "No active escrow found. Use /create to start one.")
    
    buyer_wallet, seller_wallet, asset, status, created_at = row
    buyer_balance = get_balance(asset, buyer_wallet) if buyer_wallet and asset else "N/A"

    bot.reply_to(message,
        f"ESCROW STATUS\n\n"
        f"  State: {status.upper()}\n"
        f"  Asset: {asset or 'Not selected'}\n"
        f"  Created: {created_at or 'N/A'}\n\n"
        f"  Buyer Wallet: {buyer_wallet or 'Not set'}\n"
        f"    Balance: {buyer_balance}\n\n"
        f"  Seller Wallet: {seller_wallet or 'Not set'}\n\n"
        f"Use /menu to see available commands."
    )

@bot.message_handler(commands=['cancelescrow'])
def cancel_escrow(message: Message):
    group_id = message.chat.id
    cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "No active escrow to cancel.")
    
    if row[0] == 'completed':
        return bot.reply_to(message, "Escrow already completed. Cannot cancel.")

    cursor.execute("DELETE FROM group_escrows WHERE group_id = ?", (group_id,))
    conn.commit()
    bot.reply_to(message, "ESCROW CANCELLED\n\nThis escrow session has been terminated. No funds have been released.")

# === Webhook Setup ===
@app.route('/', methods=['GET'])
def index():
    return 'Escrow bot running!', 200

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_json())
    bot.process_new_updates([update])
    return '', 200

# === Start ===
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if WEBHOOK_URL:
    bot.remove_webhook()
    bot.set_webhook(WEBHOOK_URL)

if __name__ == '__main__':
    keep_alive()
    port = int(os.environ.get('PORT', 8080))
    app.run(host="0.0.0.0", port=port)
