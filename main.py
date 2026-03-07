"""
Telegram 红包控制系统 - 完全修复版
修复了 python-telegram-bot v20.x 的关闭错误
"""

import os
import json
import asyncio
import logging
import random
import sys
import signal
from typing import Dict, Optional, Tuple
from datetime import datetime

# ==================== 关键修复：为Render环境添加事件循环 ====================
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

try:
    import nest_asyncio
    nest_asyncio.apply()
    print("✅ nest_asyncio 已应用")
except ImportError:
    print("⚠️ nest_asyncio 未安装，如果遇到事件循环错误请安装：pip install nest_asyncio")
# =========================================================================

from pyrogram import Client as UserClient
from pyrogram.types import Message as UserMessage
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    PhoneNumberInvalid, PhoneCodeInvalid, 
    PasswordHashInvalid, FloodWait,
    SessionRevoked, AuthKeyDuplicated
)

from telegram import Update, InlineKeyboardButton as TGBotton, InlineKeyboardMarkup as TGMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)
from telegram.error import TelegramError

# ==================== 你的配置信息 ====================
USER_API_ID = 38596687  # 你的api_id
USER_API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"  # 你的api_hash
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"  # 你的bot_token
YOUR_USER_ID = 7793291484  # 你的用户ID
TARGET_GROUP_ID = -1003472034414  # 目标红包群ID

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
    """红包账号管理器"""
    
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
            except Exception as e:
                logger.error(f"加载账号失败: {e}")
                self.accounts = {}
        else:
            self.accounts = {}
            self.save_accounts()
    
    def save_accounts(self):
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存账号失败: {e}")
    
    def add_account(self, phone: str):
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
            logger.info(f"✅ 已添加账号: {phone}")
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
            logger.info(f"✅ 已删除账号: {phone}")
            return True
        return False
    
    def is_redpacket(self, message: UserMessage) -> Tuple[bool, Optional[InlineKeyboardButton]]:
        if not message or not message.reply_markup:
            return False, None
        if not isinstance(message.reply_markup, InlineKeyboardMarkup):
            return False, None
        
        keywords = ["领取", "点我", "open", "claim", "红包", "red", "拆开", "开红包", "点击领取"]
        
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                button_text = button.text.lower()
                if any(keyword in button_text for keyword in keywords):
                    return True, button
                if button.callback_data and any(keyword in button_text for keyword in ["红包", "red"]):
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
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return False
        except Exception:
            return False
    
    async def listen_redpackets(self, phone: str):
        client = self.clients.get(phone)
        if not client:
            return
        
        logger.info(f"👂 开始监听账号 {phone} 的红包")
        
        @client.on_message()
        async def message_handler(client: UserClient, message: UserMessage):
            try:
                if message.chat.id != TARGET_GROUP_ID:
                    return
                
                is_rp, button = self.is_redpacket(message)
                if is_rp and button:
                    logger.info(f"💰 {phone} 发现红包")
                    if phone in self.accounts:
                        self.accounts[phone]["stats"]["total_attempts"] += 1
                    
                    success = await self.click_redpacket(client, message, button)
                    
                    if success and phone in self.accounts:
                        self.accounts[phone]["stats"]["successful_clicks"] += 1
                        self.save_accounts()
                        
            except Exception as e:
                logger.error(f"消息处理错误 {phone}: {e}")
        
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info(f"停止监听 {phone}")
    
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
        if not self.accounts:
            return
        
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
                    
                    task = asyncio.create_task(self.listen_redpackets(phone))
                    self.tasks[phone] = task
                    
                    logger.info(f"✅ 自动登录成功: {phone} ({me.first_name})")
                    
                except Exception as e:
                    logger.error(f"自动登录失败 {phone}: {e}")
                    info["status"] = "error"
                
                await asyncio.sleep(2)
        
        self.save_accounts()


# 全局管理器
manager = RedPacketManager()


