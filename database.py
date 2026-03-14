import aiosqlite

# 数据库文件，Render会自动创建
DB_PATH = "database.db"

# 初始化数据库（卡密表+订单表）
async def init_db():
    conn = await aiosqlite.connect(DB_PATH)
    cur = await conn.cursor()
    # 卡密表（原结构保留，新增card唯一约束防重复）
    await cur.execute("""
    CREATE TABLE IF NOT EXISTS cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price INTEGER NOT NULL,
        card TEXT UNIQUE NOT NULL,
        status INTEGER NOT NULL DEFAULT 0
    )
    """)
    # 订单表（新增，记录用户支付信息，方便对账）
    await cur.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY NOT NULL,
        user_id INTEGER NOT NULL,
        price_cny INTEGER NOT NULL,
        price_usdt REAL NOT NULL,
        pay_link TEXT,
        is_paid INTEGER DEFAULT 0,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    await conn.commit()
    await conn.close()

# 新增卡密（原功能保留，加异常捕获）
async def add_card(price: int, card: str) -> bool:
    try:
        conn = await aiosqlite.connect(DB_PATH)
        cur = await conn.cursor()
        await cur.execute(
            "INSERT INTO cards(price, card, status) VALUES(?, ?, ?)",
            (price, card, CARD_UNUSED)
        )
        await conn.commit()
        await conn.close()
        return True
    except aiosqlite.IntegrityError:
        await conn.close()
        return False
    except Exception:
        await conn.close()
        return False

# 获取可用卡密（原功能保留，加行级锁防并发）
async def get_card(price: int) -> str | None:
    conn = await aiosqlite.connect(DB_PATH)
    cur = await conn.cursor()
    await cur.execute(
        "SELECT id, card FROM cards WHERE price=? AND status=? LIMIT 1 FOR UPDATE",
        (price, CARD_UNUSED)
    )
    row = await cur.fetchone()
    if row:
        await cur.execute("UPDATE cards SET status=? WHERE id=?", (CARD_USED, row[0]))
        await conn.commit()
        await conn.close()
        return row[1]
    await conn.close()
    return None

# 查询卡密库存（原功能保留）
async def get_stock(price: int) -> int:
    conn = await aiosqlite.connect(DB_PATH)
    cur = await conn.cursor()
    await cur.execute(
        "SELECT COUNT(*) FROM cards WHERE price=? AND status=?",
        (price, CARD_UNUSED)
    )
    count = (await cur.fetchone())[0]
    await conn.close()
    return count

# 创建订单（新增，关联用户和支付信息）
async def create_order(order_id: str, user_id: int, cny: int, usdt: float, link: str) -> bool:
    try:
        conn = await aiosqlite.connect(DB_PATH)
        cur = await conn.cursor()
        await cur.execute(
            "INSERT INTO orders VALUES(?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)",
            (order_id, user_id, cny, usdt, link)
        )
        await conn.commit()
        await conn.close()
        return True
    except Exception:
        await conn.close()
        return False
