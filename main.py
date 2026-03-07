import os
import asyncio
import logging
import sys
from threading import Thread
from typing import Final, Dict, Any

# 尝试导入依赖，捕获环境配置错误
try:
    from pyrogram import Client, filters, idle
    from pyrogram.types import Message
    from pyrogram.errors import FloodWait, SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
    from flask import Flask
except ImportError as e:
    print(f"依赖缺失: {e}. 请确保 requirements.txt 包含 pyrogram, tgcrypto, flask")
    sys.exit(1)

# --- 核心配置 ---
# 已根据你的要求更新凭据
API_ID: Final = 38596687 
API_HASH: Final = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN: Final = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"

# 监控群组配置 (支持 ID 或 用户名)
TARGET_CHAT_IDS: Final = [-1003472034414, "red_packet_group"] 
# 抢红包触发关键词
CLICK_KEYWORDS: Final = ["领取", "抢红包", "红包", "Claim", "Get", "快抢"]

# 全局状态管理
login_state: Dict[int, Dict[str, Any]] = {}

# 日志格式化输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RedPacketBot")

# --- Render 兼容性：轻量 Web 服务 ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    """ 供 Render 负载均衡检测存活状态 """
    return "Bot is running", 200

def run_web_server():
    """ 在独立线程中启动 Flask，避免阻塞主协程 """
    # Render 会动态注入 PORT 环境变量，必须监听 0.0.0.0
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"正在绑定端口 {port} 以适配 Render 部署...")
    web_app.run(host='0.0.0.0', port=port)

# --- 客户端实例初始化 ---
# 控制机 (Bot)
bot_app = Client("control_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
# 执行机 (Userbot) - session 会在本地生成 user_session.session 文件
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH)

# --- 控制端指令逻辑 ---

@bot_app.on_message(filters.command("login") & filters.private)
async def cmd_login(_, message: Message):
    if len(message.command) < 2:
        return await message.reply("使用方式: `/login +861234567890`")
    
    phone = message.command[1]
    await message.reply(f"正在向 {phone} 发送验证码...")

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
        logger.error(f"验证码发送失败: {e}")
        await message.reply(f"发送失败: {str(e)}")

@bot_app.on_message(filters.command("verify") & filters.private)
async def cmd_verify(_, message: Message):
    chat_id = message.chat.id
    if chat_id not in login_state:
        return await message.reply("请先发送 /login")
    
    if len(message.command) < 2:
        return await message.reply("请输入验证码内容")

    code = message.command[1]
    state = login_state[chat_id]

    try:
        await user_app.sign_in(state["phone"], state["hash"], code)
        await message.reply("✅ 登录成功！Userbot 已激活监控。")
    except SessionPasswordNeeded:
        await message.reply("🔒 此账号开启了二步验证，请输入: `/pwd 你的密码`")
    except (PhoneCodeInvalid, PhoneCodeExpired):
        await message.reply("❌ 验证码无效或已过期，请重新登录。")
    except Exception as e:
        await message.reply(f"登录异常: {str(e)}")

@bot_app.on_message(filters.command("pwd") & filters.private)
async def cmd_pwd(_, message: Message):
    if len(message.command) < 2: return
    try:
        await user_app.check_password(message.command[1])
        await message.reply("✅ 二步验证成功，程序已就绪！")
    except Exception as e:
        await message.reply(f"验证失败: {str(e)}")

# --- Userbot 红包自动监听与抢夺逻辑 ---

@user_app.on_message(filters.incoming)
async def red_packet_listener(client: Client, message: Message):
    # 1. 过滤目标群组白名单
    is_target = (message.chat.id in TARGET_CHAT_IDS) or (message.chat.username in TARGET_CHAT_IDS)
    if not is_target or not message.reply_markup:
        return

    # 2. 检索内联按钮中的领取动作
    target_callback = None
    for row in message.reply_markup.inline_keyboard:
        for btn in row:
            # 按钮文本匹配关键词
            if any(key in (btn.text or "") for key in CLICK_KEYWORDS):
                target_callback = btn.callback_data
                break
    
    # 3. 模拟点击动作
    if target_callback:
        try:
            # 微小延迟，降低被风控风险
            await asyncio.sleep(0.3)
            # 发送 Callback Answer 模拟真实按钮按下
            await user_app.request_callback_answer(
                chat_id=message.chat.id,
                message_id=message.id,
                callback_data=target_callback
            )
            logger.info(f"命中红包！已尝试点击群组 {message.chat.id} 的按钮")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"红包获取动作异常: {e}")

# --- 启动器 ---

async def main():
    # 1. 启动 Web 服务保障 Render 不会因检测不到端口而 Exit
    Thread(target=run_web_server, daemon=True).start()
    
    # 2. 启动控制机器人
    await bot_app.start()
    logger.info("Bot 控制端已成功启动")
    
    # 3. 尝试热启动用户账号 (如果本地已有 session 文件)
    try:
        if not user_app.is_connected:
            await user_app.start()
            logger.info("Userbot 自动登录成功.")
    except Exception:
        logger.info("Userbot 目前处于未登录状态，等待指令。")

    # 4. 保持运行并处理信号
    await idle()
    
    # 5. 停机清理
    await bot_app.stop()
    await user_app.stop()

if __name__ == "__main__":
    try:
        # 使用 asyncio.run 可能会在 Render 的现有事件循环中冲突
        # 这里使用标准获取 loop 方式确保稳定性
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("接收到退出指令，程序关闭")
    except Exception as e:
        logger.error(f"致命错误导致崩溃: {e}")
        sys.exit(1) # 只有在真正的逻辑错误时才返回 1
