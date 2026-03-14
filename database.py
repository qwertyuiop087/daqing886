import sqlite3
import os

# 数据库文件路径，可通过环境变量 DATABASE_PATH 覆盖，默认当前目录下的 database.db
DB_PATH = os.environ.get("DATABASE_PATH", "database.db")

def get_connection():
    """获取数据库连接（每次调用新连接，避免多线程问题）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库表（启动时调用）"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price INTEGER,
            card TEXT,
            status INTEGER
        )
        """)
        conn.commit()

def add_card(price, card):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cards(price, card, status) VALUES (?, ?, 0)",
            (price, card)
        )
        conn.commit()

def get_card(price):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, card FROM cards WHERE price = ? AND status = 0 LIMIT 1",
            (price,)
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE cards SET status = 1 WHERE id = ?",
                (row[0],)
            )
            conn.commit()
            return row[1]
    return None

def stock(price):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM cards WHERE price = ? AND status = 0",
            (price,)
        )
        return cursor.fetchone()[0]