# ==================== 控制机器人 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        await update.message.reply_text("❌ 你没有权限使用这个机器人")
        return
    
    keyboard = [
        [TGBotton("📱 添加账号", callback_data="add_account")],
        [TGBotton("📋 账号列表", callback_data="list_accounts")],
        [TGBotton("📊 抢包统计", callback_data="show_stats")],
        [TGBotton("🔄 刷新状态", callback_data="refresh")]
    ]
    
    await update.message.reply_text(
        "🤖 *红包控制系统*\n\n"
        f"当前在线账号: {len(manager.clients)}/{len(manager.accounts)}\n"
        f"目标群ID: `{TARGET_GROUP_ID}`\n\n"
        "请选择操作:",
        reply_markup=TGMarkup(keyboard),
        parse_mode='Markdown'
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return PHONE
    
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
            keyboard.append([TGBotton(f"🗑️ 删除 {phone[-4:]}", callback_data=f"del_{phone}")])
        
        keyboard.append([TGBotton("🔙 返回", callback_data="back")])
        
        await query.edit_message_text(
            text,
            reply_markup=TGMarkup(keyboard),
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
            f"成功率: {success_rate:.1f}%"
        )
        
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == "refresh":
        await query.edit_message_text(f"🔄 状态已刷新\n\n在线账号: {len(manager.clients)}/{len(manager.accounts)}")
    
    elif data == "back":
        await start(update, context)
    
    elif data.startswith("del_"):
        phone = data[4:]
        if manager.remove_account(phone):
            await query.edit_message_text(f"✅ 已删除账号 {phone}")
        else:
            await query.edit_message_text(f"❌ 删除失败")
    
    return ConversationHandler.END


async def add_account_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    phone = update.message.text.strip()
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 手机号格式错误，请以 + 开头")
        return PHONE
    
    context.user_data['phone'] = phone
    
    if manager.add_account(phone):
        await update.message.reply_text(
            f"✅ 账号 {phone} 已添加\n\n"
            "现在请输入登录验证码（查看Render日志获取）:"
        )
        return CODE
    else:
        await update.message.reply_text("❌ 账号已存在")
        return ConversationHandler.END


async def add_account_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    code = update.message.text.strip()
    phone = context.user_data.get('phone')
    
    success, msg = await manager.login_account(phone, code)
    
    if success:
        await update.message.reply_text(f"✅ {msg}\n\n开始监听红包...")
        return ConversationHandler.END
    else:
        if "两步验证" in msg:
            context.user_data['code'] = code
            await update.message.reply_text("请输入两步验证密码:")
            return PASSWORD
        else:
            await update.message.reply_text(msg)
            return ConversationHandler.END


async def add_account_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    password = update.message.text.strip()
    phone = context.user_data.get('phone')
    code = context.user_data.get('code')
    
    success, msg = await manager.login_account(phone, code, password)
    await update.message.reply_text(msg)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    await update.message.reply_text("❌ 操作已取消")
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"更新出错 {update}: {context.error}")


# ==================== 主程序 ====================

class BotRunner:
    """机器人运行管理器 - 避免关闭时的错误"""
    
    def __init__(self):
        self.app = None
        self.running = True
    
    async def start(self):
        """启动机器人"""
        try:
            # 创建应用
            self.app = Application.builder().token(BOT_TOKEN).build()
            
            # 添加处理器
            conv_handler = ConversationHandler(
                entry_points=[CallbackQueryHandler(button_callback, pattern="^add_account$")],
                states={
                    PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_phone)],
                    CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_code)],
                    PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_password)],
                },
                fallbacks=[CommandHandler("cancel", cancel)]
            )
            
            self.app.add_handler(CommandHandler("start", start))
            self.app.add_handler(CallbackQueryHandler(button_callback))
            self.app.add_handler(conv_handler)
            self.app.add_error_handler(error_handler)
            
            # 启动红包监听
            asyncio.create_task(manager.auto_login_all())
            
            # 初始化并启动
            await self.app.initialize()
            await self.app.start()
            
            # 启动轮询
            await self.app.updater.start_polling()
            
            logger.info("✅ 机器人已成功启动")
            
            # 保持运行
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"机器人运行错误: {e}")
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """清理资源 - 安全的关闭方式"""
        logger.info("正在关闭机器人...")
        try:
            if self.app:
                # 先停止轮询
                if hasattr(self.app, 'updater') and self.app.updater:
                    try:
                        await self.app.updater.stop()
                    except Exception as e:
                        logger.debug(f"停止轮询时出错（可忽略）: {e}")
                
                # 停止应用
                try:
                    await self.app.stop()
                except Exception as e:
                    logger.debug(f"停止应用时出错（可忽略）: {e}")
                
                # 关闭应用
                try:
                    await self.app.shutdown()
                except Exception as e:
                    logger.debug(f"关闭应用时出错（可忽略）: {e}")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}")
        
        logger.info("机器人已关闭")
    
    def stop(self):
        """停止机器人"""
        self.running = False


async def main():
    """主函数"""
    runner = BotRunner()
    
    # 设置信号处理
    def signal_handler():
        logger.info("收到停止信号")
        runner.stop()
    
    # 在非Windows系统上设置信号处理
    if sys.platform != 'win32':
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    
    try:
        await runner.start()
    except KeyboardInterrupt:
        logger.info("收到键盘中断")
        runner.stop()
    except Exception as e:
        logger.error(f"主程序错误: {e}")
    finally:
        # 确保所有任务都被取消
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()


if __name__ == "__main__":
    print("=" * 50)
    print("🚀 启动红包控制系统...")
    print(f"📱 目标群ID: {TARGET_GROUP_ID}")
    print(f"🤖 机器人Token: {BOT_TOKEN[:10]}...")
    print(f"👤 管理员ID: {YOUR_USER_ID}")
    print("=" * 50)
    
    # 检查配置
    if not USER_API_ID or USER_API_ID == 0:
        print("❌ 错误: USER_API_ID 未设置")
        sys.exit(1)
    if not USER_API_HASH:
        print("❌ 错误: USER_API_HASH 未设置")
        sys.exit(1)
    if not BOT_TOKEN:
        print("❌ 错误: BOT_TOKEN 未设置")
        sys.exit(1)
    if not YOUR_USER_ID or YOUR_USER_ID == 0:
        print("❌ 错误: YOUR_USER_ID 未设置")
        sys.exit(1)
    
    print("✅ 配置检查通过")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序已停止")
    except Exception as e:
        print(f"❌ 程序崩溃: {e}")
