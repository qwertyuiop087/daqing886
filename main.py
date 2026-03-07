import os
import asyncio
import logging
from typing import Final, Dict, Any
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
from flask import Flask
from threading import Thread

# --- 基础配置 (请通过 my.telegram.org 获取) ---
API_ID: Final = 1234567  # 替换为你的 API ID
API_HASH: Final = "你的_API_HASH"
BOT_TOKEN: Final = "你的_CONTROL_BOT_TOKEN"

# 监控配置：指定要抢红包的群组（ID或用户名）
TARGET_CHAT_IDS: Final = [-100123456789, "red_packet_group_username"]
# 匹配红包领取按钮上的文字
CLICK_KEYWORDS: Final = ["领取", "抢红包", "红包", "Claim", "Get", "快抢"]

# 内存状态管理
login_state: Dict[int, Dict[str, Any]] = {}

# 日志初始化
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RedPacketWorker")

# --- Render 部署兼容：健康检查 Web 服务 ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    """ 让 Render 知道服务依然在线 """
    return "Userbot is Active", 200

def run_web_server():
    # Render 默认使用环境变量 PORT
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- 客户端实例初始化 ---

# 控制 Bot：负责接收你的验证码，管理登录
bot_app = Client("control_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# 抢红包 Userbot：模拟你的账号操作
# 使用 session_name="user_session" 会在本地生成 .session 文件
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH)

# --- 核心逻辑：Bot 控制指令 ---

@bot_app.on_message(filters.command("login") & filters.private)
async def bot_login(client, message: Message):
    """ 启动登录流程: /login +86138xxxxxxxx """
    if len(message.command) < 2:
        return await message.reply("❌ 请输入格式: `/login 手机号` (带国家码)")
    
    phone = message.command[1]
    await message.reply(f"正在尝试连接 Telegram 并发送验证码至 {phone}...")

    try:
        if not user_app.is_connected:
            await user_app.connect()
        
        sent_code = await user_app.send_code(phone)
        login_state[message.chat.id] = {
            "phone": phone,
            "hash": sent_code.phone_code_hash
        }
        await message.reply("📩 验证码已发送。请输入: `/verify 验证码`")
    except Exception as e:
        logger.error(f"Login failed: {e}")
        await message.reply(f"❌ 错误: {str(e)}")

@bot_app.on_message(filters.command("verify") & filters.private)
async def bot_verify(client, message: Message):
    """ 提交验证码 """
    chat_id = message.chat.id
    if chat_id not in login_state:
        return await message.reply("❌ 请先执行 /login")
    
    if len(message.command) < 2:
        return await message.reply("❌ 请输入验证码")

    code = message.command[1]
    state = login_state[chat_id]

    try:
        await user_app.sign_in(state["phone"], state["hash"], code)
        await message.reply("✅ 登录成功！账号已进入全自动抢红包模式。")
    except SessionPasswordNeeded:
        await message.reply("🔐 该账号开启了两步验证，请输入: `/pwd 密码`")
    except (PhoneCodeInvalid, PhoneCodeExpired):
        await message.reply("❌ 验证码错误或已过期。")
    except Exception as e:
        await message.reply(f"❌ 登录异常: {str(e)}")

@bot_app.on_message(filters.command("pwd") & filters.private)
async def bot_pwd(client, message: Message):
    """ 提交两步验证密码 """
    if len(message.command) < 2: return
    try:
        await user_app.check_password(message.command[1])
        await message.reply("✅ 两步验证通过，账号已激活！")
    except Exception as e:
        await message.reply(f"❌ 密码错误: {str(e)}")

# --- 核心逻辑：Userbot 自动领红包 ---

@user_app.on_message(filters.incoming)
async def red_packet_handler(client, message: Message):
    """ 实时监控消息中的内联按钮 """
    # 1. 准入过滤：只检查目标群组
    is_target = (message.chat.id in TARGET_CHAT_IDS) or (message.chat.username in TARGET_CHAT_IDS)
    if not is_target or not message.reply_markup:
        return

    # 2. 扫描所有内联按钮寻找红包关键词
    target_callback = None
    for row in message.reply_markup.inline_keyboard:
        for btn in row:
            if any(k in (btn.text or "") for k in CLICK_KEYWORDS):
                target_callback = btn.callback_data
                break
    
    # 3. 执行点击动作
    if target_callback:
        try:
            # 模拟轻微人类延迟
            await asyncio.sleep(0.5)
            
            # 发送按钮点击请求
            await user_app.request_callback_answer(
                chat_id=message.chat.id,
                message_id=message.id,
                callback_data=target_callback
            )
            logger.info(f"成功点击红包! 群组: {message.chat.title or message.chat.id}")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"抢红包操作失败: {e}")

# --- 启动入口 ---

async def start_all():
    # 启动 Web Server (守护线程)
    Thread(target=run_web_server, daemon=True).start()
    
    # 启动控制机器人
    await bot_app.start()
    logger.info("Control Bot 已就绪，等待指令...")
    
    # 尝试静默启动 Userbot (如果已有 Session)
    try:
        await user_app.start()
        logger.info("Userbot 已自动重连")
    except Exception:
        logger.info("Userbot 未登录，请通过 Bot 发送 /login 控制登录")

    # 保持主协程不退出
    await asyncio.idle()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(start_all())
    except KeyboardInterrupt:
        logger.info("程序手动停止")
