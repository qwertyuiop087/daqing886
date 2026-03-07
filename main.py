"""
Telegram 红包控制系统 - Python 3.14 兼容版
"""

import os
import json
import asyncio
import logging
import random
import sys
from typing import Dict, Optional, Tuple
from datetime import datetime

# ==================== Python 3.14 兼容性修复 ====================
# 必须在导入任何异步库之前设置事件循环
if sys.version_info >= (3, 14):
    try:
        # 尝试获取当前事件循环
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 如果没有，创建一个新的
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # 设置事件循环策略
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
# ================================================================

from pyrogram import Client as UserClient
from pyrogram.types import Message as UserMessage
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    PhoneNumberInvalid, PhoneCodeInvalid, 
    PasswordHashInvalid, FloodWait
)

from telegram import Update, InlineKeyboardButton as TGBotton, InlineKeyboardMarkup as TGMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

# ==================== 你的配置 ====================
USER_API_ID = 38596687
USER_API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
YOUR_USER_ID = 7793291484
TARGET_GROUP_ID = -1003472034414

ACCOUNTS_FILE = "accounts.json"
SESSIONS_DIR = "sessions"

PHONE, CODE, PASSWORD = range(3)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

os.makedirs(SESSIONS_DIR, exist_ok=True)
# =============================================


class RedPacketManager:
    def __init__(self):
        self.accounts: Dict[str, dict] = {}
        self.clients: Dict[str, UserClient] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.load_accounts()
    
    def load_accounts(self):
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    self.accounts = json.load(f)
                logger.info(f"✅ 已加载 {len(self.accounts)} 个账号")
            except:
                self.accounts = {}
        else:
            self.accounts = {}
            self.save_accounts()
    
    def save_accounts(self):
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def add_account(self, phone: str):
        if phone not in self.accounts:
            self.accounts[phone] = {
                "phone": phone,
                "status": "pending",
                "added_time": datetime.now().isoformat(),
                "last_active": None,
                "user_id": None,
                "first_name": None,
                "stats": {"total_attempts": 0, "successful_clicks": 0}
            }
            self.save_accounts()
            return True
        return False
    
    def remove_account(self, phone: str):
        if phone in self.accounts:
            if phone in self.tasks:
                self.tasks[phone].cancel()
                del self.tasks[phone]
            if phone in self.clients:
                asyncio.create_task(self.clients[phone].stop())
                del self.clients[phone]
            
            session_file = f"{SESSIONS_DIR}/{phone.replace('+', '')}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
            
            del self.accounts[phone]
            self.save_accounts()
            return True
        return False
    
    def is_redpacket(self, message: UserMessage) -> Tuple[bool, Optional[InlineKeyboardButton]]:
        if not message or not message.reply_markup:
            return False, None
        
        keywords = ["领取", "点我", "open", "claim", "红包", "red", "拆开", "开红包"]
        
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if any(k in button.text.lower() for k in keywords):
                    return True, button
        return False, None
    
    async def click_redpacket(self, client: UserClient, message: UserMessage, button: InlineKeyboardButton) -> bool:
        try:
            await asyncio.sleep(random.uniform(0.1, 0.3))
            if button.callback_data:
                await client.request_callback_answer(
                    chat_id=message.chat.id,
                    message_id=message.id,
                    callback_data=button.callback_data
                )
                return True
            return False
        except:
            return False
    
    async def listen_redpackets(self, phone: str):
        client = self.clients.get(phone)
        if not client:
            return
        
        @client.on_message()
        async def handler(client: UserClient, message: UserMessage):
            try:
                if message.chat.id != TARGET_GROUP_ID:
                    return
                
                is_rp, button = self.is_redpacket(message)
                if is_rp and button:
                    if phone in self.accounts:
                        self.accounts[phone]["stats"]["total_attempts"] += 1
                    
                    success = await self.click_redpacket(client, message, button)
                    
                    if success and phone in self.accounts:
                        self.accounts[phone]["stats"]["successful_clicks"] += 1
                        self.save_accounts()
            except:
                pass
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
    
    async def login_account(self, phone: str, code: str = None, password: str = None) -> Tuple[bool, str]:
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
            
            self.clients[phone] = client
            self.accounts[phone]["status"] = "active"
            self.accounts[phone]["user_id"] = me.id
            self.accounts[phone]["first_name"] = me.first_name
            self.accounts[phone]["last_active"] = datetime.now().isoformat()
            self.save_accounts()
            
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
                    
                    task = asyncio.create_task(self.listen_redpackets(phone))
                    self.tasks[phone] = task
                    
                except:
                    info["status"] = "error"
                
                await asyncio.sleep(2)
        
        self.save_accounts()


