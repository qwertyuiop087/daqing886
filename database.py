import sqlite3
DB = "cards.db"

def init():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cards
                 (price INT, card TEXT UNIQUE, status INT)''')
    conn.commit()
    conn.close()

def add(price, card):
    try:
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("INSERT INTO cards VALUES (?,?,0)", (price, card))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get(price):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT card FROM cards WHERE price=? AND status=0 LIMIT 1", (price,))
    res = c.fetchone()
    if res:
        c.execute("UPDATE cards SET status=1 WHERE card=?", (res[0],))
        conn.commit()
        conn.close()
        return res[0]
    conn.close()
    return None

def stock(price):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cards WHERE price=? AND status=0", (price,))
    cnt = c.fetchone()[0]
    conn.close()
    return cnt
