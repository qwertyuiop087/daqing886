import aiosqlite

# 数据库文件路径
DB_PATH = "database.db"

# 初始化数据库表
async def init_db():
    conn = await aiosqlite.connect(DB_PATH)
    cursor = await conn.cursor()
    # 卡密表
    await cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        price INTEGER NOT NULL,  # 卡密面值（人民币）
        card TEXT UNIQUE NOT NULL,  # 卡密内容，唯一防重复
        status INTEGER NOT NULL     # 0-未使用 1-已使用
    )
    """)
    # 订单表（新增，记录支付/卡密发放状态）
    await cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY NOT NULL,
        user_id INTEGER NOT NULL,    # 下单用户ID
        price_cny INTEGER NOT NULL,  # 订单面值（人民币）
        price_usdt REAL NOT NULL,    # 支付金额（USDT）
        pay_link TEXT,               # 支付链接
        is_paid INTEGER DEFAULT 0,   # 0-未支付 1-已支付
        card_id INTEGER,             # 关联的卡密ID
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    await conn.commit()
    await conn.close()

# 新增卡密
async def add_card(price: int, card: str) -> bool:
    try:
        conn = await aiosqlite.connect(DB_PATH)
        cursor = await conn.cursor()
        await cursor.execute(
            "INSERT INTO cards(price, card, status) VALUES(?, ?, ?)",
            (price, card, 0)
        )
        await conn.commit()
        await conn.close()
        return True
    except aiosqlite.IntegrityError:
        # 卡密重复
        await conn.close()
        return False
    except Exception:
        await conn.close()
        return False

# 获取可用卡密（并标记为已使用）
async def get_card(price: int) -> str | None:
    conn = await aiosqlite.connect(DB_PATH)
    cursor = await conn.cursor()
    # 行级锁，防止并发领取同一卡密
    await cursor.execute(
        "SELECT id, card FROM cards WHERE price=? AND status=? LIMIT 1 FOR UPDATE",
        (price, 0)
    )
    row = await cursor.fetchone()
    if row:
        card_id, card_code = row
        await cursor.execute(
            "UPDATE cards SET status=? WHERE id=?",
            (1, card_id)
        )
        await conn.commit()
        await conn.close()
        return card_code
    await conn.close()
    return None

# 查询卡密库存
async def get_card_stock(price: int) -> int:
    conn = await aiosqlite.connect(DB_PATH)
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT COUNT(*) FROM cards WHERE price=? AND status=?",
        (price, 0)
    )
    count = (await cursor.fetchone())[0]
    await conn.close()
    return count

# 创建订单
async def create_order(order_id: str, user_id: int, price_cny: int, price_usdt: float, pay_link: str) -> bool:
    try:
        conn = await aiosqlite.connect(DB_PATH)
        cursor = await conn.cursor()
        await cursor.execute(
            "INSERT INTO orders(order_id, user_id, price_cny, price_usdt, pay_link) VALUES(?, ?, ?, ?, ?)",
            (order_id, user_id, price_cny, price_usdt, pay_link)
        )
        await conn.commit()
        await conn.close()
        return True
    except Exception:
        await conn.close()
        return False

# 更新订单为已支付，并关联卡密
async def update_order_paid(order_id: str, card_id: int = None) -> bool:
    try:
        conn = await aiosqlite.connect(DB_PATH)
        cursor = await conn.cursor()
        await cursor.execute(
            "UPDATE orders SET is_paid=?, card_id=? WHERE order_id=?",
            (1, card_id, order_id)
        )
        await conn.commit()
        await conn.close()
        return True
    except Exception:
        await conn.close()
        return False

# 查询订单信息
async def get_order(order_id: str) -> dict | None:
    conn = await aiosqlite.connect(DB_PATH)
    cursor = await conn.cursor()
    await cursor.execute(
        "SELECT * FROM orders WHERE order_id=?",
        (order_id,)
    )
    row = await cursor.fetchone()
    if row:
        order = {
            "order_id": row[0],
            "user_id": row[1],
            "price_cny": row[2],
            "price_usdt": row[3],
            "pay_link": row[4],
            "is_paid": row[5],
            "card_id": row[6],
            "create_time": row[7]
        }
        await conn.close()
        return order
    await conn.close()
    return None
