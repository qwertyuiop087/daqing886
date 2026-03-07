import os
import asyncio
import signal
import sys
import time
import fcntl
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

# 环境配置（彻底消除警告）
os.environ["PYROGRAM_NO_TGCRYPTO"] = "1"
os.environ["PYROGRAM_WARN_NO_TGCRYPTO"] = "0"
os.environ["PYTHONUNBUFFERED"] = "1"

# 对话状态
PHONE, CODE, PASS = 1, 2, 3
SESSIONS = "sessions"
LOCK_FILE = "/tmp/bot.lock"  # 进程锁文件
os.makedirs(SESSIONS, exist_ok=True)

# 全局变量
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
updater = None

# ==================== 修复1：进程锁（解决多实例冲突） ====================
def acquire_lock():
    """获取进程锁，确保只有一个实例运行"""
    try:
        lock_file = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        return lock_file
    except:
        print("❌ 已有机器人实例在运行，退出！")
        sys.exit(1)

def release_lock(lock_file):
    """释放进程锁"""
    try:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
        os.remove(LOCK_FILE)
    except:
        pass

def signal_handler(signum, frame):
    """优雅退出（处理 Render 停止信号）"""
    print("\n🔌 机器人正在退出...")
    if updater:
        updater.stop()
    release_lock(lock_file)
    sys.exit(0)

# ==================== 修复2：Pyrogram send_code 兼容 ====================
async def send_code(phone):
    """发送验证码（兼容所有 Pyrogram 版本）"""
    # 清理旧会话
    session_prefix = f"{SESSIONS}/{phone.replace('+', '')}"
    for ext in [".session", ".session-journal"]:
        if os.path.exists(session_prefix + ext):
            os.remove(session_prefix + ext)
    
    try:
        # 初始化客户端（仅用必选参数，避免版本兼容问题）
        client = Client(
            name=session_prefix,
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True  # 彻底避免文件读写错误
        )
        await client.connect()
        
        # 核心修复：仅传递手机号，不使用任何可选参数
        # 兼容 Pyrogram 所有版本的 send_code 方法
        await client.send_code(phone)
        
        await client.disconnect()
        return True, "✅ 验证码已发送（查收 Telegram 消息/短信）"
    
    except PhoneNumberInvalid:
        return False, "❌ 手机号无效（格式：+8613800000000）"
    except FloodWait as e:
        return False, f"❌ 操作频繁，请等待 {e.value} 秒后重试"
    except Exception as e:
        # 完整错误信息，方便排查
        error_detail = str(e)[:60]
        return False, f"❌ 发送失败：{error_detail}"

async def login(phone, code, pwd=None):
    """登录账号（修复 EOF 错误）"""
    try:
        client = Client(
            name=f"{SESSIONS}/{phone.replace('+', '')}",
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=phone,
            phone_code=code,
            password=pwd,
            in_memory=True
        )
        await client.start()
        return True, client, "✅ 登录成功！开始抢红包"
    except PhoneCodeInvalid:
        return False, None, "❌ 验证码错误，请重新获取"
    except SessionPasswordNeeded:
        return False, None, "need_pass"
    except Exception as e:
        return False, None, f"❌ 登录失败：{str(e)[:30]}"

async def watch_redpacket(client):
    """监听抢红包"""
    @client.on_message()
    async def handler(c, msg):
        if msg.chat.id != GROUP_ID or not msg.reply_markup:
            return
        # 识别红包按钮
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                if any(k in btn.text for k in ["领取", "红包", "开", "点我", "拆开"]):
                    await asyncio.sleep(0.3)
                    await c.request_callback_answer(
                        chat_id=msg.chat.id,
                        message_id=msg.id,
                        callback_data=btn.callback_data
                    )
                    return
    while True:
        await asyncio.sleep(1)

# ==================== 机器人交互 ====================
def start(update: Update, context: CallbackContext):
    """启动命令"""
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ 无操作权限")
        return
    update.message.reply_text(
        "🤖 红包机器人（稳定版）",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ 添加账号", callback_data="add")]
        ])
    )

def button_click(update: Update, context: CallbackContext):
    """按钮回调"""
    query = update.callback_query
    query.answer()  # 必须应答，否则卡死
    if query.data == "add":
        query.edit_message_text("📱 请输入手机号（格式：+8613800000000）")
        return PHONE

def handle_phone(update: Update, context: CallbackContext):
    """处理手机号输入"""
    phone = update.message.text.strip()
    # 校验格式
    if not phone.startswith("+"):
        update.message.reply_text("❌ 格式错误！手机号必须以 + 开头（如 +8613800000000）")
        return PHONE
    
    # 保存手机号，发送验证码
    context.user_data["phone"] = phone
    ok, msg = loop.run_until_complete(send_code(phone))
    update.message.reply_text(msg)
    # 状态流转：成功则进入验证码阶段，失败则结束
    return CODE if ok else ConversationHandler.END

def handle_code(update: Update, context: CallbackContext):
    """处理验证码输入"""
    code = update.message.text.strip()
    phone = context.user_data.get("phone")
    
    if not phone:
        update.message.reply_text("❌ 未检测到手机号，请重新开始")
        return ConversationHandler.END
    
    # 登录账号
    ok, client, msg = loop.run_until_complete(login(phone, code))
    if msg == "need_pass":
        context.user_data["code"] = code
        update.message.reply_text("🔐 请输入两步验证密码")
        return PASS
    
    update.message.reply_text(msg)
    if ok:
        # 启动抢红包监听
        loop.create_task(watch_redpacket(client))
    return ConversationHandler.END

def handle_password(update: Update, context: CallbackContext):
    """处理两步验证密码"""
    pwd = update.message.text.strip()
    phone = context.user_data.get("phone")
    code = context.user_data.get("code")
    
    if not phone or not code:
        update.message.reply_text("❌ 信息丢失，请重新开始")
        return ConversationHandler.END
    
    # 登录账号（带两步验证）
    ok, client, msg = loop.run_until_complete(login(phone, code, pwd))
    update.message.reply_text(msg)
    if ok:
        loop.create_task(watch_redpacket(client))
    return ConversationHandler.END

# ==================== 主程序 ====================
if __name__ == "__main__":
    # 1. 获取进程锁，解决多实例冲突
    lock_file = acquire_lock()
    
    # 2. 注册信号处理，优雅退出
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("✅ 机器人启动中...")
    
    # 3. 初始化机器人（无冲突配置）
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # 4. 对话处理器（状态流转稳定）
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_click, pattern="^add$")],
        states={
            PHONE: [MessageHandler(Filters.text & ~Filters.command, handle_phone)],
            CODE: [MessageHandler(Filters.text & ~Filters.command, handle_code)],
            PASS: [MessageHandler(Filters.text & ~Filters.command, handle_password)],
        },
        fallbacks=[],
        per_message=False
    )
    
    # 5. 添加处理器
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv_handler)
    
    # 6. 启动轮询（无冲突参数）
    updater.start_polling(
        timeout=20,
        read_latency=2,
        drop_pending_updates=True,
        clean=False  # 关键：关闭 clean 参数，避免冲突
    )
    
    print("✅ 机器人已启动，等待指令...")
    updater.idle()
    
    # 7. 释放锁（程序正常退出时）
    release_lock(lock_file)
