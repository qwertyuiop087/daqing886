"""
Telegram 红包控制系统
功能：
1. 一个控制机器人（@your_bot）接收你的指令
2. 自动登录多个用户账号抢红包
3. 所有操作通过机器人完成
"""

import os
import json
import asyncio
import logging
import random
from typing import Dict, Optional, Tuple
from datetime import datetime
from threading import Thread

from pyrogram import Client as UserClient
from pyrogram.types import Message as UserMessage
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    PhoneNumberInvalid, PhoneCodeInvalid, 
    PasswordHashInvalid, FloodWait,
    SessionRevoked, AuthKeyDuplicated
)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

# ==================== 配置区域 ====================
# 从 my.telegram.org 获取（用于登录用户账号）
USER_API_ID = int(os.environ.get("USER_API_ID", "0"))
USER_API_HASH = os.environ.get("USER_API_HASH", "")

# 从 @BotFather 获取（你的控制机器人）
BOT_TOKEN = os.environ.get("7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0", "")

# 你的Telegram用户ID（只有你能控制机器人）
YOUR_USER_ID = int(os.environ.get("7793291484", "0"))  # 获取方式：向 @userinfobot 发送任意消息

# 目标红包群ID
TARGET_GROUP_ID = -1003472034414

# 数据文件
ACCOUNTS_FILE = "accounts.json"
SESSIONS_DIR = "sessions"

# 对话状态
PHONE, CODE, PASSWORD = range(3)

# 日志配置
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

os.makedirs(SESSIONS_DIR, exist_ok=True)
# =============================================


