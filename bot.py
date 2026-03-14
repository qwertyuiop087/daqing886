# 纯内置库版本，无任何外部依赖
import sqlite3
import random
import hashlib
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= 配置 =================
BOT_TOKEN = "你的机器人Token"
ADMIN_ID = 123456789

SHOP_ID = "29681"
SHOP_TOKEN = "8dDikTGgRuxy5ABCsEIKOPb3pL0tr47"
PAY_API = "https://okpay.com/api/deposit"
CNY_TO_USDT = 0.14

# ================= 数据库 =================
DB = "cards.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cards
                 (price INT, card TEXT UNIQUE, status INT)''')
    conn.commit()
    conn.close()

def add_card(price, card):
    try:
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("INSERT INTO cards VALUES (?,?,0)", (price, card))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_card(price):
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

def get_stock(price):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cards WHERE price=? AND status=0", (price,))
    cnt = c.fetchone()[0]
    conn.close()
    return cnt

# ================= OKPAY 支付 =================
def okpay_sign(data):
    s = sorted(data.items())
    text = "&".join(f"{k}={v}" for k, v in s) + SHOP_TOKEN
    return hashlib.md5(text.encode()).hexdigest()

def create_pay_link(price_cny):
    order_id = f"ORD{random.randint(100000,999999)}"
    usdt = price_cny * CNY_TO_USDT
    data = {
        "shopId": SHOP_ID,
        "orderId": order_id,
        "amount": round(usdt, 2),
        "coin": "USDT"
    }
    data["sign"] = okpay_sign(data)
    try:
        r = requests.post(PAY_API, json=data, timeout=10)
        return order_id, r.json()["data"]["payLink"]
    except:
        return None, None

# ================= 机器人 =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
init_db()

@dp.message_handler(commands=["start"])
async def start(msg):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("10元", callback_data="10"))
    kb.add(InlineKeyboardButton("30元", callback_data="30"))
    kb.add(InlineKeyboardButton("50元", callback_data="50"))
    await msg.answer("卡密商店", reply_markup=kb)

@dp.callback_query_handler()
async def buy(call):
    await call.answer()
    price = int(call.data)
    if get_stock(price) == 0:
        await call.message.answer("⚠️ 库存不足")
        return

    order_id, link = create_pay_link(price)
    if not link:
        await call.message.answer("❌ 支付创建失败")
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💳 去支付", url=link))
    await call.message.answer(
        f"✅ 订单创建成功\n"
        f"订单号：{order_id}\n"
        f"支付金额：{price*CNY_TO_USDT:.2f} USDT\n"
        f"请完成支付后联系管理员领取卡密～",
        reply_markup=kb
    )

# ================= 管理员导入 =================
async def admin_add(msg, price):
    if msg.from_user.id != ADMIN_ID:
        return
    lines = msg.text.split("\n")[1:]
    ok, no = 0, 0
    for card in lines:
        card = card.strip()
        if card and add_card(price, card):
            ok += 1
        else:
            no += 1
    await msg.answer(f"✅ 导入完成\n成功：{ok}\n失败：{no}")

@dp.message_handler(commands=["add10"])
async def add10(msg): await admin_add(msg, 10)

@dp.message_handler(commands=["add30"])
async def add30(msg): await admin_add(msg, 30)

@dp.message_handler(commands=["add50"])
async def add50(msg): await admin_add(msg, 50)

@dp.message_handler(commands=["stock"])
async def stock(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer(
        f"📊 库存\n10元：{get_stock(10)}\n30元：{get_stock(30)}\n50元：{get_stock(50)}"
    )

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
