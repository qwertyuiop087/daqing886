import os
import json
import asyncio
import random
from pyrogram import Client
from pyrogram.errors import (
    PhoneNumberInvalid, FloodWait, PhoneCodeInvalid, SessionPasswordNeeded
)
# 适配 python-telegram-bot 12.8 旧版 API
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, Filters, CallbackContext
)

# ==================== 你的配置（只改这里） ====================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484
GROUP_ID = -1003472034414
# ==============================================================

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

# 机器人命令（适配旧版 API）
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    update.message.reply_text(
        "🤖 Render 红包系统",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ 添加账号", callback_data="add_account")]
        ])
    )

def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == "add_account":
        query.edit_message_text("📱 输入手机号（格式：+86138xxxx）")
        return PHONE

def input_phone(update: Update, context: CallbackContext):
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        update.message.reply_text("❌ 格式错误，必须 + 开头")
        return PHONE
    context.user_data["phone"] = phone
    # 同步执行异步函数（适配旧版 telegram-bot）
    loop = asyncio.get_event_loop()
    ok, msg = loop.run_until_complete(send_verification_code(phone))
    update.message.reply_text(msg)
    return CODE if ok else ConversationHandler.END

def input_code(update: Update, context: CallbackContext):
    code = update.message.text.strip()
    phone = context.user_data["phone"]
    loop = asyncio.get_event_loop()
    ok, msg = loop.run_until_complete(login_account(phone, code))
    if msg == "need_password":
        context.user_data["code"] = code
        update.message.reply_text("🔐 输入两步验证密码")
        return PASS
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch_redpacket(clients[phone]))
    return ConversationHandler.END

def input_password(update: Update, context: CallbackContext):
    pwd = update.message.text.strip()
    phone = context.user_data["phone"]
    code = context.user_data["code"]
    loop = asyncio.get_event_loop()
    ok, msg = loop.run_until_complete(login_account(phone, code, pwd))
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch_redpacket(clients[phone]))
    return ConversationHandler.END

# Render 保活（防止掉线）
def keep_alive():
    while True:
        asyncio.sleep(300)

# 主程序
def main():
    # 初始化机器人（旧版 API）
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # 对话处理器
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="add_account")],
        states={
            PHONE: [MessageHandler(Filters.text & ~Filters.command, input_phone)],
            CODE: [MessageHandler(Filters.text & ~Filters.command, input_code)],
            PASS: [MessageHandler(Filters.text & ~Filters.command, input_password)],
        },
        fallbacks=[]
    )

    # 添加处理器
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv_handler)

    # 启动保活
    loop = asyncio.get_event_loop()
    loop.create_task(keep_alive())

    # 启动机器人
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
