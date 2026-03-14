import sqlite3
import os

# Render 服务器唯一持久化目录，避免卡密随容器重启丢失
DB_PATH = os.path.join("/tmp", "cards.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS cards(card TEXT,status INTEGER)")
    conn.commit()
    conn.close()

def add_card(card):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO cards VALUES (?,0)", (card,))
    conn.commit()
    conn.close()

def get_card():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT card FROM cards WHERE status=0 LIMIT 1")
    card = c.fetchone()
    if card:
        c.execute("UPDATE cards SET status=1 WHERE card=?", (card[0],))
        conn.commit()
    conn.close()
    return card[0] if card else None
