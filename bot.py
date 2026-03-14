import asyncio
import random
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
import database
import okpay

# 日志配置（Render可查看日志，方便排查）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 初始化机器人（原配置不变）
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot)

# 生成唯一订单号（加用户ID，避免重复）
def gen_order_id(user_id: int) -> str:
    return f"ORD{user_id}{random.randint(100000, 999999)}"

# 启动命令（原功能保留）
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10元卡密", callback_data="buy_10")],
        [InlineKeyboardButton(text="30元卡密", callback_data="buy_30")],
        [InlineKeyboardButton(text="50元卡密", callback_data="buy_50")]
    ])
    await msg.answer("欢迎来到卡密商店\n请选择需要购买的商品", reply_markup=kb)
    logger.info(f"用户 {msg.from_user.id} 进入机器人")

# 购买卡密回调（修复库存校验、金额换算、加回调响应）
@dp.callback_query_handler(lambda c: c.data.startswith("buy_"))
async def buy(call: types.CallbackQuery):
    await call.answer()  # 解决Telegram客户端加载中
    user_id = call.from_user.id
    price_cny = int(call.data.split("_")[1])
    
    # 库存校验
    stock = await database.get_stock(price_cny)
    if stock == 0:
        await call.message.answer(f"⚠️ {price_cny}元卡密库存为0，暂无法购买！")
        return
    
    # 人民币转USDT（解决原金额混乱问题）
    price_usdt = price_cny * config.CNY_TO_USDT_RATE
    # 生成订单号
    order_id = gen_order_id(user_id)
    # 创建支付订单
    pay_res = await okpay.create_order(order_id, price_usdt)
    
    if not pay_res or "data" not in pay_res or "payLink" not in pay_res["data"]:
        await call.message.answer("❌ 支付订单创建失败，请稍后再试！")
        return
    pay_link = pay_res["data"]["payLink"]
    
    # 保存订单到数据库
    if not await database.create_order(order_id, user_id, price_cny, price_usdt, pay_link):
        await call.message.answer("❌ 订单保存失败！")
        return
    
    # 发送支付链接
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="点击支付", url=pay_link)]
    ])
    await call.message.answer(
        f"✅ 订单创建成功！\n订单号：{order_id}\n面值：{price_cny}元\n支付：{price_usdt:.2f} USDT",
        reply_markup=kb
    )
    logger.info(f"用户 {user_id} 创建{price_cny}元订单：{order_id}")

# 管理员通用导入卡密（修复原代码冗余问题）
async def admin_add_card(msg: types.Message, price: int):
    if msg.from_user.id != config.ADMIN_ID:
        return
    # 提取卡密（排除命令行，过滤空行）
    cards = [c.strip() for c in msg.text.split("\n")[1:] if c.strip()]
    if not cards:
        await msg.answer("❌ 未检测到有效卡密！")
        return
    # 批量导入
    success, fail = 0, 0
    for card in cards:
        if await database.add_card(price, card):
            success += 1
        else:
            fail += 1
    await msg.answer(f"✅ 导入完成！\n成功：{success}张\n失败（重复/无效）：{fail}张")
    logger.info(f"管理员导入{price}元卡密：成功{success}，失败{fail}")

# 导入10/30/50元卡密（原命令保留）
@dp.message_handler(commands=["add10"])
async def add10(msg: types.Message):
    await admin_add_card(msg, 10)

@dp.message_handler(commands=["add30"])
async def add30(msg: types.Message):
    await admin_add_card(msg, 30)

@dp.message_handler(commands=["add50"])
async def add50(msg: types.Message):
    await admin_add_card(msg, 50)

# 管理员查询库存（新增实用功能）
@dp.message_handler(commands=["stock"])
async def stock(msg: types.Message):
    if msg.from_user.id != config.ADMIN_ID:
        return
    s10 = await database.get_stock(10)
    s30 = await database.get_stock(30)
    s50 = await database.get_stock(50)
    await msg.answer(f"📊 卡密库存：\n10元：{s10}张\n30元：{s30}张\n50元：{s50}张")

# 主程序入口（适配Render启动）
async def main():
    await database.init_db()  # 初始化数据库
    logger.info("数据库初始化完成，机器人启动中...")
    await dp.start_polling(skip_updates=True)  # 忽略离线消息

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("机器人已停止")
    except Exception as e:
        logger.error(f"机器人启动失败：{str(e)}")