class RedPacketManager:
    """红包账号管理器 - 负责所有用户账号的登录和抢红包"""
    
    def __init__(self):
        self.accounts: Dict[str, dict] = {}  # 手机号 -> 账号信息
        self.clients: Dict[str, UserClient] = {}  # 手机号 -> Pyrogram Client
        self.tasks: Dict[str, asyncio.Task] = {}  # 手机号 -> 监听任务
        self.load_accounts()
    
    def load_accounts(self):
        """从文件加载账号"""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    self.accounts = json.load(f)
                logger.info(f"✅ 已加载 {len(self.accounts)} 个账号")
            except:
                self.accounts = {}
    
    def save_accounts(self):
        """保存账号"""
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.accounts, f, indent=2, ensure_ascii=False)
    
    def add_account(self, phone: str):
        """添加新账号"""
        if phone not in self.accounts:
            self.accounts[phone] = {
                "phone": phone,
                "status": "pending",
                "added_time": datetime.now().isoformat(),
                "last_active": None,
                "user_id": None,
                "first_name": None,
                "stats": {
                    "total_attempts": 0,
                    "successful_clicks": 0
                }
            }
            self.save_accounts()
            return True
        return False
    
    def remove_account(self, phone: str):
        """删除账号"""
        if phone in self.accounts:
            # 停止监听
            if phone in self.tasks:
                self.tasks[phone].cancel()
                del self.tasks[phone]
            
            # 关闭客户端
            if phone in self.clients:
                asyncio.create_task(self.clients[phone].stop())
                del self.clients[phone]
            
            # 删除session文件
            session_file = f"{SESSIONS_DIR}/{phone.replace('+', '')}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
            
            del self.accounts[phone]
            self.save_accounts()
            return True
        return False
    
    def is_redpacket(self, message: UserMessage) -> Tuple[bool, Optional[InlineKeyboardButton]]:
        """判断是否为红包消息"""
        if not message or not message.reply_markup:
            return False, None
        
        if not isinstance(message.reply_markup, InlineKeyboardMarkup):
            return False, None
        
        # 红包按钮关键词
        keywords = ["领取", "点我", "open", "claim", "红包", "red", "拆开", "开红包"]
        
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                button_text = button.text.lower()
                if any(keyword in button_text for keyword in keywords):
                    return True, button
                if button.callback_data and "红包" in button_text:
                    return True, button
        
        return False, None
    
    async def click_redpacket(self, client: UserClient, message: UserMessage, button: InlineKeyboardButton) -> bool:
        """点击红包按钮"""
        try:
            # 随机延迟0.1-0.3秒
            await asyncio.sleep(random.uniform(0.1, 0.3))
            
            if button.callback_data:
                await client.request_callback_answer(
                    chat_id=message.chat.id,
                    message_id=message.id,
                    callback_data=button.callback_data
                )
                return True
            return False
        except Exception as e:
            logger.error(f"点击失败: {e}")
            return False
    
    async def listen_redpackets(self, phone: str):
        """监听指定账号的红包消息"""
        client = self.clients.get(phone)
        if not client:
            return
        
        logger.info(f"👂 开始监听账号 {phone} 的红包")
        
        @client.on_message()
        async def message_handler(client: UserClient, message: UserMessage):
            try:
                # 只监听目标群
                if message.chat.id != TARGET_GROUP_ID:
                    return
                
                # 判断是否为红包
                is_rp, button = self.is_redpacket(message)
                
                if is_rp and button:
                    logger.info(f"💰 {phone} 发现红包")
                    
                    # 更新统计
                    self.accounts[phone]["stats"]["total_attempts"] += 1
                    
                    # 点击红包
                    success = await self.click_redpacket(client, message, button)
                    
                    if success:
                        self.accounts[phone]["stats"]["successful_clicks"] += 1
                        logger.info(f"✅ {phone} 抢包成功")
                        self.save_accounts()
                    else:
                        logger.info(f"❌ {phone} 抢包失败")
                        
            except Exception as e:
                logger.error(f"消息处理错误: {e}")
        
        # 保持运行
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info(f"停止监听 {phone}")
    
    async def login_account(self, phone: str, code: str = None, password: str = None) -> Tuple[bool, str]:
        """登录账号"""
        try:
            session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
            client = UserClient(
                name=session_name,
                api_id=USER_API_ID,
                api_hash=USER_API_HASH,
                phone_number=phone,
                password=password,
                workdir="./"
            )
            
            await client.start()
            me = await client.get_me()
            
            # 保存客户端
            self.clients[phone] = client
            
            # 更新账号信息
            self.accounts[phone]["status"] = "active"
            self.accounts[phone]["user_id"] = me.id
            self.accounts[phone]["first_name"] = me.first_name
            self.accounts[phone]["last_active"] = datetime.now().isoformat()
            self.save_accounts()
            
            # 启动监听任务
            task = asyncio.create_task(self.listen_redpackets(phone))
            self.tasks[phone] = task
            
            return True, f"✅ 登录成功！用户: {me.first_name}"
            
        except PhoneNumberInvalid:
            return False, "❌ 手机号无效"
        except PhoneCodeInvalid:
            return False, "❌ 验证码错误"
        except PasswordHashInvalid:
            return False, "❌ 两步验证密码错误"
        except Exception as e:
            return False, f"❌ 登录失败: {str(e)}"
    
    async def auto_login_all(self):
        """自动登录所有已保存的账号"""
        for phone, info in self.accounts.items():
            if info.get("status") == "active":
                try:
                    session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
                    client = UserClient(
                        name=session_name,
                        api_id=USER_API_ID,
                        api_hash=USER_API_HASH,
                        workdir="./"
                    )
                    
                    await client.start()
                    me = await client.get_me()
                    
                    self.clients[phone] = client
                    info["status"] = "active"
                    info["last_active"] = datetime.now().isoformat()
                    
                    # 启动监听
                    task = asyncio.create_task(self.listen_redpackets(phone))
                    self.tasks[phone] = task
                    
                    logger.info(f"✅ 自动登录成功: {phone}")
                    
                except Exception as e:
                    logger.error(f"自动登录失败 {phone}: {e}")
                    info["status"] = "error"
                
                await asyncio.sleep(2)
        
        self.save_accounts()


# 全局管理器
manager = RedPacketManager()


# ==================== 控制机器人 ====================

