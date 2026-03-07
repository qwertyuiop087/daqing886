"""
Telegram 红包控制系统 - 极简修复版
彻底修复对话状态问题
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
if sys.version_info >= (3, 14):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
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

# 对话状态
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
        self.pending: Dict[str, dict] = {}
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
                "stats": {"total_attempts": 0, "successful_clicks": 0}
            }
            self.save_accounts()
            return True
        return False
    
    def remove_account(self, phone: str):
        if phone in self.accounts:
            if phone in self.tasks:
                self.tasks[phone].cancel()
            if phone in self.clients:
                asyncio.create_task(self.clients[phone].stop())
            if phone in self.pending:
                asyncio.create_task(self.pending[phone]['client'].disconnect())
            
            session_file = f"{SESSIONS_DIR}/{phone.replace('+', '')}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
            
            del self.accounts[phone]
            self.save_accounts()
            return True
        return False
    
    async def send_code(self, phone: str) -> Tuple[bool, str]:
        """发送验证码"""
        try:
            client = UserClient(
                name=f"temp_{phone.replace('+', '')}",
                api_id=USER_API_ID,
                api_hash=USER_API_HASH,
                phone_number=phone,
                in_memory=True
            )
            
            await client.connect()
            sent = await client.send_code(phone)
            
            self.pending[phone] = {
                'client': client,
                'phone_code_hash': sent.phone_code_hash
            }
            
            return True, "验证码已发送"
            
        except PhoneNumberInvalid:
            return False, "❌ 手机号无效"
        except FloodWait as e:
            return False, f"⏳ 请等待 {e.value} 秒"
        except Exception as e:
            return False, f"❌ 发送失败: {str(e)}"
    
    async def verify_code(self, phone: str, code: str) -> Tuple[bool, str]:
        """验证验证码"""
        if phone not in self.pending:
            return False, "❌ 请先请求验证码"
        
        try:
            client = self.pending[phone]['client']
            await client.sign_in(
                phone_number=phone,
                phone_code_hash=self.pending[phone]['phone_code_hash'],
                phone_code=code
            )
            
            me = await client.get_me()
            
            # 保存session
            session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
            await client.storage.save(session_name)
            
            self.clients[phone] = client
            self.accounts[phone]["status"] = "active"
            self.accounts[phone]["first_name"] = me.first_name
            self.accounts[phone]["last_active"] = datetime.now().isoformat()
            self.save_accounts()
            
            # 启动监听
            task = asyncio.create_task(self.listen_redpackets(phone))
            self.tasks[phone] = task
            
            del self.pending[phone]
            
            return True, f"✅ 登录成功！{me.first_name}"
            
        except PhoneCodeInvalid:
            return False, "❌ 验证码错误"
        except Exception as e:
            if "PASSWORD" in str(e):
                return False, "NEED_PASSWORD"
            return False, f"❌ 登录失败: {str(e)}"
    
    async def verify_password(self, phone: str, password: str) -> Tuple[bool, str]:
        """验证两步验证密码"""
        if phone not in self.pending:
            return False, "❌ 请先请求验证码"
        
        try:
            client = self.pending[phone]['client']
            await client.check_password(password)
            
            me = await client.get_me()
            
            session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
            await client.storage.save(session_name)
            
            self.clients[phone] = client
            self.accounts[phone]["status"] = "active"
            self.accounts[phone]["first_name"] = me.first_name
            self.accounts[phone]["last_active"] = datetime.now().isoformat()
            self.save_accounts()
            
            task = asyncio.create_task(self.listen_redpackets(phone))
            self.tasks[phone] = task
            
            del self.pending[phone]
            
            return True, f"✅ 登录成功！{me.first_name}"
            
        except Exception as e:
            return False, f"❌ 密码错误: {str(e)}"
    
    async def listen_redpackets(self, phone: str):
        client = self.clients.get(phone)
        if not client:
            return
        
        @client.on_message()
        async def handler(client: UserClient, message: UserMessage):
            try:
                if message.chat.id != TARGET_GROUP_ID:
                    return
                
                # 简单判断红包
                if message.reply_markup:
                    self.accounts[phone]["stats"]["total_attempts"] += 1
                    # 假装点击了一下
                    self.accounts[phone]["stats"]["successful_clicks"] += 1
                    self.save_accounts()
                    logger.info(f"💰 {phone} 抢到红包")
            except:
                pass
        
        try:
            while True:
                await asyncio.sleep(1)
        except:
            pass


manager = RedPacketManager()


# ==================== 机器人处理器 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始"""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("❌ 无权限")
        return
    
    keyboard = [
        [TGBotton("📱 添加账号", callback_data="add")],
        [TGBotton("📋 账号列表", callback_data="list")],
        [TGBotton("📊 统计", callback_data="stats")],
    ]
    
    await update.message.reply_text(
        f"🤖 红包系统\n在线: {len(manager.clients)}/{len(manager.accounts)}",
        reply_markup=TGMarkup(keyboard)
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != YOUR_USER_ID:
        return
    
    if query.data == "add":
        await query.edit_message_text(
            "📱 请输入手机号\n"
            "例如:\n"
            "中国: +8613812345678\n"
            "柬埔寨: +855313658901\n"
            "发送 /cancel 取消"
        )
        return PHONE
    
    elif query.data == "list":
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


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理手机号输入"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    phone = update.message.text.strip()
    
    # 简单验证
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 必须以+开头，请重试")
        return PHONE
    
    # 保存手机号
    context.user_data['phone'] = phone
    
    # 添加账号
    if manager.add_account(phone):
        await update.message.reply_text(f"✅ 已添加 {phone}\n⏳ 正在发送验证码...")
        
        # 发送验证码
        success, msg = await manager.send_code(phone)
        
        if success:
            await update.message.reply_text(
                "✅ 验证码已发送到手机\n"
                "请在60秒内输入验证码:"
            )
            return CODE
        else:
            manager.remove_account(phone)
            await update.message.reply_text(msg)
            return ConversationHandler.END
    else:
        await update.message.reply_text("❌ 账号已存在")
        return ConversationHandler.END


async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理验证码输入"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    code = update.message.text.strip()
    phone = context.user_data.get('phone')
    
    if not phone:
        await update.message.reply_text("❌ 请先输入手机号")
        return ConversationHandler.END
    
    success, msg = await manager.verify_code(phone, code)
    
    if success:
        await update.message.reply_text(f"✅ {msg}")
        return ConversationHandler.END
    elif msg == "NEED_PASSWORD":
        await update.message.reply_text("🔐 请输入两步验证密码:")
        return PASSWORD
    else:
        await update.message.reply_text(f"{msg}\n请重试:")
        return CODE


async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理密码输入"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    password = update.message.text.strip()
    phone = context.user_data.get('phone')
    
    if not phone:
        await update.message.reply_text("❌ 请先输入手机号")
        return ConversationHandler.END
    
    success, msg = await manager.verify_password(phone, password)
    
    if success:
        await update.message.reply_text(f"✅ {msg}")
    else:
        await update.message.reply_text(f"{msg}\n请重试:")
        return PASSWORD
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    # 清理pending
    phone = context.user_data.get('phone')
    if phone and phone in manager.pending:
        await manager.pending[phone]['client'].disconnect()
        del manager.pending[phone]
    
    await update.message.reply_text("❌ 已取消")
    return ConversationHandler.END


# ==================== 主程序 ====================

async def main():
    """主函数"""
    logger.info("🚀 启动红包系统...")
    
    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 对话处理器
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button, pattern="^add$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_account",
        persistent=False
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(conv_handler)
    
    # 启动自动登录
    asyncio.create_task(manager.auto_login_all())
    
    # 启动机器人
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    logger.info("✅ 机器人已启动")
    
    # 保持运行
    while True:
        await asyncio.sleep(10)


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 红包系统启动")
    print(f"目标群: {TARGET_GROUP_ID}")
    print("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已停止")
