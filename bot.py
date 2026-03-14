import asyncio
import random

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database
import okpay

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


@dp.message(commands=["start"])
async def start(msg: types.Message):

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10元卡密", callback_data="buy_10")],
        [InlineKeyboardButton(text="30元卡密", callback_data="buy_30")],
        [InlineKeyboardButton(text="50元卡密", callback_data="buy_50")]
    ])

    await msg.answer(
        "欢迎来到卡密商店\n请选择商品",
        reply_markup=kb
    )


@dp.callback_query(lambda c: c.data.startswith("buy"))
async def buy(call: types.CallbackQuery):

    price = int(call.data.split("_")[1])

    order_id = f"ORD{random.randint(100000,999999)}"

    pay = okpay.create_order(order_id, price)

    try:
        link = pay["data"]["payLink"]
    except:
        await call.message.answer("支付创建失败")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="点击支付", url=link)]
        ]
    )

    await call.message.answer(
        f"订单号: {order_id}\n金额: {price} USDT",
        reply_markup=kb
    )


@dp.message(commands=["add10"])
async def add10(msg: types.Message):

    if msg.from_user.id != config.ADMIN_ID:
        return

    cards = msg.text.split("\n")[1:]

    for c in cards:
        database.add_card(10, c)

    await msg.answer("10元卡密导入成功")


@dp.message(commands=["add30"])
async def add30(msg: types.Message):

    if msg.from_user.id != config.ADMIN_ID:
        return

    cards = msg.text.split("\n")[1:]

    for c in cards:
        database.add_card(30, c)

    await msg.answer("30元卡密导入成功")


@dp.message(commands=["add50"])
async def add50(msg: types.Message):

    if msg.from_user.id != config.ADMIN_ID:
        return

    cards = msg.text.split("\n")[1:]

    for c in cards:
        database.add_card(50, c)

    await msg.answer("50元卡密导入成功")


async def main():

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
