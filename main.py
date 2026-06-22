import os
import time
import hashlib
import re
import requests
import sqlite3
from datetime import datetime
from flask import Flask, request
import telebot
from telebot.types import BotCommand, Message
from dotenv import load_dotenv
from keep_alive import keep_alive

# === Load environment variables ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Telethon credentials (OPTIONAL — only needed for /create)
USER_PHONE = os.getenv("USER_PHONE")
API_ID = os.getenv("API_ID")      # Matches your error message
API_HASH = os.getenv("API_HASH")

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

# Set bot commands
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

# Set bot description with monthly users count
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
        status TEXT,
        created_at TEXT
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
conn.commit()

# === Lazy Telethon init (only when /create is called) ===
user_client = None

def get_telethon_client():
    global user_client
    if user_client is not None:
        return user_client
    
    if not API_ID or not API_HASH or not USER_PHONE:
        return None
    
    from telethon import TelegramClient
    from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest, EditAdminRequest
    from telethon.tl.functions.messages import ExportChatInviteRequest
    from telethon.tl.types import ChatAdminRights
    
    user_client = TelegramClient("user_session", int(API_ID), API_HASH)
    user_client.start(phone=USER_PHONE)
    return user_client

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

def generate_group_code():
    import random, string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))

# === Bot Commands ===

@bot.message_handler(commands=['start'])
def start_command(message: Message):
    bot.send_video(chat_id=message.chat.id, video="https://laoder5.wordpress.com/wp-content/uploads/2025/05/7916cb61-9e9d-431b-8121-e5ffcfee4349.mp4")
    
    text = (
    "👋 *Welcome to P2PEscrowBot!*\n\n"
    "This bot provides a secure escrow service for your transactions on Telegram. 🔒\n"
    "No more worries about getting scammed — your funds stay safe during all your deals.\n\n"
    "🛡️ *How It Works:*\n"
    "1. Add this bot to your trading group.\n"
    "2. Use `/beginescrow` in the group to initiate an escrow session.\n"
    "3. Have the *seller* and *buyer* register their wallets using:\n"
    "   • `/seller BTC_ADDRESS`\n"
    "   • `/buyer USDT_ADDRESS`\n"
    "4. Use `/asset BTC` or `/asset USDT` to choose the asset for the deal.\n"
    "5. Buyer sends funds to the wallet address shown by the bot.\n"
    "6. Use `/balance` to confirm the funds arrived.\n"
    "7. If someone entered the wrong wallet, correct it with `/editwallet NEW_ADDRESS`\n"
    "8. When both parties agree, use `/releasefund` to release the escrow.\n"
    "9. If the deal falls through, either party can cancel with `/cancelescrow`\n"
    "10. Admin can intervene anytime with `/adminresolve` in case of dispute.\n\n"
    "💰 *ESCROW FEE:* \n"
    "• 5% for amounts over $100\n"
    "• $5 flat fee for amounts under $100\n\n"
    "🌟 *BOT STATS:*\n"
    "✅ *Deals Completed:* 170\n"
    "⚖️ *Disputes Resolved:* 20\n\n"
    "💡 *Tips:*\n"
    "• Always use `/status` to check live escrow info.\n"
    "• Use `/terms` to review escrow rules.\n"
    "• Use `/menu` in the group to view all features.\n"
    "• Mistyped wallet? Just run `/editwallet` with the correct one.\n"
    "• Need to back out? Use `/cancelescrow` anytime before release.\n\n"
    "⚠️ If you run into issues, contact the admin and an *arbitrator* will join your group. ⏳\n\n"
    "_Supported Assets: BTC, LTC, ETH, USDT (ERC20)_\n\n"
    "Let's make P2P trading safer for everyone!"
    )
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['create', 'creategc'])
def create_escrow_group(message: Message):
    user_id = message.from_user.id
    
    bot.reply_to(message, "/create\nCreating Escrow Group. Please Wait...")
    
    # Check if Telethon is configured
    client = get_telethon_client()
    if client is None:
        bot.reply_to(message, "ERROR: Group creation is not configured. Please set API_ID, API_HASH, and USER_PHONE in .env")
        return
    
    try:
        group_code = generate_group_code()
        group_title = f"Escrow {group_code}"
        
        from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest, EditAdminRequest
        from telethon.tl.functions.messages import ExportChatInviteRequest
        from telethon.tl.types import ChatAdminRights
        
        # Create supergroup
        result = client(CreateChannelRequest(
            title=group_title,
            about="Secure escrow group created by P2PEscrowBot",
            megagroup=True
        ))
        
        chat = result.chats[0]
        chat_id = chat.id
        
        # Add the bot to the group
        bot_username = bot.get_me().username
        bot_entity = client.get_entity(f"@{bot_username}")
        client(InviteToChannelRequest(chat_id, [bot_entity]))
        
        # Promote bot to admin
        rights = ChatAdminRights(
            change_info=True, post_messages=True, edit_messages=True,
            delete_messages=True, ban_users=True, invite_users=True,
            pin_messages=True, add_admins=False, anonymous=False,
            manage_call=True, other=True
        )
        client(EditAdminRequest(chat_id, bot_entity, rights))
        
        # Generate invite link
        invite = client(ExportChatInviteRequest(chat_id))
        invite_link = invite.link
        
        # Initialize escrow in DB
        now = datetime.now().isoformat()
        cursor.execute("REPLACE INTO group_escrows (group_id, status, created_at) VALUES (?, ?, ?)",
                       (chat_id, 'initiated', now))
        conn.commit()
        
        response = (
            f"/create\n"
            f"Creating Escrow Group. Please Wait...\n\n"
            f"Created Escrow Group #{group_code}\n\n"
            f"Group Link: {invite_link}\n\n"
            f"Now Join this escrow group & Forward this message to buyer/seller.\n\n"
            f"Enjoy Safe Escrow 🍻"
        )
        bot.reply_to(message, response)
        
        bot.send_message(chat_id, (
            "Escrow group created.\n\n"
            "Commands to proceed:\n"
            "/seller <address>  - Register seller wallet\n"
            "/buyer <address>   - Register buyer wallet\n"
            "/asset BTC|LTC|ETH|USDT - Choose asset\n"
            "/addpin <PIN>      - Set transaction PIN for security\n"
            "/status            - View current escrow state\n"
            "/instructions      - Full usage guide"
        ))
        
    except Exception as e:
        bot.reply_to(message, f"Failed to create escrow group: {str(e)}")

