import sqlite3
import random
import hashlib
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= 配置 =================
BOT_TOKEN = "7750611624:AAHlHYVD7aXqQr1aZw3FOWxKO_msw5G0DJU"
ADMIN_ID = 7793291484  # 填你的数字ID

SHOP_ID = "29681"
SHOP_TOKEN = "8dDikTGgRuxy5ABCsEIKOPb3pL0tr47"
PAY_API_URL = "https://okpay.com/api/deposit"
CNY_TO_USDT_RATE = 0.14  # 汇率

# ================= 数据库 (内置sqlite3) =================
DB_FILE = "cards.db"

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 卡密表: price(面值), card(卡密内容), status(0未使用 1已使用)
    c.execute('''CREATE TABLE IF NOT EXISTS cards
                 (price INT, card TEXT UNIQUE, status INT)''')
    conn.commit()
    conn.close()

def add_card_to_db(price, card_code):
    """添加卡密到数据库"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO cards VALUES (?,?, 0)", (price, card_code))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False
    except Exception:
        return False

def get_random_card(price):
    """获取一张可用的卡密并标记为已使用"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 先查询
    c.execute("SELECT card FROM cards WHERE price=? AND status=0 LIMIT 1", (price,))
    res = c.fetchone()
    if res:
        # 标记为已使用
        c.execute("UPDATE cards SET status=1 WHERE card=?", (res[0],))
        conn.commit()
        conn.close()
        return res[0]
    conn.close()
    return None

def get_stock(price):
    """查询库存"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM cards WHERE price=? AND status=0", (price,))
    count = c.fetchone()[0]
    conn.close()
    return count

# ================= OKPAY 支付逻辑 =================
def okpay_sign(data):
    """生成OKPAY签名(按key排序)"""
    sorted_items = sorted(data.items())
    sign_str = "&".join(f"{k}={v}" for k, v in sorted_items) + SHOP_TOKEN
    return hashlib.md5(sign_str.encode()).hexdigest()

def create_pay_order(price_cny):
    """创建支付订单并返回链接"""
    order_id = f"ORD{random.randint(100000, 999999)}"
    usdt_amount = price_cny * CNY_TO_USDT_RATE
    
    payload = {
        "shopId": SHOP_ID,
        "orderId": order_id,
        "amount": round(usdt_amount, 2),
        "coin": "USDT"
    }
    
    # 签名
    payload["sign"] = okpay_sign(payload)
    
    try:
        response = requests.post(PAY_API_URL, json=payload, timeout=10)
        response.raise_for_status() # 报错则抛出异常
        data = response.json()
        
        if "data" in data and "payLink" in data["data"]:
            return order_id, data["data"]["payLink"]
        else:
            return None, None
    except Exception:
        return None, None

# ================= 机器人核心 =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
init_db() # 启动前初始化数据库

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    """欢迎界面"""
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("10元卡密", callback_data="buy_10"))
    keyboard.add(InlineKeyboardButton("30元卡密", callback_data="buy_30"))
    keyboard.add(InlineKeyboardButton("50元卡密", callback_data="buy_50"))
    
    await message.answer("🎁 欢迎来到卡密商店\n请选择需要购买的面值：", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith("buy_"))
async def process_buy(callback_query: types.CallbackQuery):
    """处理购买请求"""
    await callback_query.answer() # 必须应答，否则按钮会一直转圈
    
    price_str = callback_query.data.split("_")[1]
    price = int(price_str)
    
    # 1. 检查库存
    if get_stock(price) == 0:
        await callback_query.message.answer(f"❌ 抱歉，{price}元卡密库存不足！")
        return
    
    # 2. 创建支付链接
    order_id, pay_link = create_pay_order(price)
    
    if not pay_link:
        await callback_query.message.answer("❌ 支付接口异常，无法创建订单，请稍后重试。")
        return
    
    # 3. 发送支付链接
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("💳 点击完成支付", url=pay_link))
    
    await callback_query.message.answer(
        f"✅ 订单创建成功！\n"
        f"📝 订单号：{order_id}\n"
        f"💵 支付金额：{price * CNY_TO_USDT_RATE:.2f} USDT\n"
        f"请完成支付后截图联系管理员发货！",
        reply_markup=keyboard
    )

# ================= 管理员命令 =================
async def admin_add_cards(message: types.Message, price: int):
    """管理员导入卡密"""
    if message.from_user.id != ADMIN_ID:
        return
    
    # 解析内容: 第一行是命令，下面是卡密
    lines = message.text.split("\n")[1:]
    success = 0
    failed = 0
    
    for line in lines:
        card = line.strip()
        if card:
            if add_card_to_db(price, card):
                success += 1
            else:
                failed += 1
    
    await message.answer(f"📥 导入完成！\n✅ 成功：{success} 张\n❌ 失败：{failed} 张(重复或无效)")

@dp.message_handler(commands=["add10"])
async def add10(message: types.Message):
    await admin_add_cards(message, 10)

@dp.message_handler(commands=["add30"])
async def add30(message: types.Message):
    await admin_add_cards(message, 30)

@dp.message_handler(commands=["add50"])
async def add50(message: types.Message):
    await admin_add_cards(message, 50)

@dp.message_handler(commands=["stock"])
async def check_stock(message: types.Message):
    """查询库存"""
    if message.from_user.id != ADMIN_ID:
        return
    
    s10 = get_stock(10)
    s30 = get_stock(30)
    s50 = get_stock(50)
    
    await message.answer(f"📊 当前库存情况：\n10元：{s10} 张\n30元：{s30} 张\n50元：{s50} 张")

# ================= 启动 =================
if __name__ == "__main__":
    # 使用 executor 启动，不使用 webhook，Render 兼容好
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
