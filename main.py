import os
import time
import hashlib
import requests
import sqlite3
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import telebot
from telebot.types import BotCommand, Message, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()

# === Config ===
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
    raise ValueError("BOT_TOKEN not set.")
if not ETHERSCAN_API_KEY:
    raise ValueError("ETHERSCAN_API_KEY not set.")

bot = telebot.TeleBot(BOT_TOKEN)

# Commands
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

# Bot description
bot.set_my_short_description("P2P Escrow · 3,728 monthly users")
bot.set_my_description(
    "P2P Escrow Bot for Telegram trades. "
    "3,728 monthly users · 170+ deals completed · 20 disputes resolved. "
    "Supported assets: BTC, LTC, ETH, USDT (ERC-20)."
)

# DB
conn = sqlite3.connect("group_escrow.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS group_escrows (
    group_id INTEGER PRIMARY KEY,
    creator_id INTEGER,
    buyer_id INTEGER,
    seller_id INTEGER,
    buyer_wallet TEXT,
    seller_wallet TEXT,
    asset TEXT,
    status TEXT DEFAULT 'initiated',
    created_at TEXT DEFAULT (datetime('now'))
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS pins (
    group_id INTEGER, user_id INTEGER, pin_hash TEXT,
    PRIMARY KEY (group_id, user_id)
)''')
conn.commit()

# Keyboard
def main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("/create"), KeyboardButton("/seller"),
        KeyboardButton("/buyer"), KeyboardButton("/asset"),
        KeyboardButton("/addpin"), KeyboardButton("/balance"),
        KeyboardButton("/releasefund"), KeyboardButton("/status"),
        KeyboardButton("/instructions"), KeyboardButton("/terms"),
        KeyboardButton("/about"), KeyboardButton("/help")
    )
    return markup

# Helpers
def is_group(msg):
    return msg.chat.type in ['group', 'supergroup']

def get_balance(asset, address):
    try:
        if asset in ['BTC', 'LTC']:
            r = requests.get(f"https://sochain.com/api/v2/get_address_balance/{asset}/{address}")
            if r.status_code == 200:
                d = r.json()
                if d.get('status') == 'success':
                    return d['data']['confirmed_balance']
        elif asset in ['ETH', 'USDT']:
            if asset == 'USDT':
                url = f"https://api.etherscan.io/api?module=account&action=tokenbalance&contractaddress=0xdAC17F958D2ee523a2206206994597C13D831ec7&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
                dec = 1e6
            else:
                url = f"https://api.etherscan.io/api?module=account&action=balance&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
                dec = 1e18
            r = requests.get(url)
            if r.status_code == 200:
                d = r.json()
                if d.get('status') == '1':
                    return str(int(d['result']) / dec)
    except: pass
    return None

def gen_code():
    import random, string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))

# === HANDLERS ===

@bot.message_handler(commands=['start'])
def start_handler(msg):
    # Send video only
    bot.send_video(chat_id=msg.chat.id, video="https://laoder5.wordpress.com/wp-content/uploads/2025/05/7916cb61-9e9d-431b-8121-e5ffcfee4349.mp4")
    
    text = (
        "P2P Escrow Bot\n\n"
        "Neutral escrow service for Telegram P2P trades.\n\n"
        "How it works:\n"
        "  /create - Set up escrow session\n"
        "  /seller <addr> - Register seller\n"
        "  /buyer <addr> - Register buyer\n"
        "  /asset <coin> - Pick asset\n"
        "  /addpin <pin> - Set your PIN\n"
        "  /releasefund <pin> - Release funds\n\n"
        "Stats: 3,728 monthly users | 170 deals | 20 disputes resolved\n"
        "Fees: 5% (>$100) | $5 flat (<$100)\n"
        "Assets: BTC | LTC | ETH | USDT\n\n"
        "Select a command below."
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(commands=['create', 'creategc'])
def create_handler(msg):
    user_id = msg.from_user.id
    chat_id = msg.chat.id
    
    if is_group(msg):
        cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row[0] not in ('completed', 'cancelled'):
            return bot.reply_to(msg, "Escrow already active in this group.")
        cursor.execute("REPLACE INTO group_escrows (group_id, status) VALUES (?, 'initiated')", (chat_id,))
        conn.commit()
        bot.reply_to(msg, "Escrow started. Register /seller and /buyer.")
        return
    
    bot.reply_to(msg, "/create\nCreating Escrow Group. Please Wait...")
    
    code = gen_code()
    cursor.execute("REPLACE INTO group_escrows (group_id, creator_id, status) VALUES (?, ?, 'initiated')",
                   (chat_id, user_id))
    conn.commit()
    
    bot.reply_to(msg,
        f"/create\n"
        f"Creating Escrow Group. Please Wait...\n\n"
        f"Created Escrow Group #{code}\n\n"
        f"Group Link: https://t.me/{bot.get_me().username}?startgroup=escrow_{code}\n\n"
        f"Now Join this escrow group & Forward this message to buyer/seller.\n\n"
        f"Enjoy Safe Escrow."
    )

@bot.message_handler(commands=['beginescrow'])
def begin_escrow(msg):
    if not is_group(msg):
        return bot.reply_to(msg, "Use this in a group.")
    gid = msg.chat.id
    cursor.execute("SELECT status FROM group_escrows WHERE group_id = ?", (gid,))
    row = cursor.fetchone()
    if row and row[0] not in ('completed', 'cancelled'):
        return bot.reply_to(msg, "Escrow already active.")
    cursor.execute("REPLACE INTO group_escrows (group_id, status) VALUES (?, 'initiated')", (gid,))
    conn.commit()
    bot.reply_to(msg, "Escrow activated. Register /seller and /buyer.")

@bot.message_handler(commands=['seller'])
def seller_handler(msg):
    p = msg.text.split()
    if len(p) != 2:
        return bot.reply_to(msg, "Usage: /seller <wallet_address>")
    cursor.execute("UPDATE group_escrows SET seller_id=?, seller_wallet=? WHERE group_id=?",
                   (msg.from_user.id, p[1], msg.chat.id))
    conn.commit()
    bot.reply_to(msg, f"SELLER\n  User: {msg.from_user.first_name}\n  Wallet: {p[1]}")

@bot.message_handler(commands=['buyer'])
def buyer_handler(msg):
    p = msg.text.split()
    if len(p) != 2:
        return bot.reply_to(msg, "Usage: /buyer <wallet_address>")
    cursor.execute("UPDATE group_escrows SET buyer_id=?, buyer_wallet=? WHERE group_id=?",
                   (msg.from_user.id, p[1], msg.chat.id))
    conn.commit()
    bot.reply_to(msg, f"BUYER\n  User: {msg.from_user.first_name}\n  Wallet: {p[1]}")

@bot.message_handler(commands=['asset', 'choose'])
def asset_handler(msg):
    p = msg.text.split()
    if len(p) != 2:
        return bot.reply_to(msg, f"Usage: /asset <coin>\nOptions: {', '.join(ASSET_WALLETS)}")
    a = p[1].upper()
    if a not in ASSET_WALLETS:
        return bot.reply_to(msg, f"Invalid. Options: {', '.join(ASSET_WALLETS)}")
    cursor.execute("UPDATE group_escrows SET asset=? WHERE group_id=?", (a, msg.chat.id))
    conn.commit()
    bot.reply_to(msg, f"ASSET: {a}\nSend funds to: {ASSET_WALLETS[a]}")

@bot.message_handler(commands=['addpin'])
def addpin_handler(msg):
    p = msg.text.split()
    if len(p) != 2 or not p[1].isdigit() or len(p[1]) not in (4, 6):
        return bot.reply_to(msg, "Usage: /addpin <4 or 6 digit PIN>")
    h = hashlib.sha256(p[1].encode()).hexdigest()
    cursor.execute("REPLACE INTO pins VALUES (?, ?, ?)", (msg.chat.id, msg.from_user.id, h))
    conn.commit()
    bot.reply_to(msg, "PIN stored.")

@bot.message_handler(commands=['editwallet'])
def edit_handler(msg):
    p = msg.text.split()
    if len(p) != 2:
        return bot.reply_to(msg, "Usage: /editwallet <new_address>")
    uid = msg.from_user.id
    gid = msg.chat.id
    cursor.execute("SELECT buyer_id, seller_id FROM group_escrows WHERE group_id=?", (gid,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(msg, "No active escrow.")
    if uid == row[0]:
        cursor.execute("UPDATE group_escrows SET buyer_wallet=? WHERE group_id=?", (p[1], gid))
        conn.commit()
        bot.reply_to(msg, f"BUYER WALLET UPDATED\n  {p[1]}")
    elif uid == row[1]:
        cursor.execute("UPDATE group_escrows SET seller_wallet=? WHERE group_id=?", (p[1], gid))
        conn.commit()
        bot.reply_to(msg, f"SELLER WALLET UPDATED\n  {p[1]}")
    else:
        bot.reply_to(msg, "Not part of this escrow.")

@bot.message_handler(commands=['balance'])
def balance_handler(msg):
    gid = msg.chat.id
    cursor.execute("SELECT asset, buyer_wallet FROM group_escrows WHERE group_id=?", (gid,))
    row = cursor.fetchone()
    if not row or not row[0] or not row[1]:
        return bot.reply_to(msg, "Set asset and buyer wallet first.")
    bal = get_balance(row[0], row[1])
    if bal is None:
        return bot.reply_to(msg, f"Balance fetch failed for {row[0]}.")
    bot.reply_to(msg, f"BALANCE\n  Asset: {row[0]}\n  Amount: {bal} {row[0]}")

@bot.message_handler(commands=['releasefund'])
def release_handler(msg):
    gid = msg.chat.id
    uid = msg.from_user.id
    cursor.execute("SELECT seller_wallet, asset, buyer_id FROM group_escrows WHERE group_id=?", (gid,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(msg, "No active escrow.")
    if uid != row[2]:
        return bot.reply_to(msg, "Only buyer can release.")
    p = msg.text.split()
    if len(p) < 2:
        return bot.reply_to(msg, "Usage: /releasefund <PIN>")
    h = hashlib.sha256(p[1].encode()).hexdigest()
    cursor.execute("SELECT pin_hash FROM pins WHERE group_id=? AND user_id=?", (gid, uid))
    pr = cursor.fetchone()
    if not pr or pr[0] != h:
        return bot.reply_to(msg, "Invalid PIN.")
    cursor.execute("UPDATE group_escrows SET status='completed' WHERE group_id=?", (gid,))
    conn.commit()
    bot.reply_to(msg, f"FUNDS RELEASED\n  Seller: {row[0]}\n  Asset: {row[1]}")

@bot.message_handler(commands=['adminresolve'])
def admin_resolve(msg):
    if msg.from_user.id != ADMIN_ID:
        return bot.reply_to(msg, "Admin only.")
    cursor.execute("DELETE FROM group_escrows WHERE group_id=?", (msg.chat.id,))
    conn.commit()
    bot.reply_to(msg, "Admin resolved.")

@bot.message_handler(commands=['status'])
def status_handler(msg):
    gid = msg.chat.id
    cursor.execute("SELECT buyer_wallet, seller_wallet, asset, status, created_at FROM group_escrows WHERE group_id=?", (gid,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(msg, "No active escrow.")
    bb = get_balance(row[2], row[0]) if row[0] and row[2] else "N/A"
    bot.reply_to(msg,
        f"STATUS\n"
        f"  State: {row[3].upper()}\n"
        f"  Asset: {row[2] or 'N/A'}\n"
        f"  Buyer: {row[0] or 'N/A'} ({bb})\n"
        f"  Seller: {row[1] or 'N/A'}\n"
        f"  Created: {row[4] or 'N/A'}")

@bot.message_handler(commands=['cancelescrow'])
def cancel_handler(msg):
    gid = msg.chat.id
    cursor.execute("SELECT status FROM group_escrows WHERE group_id=?", (gid,))
    row = cursor.fetchone()
    if not row:
        return bot.reply_to(msg, "No active escrow.")
    if row[0] == 'completed':
        return bot.reply_to(msg, "Already completed.")
    cursor.execute("DELETE FROM group_escrows WHERE group_id=?", (gid,))
    conn.commit()
    bot.reply_to(msg, "ESCROW CANCELLED")

@bot.message_handler(commands=['menu'])
def menu_handler(msg):
    bot.reply_to(msg,
        "MENU\n\n"
        "/create - New escrow\n"
        "/seller <addr> - Register seller\n"
        "/buyer <addr> - Register buyer\n"
        "/asset <coin> - Choose asset\n"
        "/addpin <pin> - Set PIN\n"
        "/editwallet <addr> - Fix wallet\n"
        "/balance - Check funds\n"
        "/releasefund <pin> - Release\n"
        "/cancelescrow - Cancel\n"
        "/status - View state\n"
        "/terms - Terms of service\n"
        "/instructions - Full guide\n"
        "/about - Bot info\n"
        "/help - Quick help\n"
        "/adminresolve - Admin only"
    )

@bot.message_handler(commands=['instructions'])
def instructions_handler(msg):
    bot.reply_to(msg,
        "INSTRUCTIONS\n\n"
        "1. /create - Prepare escrow session\n"
        "2. Add bot to group, use /beginescrow\n"
        "3. /seller <addr> - Register seller\n"
        "4. /buyer <addr> - Register buyer\n"
        "5. /asset BTC|LTC|ETH|USDT\n"
        "6. /addpin <pin> - Set PIN\n"
        "7. Buyer sends funds to escrow wallet\n"
        "8. /balance - Confirm deposit\n"
        "9. /releasefund <pin> - Release\n\n"
        "Cancel: /cancelescrow\n"
        "Fees: 5% (>$100) | $5 flat (<$100)")

@bot.message_handler(commands=['terms'])
def terms_handler(msg):
    bot.reply_to(msg,
        "TERMS\n\n"
        "1. Both parties must register wallets.\n"
        "2. Bot is a neutral intermediary.\n"
        "3. Fees: 5% (>$100) or $5 flat (<$100).\n"
        "4. PIN required for release.\n"
        "5. Admin resolves disputes.\n"
        "6. Cancel anytime before release.\n"
        "7. Bot not liable for user errors.\n"
        "8. Data: wallet addresses + user IDs stored temporarily.")

@bot.message_handler(commands=['about'])
def about_handler(msg):
    bot.reply_to(msg,
        "ABOUT\n\n"
        "P2P Escrow Bot\n"
        "By @streaks100\n\n"
        "3,728 monthly users\n"
        "170 deals completed\n"
        "20 disputes resolved\n\n"
        "Assets: BTC, LTC, ETH, USDT\n"
        "24/7 availability")

@bot.message_handler(commands=['help'])
def help_handler(msg):
    bot.reply_to(msg,
        "HELP\n\n"
        "Start: /start\n"
        "Create: /create\n"
        "Guide: /instructions\n"
        "Menu: /menu\n"
        "Terms: /terms\n\n"
        "Contact: @streaks100")

# === Webhook HTTP Server (no Flask) ===
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Escrow bot running!")
    
    def do_POST(self):
        if self.path == f"/{BOT_TOKEN}":
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            update = telebot.types.Update.de_json(json.loads(body))
            bot.process_new_updates([update])
        self.send_response(200)
        self.end_headers()

# === Start ===
if __name__ == '__main__':
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(WEBHOOK_URL)
    
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Listening on port {port}")
    server.serve_forever()
