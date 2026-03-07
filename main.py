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

PHONE, CODE, PASS = range(3)
SESSIONS = "sessions"
os.makedirs(SESSIONS, exist_ok=True)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# 发送验证码
async def send_code(phone):
    try:
        c = Client(f"{SESSIONS}/{phone}", API_ID, API_HASH, in_memory=True)
        await c.connect()
        await c.send_code(phone, force_sms=True)
        await c.disconnect()
        return True, "✅ 验证码已发送"
    except Exception as e:
        return False, f"❌ 发送失败：{str(e)[:30]}"

# 登录账号
async def login(phone, code, pwd=None):
    try:
        c = Client(f"{SESSIONS}/{phone}", API_ID, API_HASH,
                   phone_number=phone, phone_code=code, password=pwd, in_memory=True)
        await c.start()
        return True, c, "✅ 登录成功"
    except PhoneCodeInvalid:
        return False, None, "❌ 验证码错误"
    except SessionPasswordNeeded:
        return False, None, "need_pass"
    except Exception as e:
        return False, None, f"❌ 登录失败：{str(e)[:30]}"

# 抢红包监听
async def watch(client):
    @client.on_message()
    async def handler(c, m):
        if m.chat.id != GROUP_ID or not m.reply_markup:
            return
        for row in m.reply_markup.inline_keyboard:
            for b in row:
                if any(k in b.text for k in ["领取","红包","开","点我"]):
                    await asyncio.sleep(0.3)
                    await c.request_callback_answer(m.chat.id, m.id, b.callback_data)
                    return
    while True:
        await asyncio.sleep(1)

# 机器人命令
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ 无权限")
        return
    update.message.reply_text(
        "🤖 红包机器人",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ 添加账号", callback_data="add")]
        ])
    )

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == "add":
        query.edit_message_text("📱 输入手机号（+86...）")
        return PHONE

def get_phone(update: Update, context: CallbackContext):
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        update.message.reply_text("❌ 格式：+86138...")
        return PHONE
    context.user_data["phone"] = phone
    # 发送验证码（关键：必须同步执行）
    ok, msg = loop.run_until_complete(send_code(phone))
    update.message.reply_text(msg)
    # 状态流转：成功则进入CODE，否则结束对话
    return CODE if ok else ConversationHandler.END

def get_code(update: Update, context: CallbackContext):
    code = update.message.text.strip()
    phone = context.user_data.get("phone")
    if not phone:
        update.message.reply_text("❌ 重新开始")
        return ConversationHandler.END
    ok, client, msg = loop.run_until_complete(login(phone, code))
    if msg == "need_pass":
        context.user_data["code"] = code
        update.message.reply_text("🔐 输入两步密码")
        return PASS
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch(client))
    return ConversationHandler.END

def get_pass(update: Update, context: CallbackContext):
    pwd = update.message.text.strip()
    phone = context.user_data.get("phone")
    code = context.user_data.get("code")
    ok, client, msg = loop.run_until_complete(login(phone, code, pwd))
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch(client))
    return ConversationHandler.END

# 主程序
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    # 对话处理器（状态流转修复）
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button, pattern="^add$")],
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
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == "__main__":
    main()
