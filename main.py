import os
import sys
import logging
import asyncio
import threading
from typing import Final, Dict, Any

# ---------- 依赖检查 ----------
try:
    from pyrogram import Client, filters
    from pyrogram.types import Message
    from pyrogram.errors import FloodWait, SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
    from flask import Flask
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}", file=sys.stderr)
    print("请确认 requirements.txt 包含：pyrogram, tgcrypto, flask", file=sys.stderr)
    sys.exit(1)

# ---------- 配置（已填入你的凭据） ----------
API_ID: Final = 38596687
API_HASH: Final = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN: Final = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"

TARGET_CHAT_IDS: Final = [-1003472034414, "red_packet_group"]
CLICK_KEYWORDS: Final = ["领取", "抢红包", "红包", "Claim", "Get"]

login_state: Dict[int, Dict[str, Any]] = {}

# 日志输出到 stdout（Render 可见）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RedPacketBot")

# ---------- Web 服务（Render 生存必需) ----------
app = Flask(__name__)

@app.route('/')
def health():
    return "OK", 200

def start_web():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🚀 启动 Web 服务监听端口 {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)

# ---------- 客户端初始化 ----------
bot_app = Client("control_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH)

# ---------- 指令处理器 ----------
@bot_app.on_message(filters.command("login") & filters.private)
async def login_cmd(_, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("格式: `/login +86138xxxxxxx`")
    phone = msg.command[1]
    try:
        if not user_app.is_connected:
            await user_app.connect()
        code = await user_app.send_code(phone)
        login_state[msg.chat.id] = {"phone": phone, "hash": code.phone_code_hash}
        await msg.reply("✅ 验证码已发送，请用 `/verify 12345` 提交")
    except Exception as e:
        await msg.reply(f"❌ 错误: {e}")

@bot_app.on_message(filters.command("verify") & filters.private)
async def verify_cmd(_, msg: Message):
    if msg.chat.id not in login_state or len(msg.command) < 2:
        return await msg.reply("请先 /login 并输入验证码")
    state = login_state[msg.chat.id]
    try:
        await user_app.sign_in(state["phone"], state["hash"], msg.command[1])
        await msg.reply("🎉 登录成功！Userbot 已开始监控红包。")
    except SessionPasswordNeeded:
        await msg.reply("🔐 请输入两步验证密码: `/pwd 密码`")
    except Exception as e:
        await msg.reply(f"❌ 验证失败: {e}")

@bot_app.on_message(filters.command("pwd") & filters.private)
async def pwd_cmd(_, msg: Message):
    if len(msg.command) < 2: return
    try:
        await user_app.check_password(msg.command[1])
        await msg.reply("✅ 两步验证通过！")
    except Exception as e:
        await msg.reply(f"❌ 密码错误: {e}")

# ---------- 红包监听器 ----------
@user_app.on_message(filters.incoming)
async def on_msg(client, msg: Message):
    if not (msg.chat.id in TARGET_CHAT_IDS or msg.chat.username in TARGET_CHAT_IDS):
        return
    if not msg.reply_markup:
        return

    for row in msg.reply_markup.inline_keyboard:
        for btn in row:
            if any(k in (btn.text or "") for k in CLICK_KEYWORDS):
                try:
                    await asyncio.sleep(0.3)
                    await client.request_callback_answer(
                        chat_id=msg.chat.id,
                        message_id=msg.id,
                        callback_data=btn.callback_data
                    )
                    logger.info(f"[+] 成功点击红包按钮 in {msg.chat.id}")
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except Exception as e:
                    logger.error(f"[!] 点击失败: {e}")

# ---------- 主启动函数 ----------
async def _start():
    # 启动 Web 服务（后台线程）
    threading.Thread(target=start_web, daemon=True).start()

    # 启动 Bot
    await bot_app.start()
    logger.info("🤖 控制 Bot 已启动")

    # 尝试恢复 Userbot
    try:
        await user_app.start()
        logger.info("👤 Userbot 已自动登录")
    except Exception as e:
        logger.warning(f"⚠️ Userbot 未登录，需手动 /login: {e}")

    # 关键：**不能用 idle()** → 改为长轮询等待
    while True:
        try:
            await asyncio.sleep(30)  # 防止空循环占用过高 CPU
        except KeyboardInterrupt:
            break

# ---------- 真正的入口点 ----------
def main():
    try:
        # 显式创建并运行事件循环（兼容 Render 的无 loop 环境）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_start())
    except Exception as e:
        logger.critical(f"[FATAL] 启动失败: {e}")
        sys.exit(1)
    finally:
        # 清理
        try:
            loop.run_until_complete(bot_app.stop())
            loop.run_until_complete(user_app.stop())
        except:
            pass
        loop.close()

if __name__ == "__main__":
    main()