# 启动命令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    user_id = update.effective_user.id
    
    # 只有你能用
    if user_id != YOUR_USER_ID:
        await update.message.reply_text("❌ 你没有权限使用这个机器人")
        return
    
    keyboard = [
        [InlineKeyboardButton("📱 添加账号", callback_data="add_account")],
        [InlineKeyboardButton("📋 账号列表", callback_data="list_accounts")],
        [InlineKeyboardButton("📊 抢包统计", callback_data="show_stats")],
        [InlineKeyboardButton("🔄 刷新状态", callback_data="refresh")]
    ]
    
    await update.message.reply_text(
        "🤖 *红包控制系统*\n\n"
        f"当前在线账号: {len(manager.clients)}/{len(manager.accounts)}\n"
        f"目标群ID: `{TARGET_GROUP_ID}`\n\n"
        "请选择操作:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


# 处理按钮回调
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮点击"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        await query.edit_message_text("❌ 你没有权限")
        return
    
    data = query.data
    
    if data == "add_account":
        await query.edit_message_text(
            "📱 *添加新账号*\n\n"
            "请输入手机号（格式：+861234567890）:",
            parse_mode='Markdown'
        )
        return ConversationHandler.END  # 这里需要设置正确的状态
    
    elif data == "list_accounts":
        if not manager.accounts:
            await query.edit_message_text("📭 暂无账号")
            return
        
        text = "📋 *账号列表*\n\n"
        keyboard = []
        
        for phone, info in manager.accounts.items():
            status_icon = "🟢" if info["status"] == "active" else "🔴" if info["status"] == "error" else "🟡"
            name = info.get("first_name", "未登录")
            text += f"{status_icon} `{phone}`\n   └ {name}\n"
            
            # 添加删除按钮
            keyboard.append([InlineKeyboardButton(
                f"🗑️ 删除 {phone[-4:]}", 
                callback_data=f"del_{phone}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="back")])
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == "show_stats":
        total = len(manager.accounts)
        active = len(manager.clients)
        
        total_attempts = sum(a.get("stats", {}).get("total_attempts", 0) for a in manager.accounts.values())
        total_success = sum(a.get("stats", {}).get("successful_clicks", 0) for a in manager.accounts.values())
        
        success_rate = (total_success / total_attempts * 100) if total_attempts > 0 else 0
        
        text = (
            "📊 *抢包统计*\n\n"
            f"总账号数: {total}\n"
            f"在线账号: {active}\n"
            f"总尝试: {total_attempts}\n"
            f"成功次数: {total_success}\n"
            f"成功率: {success_rate:.1f}%\n\n"
            f"目标群: `{TARGET_GROUP_ID}`"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="back")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == "refresh":
        text = (
            "🔄 *状态已刷新*\n\n"
            f"在线账号: {len(manager.clients)}/{len(manager.accounts)}"
        )
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="back")]]
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == "back":
        await start(update, context)
    
    elif data.startswith("del_"):
        phone = data[4:]
        if manager.remove_account(phone):
            await query.edit_message_text(f"✅ 已删除账号 {phone}")
        else:
            await query.edit_message_text(f"❌ 删除失败")


# 添加账号 - 输入手机号
async def add_account_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """输入手机号"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    phone = update.message.text.strip()
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 手机号格式错误，请以 + 开头（如 +861234567890）")
        return PHONE
    
    # 保存手机号到context
    context.user_data['phone'] = phone
    
    # 添加账号
    if manager.add_account(phone):
        await update.message.reply_text(
            f"✅ 账号 {phone} 已添加\n\n"
            "现在请输入登录验证码（查看控制台日志获取）:"
        )
        return CODE
    else:
        await update.message.reply_text("❌ 账号已存在")
        return ConversationHandler.END


# 输入验证码
async def add_account_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """输入验证码"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    code = update.message.text.strip()
    phone = context.user_data.get('phone')
    
    # 尝试登录
    success, msg = await manager.login_account(phone, code)
    
    if success:
        await update.message.reply_text(f"✅ {msg}\n\n开始监听红包...")
        return ConversationHandler.END
    else:
        # 可能需要两步验证
        if "两步验证" in msg:
            context.user_data['code'] = code
            await update.message.reply_text("请输入两步验证密码:")
            return PASSWORD
        else:
            await update.message.reply_text(msg)
            return ConversationHandler.END


# 输入两步验证密码
async def add_account_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """输入两步验证密码"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    password = update.message.text.strip()
    phone = context.user_data.get('phone')
    code = context.user_data.get('code')
    
    success, msg = await manager.login_account(phone, code, password)
    
    await update.message.reply_text(msg)
    return ConversationHandler.END


# 取消
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消操作"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    await update.message.reply_text("❌ 操作已取消")
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    logger.error(f"更新出错 {update}: {context.error}")


# ==================== 主程序 ====================

async def main():
    """主函数"""
    # 创建机器人应用
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 添加对话处理器
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="^add_account$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_phone)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_code)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(conv_handler)
    app.add_error_handler(error_handler)
    
    # 启动自动登录已有账号
    asyncio.create_task(manager.auto_login_all())
    
    # 启动机器人
    print("🤖 红包控制系统已启动...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # 保持运行
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("🛑 正在关闭...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
