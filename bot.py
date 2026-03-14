from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import uuid
import requests
from database import add_card, init_db

BOT_TOKEN = "7750611624:AAHlHYVD7aXqQr1aZw3FOWxKO_msw5G0DJU"
ADMIN_ID = 7793291484

SHOP_ID = "29681"
PAY_TOKEN = "8dDikTGgRuxy5ABCsEIKOPb3pL0tr47"

CALLBACK_URL = "https://daqing886.onrender.com/callback"

PAY_API = "https://api.okaypay.me/shop/payLink"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

init_db()


def create_payment(user_id):

    order_id = str(uuid.uuid4())

    data = {
        "id": SHOP_ID,
        "amount": 10,
        "coin": "USDT",
        "unique_id": order_id,
        "name": "卡密商品",
        "callback_url": CALLBACK_URL
    }

    r = requests.post(PAY_API, data=data).json()

    return r["data"]["pay_url"]


@dp.message_handler(commands=["start"])
async def start(message: types.Message):

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("购买卡密 10元", callback_data="buy"))

    await message.answer("欢迎购买卡密", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "buy")
async def buy(call: types.CallbackQuery):

    pay_url = create_payment(call.from_user.id)

    await bot.send_message(
        call.from_user.id,
        f"点击支付：\n{pay_url}"
    )


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

    await message.reply("卡密已添加")


if __name__ == "__main__":
    executor.start_polling(dp)
