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
