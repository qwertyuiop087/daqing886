from aiogram import Bot,Dispatcher,types
from aiogram.utils import executor
import requests
import uuid
from database import init_db,add_card

BOT_TOKEN="7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY"
ADMIN_ID=7793291484

SHOP_ID="29681"
CALLBACK="https://daqing886.onrender.com/callback"

bot=Bot(token=BOT_TOKEN)
dp=Dispatcher(bot)

init_db()

def create_pay():

    order=str(uuid.uuid4())

    data={
        "id":SHOP_ID,
        "amount":10,
        "coin":"USDT",
        "unique_id":order,
        "name":"卡密",
        "callback_url":CALLBACK
    }

    r=requests.post("https://api.okaypay.me/shop/payLink",data=data).json()

    return r["data"]["pay_url"]


@dp.message_handler(commands=["start"])
async def start(msg:types.Message):

    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("购买卡密10元",callback_data="buy"))

    await msg.answer("欢迎购买",reply_markup=kb)


@dp.callback_query_handler(lambda c:c.data=="buy")
async def buy(call:types.CallbackQuery):

    url=create_pay()

    await bot.send_message(call.from_user.id,f"支付链接\n{url}")


@dp.message_handler(commands=["addcard"])
async def addcard(msg:types.Message):

    if msg.from_user.id!=ADMIN_ID:
        return

    card=msg.text.split(" ")[1]

    add_card(card)

    await msg.reply("卡密添加成功")


executor.start_polling(dp)
