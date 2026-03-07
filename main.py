import os
import json
import asyncio
import random
from pyrogram import Client
from pyrogram.errors import (
    PhoneNumberInvalid, FloodWait, PhoneCodeInvalid, SessionPasswordNeeded
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# ==================== 配置（Render 可直接用） ====================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484
GROUP_ID = -1003472034414
# ================================================================

PHONE, CODE, PASS = range(3)
ACCOUNTS = "accounts.json"
SESSIONS = "sessions"
os.makedirs(SESSIONS, exist_ok=True)

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

# 发送验证码（Render 稳定版）
async def send_verification_code(phone):
    try:
        client = Client(f"{SESSIONS}/{phone}", API_ID, API_HASH)
        await client.connect()
        await client.send_code(phone)
        await client.disconnect()
        return True, "✅ 验证码已发送"
    except PhoneNumberInvalid:
        return False, "❌ 手机号无效"
    except FloodWait as e:
        return False, f"❌ 操作频繁，等待 {e.value} 秒"
    except Exception as e:
        return False, f"❌ 发送失败：{str(e)[:30]}"

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
        return True, "✅ 登录成功"
    except PhoneCodeInvalid:
        return False, "❌ 验证码错误"
    except SessionPasswordNeeded:
        return False, "need_password"
    except Exception as e:
        return False, f"❌ 登录失败：{str(e)[:30]}"

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

# 机器人命令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "🤖 Render 红包系统",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ 添加账号", callback_data="add_account")]
        ])
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "add_account":
        await query.edit_message_text("📱 输入手机号（格式：+86138xxxx）")
        return PHONE

async def input_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        await update.message.reply_text("❌ 格式错误，必须 + 开头")
        return PHONE
    context.user_data["phone"] = phone
    ok, msg = await send_verification_code(phone)
    await update.message.reply_text(msg)
    return CODE if ok else ConversationHandler.END

async def input_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    phone = context.user_data["phone"]
    ok, msg = await login_account(phone, code)
    if msg == "need_password":
        context.user_data["code"] = code
        await update.message.reply_text("🔐 输入两步验证密码")
        return PASS
    await update.message.reply_text(msg)
    if ok:
        asyncio.create_task(watch_redpacket(clients[phone]))
    return ConversationHandler.END

async def input_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pwd = update.message.text.strip()
    phone = context.user_data["phone"]
    code = context.user_data["code"]
    ok, msg = await login_account(phone, code, pwd)
    await update.message.reply_text(msg)
    if ok:
        asyncio.create_task(watch_redpacket(clients[phone]))
    return ConversationHandler.END

# Render 保活（防止掉线）
async def keep_alive():
    while True:
        await asyncio.sleep(300)

# 主程序
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="add_account")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_phone)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_code)],
            PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_password)],
        },
        fallbacks=[]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    asyncio.create_task(keep_alive())
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(100)

if __name__ == "__main__":
    asyncio.run(main())
