import os
import json
import asyncio
import random
import threading
import time
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import (
    PhoneNumberInvalid, FloodWait, PhoneCodeInvalid, SessionPasswordNeeded,
    AuthKeyUnregistered, UserDeactivated, RPCError
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, Filters, CallbackContext
)

# ==================== 你的配置 ====================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484
GROUP_ID = -1003472034414
# ==================================================

# 关键修复：强制输出刷新 + 禁用控制台交互 + 消除 TgCrypto 警告
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYROGRAM_NO_TGCRYPTO"] = "1"
os.environ["PYROGRAM_DISABLE_TELETHON"] = "1"
# 额外消除 TgCrypto 警告的配置
os.environ["PYROGRAM_WARN_NO_TGCRYPTO"] = "0"

# 对话状态
PHONE, CODE, PASS, DELETE = range(4)
# 文件路径
ACCOUNTS_FILE = "accounts.json"
SESSIONS_DIR = "sessions"
LOG_FILE = "redpacket.log"

# 初始化目录
os.makedirs(SESSIONS_DIR, exist_ok=True)

# 全局变量（确保单例，避免冲突）
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
accounts = {}
clients = {}
tasks = {}

# ==================== 核心修复工具函数 ====================
def clean_session(phone):
    """清理无效会话"""
    session_prefix = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
    for ext in [".session", ".session-journal"]:
        if os.path.exists(session_prefix + ext):
            os.remove(session_prefix + ext)

def load_accounts():
    """加载账号（容错修复）"""
    global accounts
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
        else:
            accounts = {}
    except:
        accounts = {}
    # 初始化默认值
    for phone in accounts:
        if "stats" not in accounts[phone]:
            accounts[phone]["stats"] = {"total_attempts": 0, "successful_clicks": 0, "success_rate": 0.0}
        if "status" not in accounts[phone]:
            accounts[phone]["status"] = "offline"

def save_accounts():
    """保存账号（强制刷新）"""
    try:
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        # 强制刷新文件缓存
        os.fsync(f.fileno())
    except Exception as e:
        log(f"保存账号失败：{e}")

def log(content):
    """日志（修复 flush 参数错误）"""
    log_str = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {content}"
    print(log_str, flush=True)  # flush 放在 print 里，不是 log 函数参数
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_str + "\n")
            os.fsync(f.fileno())
    except:
        pass

def update_stats(phone, success):
    """更新统计"""
    if phone in accounts:
        accounts[phone]["stats"]["total_attempts"] += 1
        if success:
            accounts[phone]["stats"]["successful_clicks"] += 1
        total = accounts[phone]["stats"]["total_attempts"]
        success_cnt = accounts[phone]["stats"]["successful_clicks"]
        accounts[phone]["stats"]["success_rate"] = round(success_cnt/total*100, 2) if total > 0 else 0.0
        accounts[phone]["last_active"] = datetime.now().isoformat()
        save_accounts()

# ==================== 核心功能（修复响应） ====================
async def send_verification_code(phone):
    """发送验证码（强制响应）"""
    clean_session(phone)
    try:
        client = Client(
            f"{SESSIONS_DIR}/{phone.replace('+', '')}",
            API_ID, API_HASH,
            in_memory=True  # 彻底解决 EOF 错误
        )
        await client.connect()
        # 强制短信验证码，避免控制台交互
        await client.send_code(phone, force_sms=True, allow_flashcall=False)
        await client.disconnect()
        log(f"验证码已发送到 {phone}")
        return True, "✅ 验证码已发送（查收 Telegram 消息）"
    except PhoneNumberInvalid:
        return False, "❌ 手机号无效（格式：+8613800000000）"
    except FloodWait as e:
        return False, f"❌ 操作频繁，请等待 {e.value} 秒后重试"
    except Exception as e:
        log(f"发送验证码失败 {phone}：{e}")
        return False, f"❌ 发送失败：{str(e)[:30]}"

async def login_account(phone, code, password=None):
    """登录账号（修复 EOF）"""
    try:
        client = Client(
            f"{SESSIONS_DIR}/{phone.replace('+', '')}",
            API_ID, API_HASH,
            phone_number=phone,
            phone_code=code,
            password=password,
            in_memory=True,  # 内存模式，无文件读写
            takeout=False
        )
        await client.start()
        me = await client.get_me()
        clients[phone] = client
        accounts[phone] = {
            "status": "active",
            "user_id": me.id,
            "username": me.username or "无",
            "first_name": me.first_name or "无",
            "stats": accounts.get(phone, {}).get("stats", {"total_attempts": 0, "successful_clicks": 0, "success_rate": 0.0}),
            "last_active": datetime.now().isoformat(),
            "login_time": datetime.now().isoformat()
        }
        save_accounts()
        log(f"账号登录成功 {phone}（{me.first_name}）")
        return True, f"✅ 登录成功！账号：{me.first_name}"
    except PhoneCodeInvalid:
        clean_session(phone)
        return False, "❌ 验证码错误，请重新获取验证码"
    except SessionPasswordNeeded:
        return False, "need_password"
    except (AuthKeyUnregistered, UserDeactivated):
        clean_session(phone)
        return False, "❌ 账号未注册/已封禁"
    except EOFError:
        clean_session(phone)
        return False, "❌ 登录失败：请重新获取验证码"
    except Exception as e:
        clean_session(phone)
        log(f"登录失败 {phone}：{e}")
        return False, f"❌ 登录失败：{str(e)[:30]}"

