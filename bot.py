import random
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
import database
import okpay

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot)
database.init()

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
    if database.stock(price) == 0:
        await call.message.answer("没货")
        return
    order_id = f"ORD{random.randint(100000,999999)}"
    usdt = price * config.CNY_TO_USDT
    link = okpay.pay_link(order_id, usdt)
    if not link:
        await call.message.answer("支付接口异常")
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("支付", url=link))
    await call.message.answer(f"订单：{order_id}\n金额：{usdt} USDT", reply_markup=kb)

async def add_cmd(msg, price):
    if msg.from_user.id != config.ADMIN_ID:
        return
    lines = msg.text.split("\n")[1:]
    ok, no = 0, 0
    for card in lines:
        card = card.strip()
        if card and database.add(price, card):
            ok +=1
        else:
            no +=1
    await msg.answer(f"成功：{ok} 失败：{no}")

@dp.message_handler(commands=["add10"])
async def add10(msg): await add_cmd(msg,10)
@dp.message_handler(commands=["add30"])
async def add30(msg): await add_cmd(msg,30)
@dp.message_handler(commands=["add50"])
async def add50(msg): await add_cmd(msg,50)

@dp.message_handler(commands=["stock"])
async def st(msg):
    if msg.from_user.id != config.ADMIN_ID:
        return
    await msg.answer(f"10:{database.stock(10)} 30:{database.stock(30)} 50:{database.stock(50)}")

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
