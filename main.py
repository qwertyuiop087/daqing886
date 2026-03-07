import os
import json
import asyncio
import random
import threading
from pyrogram import Client
from pyrogram.errors import (
    PhoneNumberInvalid, FloodWait, PhoneCodeInvalid, SessionPasswordNeeded
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, Filters, CallbackContext
)

# ==================== 你的配置（只改这里） ====================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"  # 更换为您的 Bot Token
ADMIN_ID = 7793291484
GROUP_ID = -1003472034414
# ==============================================================

# 消除 Pyrogram 警告（不影响功能，仅清理日志）
os.environ["PYROGRAM_NO_TGCRYPTO"] = "1"

PHONE, CODE, PASS = range(3)
ACCOUNTS = "accounts.json"
SESSIONS = "sessions"
os.makedirs(SESSIONS, exist_ok=True)

# 加载/保存账号
def load_accounts():
    if os.path.exists(ACCOUNTS):
        with open(ACCOUNTS, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_accounts(data):
    with open(ACCOUNTS, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

accounts = load_accounts()
clients = {}

# 创建全局异步循环
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# 发送验证码
async def send_verification_code(phone):
    try:
        client = Client(f"{SESSIONS}/{phone}", API_ID, API_HASH)
        await client.connect()
        await client.send_code(phone)
        await client.disconnect()
        return True, "✅ 验证码已发送（查收 Telegram 消息）"
    except PhoneNumberInvalid:
        return False, "❌ 手机号无效（格式：+8613800000000）"
    except FloodWait as e:
        return False, f"❌ 操作频繁，请等待 {e.value} 秒后重试"
    except Exception as e:
        return False, f"❌ 发送失败：{str(e)}"

# 登录账号
async def login_account(phone, code, password=None):
    try:
        client = Client(
            f"{SESSIONS}/{phone}",
            API_ID, API_HASH,
            phone_number=phone,
            phone_code=code,
            password=password
        )
        await client.start()
        clients[phone] = client
        accounts[phone] = {"status": "active"}
        save_accounts(accounts)
        return True, "✅ 登录成功！已开始监听红包"
    except PhoneCodeInvalid:
        return False, "❌ 验证码错误，请重新输入"
    except SessionPasswordNeeded:
        return False, "need_password"
    except Exception as e:
        return False, f"❌ 登录失败：{str(e)}"

# 自动抢红包
async def watch_redpacket(client):
    @client.on_message()
    async def handler(c, msg):
        if msg.chat.id != GROUP_ID or not msg.reply_markup:
            return
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                if any(k in btn.text for k in ["领取", "红包", "开", "点我", "拆开"]):
                    await asyncio.sleep(random.uniform(0.2, 0.6))
                    await c.request_callback_answer(msg.chat.id, msg.id, btn.callback_data)
                    return
    while True:
        await asyncio.sleep(1)

# 机器人命令 - 启动
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ 无操作权限")
        return
    update.message.reply_text(
        "🤖 红包机器人（Render 稳定版）\n\n操作说明：\n1. 点击「添加账号」\n2. 输入+86开头手机号\n3. 输入验证码完成登录",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ 添加账号", callback_data="add_account")]])
    )

# 按钮回调 - 添加账号
def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()  # 必须调用，否则 Telegram 会卡住
    if query.data == "add_account":
        query.edit_message_text("📱 请输入手机号（格式：+8613800000000）")
        return PHONE

# 接收手机号
def input_phone(update: Update, context: CallbackContext):
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        update.message.reply_text("❌ 格式错误！手机号必须以 + 开头（如 +8613800000000）")
        return PHONE
    context.user_data["phone"] = phone
    try:
        ok, msg = loop.run_until_complete(send_verification_code(phone))
        update.message.reply_text(msg)
        return CODE if ok else ConversationHandler.END
    except Exception as e:
        update.message.reply_text(f"❌ 系统错误：{str(e)}")
        return ConversationHandler.END

# 接收验证码
def input_code(update: Update, context: CallbackContext):
    code = update.message.text.strip()
    phone = context.user_data.get("phone")
    if not phone:
        update.message.reply_text("❌ 未检测到手机号，请重新开始")
        return ConversationHandler.END
    ok, msg = loop.run_until_complete(login_account(phone, code))
    if msg == "need_password":
        context.user_data["code"] = code
        update.message.reply_text("🔐 请输入两步验证密码")
        return PASS
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch_redpacket(clients[phone]))
    return ConversationHandler.END

# 接收两步验证密码
def input_password(update: Update, context: CallbackContext):
    pwd = update.message.text.strip()
    phone = context.user_data.get("phone")
    code = context.user_data.get("code")
    if not phone or not code:
        update.message.reply_text("❌ 信息丢失，请重新开始")
        return ConversationHandler.END
    ok, msg = loop.run_until_complete(login_account(phone, code, pwd))
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch_redpacket(clients[phone]))
    return ConversationHandler.END

# Render 保活（线程版，防止掉线）
def keep_alive():
    while True:
        threading.Event().wait(300)  # 每5分钟心跳

# 主程序
def main():
    threading.Thread(target=keep_alive, daemon=True).start()
    
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="^add_account$")],
        states={
            PHONE: [MessageHandler(Filters.text & ~Filters.command, input_phone)],
            CODE: [MessageHandler(Filters.text & ~Filters.command, input_code)],
            PASS: [MessageHandler(Filters.text & ~Filters.command, input_password)],
        },
        fallbacks=[],
    )

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv_handler)

    print("✅ 机器人已启动，等待指令...")
    updater.start_polling(timeout=10, read_latency=2)
    updater.idle()

if __name__ == "__main__":
    main()