async def watch_redpacket(phone):
    """监听抢红包"""
    client = clients.get(phone)
    if not client:
        return

    @client.on_message()
    async def handler(c, msg):
        if msg.chat.id != GROUP_ID or not msg.reply_markup:
            return
        
        redpacket_btn = None
        for row in msg.reply_markup.inline_keyboard:
            for btn in row:
                if any(k in btn.text for k in ["领取", "红包", "开", "点我", "拆开"]):
                    redpacket_btn = btn
                    break
            if redpacket_btn:
                break
        
        if redpacket_btn:
            log(f"{phone} 检测到红包，尝试领取...")
            update_stats(phone, False)
            try:
                await asyncio.sleep(random.uniform(0.2, 0.8))
                await c.request_callback_answer(
                    chat_id=msg.chat.id,
                    message_id=msg.id,
                    callback_data=redpacket_btn.callback_data
                )
                update_stats(phone, True)
                log(f"{phone} 红包领取成功！")
            except Exception as e:
                log(f"{phone} 红包领取失败：{e}")

    while True:
        if phone not in clients:
            break
        await asyncio.sleep(1)

async def auto_reconnect(phone):
    """自动重连"""
    while True:
        if phone in clients and clients[phone].is_connected:
            await asyncio.sleep(60)
            continue
        
        log(f"{phone} 账号掉线，尝试重连...")
        clean_session(phone)
        try:
            client = Client(
                f"{SESSIONS_DIR}/{phone.replace('+', '')}",
                API_ID, API_HASH,
                phone_number=phone,
                in_memory=True
            )
            await client.start()
            clients[phone] = client
            accounts[phone]["status"] = "active"
            save_accounts()
            log(f"{phone} 重连成功")
            tasks[phone] = loop.create_task(watch_redpacket(phone))
        except:
            accounts[phone]["status"] = "offline"
            save_accounts()
            log(f"{phone} 重连失败，5分钟后重试")
            await asyncio.sleep(300)

def remove_account(phone):
    """删除账号"""
    if phone in clients:
        loop.run_until_complete(clients[phone].stop())
        del clients[phone]
    if phone in tasks:
        tasks[phone].cancel()
        del tasks[phone]
    if phone in accounts:
        del accounts[phone]
    clean_session(phone)
    save_accounts()
    log(f"账号已删除 {phone}")

