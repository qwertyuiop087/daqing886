import asyncio
import random
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database
import okpay

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10元卡密", callback_data="buy_10")],
        [InlineKeyboardButton(text="30元卡密", callback_data="buy_30")],
        [InlineKeyboardButton(text="50元卡密", callback_data="buy_50")]
    ])
    await msg.answer("欢迎来到卡密商店\n请选择商品", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("buy"))
async def buy(call: types.CallbackQuery):
    price = int(call.data.split("_")[1])
    order_id = f"ORD{random.randint(100000, 999999)}"
    pay = okpay.create_order(order_id, price)

    if "data" in pay and "payLink" in pay["data"]:
        link = pay["data"]["payLink"]
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="点击支付", url=link)]]
        )
        await call.message.answer(
            f"订单号: {order_id}\n金额: {price} USDT",
            reply_markup=kb
        )
    else:
        await call.message.answer("支付创建失败，请稍后重试")

# 管理员导入卡密（通用函数）
async def add_cards_by_price(msg: types.Message, price: int):
    if msg.from_user.id != config.ADMIN_ID:
        return
    cards = msg.text.split("\n")[1:]
    if not cards:
        await msg.answer("请提供卡密列表，每行一个")
        return
    for c in cards:
        if c.strip():
            database.add_card(price, c.strip())
    await msg.answer(f"{price}元卡密导入成功，共 {len(cards)} 条")

@dp.message_handler(commands=["add10"])
async def add10(msg: types.Message):
    await add_cards_by_price(msg, 10)

@dp.message_handler(commands=["add30"])
async def add30(msg: types.Message):
    await add_cards_by_price(msg, 30)

@dp.message_handler(commands=["add50"])
async def add50(msg: types.Message):
    await add_cards_by_price(msg, 50)

# 可选：管理员查询库存
@dp.message_handler(commands=["stock"])
async def check_stock(msg: types.Message):
    if msg.from_user.id != config.ADMIN_ID:
        return
    s10 = database.stock(10)
    s30 = database.stock(30)
    s50 = database.stock(50)
    await msg.answer(f"库存：\n10元: {s10}\n30元: {s30}\n50元: {s50}")

async def on_startup(_):
    logger.info("机器人启动中...")
    database.init_db()  # 初始化数据库表
    logger.info("数据库初始化完成")

async def main():
    dp.startup.register(on_startup)
    logger.info("开始轮询...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