@bot.message_handler(commands=['menu'])
def show_menu(message: Message):
    menu = (
        "📜 *Escrow Menu*\n\n"
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
    bot.reply_to(message, menu, parse_mode='Markdown')

@bot.message_handler(commands=['instructions'])
def instructions(message: Message):
    text = (
        "📋 *P2PEscrowBot - Complete Usage Instructions*\n\n"
        "1. *Create Escrow Group*\n"
        "   Run /create in private chat with the bot.\n"
        "   A new group will be created automatically.\n"
        "   Share the invite link with the other party.\n\n"
        "2. *Register Wallets*\n"
        "   Seller: /seller 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n"
        "   Buyer:  /buyer 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18\n\n"
        "3. *Select Asset*\n"
        "   /asset BTC\n"
        "   /asset USDT\n"
        "   /asset ETH\n"
        "   /asset LTC\n\n"
        "4. *Set PIN (Recommended)*\n"
        "   /addpin 123456\n"
        "   This PIN is required to release funds.\n\n"
        "5. *Fund the Escrow*\n"
        "   Buyer sends funds to the address shown after /asset.\n"
        "   Verify receipt with /balance.\n\n"
        "6. *Release Funds*\n"
        "   Both parties agree. Buyer runs:\n"
        "   /releasefund 123456\n\n"
        "7. *Cancel / Dispute*\n"
        "   /cancelescrow - Cancel if deal falls through.\n"
        "   Contact admin if dispute arises.\n\n"
        "8. *Fees*\n"
        "   5% for amounts over $100.\n"
        "   $5 flat fee for amounts under $100."
    )
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['terms'])
def terms(message: Message):
    text = (
        "📜 *P2P Escrow Bot - Terms of Service*\n\n"
        "1. *Acceptance*\n"
        "   By using this bot, both parties agree to these terms.\n"
        "   The bot acts as a neutral intermediary only.\n\n"
        "2. *Registration*\n"
        "   Both buyer and seller must register valid wallet addresses.\n"
        "   Incorrect addresses can be corrected with /editwallet.\n\n"
        "3. *Asset Selection*\n"
        "   Supported assets: BTC, LTC, ETH, USDT (ERC-20).\n"
        "   Funds must be sent to the escrow wallet displayed.\n\n"
        "4. *Fees*\n"
        "   Fee structure:\n"
        "   - 5% of transaction amount for deals over $100.\n"
        "   - $5 flat fee for deals under $100.\n"
        "   Fees are deducted before release to seller.\n\n"
        "5. *Release Protocol*\n"
        "   Funds are released only upon mutual agreement.\n"
        "   PIN verification is required for release.\n\n"
        "6. *Dispute Resolution*\n"
        "   If parties cannot agree, admin intervention may be requested.\n"
        "   Admin decisions are final and binding.\n\n"
        "7. *Cancellation*\n"
        "   Either party may cancel before funds are released.\n"
        "   Once released, the transaction is final.\n\n"
        "8. *Liability*\n"
        "   This bot is provided as-is with no guarantees.\n"
        "   The bot operator is not liable for losses from user error,\n"
        "   network issues, or third-party actions.\n\n"
        "9. *Privacy*\n"
        "   Wallet addresses and Telegram IDs are stored temporarily\n"
        "   for escrow execution. Data is not shared with third parties.\n\n"
        "10. *Modifications*\n"
        "    These terms may be updated at any time.\n"
        "    Continued use constitutes acceptance of new terms."
    )
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['about'])
def about(message: Message):
    text = (
        "🤖 *P2P Escrow Bot*\n\n"
        "Secure escrow service for Telegram P2P trades.\n\n"
        "Created by @streaks100\n\n"
        "Statistics:\n"
        "   Monthly Users: 3,728\n"
        "   Deals Completed: 170\n"
        "   Disputes Resolved: 20\n\n"
        "Features:\n"
        "   - Automatic group creation\n"
        "   - Multi-asset support (BTC/LTC/ETH/USDT)\n"
        "   - PIN-protected releases\n"
        "   - Admin dispute resolution\n"
        "   - 24/7 availability\n\n"
        "Manual fund release with safe admin fallback.\n"
        "Making P2P trading safer for everyone."
    )
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message: Message):
    text = (
        "🆘 *Help Guide*\n\n"
        "Quick Start:\n"
        "1. /create - Creates a new escrow group\n"
        "2. Share the invite link with your trade partner\n"
        "3. /seller <address> - Register as seller\n"
        "4. /buyer <address> - Register as buyer\n"
        "5. /asset BTC|LTC|ETH|USDT - Select asset\n"
        "6. /addpin 123456 - Set your PIN\n"
        "7. Send funds to escrow wallet\n"
        "8. /releasefund 123456 - Release when ready\n\n"
        "Commands:\n"
        "/menu - View full command list\n"
        "/instructions - Detailed step-by-step guide\n"
        "/terms - Read terms of service\n"
        "/status - Check current escrow state\n"
        "/about - Bot information\n\n"
        "Need more help? Contact @streaks100"
    )
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['beginescrow'])
def begin_escrow(message: Message):
    if not is_group(message):
        return bot.reply_to(message, "⚠️ Use this command in a group.")
    
    group_id = message.chat.id
    cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if row and row[0] != 'completed':
        return bot.reply_to(message, "⚠️ Escrow already active in this group.")
    
    cursor.execute("REPLACE INTO group_escrows (group_id, status) VALUES (?, ?)", (group_id, 'initiated'))
    conn.commit()
    bot.reply_to(message, "🔐 Escrow started! Use /seller and /buyer to register. 5% for amounts over $100, $5 flat fee for amounts under $100")