# ==================== 机器人命令（强制响应） ====================
def start(update: Update, context: CallbackContext):
    """启动命令（秒回）"""
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("❌ 无操作权限")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加账号", callback_data="add_account")],
        [InlineKeyboardButton("📋 账号列表", callback_data="list_accounts")],
        [InlineKeyboardButton("📊 抢包统计", callback_data="show_stats")],
        [InlineKeyboardButton("🗑️ 清理日志", callback_data="clear_log")]
    ]
    update.message.reply_text(
        f"🤖 红包机器人（完整版）\n"
        f"📅 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📱 在线账号：{len([p for p in accounts if accounts[p]['status'] == 'active'])}/{len(accounts)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def button_callback(update: Update, context: CallbackContext):
    """按钮回调（必应答）"""
    query = update.callback_query
    query.answer()  # Telegram 强制要求，否则卡死
    
    # 添加账号
    if query.data == "add_account":
        query.edit_message_text("📱 请输入手机号（格式：+8613800000000）")
        return PHONE
    
    # 账号列表
    elif query.data == "list_accounts":
        if not accounts:
            query.edit_message_text("📭 暂无账号")
            return
        
        text = "📋 账号列表：\n\n"
        for idx, (phone, info) in enumerate(accounts.items(), 1):
            status = "🟢 在线" if info["status"] == "active" else "🔴 离线"
            text += f"{idx}. {phone} - {status}\n"
            text += f"   昵称：{info['first_name']} | 最后活跃：{info['last_active'][:19]}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")],
            [InlineKeyboardButton("🗑️ 删除账号", callback_data="delete_account")]
        ]
        query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # 抢包统计
    elif query.data == "show_stats":
        if not accounts:
            query.edit_message_text("📭 暂无统计数据")
            return
        
        text = "📊 抢红包统计：\n\n"
        total_attempts = 0
        total_success = 0
        
        for phone, info in accounts.items():
            stats = info["stats"]
            text += f"📱 {phone}：\n"
            text += f"   总尝试：{stats['total_attempts']} | 成功：{stats['successful_clicks']}\n"
            text += f"   成功率：{stats['success_rate']}%\n\n"
            total_attempts += stats["total_attempts"]
            total_success += stats["successful_clicks"]
        
        total_rate = round(total_success/total_attempts*100, 2) if total_attempts > 0 else 0.0
        text += f"📈 总计：\n"
        text += f"   总尝试：{total_attempts} | 成功：{total_success} | 成功率：{total_rate}%"
        
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")]]
        query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # 清理日志
    elif query.data == "clear_log":
        if os.path.exists(LOG_FILE):
            open(LOG_FILE, 'w').close()
        query.edit_message_text("✅ 日志已清空", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")]
        ]))
    
    # 返回主菜单
    elif query.data == "back_main":
        keyboard = [
            [InlineKeyboardButton("➕ 添加账号", callback_data="add_account")],
            [InlineKeyboardButton("📋 账号列表", callback_data="list_accounts")],
            [InlineKeyboardButton("📊 抢包统计", callback_data="show_stats")],
            [InlineKeyboardButton("🗑️ 清理日志", callback_data="clear_log")]
        ]
        query.edit_message_text(
            f"🤖 红包机器人（完整版）\n"
            f"📅 当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📱 在线账号：{len([p for p in accounts if accounts[p]['status'] == 'active'])}/{len(accounts)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # 删除账号
    elif query.data == "delete_account":
        query.edit_message_text("📱 请输入要删除的手机号（格式：+8613800000000）")
        context.user_data["action"] = "delete"
        return PHONE

def input_phone(update: Update, context: CallbackContext):
    """处理手机号（强制响应）"""
    phone = update.message.text.strip()
    action = context.user_data.get("action", "add")
    
    # 删除账号
    if action == "delete":
        if phone in accounts:
            remove_account(phone)
            update.message.reply_text(f"✅ 账号 {phone} 已删除")
        else:
            update.message.reply_text(f"❌ 账号 {phone} 不存在")
        context.user_data.pop("action", None)
        return ConversationHandler.END
    
    # 添加账号
    if not phone.startswith("+"):
        update.message.reply_text("❌ 格式错误！手机号必须以 + 开头（如 +8613800000000）")
        return PHONE
    
    context.user_data["phone"] = phone
    # 同步执行，确保响应
    ok, msg = loop.run_until_complete(send_verification_code(phone))
    update.message.reply_text(msg)  # 强制发送回复
    return CODE if ok else ConversationHandler.END

def input_code(update: Update, context: CallbackContext):
    """处理验证码"""
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
        tasks[phone] = loop.create_task(watch_redpacket(phone))
        loop.create_task(auto_reconnect(phone))
    
    return ConversationHandler.END

def input_password(update: Update, context: CallbackContext):
    """处理两步验证"""
    pwd = update.message.text.strip()
    phone = context.user_data.get("phone")
    code = context.user_data.get("code")
    
    if not phone or not code:
        update.message.reply_text("❌ 信息丢失，请重新开始")
        return ConversationHandler.END
    
    ok, msg = loop.run_until_complete(login_account(phone, code, pwd))
    update.message.reply_text(msg)
    if ok:
        tasks[phone] = loop.create_task(watch_redpacket(phone))
        loop.create_task(auto_reconnect(phone))
    
    return ConversationHandler.END

# ==================== 保活 + 启动 ====================
def keep_alive():
    """Render 保活（线程版）"""
    while True:
        time.sleep(300)

def main():
    """主程序（修复启动）"""
    load_accounts()
    log("✅ 机器人启动中...")
    
    # 启动保活线程
    threading.Thread(target=keep_alive, daemon=True).start()
    
    # 机器人初始化（强制响应配置）
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # 对话处理器（无警告）
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="^add_account$|^delete_account$")],
        states={
            PHONE: [MessageHandler(Filters.text & ~Filters.command, input_phone)],
            CODE: [MessageHandler(Filters.text & ~Filters.command, input_code)],
            PASS: [MessageHandler(Filters.text & ~Filters.command, input_password)],
        },
        fallbacks=[],
        per_message=False
    )
    
    # 添加处理器
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_callback))
    dp.add_handler(conv_handler)
    
    # 强制轮询配置（确保响应）
    updater.start_polling(
        timeout=15, 
        read_latency=1, 
        drop_pending_updates=True,
        clean=True
    )
    log("✅ 机器人已启动，等待指令...")
    updater.idle()

if __name__ == "__main__":
    main()
