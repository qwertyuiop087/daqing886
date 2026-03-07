"""
Telegram 红包控制系统 - 完整修复版
"""

import os
import json
import asyncio
import logging
import random
import sys
from typing import Dict, Optional, Tuple
from datetime import datetime

# ==================== Python 3.10 兼容 ====================
import asyncio
# ==========================================================

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
        """加载账号"""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    self.accounts = json.load(f)
                logger.info(f"✅ 已加载 {len(self.accounts)} 个账号")
            except Exception as e:
                logger.error(f"加载账号失败: {e}")
                self.accounts = {}
        else:
            self.accounts = {}
            self.save_accounts()
    
    def save_accounts(self):
        """保存账号"""
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存账号失败: {e}")
    
    def add_account(self, phone: str):
        """添加账号"""
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
            logger.info(f"✅ 已添加账号: {phone}")
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
            
            # 清理pending
            if phone in self.pending:
                asyncio.create_task(self.pending[phone]['client'].disconnect())
                del self.pending[phone]
            
            # 删除session文件
            session_file = f"{SESSIONS_DIR}/{phone.replace('+', '')}.session"
            if os.path.exists(session_file):
                os.remove(session_file)
            
            del self.accounts[phone]
            self.save_accounts()
            logger.info(f"✅ 已删除账号: {phone}")
            return True
        return False
    
    async def auto_login_all(self):
        """自动登录所有已保存的账号"""
        logger.info("🔄 开始自动登录已有账号...")
        
        for phone, info in self.accounts.items():
            if info.get("status") == "active":
                try:
                    session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
                    
                    # 检查session文件是否存在
                    if not os.path.exists(f"{session_name}.session"):
                        logger.info(f"⏳ 账号 {phone} 需要首次登录")
                        info["status"] = "pending"
                        self.save_accounts()
                        continue
                    
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
                    info["user_id"] = me.id
                    info["first_name"] = me.first_name
                    info["last_active"] = datetime.now().isoformat()
                    
                    # 启动监听
                    task = asyncio.create_task(self.listen_redpackets(phone))
                    self.tasks[phone] = task
                    
                    logger.info(f"✅ 自动登录成功: {phone} ({me.first_name})")
                    
                except Exception as e:
                    logger.error(f"自动登录失败 {phone}: {e}")
                    info["status"] = "error"
                    self.save_accounts()
                
                await asyncio.sleep(2)  # 避免请求过快
        
        self.save_accounts()
        logger.info(f"🎯 当前在线账号: {len(self.clients)} 个")
    
    async def send_code(self, phone: str) -> Tuple[bool, str]:
        """发送验证码"""
        try:
            # 创建临时客户端
            client = UserClient(
                name=f"temp_{phone.replace('+', '')}",
                api_id=USER_API_ID,
                api_hash=USER_API_HASH,
                phone_number=phone,
                in_memory=True
            )
            
            await client.connect()
            sent = await client.send_code(phone)
            
            # 保存到pending
            self.pending[phone] = {
                'client': client,
                'phone_code_hash': sent.phone_code_hash
            }
            
            return True, "✅ 验证码已发送到你的手机"
            
        except PhoneNumberInvalid:
            return False, "❌ 手机号无效，请检查格式"
        except FloodWait as e:
            return False, f"⏳ 请求太频繁，请等待 {e.value} 秒"
        except Exception as e:
            return False, f"❌ 发送失败: {str(e)}"
    
    async def verify_code(self, phone: str, code: str) -> Tuple[bool, str]:
        """验证验证码"""
        if phone not in self.pending:
            return False, "❌ 请先请求验证码"
        
        try:
            client = self.pending[phone]['client']
            
            # 尝试登录
            await client.sign_in(
                phone_number=phone,
                phone_code_hash=self.pending[phone]['phone_code_hash'],
                phone_code=code
            )
            
            # 登录成功
            me = await client.get_me()
            
            # 保存session
            session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
            await client.storage.save(session_name)
            
            # 更新账号状态
            self.clients[phone] = client
            self.accounts[phone]["status"] = "active"
            self.accounts[phone]["user_id"] = me.id
            self.accounts[phone]["first_name"] = me.first_name
            self.accounts[phone]["last_active"] = datetime.now().isoformat()
            self.save_accounts()
            
            # 启动监听
            task = asyncio.create_task(self.listen_redpackets(phone))
            self.tasks[phone] = task
            
            # 清理pending
            del self.pending[phone]
            
            return True, f"✅ 登录成功！用户: {me.first_name}"
            
        except PhoneCodeInvalid:
            return False, "❌ 验证码错误，请重试"
        except Exception as e:
            error_str = str(e)
            if "PASSWORD" in error_str.upper():
                return False, "NEED_PASSWORD"
            return False, f"❌ 登录失败: {error_str}"
    
    async def verify_password(self, phone: str, password: str) -> Tuple[bool, str]:
        """验证两步验证密码"""
        if phone not in self.pending:
            return False, "❌ 请先请求验证码"
        
        try:
            client = self.pending[phone]['client']
            
            # 使用密码登录
            await client.check_password(password)
            
            # 登录成功
            me = await client.get_me()
            
            # 保存session
            session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
            await client.storage.save(session_name)
            
            # 更新账号状态
            self.clients[phone] = client
            self.accounts[phone]["status"] = "active"
            self.accounts[phone]["user_id"] = me.id
            self.accounts[phone]["first_name"] = me.first_name
            self.accounts[phone]["last_active"] = datetime.now().isoformat()
            self.save_accounts()
            
            # 启动监听
            task = asyncio.create_task(self.listen_redpackets(phone))
            self.tasks[phone] = task
            
            # 清理pending
            del self.pending[phone]
            
            return True, f"✅ 登录成功！用户: {me.first_name}"
            
        except Exception as e:
            return False, f"❌ 密码错误: {str(e)}"
    
    def is_redpacket(self, message: UserMessage) -> Tuple[bool, Optional[InlineKeyboardButton]]:
        """判断是否为红包"""
        if not message or not message.reply_markup:
            return False, None
        
        # 红包关键词
        keywords = ["领取", "点我", "open", "claim", "红包", "red", "拆开", "开红包"]
        
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if any(k in button.text.lower() for k in keywords):
                    return True, button
        return False, None
    
    async def click_redpacket(self, client: UserClient, message: UserMessage, button: InlineKeyboardButton) -> bool:
        """点击红包"""
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
        """监听红包"""
        client = self.clients.get(phone)
        if not client:
            return
        
        @client.on_message()
        async def handler(client: UserClient, message: UserMessage):
            try:
                if message.chat.id != TARGET_GROUP_ID:
                    return
                
                is_rp, button = self.is_redpacket(message)
                if is_rp and button and phone in self.accounts:
                    # 更新统计
                    self.accounts[phone]["stats"]["total_attempts"] += 1
                    
                    # 点击
                    success = await self.click_redpacket(client, message, button)
                    
                    if success:
                        self.accounts[phone]["stats"]["successful_clicks"] += 1
                        self.save_accounts()
                        logger.info(f"💰 {phone} 抢到红包")
                    else:
                        logger.info(f"❌ {phone} 抢包失败")
                        
            except Exception as e:
                logger.error(f"处理消息错误: {e}")
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass


