import os
import asyncio
import logging
from typing import Final, Dict, Any
from threading import Thread

# 尝试导入依赖，并捕获错误给出更清晰的提示
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message
    from pyrogram.errors import FloodWait, SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
    from flask import Flask
except ImportError as e:
    print(f"检测到缺少依赖库: {e}. 请确保执行了 'pip install -r requirements.txt'")
    raise

# --- 基础配置 ---
API_ID: Final = 38596687  # 替换为你的真实 API ID
API_HASH: Final = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN: Final = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"

TARGET_CHAT_IDS: Final = [-1003472034414, "red_packet_group"]  # 监控群组
CLICK_KEYWORDS: Final = ["领取", "抢红包", "红包", "Claim", "Get"] # 领取关键词

# 登录状态管理
login_state: Dict[int, Dict[str, Any]] = {}

# 日志初始化
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RedPacketBot")

# --- Render 服务保持存活 (Flask) ---
web_app = Flask(__name__)

@web_app.route('/')
def index():
    return "Userbot Status: Running", 200

def start_flask():
    # Render 会自动分配端口，默认通常是 10000 或通过 PORT 注入
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Web Server on port {port}")
    web_app.run(host='0.0.0.0', port=port)

# --- 客户端实例 ---

# 控制端机器人
bot_app = Client("ctrl_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# 抢红包执行端 (Userbot)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH)

# --- 指令逻辑 (Bot API) ---

@bot_app.on_message(filters.command("login") & filters.private)
async def handle_login(client, message: Message):
    if len(message.command) < 2:
        return await message.reply("请使用: `/login +86xxxx`")
    
    phone = message.command[1]
    await message.reply(f"正在申请验证码至: {phone}")

    try:
        if not user_app.is_connected:
            await user_app.connect()
        
        sent_code = await user_app.send_code(phone)
        login_state[message.chat.id] = {
            "phone": phone,
            "hash": sent_code.phone_code_hash
        }
        await message.reply("请输入验证码: `/verify 12345`")
    except Exception as e:
        await message.reply(f"失败: {e}")

@bot_app.on_message(filters.command("verify") & filters.private)
async def handle_verify(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in login_state:
        return await message.reply("请先 /login")
    
    code = message.command[1]
    state = login_state[chat_id]

    try:
        await user_app.sign_in(state["phone"], state["hash"], code)
        await message.reply("✅ 登录成功！Userbot 已激活。")
    except SessionPasswordNeeded:
        await message.reply("请输入二步验证密码: `/pwd 密码`")
    except Exception as e:
        await message.reply(f"验证错误: {e}")

@bot_app.on_message(filters.command("pwd") & filters.private)
async def handle_pwd(client, message: Message):
    if len(message.command) < 2: return
    try:
        await user_app.check_password(message.command[1])
        await message.reply("✅ 用户账号已就绪")
    except Exception as e:
        await message.reply(f"错误: {e}")

# --- 核心：红包领取逻辑 (Userbot API) ---

@user_app.on_message(filters.incoming)
async def capture_red_packet(client, message: Message):
    # 过滤群组
    is_target = (message.chat.id in TARGET_CHAT_IDS) or (message.chat.username in TARGET_CHAT_IDS)
    if not is_target or not message.reply_markup:
        return

    # 寻找领取按钮
    target_data = None
    for row in message.reply_markup.inline_keyboard:
        for btn in row:
            if any(k in (btn.text or "") for k in CLICK_KEYWORDS):
                target_data = btn.callback_data
                break
    
    if target_data:
        try:
            # 模拟点击延迟
            await asyncio.sleep(0.3)
            # 点击动作
            await user_app.request_callback_answer(
                chat_id=message.chat.id,
                message_id=message.id,
                callback_data=target_data
            )
            logger.info(f"成功点击红包按钮: {message.chat.id}")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"领取红包失败: {e}")

# --- 启动 ---

async def run_server():
    # 1. 启动 Web 存活线程
    Thread(target=start_flask, daemon=True).start()
    
    # 2. 启动控制机器人
    await bot_app.start()
    logger.info("Control Bot 启动")
    
    # 3. 尝试启动用户端
    try:
        await user_app.start()
        logger.info("Userbot 自动登录成功")
    except:
        logger.info("Userbot 需要手动 /login")
        
    await asyncio.idle()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(run_server())
    except KeyboardInterrupt:
        pass
