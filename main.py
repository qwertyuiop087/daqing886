import os
import json
import asyncio
import random
import threading
from typing import Dict, Any, Tuple, Optional

from pyrogram import Client, errors as py_errors
from pyrogram.types import Message
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

# Conversation states
PHONE, CODE, PASS = range(3)

# 文件/目录
ACCOUNTS = "accounts.json"
SESSIONS = "sessions"
os.makedirs(SESSIONS, exist_ok=True)

# 线程安全锁与全局结构
_accounts_lock = threading.Lock()
_clients_lock = threading.Lock()
_pending_lock = threading.Lock()  # 用于存放需要两步密码完成的临时 client
accounts: Dict[str, Any] = {}
clients: Dict[str, Client] = {}
pending_clients: Dict[str, Client] = {}  # 存放因两步验证等待密码的 client

# 加载/保存账号（线程安全）
def load_accounts() -> Dict[str, Any]:
    if os.path.exists(ACCOUNTS):
        with open(ACCOUNTS, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_accounts(data: Dict[str, Any]) -> None:
    with _accounts_lock:
        with open(ACCOUNTS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# 初始化 accounts
accounts = load_accounts()

# 后台 asyncio loop（独立线程运行，避免阻塞主线程）
_async_loop = asyncio.new_event_loop()

def _start_event_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

_loop_thread = threading.Thread(target=_start_event_loop, args=(_async_loop,), daemon=True)
_loop_thread.start()

# 将协程提交到后台事件循环并等待结果（同步调用时使用）
def run_async(coro: asyncio.coroutine, timeout: Optional[float] = 30):
    """
    将协程提交到后台事件循环并等待结果（线程安全）。
    """
    future = asyncio.run_coroutine_threadsafe(coro, _async_loop)
    return future.result(timeout)

# 发送验证码（异步实现）
async def _send_verification_code_async(phone: str) -> Tuple[bool, str, Optional[str]]:
    """
    发送验证码并返回 (ok, message, phone_code_hash)
    phone_code_hash 需要在后续 sign_in 时使用以避免 client.start() 的交互提示。
    """
    session_name = os.path.join(SESSIONS, phone)
    client = Client(session_name, API_ID, API_HASH)
    try:
        await client.connect()
        # send_code 会返回一个对象，通常包含 phone_code_hash
        sent = await client.send_code(phone)
        phone_code_hash = getattr(sent, "phone_code_hash", None)
        return True, "✅ 验证码已发送（请在设备或 Telegram 客户端查收）", phone_code_hash
    except py_errors.PhoneNumberInvalid:
        return False, "❌ 手机号无效（格式：+8613800000000）", None
    except py_errors.FloodWait as e:
        # FloodWait 中字段名版本差异，尽量兼容
        wait_seconds = getattr(e, "value", None) or getattr(e, "x", None) or getattr(e, "timeout", None) or getattr(e, "wait", None)
        return False, f"❌ 操作频繁，请等待 {wait_seconds} 秒后重试", None
    except Exception as e:
        return False, f"❌ 发送失败：{str(e)}", None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

def send_verification_code(phone: str) -> Tuple[bool, str, Optional[str]]:
    """
    同步包装：在主线程中调用以请求发送验证码并获取 phone_code_hash。
    """
    return run_async(_send_verification_code_async(phone))

# 登录账号（异步实现，避免 client.start() 触发 stdin 读取）
async def _login_account_async(phone: str, code: str, phone_code_hash: Optional[str] = None, password: Optional[str] = None) -> Tuple[bool, str]:
    """
    使用 sign_in 流程完成登录，避免调用会尝试读取 stdin 的 client.start()。
    - 若服务器要求两步验证（SessionPasswordNeeded），会将 client 放入 pending_clients 并返回 "need_password"。
    - 成功登录后将 client 放入 clients 并保存账号状态。
    """
    session_name = os.path.join(SESSIONS, phone)
    client = Client(session_name, API_ID, API_HASH)
    try:
        await client.connect()
        # 如果提供了密码，尝试用密码完成两步登录（此处为补充路径）
        if password:
            try:
                # 尝试 sign_in(password=...)（pyrogram 不同版本方法名差异）
                await client.sign_in(password=password)
            except AttributeError:
                # 若没有 sign_in(password), 使用 check_password
                await client.check_password(password)
        else:
            # 使用 phone_code + phone_code_hash 完成首次登录
            try:
                if phone_code_hash:
                    # 常见用法：sign_in(phone_number=..., phone_code=..., phone_code_hash=...)
                    await client.sign_in(phone_number=phone, phone_code=code, phone_code_hash=phone_code_hash)
                else:
                    # 不含 phone_code_hash 时尝试不带 hash 的 sign_in（某些版本接受）
                    await client.sign_in(phone_number=phone, phone_code=code)
            except py_errors.SessionPasswordNeeded:
                # 需要两步验证密码，保留 client 等待密码
                with _pending_lock:
                    pending_clients[phone] = client
                return False, "need_password"
            except py_errors.PhoneCodeInvalid:
                await client.disconnect()
                return False, "❌ 验证码错误，请重新输入"
            except Exception as e:
                # 若 sign_in 接口不存在或行为不同，尝试更通用的 start 登录方式但传入参数以避免 stdin 交互
                try:
                    await client.start(phone_number=phone, password=password)
                except Exception:
                    await client.disconnect()
                    return False, f"❌ 登录失败：{str(e)}"

        # 检查是否已授权（获取当前用户信息作为验证）
        try:
            me = await client.get_me()
            if me is None:
                await client.disconnect()
                return False, "❌ 登录失败（未能获取用户信息）"
        except Exception:
            await client.disconnect()
            return False, "❌ 登录失败（获取用户信息时出错）"

        # 登录成功：将 client 放入全局 clients（持久保持连接）
        with _clients_lock:
            clients[phone] = client
        with _accounts_lock:
            accounts[phone] = {"status": "active"}
            save_accounts(accounts)
        return True, "✅ 登录成功！已开始监听红包"
    except py_errors.PhoneCodeInvalid:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, "❌ 验证码错误，请重新输入"
    except py_errors.SessionPasswordNeeded:
        # 备用处理（若上面未捕获到）
        with _pending_lock:
            pending_clients[phone] = client
        return False, "need_password"
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"❌ 登录失败：{str(e)}"

def login_account(phone: str, code: str, phone_code_hash: Optional[str] = None, password: Optional[str] = None) -> Tuple[bool, str]:
    """
    同步包装：提交异步登录任务到后台 loop 并等待结果。
    """
    return run_async(_login_account_async(phone, code, phone_code_hash, password))

# 当用户输入两步验证密码时，完成登录（如果有 pending client）
def finish_two_factor_and_store(phone: str, password: str) -> Tuple[bool, str]:
    with _pending_lock:
        client = pending_clients.pop(phone, None)
    if client is None:
        return False, "❌ 未找到等待两步验证的会话，请重新开始登录流程"

    async def _complete():
        try:
            try:
                await client.sign_in(password=password)
            except AttributeError:
                await client.check_password(password)
            me = await client.get_me()
            if me is None:
                await client.disconnect()
                return False, "❌ 两步验证完成失败（未能获取用户信息）"
            with _clients_lock:
                clients[phone] = client
            with _accounts_lock:
                accounts[phone] = {"status": "active"}
                save_accounts(accounts)
            return True, "✅ 登录成功！已开始监听红包"
        except py_errors.SessionPasswordNeeded:
            try:
                await client.disconnect()
            except Exception:
                pass
            return False, "❌ 两步验证密码错误，请重试"
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            return False, f"❌ 两步验证失败：{str(e)}"

    return run_async(_complete())

# 自动抢红包：简单轮询实现（兼容性更高）
async def _watch_redpacket_loop(phone: str):
    """
    轮询获取群组最新消息并扫描 inline_keyboard 按钮文本。
    若发现匹配关键词，则尝试触发 callback（仅在 client 支持的情况下尝试）。
    该实现为保守兼容版本，避免依赖 pyrogram handler 版本差异。
    """
    with _clients_lock:
        client = clients.get(phone)
    if client is None:
        return

    last_message_id = 0

    try:
        while True:
            try:
                # 尝试获取最近若干条消息（方法名在不同 pyrogram 版本可能不同）
                # 优先使用 get_history，如果不存在再尝试 get_chat_history
                if hasattr(client, "get_history"):
                    msgs = await client.get_history(GROUP_ID, limit=10)
                else:
                    msgs = await client.get_chat_history(GROUP_ID, limit=10)
            except Exception:
                # 若获取失败，等待后重试
                await asyncio.sleep(5)
                continue

            # msgs 可能为 单条或列表，确保为列表
            if not isinstance(msgs, (list, tuple)):
                msgs = [msgs]

            # 按时间/ID递增处理
            msgs = sorted([m for m in msgs if getattr(m, "id", 0) > last_message_id], key=lambda x: x.id)
            for m in msgs:
                last_message_id = max(last_message_id, getattr(m, "id", 0))
                markup = getattr(m, "reply_markup", None)
                if not markup or not getattr(markup, "inline_keyboard", None):
                    continue
                for row in markup.inline_keyboard:
                    for btn in row:
                        text = getattr(btn, "text", "") or ""
                        if any(keyword in text for keyword in ["领取", "红包", "开", "点我", "拆开"]):
                            # 随机短暂等待以模拟人工点击
                            await asyncio.sleep(random.uniform(0.2, 0.6))
                            # 尝试触发回调（若 client 提供 click API）
                            try:
                                if hasattr(client, "click"):
                                    await client.click(m.chat.id, m.id, btn.callback_data)
                                # 若无 click，则尽量不抛异常，记录并继续
                            except Exception:
                                pass
                            # 触发一次后跳出该消息的按钮循环
                            break
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        return
    except Exception:
        # 若出现不可预见错误，短暂休眠后重试主循环
        await asyncio.sleep(5)
        return

def start_watch_redpacket(phone: str):
    """
    将抢红包协程提交到后台事件循环。
    """
    asyncio.run_coroutine_threadsafe(_watch_redpacket_loop(phone), _async_loop)

# Telegram Bot Command: /start
def start(update: Update, context: CallbackContext):
    """
    /start 命令，仅允许 ADMIN_ID 使用。
    通过内联按钮触发添加账号流程。
    """
    user = update.effective_user
    if user is None or user.id != ADMIN_ID:
        update.message.reply_text("❌ 无操作权限")
        return
    update.message.reply_text(
        "🤖 红包机器人（修复版）\n\n操作说明：\n1. 点击「添加账号」\n2. 输入+86开头手机号\n3. 输入验证码完成登录",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ 添加账号", callback_data="add_account")]])
    )

# 回调按钮处理：添加账号
def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    if query is None:
        return
    query.answer()
    if query.data == "add_account":
        query.edit_message_text("📱 请输入手机号（格式：+8613800000000）")
        return PHONE

# 接收手机号（同步处理）
def input_phone(update: Update, context: CallbackContext):
    msg = update.message
    if msg is None:
        return ConversationHandler.END
    phone = msg.text.strip()
    if not phone.startswith("+"):
        update.message.reply_text("❌ 格式错误！手机号必须以 + 开头（如 +8613800000000）")
        return PHONE
    context.user_data["phone"] = phone
    try:
        ok, rsp, phone_code_hash = send_verification_code(phone)
        update.message.reply_text(rsp)
        if ok:
            # 保存 phone_code_hash 供后续 sign_in 使用
            context.user_data["phone_code_hash"] = phone_code_hash
            return CODE
        else:
            return ConversationHandler.END
    except Exception as e:
        update.message.reply_text(f"❌ 系统错误：{str(e)}")
        return ConversationHandler.END

# 接收验证码（同步处理）
def input_code(update: Update, context: CallbackContext):
    msg = update.message
    if msg is None:
        return ConversationHandler.END
    code = msg.text.strip()
    phone = context.user_data.get("phone")
    phone_code_hash = context.user_data.get("phone_code_hash")
    if not phone:
        update.message.reply_text("❌ 未检测到手机号，请重新开始")
        return ConversationHandler.END
    try:
        ok, rsp = login_account(phone, code, phone_code_hash)
    except Exception as e:
        update.message.reply_text(f"❌ 系统错误：{str(e)}")
        return ConversationHandler.END

    if rsp == "need_password":
        # 登录流程等待两步验证密码
        context.user_data["code"] = code
        update.message.reply_text("🔐 请输入两步验证密码")
        return PASS

    update.message.reply_text(rsp)
    if ok:
        # 在后台开始监听抢红包任务
        start_watch_redpacket(phone)
    return ConversationHandler.END

# 接收两步验证密码（同步处理）
def input_password(update: Update, context: CallbackContext):
    msg = update.message
    if msg is None:
        return ConversationHandler.END
    pwd = msg.text.strip()
    phone = context.user_data.get("phone")
    code = context.user_data.get("code")
    if not phone or not code:
        update.message.reply_text("❌ 信息丢失，请重新开始")
        return ConversationHandler.END
    try:
        ok, rsp = finish_two_factor_and_store(phone, pwd)
    except Exception as e:
        update.message.reply_text(f"❌ 系统错误：{str(e)}")
        return ConversationHandler.END

    update.message.reply_text(rsp)
    if ok:
        start_watch_redpacket(phone)
    return ConversationHandler.END

# Render 保活（线程版，防止容器被回收）——仅心跳，不影响业务逻辑
def keep_alive():
    while True:
        threading.Event().wait(300)

# 主程序入口
def main():
    # 后台保活线程
    threading.Thread(target=keep_alive, daemon=True).start()

    # Telegram Bot（python-telegram-bot v13 风格）
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