# 全局管理器
manager = RedPacketManager()


# ==================== 机器人处理器 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令"""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("❌ 无权限")
        return
    
    keyboard = [
        [TGBotton("📱 添加账号", callback_data="add")],
        [TGBotton("📋 账号列表", callback_data="list")],
        [TGBotton("📊 抢包统计", callback_data="stats")],
    ]
    
    await update.message.reply_text(
        f"🤖 红包控制系统\n"
        f"在线: {len(manager.clients)}/{len(manager.accounts)}\n"
        f"目标群: {TARGET_GROUP_ID}",
        reply_markup=TGMarkup(keyboard)
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """按钮回调"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != YOUR_USER_ID:
        return
    
    if query.data == "add":
        await query.edit_message_text(
            "📱 请输入手机号\n"
            "格式: +国家代码手机号\n"
            "例如:\n"
            "中国: +8613812345678\n"
            "柬埔寨: +855313658901\n"
            "美国: +11234567890\n\n"
            "发送 /cancel 取消"
        )
        return PHONE
    
    elif query.data == "list":
        if not manager.accounts:
            await query.edit_message_text("📭 暂无账号")
            return
        
        text = "📋 账号列表:\n"
        for phone, info in manager.accounts.items():
            status_icon = "🟢" if info["status"] == "active" else "🔴"
            name = info.get("first_name", "未登录")
            text += f"{status_icon} {phone} - {name}\n"
        await query.edit_message_text(text)
    
    elif query.data == "stats":
        total = sum(a["stats"]["total_attempts"] for a in manager.accounts.values())
        success = sum(a["stats"]["successful_clicks"] for a in manager.accounts.values())
        rate = (success / total * 100) if total > 0 else 0
        await query.edit_message_text(
            f"📊 抢包统计\n"
            f"总尝试: {total}\n"
            f"成功: {success}\n"
            f"成功率: {rate:.1f}%"
        )
    
    return ConversationHandler.END


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理手机号"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    phone = update.message.text.strip()
    
    # 验证格式
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 必须以+开头，请重新输入:")
        return PHONE
    
    if not phone[1:].isdigit():
        await update.message.reply_text("❌ 只能包含数字和+号，请重新输入:")
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
                f"{msg}\n"
                "📱 请在60秒内输入验证码:"
            )
            return CODE
        else:
            # 发送失败，删除账号
            manager.remove_account(phone)
            await update.message.reply_text(f"{msg}\n请稍后重试")
            return ConversationHandler.END
    else:
        await update.message.reply_text("❌ 账号已存在")
        return ConversationHandler.END


async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理验证码"""
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
        await update.message.reply_text("🔐 需要两步验证，请输入密码:")
        return PASSWORD
    else:
        await update.message.reply_text(f"{msg}\n请重新输入验证码:")
        return CODE


async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理密码"""
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
        return ConversationHandler.END
    else:
        await update.message.reply_text(f"{msg}\n请重新输入密码:")
        return PASSWORD


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    # 清理pending
    phone = context.user_data.get('phone')
    if phone and phone in manager.pending:
        await manager.pending[phone]['client'].disconnect()
        del manager.pending[phone]
        manager.remove_account(phone)
    
    await update.message.reply_text("❌ 已取消")
    return ConversationHandler.END


# ==================== 主程序 ====================

async def main():
    """主函数"""
    logger.info("🚀 启动红包控制系统...")
    logger.info(f"目标群ID: {TARGET_GROUP_ID}")
    
    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 对话处理器
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern="^add$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_account"
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(conv_handler)
    
    # 启动自动登录
    asyncio.create_task(manager.auto_login_all())
    
    # 启动机器人
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    logger.info("✅ 机器人已启动")
    
    # 保持运行
    try:
        while True:
            await asyncio.sleep(10)
            logger.debug(f"心跳 - 在线账号: {len(manager.clients)}")
    except KeyboardInterrupt:
        logger.info("收到停止信号")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 红包控制系统启动")
    print(f"目标群: {TARGET_GROUP_ID}")
    print("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已停止")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
