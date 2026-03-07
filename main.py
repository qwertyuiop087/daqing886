import os
import asyncio
from pyrogram import Client
from pyrogram.errors import PhoneNumberInvalid, FloodWait, PhoneCodeInvalid, SessionPasswordNeeded
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, Filters, CallbackContext
)
import warnings
warnings.filterwarnings("ignore")

# ==================== 你的配置 ====================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484
GROUP_ID = -1003472034414
# ==================================================

os.environ["PYROGRAM_NO_TGCRYPTO"] = "1"
os.environ["PYROGRAM_WARN_NO_TGCRYPTO"] = "0"
os.environ["PYTHONUNBUFFERED"] = "1"

PHONE, CODE, PASS = 1, 2, 3
SESSIONS = "sessions"
os.makedirs(SESSIONS, exist_ok=True)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# 发送验证码（修复参数错误）
async def send_code(phone):
    try:
        c = Client(f"{SESSIONS}/{phone}", API_ID, API_HASH, in_memory=True)
        await c.connect()
        await c.send_code(phone)  # 只传 phone，不额外参数
        await c.disconnect()
        return True, "✅ 验证码已发送"
    except Exception as e:
        return False, f"❌ 发送失败：{str(e)[:40]}"

# 登录（修复 EOF）
async def login(phone, code, pwd=None):
    try:
        c = Client(
            f"{SESSIONS}/{phone}", API_ID, API_HASH,
            phone_number=phone, phone_code=code, password=pwd, in_memory=True
        )
        await c.start()
        return True, c, "✅ 登录成功"
    except PhoneCodeInvalid:
        return False, None, "❌ 验证码错误"
    except SessionPasswordNeeded:
        return False, None, "need_pass"
    except Exception as e:
        return False, None, f"❌ 登录失败：{str(e)[:40]}"

# 抢红包
async def run(client):
    @client.on_message()
    async def h(c, m):
        if m.chat.id != GROUP_ID or not m.reply_markup:
            return
        for row in m.reply_markup.inline_keyboard:
            for b in row:
                if any(i in b.text for i in ["红包","领取","开","点我"]):
                    await asyncio.sleep(0.3)
                    await c.request_callback_answer(m.chat.id, m.id, b.callback_data)
                    return
    while True:
        await asyncio.sleep(1)

# 机器人
def start(u: Update, c: CallbackContext):
    if u.effective_user.id != ADMIN_ID:
        return
    u.message.reply_text("🤖 红包控制系统",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ 添加账号", callback_data="add")]]))

def btn(u: Update, c: CallbackContext):
    q = u.callback_query
    q.answer()
    if q.data == "add":
        q.edit_message_text("📱 请输入手机号（+86...）")
        return PHONE

def get_phone(u: Update, c: CallbackContext):
    phone = u.message.text.strip()
    if not phone.startswith("+"):
        u.message.reply_text("❌ 格式：+86138...")
        return PHONE
    c.user_data["phone"] = phone
    ok, msg = loop.run_until_complete(send_code(phone))
    u.message.reply_text(msg)
    return CODE if ok else ConversationHandler.END

def get_code(u: Update, c: CallbackContext):
    code = u.message.text.strip()
    phone = c.user_data["phone"]
    ok, client, msg = loop.run_until_complete(login(phone, code))
    if msg == "need_pass":
        c.user_data["code"] = code
        u.message.reply_text("🔐 输入两步密码")
        return PASS
    u.message.reply_text(msg)
    if ok:
        loop.create_task(run(client))
    return ConversationHandler.END

def get_pass(u: Update, c: CallbackContext):
    pwd = u.message.text.strip()
    phone = c.user_data["phone"]
    code = c.user_data["code"]
    ok, client, msg = loop.run_until_complete(login(phone, code, pwd))
    u.message.reply_text(msg)
    if ok:
        loop.create_task(run(client))
    return ConversationHandler.END

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(btn, pattern="add")],
        states={
            PHONE: [MessageHandler(Filters.text & ~Filters.command, get_phone)],
            CODE: [MessageHandler(Filters.text & ~Filters.command, get_code)],
            PASS: [MessageHandler(Filters.text & ~Filters.command, get_pass)],
        },
        fallbacks=[],
        per_message=False
    )
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv)
    updater.start_polling(drop_pending_updates=True, clean=False)
    updater.idle()

if __name__ == "__main__":
    main()