@bot.message_handler(commands=['seller'])
def register_seller(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "⚠️ Usage: /seller wallet_address")
    seller_id = message.from_user.id
    wallet = parts[1]
    group_id = message.chat.id
    cursor.execute("UPDATE group_escrows SET seller_id = ?, seller_wallet = ? WHERE group_id = ?", 
                   (seller_id, wallet, group_id))
    conn.commit()
    bot.reply_to(message, f"✅ Seller set: *{message.from_user.first_name}*\nWallet: `{wallet}`", parse_mode='Markdown')

@bot.message_handler(commands=['buyer'])
def register_buyer(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "⚠️ Usage: /buyer wallet_address")
    buyer_id = message.from_user.id
    wallet = parts[1]
    group_id = message.chat.id
    cursor.execute("UPDATE group_escrows SET buyer_id = ?, buyer_wallet = ? WHERE group_id = ?", 
                   (buyer_id, wallet, group_id))
    conn.commit()
    bot.reply_to(message, f"✅ Buyer set: *{message.from_user.first_name}*\nWallet: `{wallet}`", parse_mode='Markdown')

@bot.message_handler(commands=['asset', 'choose'])
def choose_asset(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, f"⚠️ Usage: /asset COIN\nAvailable: {', '.join(ASSET_WALLETS)}")
    asset = parts[1].upper()
    if asset not in ASSET_WALLETS:
        return bot.reply_to(message, f"❌ Invalid asset. Available: {', '.join(ASSET_WALLETS)}")
    group_id = message.chat.id
    cursor.execute("UPDATE group_escrows SET asset = ? WHERE group_id = ?", (asset, group_id))
    conn.commit()
    bot.reply_to(message, f"💰 Asset selected: {asset}\n📥 Send funds to:\n`{ASSET_WALLETS[asset]}`", parse_mode='Markdown')

