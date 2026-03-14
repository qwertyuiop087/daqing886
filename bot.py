from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import requests
import uuid
from database import init_db, add_card
import os

# ===== 配置 (请务必在 Render 的环境变量中设置，不要写在代码里) =====
BOT_TOKEN = "7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY" # <--- 请先换掉这个 Token
ADMIN_ID = 7793291484
SHOP_ID = "29681"
# 动态获取 Render 提供的域名
DOMAIN = os.getenv("RENDER_EXTERNAL_URL", "daqing886.onrender.com") 
WEBHOOK_PATH = f"/bot{BOT_TOKEN}"
WEBHOOK_URL = f"https://{DOMAIN}{WEBHOOK_PATH}"

PAY_API = "https://api.okaypay.me/shop/payLink"

# ===== 初始化 =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
init_db()

# ... (保留你的 create_payment, /start, /buy, /addcard 处理函数不变) ...

# ===== 启动逻辑 (Webhook) =====
if __name__ == "__main__":
    # 设置 Webhook 并启动 Web 服务器
    executor.start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH, # 必须匹配上面的路径
        on_startup=lambda x: bot.set_webhook(WEBHOOK_URL), # 启动时注册 Webhook
        on_shutdown=lambda x: bot.delete_webhook(), # 关闭时注销
        skip_updates=True,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
