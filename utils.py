import os

def create_tables(cursor):
    """Ensure all required tables exist."""
    cursor.execute("""
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
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pins (
            group_id INTEGER,
            user_id INTEGER,
            pin_hash TEXT,
            PRIMARY KEY (group_id, user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_escrows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            buyer_wallet TEXT,
            seller_wallet TEXT,
            asset TEXT,
            amount TEXT,
            fee TEXT,
            completed_at TEXT
        )
    """)

# These legacy functions are kept for backward compatibility
# but the new system uses main.py's direct DB access

def create_escrow(message, cursor, conn, bot):
    chat_id = message.chat.id
    cursor.execute("SELECT * FROM escrows WHERE chat_id = ?", (chat_id,))
    if cursor.fetchone():
        return bot.send_message(chat_id, "⚠️ You already have an active escrow. Use /status to view it.")
    cursor.execute(
        "INSERT INTO escrows (chat_id, confirmed_users, cancelled) VALUES (?, ?, ?)",
        (chat_id, "", 0)
    )
    conn.commit()
    bot.send_message(chat_id, f"✅ Escrow started!\n{get_wallets()}", parse_mode='Markdown')

def confirm_escrow(message, cursor, conn, bot):
    chat_id = message.chat.id
    user_id = str(message.from_user.id)
    cursor.execute("SELECT confirmed_users FROM escrows WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    if not row:
        return bot.send_message(chat_id, "❌ No active escrow. Use /escrow to start one.")
    confirmed_users = row[0].split(",") if row[0] else []
    if user_id not in confirmed_users:
        confirmed_users.append(user_id)
        cursor.execute("UPDATE escrows SET confirmed_users = ? WHERE chat_id = ?", (",".join(confirmed_users), chat_id))
        conn.commit()
    if len(confirmed_users) >= 2:
        bot.send_message(chat_id, "✅ Both users confirmed! Escrow complete. Funds can now be released.")
    else:
        bot.send_message(chat_id, "☑️ Your confirmation is recorded. Waiting for the second party...")

def cancel_escrow(message, cursor, conn, bot):
    chat_id = message.chat.id
    cursor.execute("SELECT * FROM escrows WHERE chat_id = ?", (chat_id,))
    if not cursor.fetchone():
        return bot.send_message(chat_id, "❌ No active escrow to cancel.")
    cursor.execute("UPDATE escrows SET cancelled = 1 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    bot.send_message(chat_id, "❌ Escrow has been cancelled.")

def get_status(message, cursor, bot):
    chat_id = message.chat.id
    cursor.execute("SELECT confirmed_users, cancelled FROM escrows WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    if not row:
        return bot.send_message(chat_id, "ℹ️ You have no active escrow.")
    confirmed = len(row[0].split(",")) if row[0] else 0
    cancelled = bool(row[1])
    bot.send_message(message.chat.id, f"🔒 *Escrow Status*:\n- Confirmations: {confirmed}/2\n- Cancelled: {'✅ Yes' if cancelled else '❌ No'}", parse_mode='Markdown')

def get_wallets():
    return f"""
💼 *Send Crypto to Escrow*:
₿ *BTC*: `{os.getenv("BTC_ADDRESS")}`
Ł *LTC*: `{os.getenv("LTC_ADDRESS")}`
Ξ *ETH*: `{os.getenv("ETH_ADDRESS")}`
💲 *USDT*: `{os.getenv("USDT_ADDRESS")}`
"""

def verify_wallet(message, bot):
    bot.send_message(message.chat.id, get_wallets(), parse_mode='Markdown')