manager = RedPacketManager()


# ==================== 机器人处理器 ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("❌ 无权限")
        return
    
    keyboard = [
        [TGBotton("📱 添加账号", callback_data="add_account")],
        [TGBotton("📋 账号列表", callback_data="list_accounts")],
        [TGBotton("📊 统计", callback_data="stats")],
    ]
    
    await update.message.reply_text(
        f"🤖 红包系统\n在线: {len(manager.clients)}/{len(manager.accounts)}",
        reply_markup=TGMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != YOUR_USER_ID:
        return
    
    if query.data == "add_account":
        await query.edit_message_text("📱 请输入手机号 (+86...):")
        return PHONE
    
    elif query.data == "list_accounts":
        if not manager.accounts:
            await query.edit_message_text("📭 暂无账号")
            return
        
        text = "📋 账号列表:\n"
        for phone, info in manager.accounts.items():
            status = "🟢" if info["status"] == "active" else "🔴"
            text += f"{status} {phone}\n"
        await query.edit_message_text(text)
    
    elif query.data == "stats":
        total = sum(a["stats"]["total_attempts"] for a in manager.accounts.values())
        success = sum(a["stats"]["successful_clicks"] for a in manager.accounts.values())
        await query.edit_message_text(f"📊 总尝试: {total}\n✅ 成功: {success}")
    
    return ConversationHandler.END


async def add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    phone = update.message.text.strip()
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 格式错误，请以+开头")
        return PHONE
    
    context.user_data['phone'] = phone
    manager.add_account(phone)
    await update.message.reply_text("✅ 已添加，请输入验证码:")
    return CODE


async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    code = update.message.text.strip()
    phone = context.user_data.get('phone')
    
    success, msg = await manager.login_account(phone, code)
    
    if success:
        await update.message.reply_text(f"✅ {msg}")
        return ConversationHandler.END
    else:
        if "两步验证" in msg:
            context.user_data['code'] = code
            await update.message.reply_text("请输入两步验证密码:")
            return PASSWORD
        else:
            await update.message.reply_text(msg)
            return ConversationHandler.END


async def add_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    password = update.message.text.strip()
    phone = context.user_data.get('phone')
    code = context.user_data.get('code')
    
    success, msg = await manager.login_account(phone, code, password)
    await update.message.reply_text(msg)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ 已取消")
    return ConversationHandler.END


# ==================== 主函数 ====================
async def main():
    """主函数"""
    logger.info("🚀 启动红包系统...")
    
    # 再次确保事件循环存在（Python 3.14+）
    if sys.version_info >= (3, 14):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    
    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 添加处理器
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add_account$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_code)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(conv_handler)
    
    # 启动自动登录
    asyncio.create_task(manager.auto_login_all())
    
    # 启动机器人
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    logger.info("✅ 机器人已启动")
    
    # 无限循环
    while True:
        await asyncio.sleep(10)
        logger.debug(f"心跳 - 在线账号: {len(manager.clients)}")


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 启动红包控制系统")
    print(f"目标群: {TARGET_GROUP_ID}")
    print("=" * 50)
    
    # Python 3.14+ 兼容性修复
    if sys.version_info >= (3, 14):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        except:
            pass
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序停止")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import time
        time.sleep(5)
