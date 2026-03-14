from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import requests
import uuid
from database import init_db, add_card

# ===== 配置 =====

BOT_TOKEN = "7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY"
ADMIN_ID = 7793291484

SHOP_ID = "29681"

CALLBACK_URL = "https://daqing886.onrender.com/callback"

PAY_API = "https://api.okaypay.me/shop/payLink"

# ===== 初始化 =====

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

init_db()


# ===== 创建支付链接 =====

def create_payment():

    order_id = str(uuid.uuid4())

    data = {
        "id": SHOP_ID,
        "amount": 10,
        "coin": "USDT",
        "unique_id": order_id,
        "name": "卡密商品",
        "callback_url": CALLBACK_URL
    }

    try:

        r = requests.post(PAY_API, data=data).json()

        return r["data"]["pay_url"]

    except Exception as e:

        print("支付接口错误:", e)

        return None


# ===== /start =====

@dp.message_handler(commands=["start"])
async def start(message: types.Message):

    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "购买卡密 10元",
            callback_data="buy"
        )
    )

    await message.answer(
        "欢迎使用卡密机器人\n请选择商品",
        reply_markup=keyboard
    )


# ===== 点击购买 =====

@dp.callback_query_handler(lambda c: c.data == "buy")
async def buy(call: types.CallbackQuery):

    pay_url = create_payment()

    if not pay_url:

        await bot.send_message(
            call.from_user.id,
            "支付接口错误，请稍后再试"
        )

        return

    await bot.send_message(
        call.from_user.id,
        f"点击支付链接完成购买\n\n{pay_url}"
    )


# ===== 管理员添加卡密 =====

@dp.message_handler(commands=["addcard"])
async def addcard(message: types.Message):

    if message.from_user.id != ADMIN_ID:

        return

    try:

        card = message.text.split(" ")[1]

    except:

        await message.reply("格式: /addcard 卡密")

        return

    add_card(card)

    await message.reply("卡密添加成功")


# ===== 启动机器人 =====

if __name__ == "__main__":

    print("Bot started...")

    executor.start_polling(
        dp,
        skip_updates=True
    )
