import asyncio
import random
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
import database
import okpay

# 配置日志（方便排查问题）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 初始化机器人
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot)

# 生成唯一订单号（新增用户ID前缀，降低重复概率）
def generate_order_id(user_id: int) -> str:
    random_num = random.randint(100000, 999999)
    return f"ORD{user_id}{random_num}"

# 启动命令
@dp.message_handler(commands=["start"])
async def start_handler(msg: types.Message):
    # 构造键盘
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10元卡密", callback_data="buy_10")],
        [InlineKeyboardButton(text="30元卡密", callback_data="buy_30")],
        [InlineKeyboardButton(text="50元卡密", callback_data="buy_50")]
    ])
    await msg.answer("欢迎来到卡密商店\n请选择需要购买的商品", reply_markup=kb)
    logger.info(f"用户 {msg.from_user.id} 进入机器人")

# 购买卡密回调
@dp.callback_query_handler(lambda c: c.data.startswith("buy_"))
async def buy_callback(call: types.CallbackQuery):
    # 先响应Telegram回调，防止客户端加载中
    await call.answer()
    user_id = call.from_user.id
    price_cny = int(call.data.split("_")[1])
    
    # 1. 校验卡密库存
    stock = await database.get_card_stock(price_cny)
    if stock == 0:
        await call.message.answer(f"⚠️ {price_cny}元卡密当前库存为0，暂无法购买！")
        logger.warning(f"用户 {user_id} 购买{price_cny}元卡密，库存不足")
        return
    
    # 2. 计算支付金额（人民币转USDT，按配置的汇率）
    price_usdt = price_cny * config.CNY_TO_USDT_RATE
    
    # 3. 生成唯一订单号
    order_id = generate_order_id(user_id)
    
    # 4. 调用支付接口创建订单
    pay_result = await okpay.create_order(order_id, price_usdt)
    if not pay_result or "data" not in pay_result or "payLink" not in pay_result["data"]:
        await call.message.answer("❌ 支付订单创建失败，请稍后再试！")
        logger.error(f"用户 {user_id} 购买{price_cny}元卡密，支付接口返回异常：{pay_result}")
        return
    pay_link = pay_result["data"]["payLink"]
    
    # 5. 保存订单到数据库
    is_save = await database.create_order(order_id, user_id, price_cny, price_usdt, pay_link)
    if not is_save:
        await call.message.answer("❌ 订单保存失败，请稍后再试！")
        logger.error(f"用户 {user_id} 购买{price_cny}元卡密，订单保存失败，订单号：{order_id}")
        return
    
    # 6. 发送支付链接
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="点击前往支付", url=pay_link)]
    ])
    await call.message.answer(
        f"✅ 订单创建成功！\n"
        f"订单号：{order_id}\n"
        f"卡密面值：{price_cny}元\n"
        f"支付金额：{price_usdt:.2f} USDT\n"
        f"请点击下方链接完成支付，支付后联系管理员发放卡密～",
        reply_markup=kb
    )
    logger.info(f"用户 {user_id} 购买{price_cny}元卡密，订单创建成功：{order_id}")

# 管理员导入卡密（通用函数，修复代码冗余）
async def admin_add_card(msg: types.Message, price: int):
    if msg.from_user.id != config.ADMIN_ID:
        return
    # 提取卡密内容（排除命令行）
    try:
        cards = [c.strip() for c in msg.text.split("\n")[1:] if c.strip()]
    except:
        await msg.answer("❌ 卡密格式错误，请按「命令+换行+卡密」的格式发送！")
        return
    if not cards:
        await msg.answer("❌ 未检测到有效卡密，请检查后重新发送！")
        return
    
    # 批量导入卡密
    success = 0
    fail = 0
    for card in cards:
        is_add = await database.add_card(price, card)
        if is_add:
            success += 1
        else:
            fail += 1
    
    await msg.answer(f"✅ 卡密导入完成！\n成功：{success}张\n失败（重复/无效）：{fail}张")
    logger.info(f"管理员 {msg.from_user.id} 导入{price}元卡密，成功{success}张，失败{fail}张")

# 导入10元卡密
@dp.message_handler(commands=["add10"])
async def add10_handler(msg: types.Message):
    await admin_add_card(msg, 10)

# 导入30元卡密
@dp.message_handler(commands=["add30"])
async def add30_handler(msg: types.Message):
    await admin_add_card(msg, 30)

# 导入50元卡密
@dp.message_handler(commands=["add50"])
async def add50_handler(msg: types.Message):
    await admin_add_card(msg, 50)

# 管理员查询库存（新增实用功能）
@dp.message_handler(commands=["stock"])
async def stock_handler(msg: types.Message):
    if msg.from_user.id != config.ADMIN_ID:
        return
    stock10 = await database.get_card_stock(10)
    stock30 = await database.get_card_stock(30)
    stock50 = await database.get_card_stock(50)
    await msg.answer(f"📊 当前卡密库存：\n10元：{stock10}张\n30元：{stock30}张\n50元：{stock50}张")

# 主程序入口
async def main():
    # 初始化数据库
    await database.init_db()
    logger.info("数据库初始化完成")
    # 启动机器人轮询
    await dp.start_polling(skip_updates=True)  # skip_updates=True 忽略离线消息

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("机器人已停止运行")
    except Exception as e:
        logger.error(f"机器人启动失败：{str(e)}")