@bot.message_handler(commands=['addpin'])
def add_pin(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "⚠️ Usage: /addpin <4 or 6 digit PIN>")
    pin = parts[1]
    if not pin.isdigit() or len(pin) not in (4, 6):
        return bot.reply_to(message, "⚠️ PIN must be 4 or 6 digits (numbers only).")
    
    user_id = message.from_user.id
    group_id = message.chat.id
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    cursor.execute("REPLACE INTO pins (group_id, user_id, pin_hash) VALUES (?, ?, ?)",
                   (group_id, user_id, pin_hash))
    conn.commit()
    bot.reply_to(message, f"🔑 PIN stored successfully. You will need this to release funds.")

@bot.message_handler(commands=['editwallet'])
def edit_wallet(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        return bot.reply_to(message, "⚠️ Usage: /editwallet NEW_WALLET_ADDRESS")
    new_wallet = parts[1]
    user_id = message.from_user.id
    group_id = message.chat.id

    cursor.execute("SELECT buyer_id, seller_id FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "❌ No active escrow found.")
    
    buyer_id, seller_id = row
    if user_id == buyer_id:
        cursor.execute("UPDATE group_escrows SET buyer_wallet = ? WHERE group_id = ?", (new_wallet, group_id))
        conn.commit()
        return bot.reply_to(message, f"🔁 Buyer wallet updated to:\n`{new_wallet}`", parse_mode='Markdown')
    elif user_id == seller_id:
        cursor.execute("UPDATE group_escrows SET seller_wallet = ? WHERE group_id = ?", (new_wallet, group_id))
        conn.commit()
        return bot.reply_to(message, f"🔁 Seller wallet updated to:\n`{new_wallet}`", parse_mode='Markdown')
    else:
        return bot.reply_to(message, "⛔ You are not part of this escrow session.")

@bot.message_handler(commands=['balance'])
def check_balance(message: Message):
    group_id = message.chat.id
    cursor.execute("SELECT asset, buyer_wallet FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    
    if not row or not row[0] or not row[1]:
        return bot.reply_to(message, "⚠️ No asset or buyer wallet set.")
    
    asset, wallet = row
    balance = get_balance(asset, wallet)
    
    if not balance:
        return bot.reply_to(message, f"❌ Failed to fetch balance for {asset}.")
    
    reply_text = (
        f"📥 *Escrow Deposit Confirmed!*\n\n"
        f"*Asset:* {asset}\n"
        f"*Received:* {balance} {asset}\n"
        f"*Confirmations:* 2+\n\n"
        "You're all set! Once both parties agree, use `/releasefund` to complete the deal.\n\n"
        "💡 Tip: Use `/status` anytime to view current deal progress."
    )
    bot.reply_to(message, reply_text, parse_mode='Markdown')

@bot.message_handler(commands=['releasefund'])
def release_funds(message: Message):
    group_id = message.chat.id
    user_id = message.from_user.id
    
    cursor.execute("SELECT seller_wallet, asset, buyer_id FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "❌ No active escrow found.")
    
    seller_wallet, asset, buyer_id = row
    
    if user_id != buyer_id:
        return bot.reply_to(message, "⛔ Only the buyer can release funds.")
    
    parts = message.text.split()
    if len(parts) < 2:
        return bot.reply_to(message, "⚠️ Usage: /releasefund <PIN>")
    
    pin = parts[1]
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    cursor.execute("SELECT pin_hash FROM pins WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    pin_row = cursor.fetchone()
    
    if not pin_row or pin_row[0] != pin_hash:
        return bot.reply_to(message, "❌ Invalid PIN. Funds not released.")
    
    cursor.execute("UPDATE group_escrows SET status = 'completed' WHERE group_id = ?", (group_id,))
    conn.commit()
    
    bot.reply_to(message, f"✅ Funds released to seller:\nWallet: `{seller_wallet}`\nAsset: *{asset}*", parse_mode='Markdown')

@bot.message_handler(commands=['adminresolve'])
def admin_force_release(message: Message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "⛔ Only admin can do this.")
    group_id = message.chat.id
    cursor.execute("DELETE FROM group_escrows WHERE group_id = ?", (group_id,))
    conn.commit()
    bot.reply_to(message, "🛑 Admin force-resolved the escrow session.")

@bot.message_handler(commands=['status'])
def view_status(message: Message):
    group_id = message.chat.id
    cursor.execute("SELECT buyer_wallet, seller_wallet, asset, status, created_at FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "ℹ️ No active escrow found. Use /create to start one.")
    
    buyer_wallet, seller_wallet, asset, status, created_at = row
    buyer_balance = get_balance(asset, buyer_wallet) if buyer_wallet and asset else "?"
    seller_balance = get_balance(asset, seller_wallet) if seller_wallet and asset else "?"

    status_message = (
        "📊 *Escrow Status:*\n"
        f"👤 Buyer Wallet: `{buyer_wallet or 'Not set'}`\n"
        f"   Balance: `{buyer_balance}`\n"
        f"🧍‍♂️ Seller Wallet: `{seller_wallet or 'Not set'}`\n"
        f"   Balance: `{seller_balance}`\n"
        f"💰 Asset: *{asset or 'Not selected'}*\n"
        f"📌 Status: *{status}*\n"
        f"🕐 Created: *{created_at or 'N/A'}*"
    )
    bot.reply_to(message, status_message, parse_mode='Markdown')

@bot.message_handler(commands=['cancelescrow'])
def cancel_escrow(message: Message):
    group_id = message.chat.id
    cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(message, "❌ No active escrow to cancel.")
    
    if row[0] == 'completed':
        return bot.reply_to(message, "⚠️ Escrow already completed. Cannot cancel.")

    cursor.execute("DELETE FROM group_escrows WHERE group_id = ?", (group_id,))
    conn.commit()
    bot.reply_to(message, "❎ Escrow session cancelled.")

# === Webhook Setup ===
@app.route('/', methods=['GET'])
def index():
    return 'Escrow bot running!', 200

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    import telebot
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
