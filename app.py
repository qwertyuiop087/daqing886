"""
Telegram 多账号自动抢红包机器人 - 完整版
已配置红包群ID: -1003472034414
支持：自动识别红包消息、自动点击领取按钮、多账号并发、Web监控
"""

import os
import json
import asyncio
import logging
import re
import random
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn

from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    PhoneNumberInvalid, PhoneCodeInvalid, 
    PasswordHashInvalid, FloodWait,
    AuthKeyDuplicated, SessionRevoked
)

# ==================== 配置区域 ====================
# 从环境变量获取（在Render dashboard设置）
API_ID = int(os.environ.get("API_ID", "0"))  # 必须设置
API_HASH = os.environ.get("API_HASH", "")    # 必须设置

# 红包机器人关键词配置（根据实际情况调整）
REDPACKET_KEYWORDS = [
    "红包", "red packet", "领取", "claim", 
    "点我", "点击领取", "open", "红包来了",
    "点击拆开", "拆红包", "开红包", "领取红包",
    "get", "claim红包", "red envelope"
]

# 目标群组配置 - 已配置你的红包群
TARGET_GROUPS = {
    -1003472034414: "红包群",  # 你的红包群
    # 可以继续添加更多群组
    # -1001234567890: "福利群",
}

# 文件路径
ACCOUNTS_FILE = "accounts.json"
SESSIONS_DIR = "sessions"
LOG_FILE = "redpacket_log.json"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建必要目录
os.makedirs(SESSIONS_DIR, exist_ok=True)
# =============================================


class RedPacketLogger:
    """红包抢包日志"""
    def __init__(self):
        self.logs = []
        self.load()
    
    def load(self):
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r', encoding='utf-8') as f:
                    self.logs = json.load(f)
            except:
                self.logs = []
    
    def save(self):
        try:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.logs[-100:], f, indent=2, ensure_ascii=False)  # 只保留最近100条
        except:
            pass
    
    def add(self, phone: str, group_name: str, group_id: int, result: str, amount: float = None):
        log = {
            "time": datetime.now().isoformat(),
            "phone": phone,
            "group_name": group_name,
            "group_id": group_id,
            "result": result,
            "amount": amount
        }
        self.logs.append(log)
        self.save()
        
        amount_str = f" {amount}U" if amount else ""
        logger.info(f"[红包日志] {phone} @ {group_name}: {result}{amount_str}")


class AccountManager:
    """账号管理器"""
    def __init__(self):
        self.accounts: Dict[str, dict] = {}
        self.clients: Dict[str, Client] = {}
        self.listen_tasks: Dict[str, asyncio.Task] = {}
        self.redpacket_logger = RedPacketLogger()
        self.load_accounts()
    
    def load_accounts(self):
        """从文件加载账号"""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    self.accounts = json.load(f)
                logger.info(f"✅ 已加载 {len(self.accounts)} 个账号配置")
            except Exception as e:
                logger.error(f"加载账号失败: {e}")
                self.accounts = {}
        else:
            logger.info("未找到账号配置文件，将创建新配置")
            self.accounts = {}
    
    def save_accounts(self):
        """保存账号到文件"""
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存账号失败: {e}")
    
    def add_account(self, phone: str, note: str = ""):
        """添加新账号"""
        if phone not in self.accounts:
            self.accounts[phone] = {
                "phone": phone,
                "status": "pending",
                "note": note,
                "session_string": "",
                "last_active": None,
                "user_id": None,
                "first_name": None,
                "stats": {
                    "total_attempts": 0,
                    "successful_clicks": 0,
                    "failed_clicks": 0,
                    "last_redpacket_time": None
                }
            }
            self.save_accounts()
            logger.info(f"✅ 已添加账号: {phone}")
            return True
        return False
    
    def remove_account(self, phone: str):
        """移除账号"""
        if phone in self.accounts:
            # 停止监听任务
            if phone in self.listen_tasks:
                self.listen_tasks[phone].cancel()
                del self.listen_tasks[phone]
            
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
            logger.info(f"✅ 已移除账号: {phone}")
            return True
        return False
    
    def update_account_stats(self, phone: str, success: bool):
        """更新账号抢包统计"""
        if phone in self.accounts:
            stats = self.accounts[phone].get("stats", {})
            stats["total_attempts"] = stats.get("total_attempts", 0) + 1
            if success:
                stats["successful_clicks"] = stats.get("successful_clicks", 0) + 1
                stats["last_redpacket_time"] = datetime.now().isoformat()
            else:
                stats["failed_clicks"] = stats.get("failed_clicks", 0) + 1
            self.accounts[phone]["stats"] = stats
            self.save_accounts()


# 全局管理器
account_manager = AccountManager()


# ==================== 红包识别和点击核心逻辑 ====================

async def verify_group_id(client: Client, group_id: int) -> bool:
    """验证群组ID是否有效"""
    try:
        chat = await client.get_chat(group_id)
        logger.info(f"✅ 群组验证成功: {chat.title} (ID: {chat.id})")
        return True
    except Exception as e:
        logger.error(f"❌ 群组ID无效或账号不在群内: {e}")
        return False


def is_redpacket_message(message: Message) -> Tuple[bool, Optional[InlineKeyboardButton], Optional[str]]:
    """
    判断一条消息是否为红包消息
    返回: (是否是红包, 红包按钮, 按钮类型)
    """
    if not message:
        return False, None, None
    
    # 记录消息基本信息（用于调试）
    chat_info = f"群 {message.chat.id} ({message.chat.title})"
    
    # 1. 检查是否有按钮
    if not message.reply_markup or not isinstance(message.reply_markup, InlineKeyboardMarkup):
        return False, None, None
    
    # 2. 获取消息文本
    text = (message.text or message.caption or "").lower()
    
    # 3. 检查按钮
    redpacket_button = None
    button_type = None
    
    for row in message.reply_markup.inline_keyboard:
        for button in row:
            button_text = button.text.lower()
            
            # 检查按钮文本是否包含领取相关词
            if any(word in button_text for word in ["领取", "点我", "open", "claim", "红包", "red", "拆开", "开红包"]):
                redpacket_button = button
                button_type = "claim_button"
                logger.debug(f"🔍 {chat_info} 发现领取按钮: {button.text}")
                break
            
            # 检查是否有callback_data（红包通常都有）
            if button.callback_data and any(word in button_text for word in ["红包", "red", "领取"]):
                redpacket_button = button
                button_type = "callback_button"
                logger.debug(f"🔍 {chat_info} 发现callback按钮: {button.text}")
                break
            
            # 如果按钮文本包含"红包"关键词
            if any(keyword in button_text for keyword in ["红包", "red packet", "red envelope"]):
                redpacket_button = button
                button_type = "keyword_button"
                logger.debug(f"🔍 {chat_info} 发现红包关键词按钮: {button.text}")
                break
        
        if redpacket_button:
            break
    
    # 4. 检查消息文本是否包含红包关键词
    has_text_keyword = any(keyword in text for keyword in REDPACKET_KEYWORDS)
    
    # 如果有按钮或者有文本关键词，就认为是红包
    if redpacket_button or has_text_keyword:
        return True, redpacket_button, button_type
    
    return False, None, None


async def click_redpacket_button(client: Client, message: Message, button: InlineKeyboardButton) -> Tuple[bool, str]:
    """
    点击红包按钮 - 核心抢包函数
    返回: (是否成功, 结果信息)
    """
    try:
        # 获取按钮信息
        chat_id = message.chat.id
        message_id = message.id
        chat_title = message.chat.title or str(chat_id)
        
        logger.info(f"💰 尝试抢包: {chat_title} - 按钮: {button.text}")
        
        # 随机延迟0.1-0.3秒，模拟人类点击（也避免并发冲突）
        delay = random.uniform(0.1, 0.3)
        await asyncio.sleep(delay)
        
        # 方法1：如果有callback_data，直接请求
        if button.callback_data:
            await client.request_callback_answer(
                chat_id=chat_id,
                message_id=message_id,
                callback_data=button.callback_data
            )
            logger.info(f"✅ 点击成功 (callback_data): {button.text}")
            return True, "callback_click"
        
        # 方法2：如果有url，打开链接（但红包通常不是url）
        elif button.url:
            logger.info(f"🔗 按钮是链接，无法自动点击: {button.url}")
            return False, "url_button"
        
        # 方法3：如果都没找到，可能是其他类型
        else:
            logger.warning(f"⚠️ 未知按钮类型: {button}")
            return False, "unknown_button"
            
    except FloodWait as e:
        logger.warning(f"⏳ 触发频率限制，等待 {e.value} 秒")
        await asyncio.sleep(e.value)
        return False, f"flood_wait_{e.value}"
        
    except Exception as e:
        logger.error(f"❌ 点击失败: {e}")
        return False, f"error: {str(e)}"


async def redpacket_handler(client: Client, message: Message):
    """
    消息处理器 - 自动识别并抢红包
    只监听目标群组
    """
    try:
        # 获取当前账号
        current_phone = None
        for phone, cl in account_manager.clients.items():
            if cl == client:
                current_phone = phone
                break
        
        if not current_phone:
            return
        
        # 只监听目标群组
        if message.chat.id not in TARGET_GROUPS:
            return
        
        # 获取群组名称
        group_name = TARGET_GROUPS.get(message.chat.id, message.chat.title or str(message.chat.id))
        
        # 判断是否为红包
        is_red, button, button_type = is_redpacket_message(message)
        
        if is_red:
            logger.info(f"🎁 {group_name} 发现红包消息")
            
            # 记录尝试
            account_manager.update_account_stats(current_phone, False)
            
            # 如果没有找到具体按钮，尝试从所有按钮中选择一个
            if not button and message.reply_markup:
                # 取第一个按钮尝试
                for row in message.reply_markup.inline_keyboard:
                    if row:
                        button = row[0]
                        break
            
            if button:
                # 随机延迟0.1-0.5秒
                delay = random.uniform(0.1, 0.5)
                await asyncio.sleep(delay)
                
                # 点击按钮
                success, method = await click_redpacket_button(client, message, button)
                
                if success:
                    # 更新成功统计
                    account_manager.update_account_stats(current_phone, True)
                    
                    # 记录日志
                    account_manager.redpacket_logger.add(
                        phone=current_phone,
                        group_name=group_name,
                        group_id=message.chat.id,
                        result="抢包成功",
                        amount=None
                    )
                    
                    logger.info(f"✅ {current_phone} @ {group_name} 抢包成功！")
                    
                else:
                    # 记录失败
                    account_manager.redpacket_logger.add(
                        phone=current_phone,
                        group_name=group_name,
                        group_id=message.chat.id,
                        result=f"抢包失败: {method}"
                    )
            else:
                logger.warning(f"⚠️ {group_name} 红包消息但未找到可点击按钮")
                
    except Exception as e:
        logger.error(f"红包处理器异常: {e}")


async def login_account(phone: str, verification_code: str = None, 
                        password: str = None) -> Tuple[bool, str]:
    """
    登录账号
    Args:
        phone: 手机号
        verification_code: 验证码
        password: 两步验证密码
    Returns: (成功?, 消息)
    """
    try:
        session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
        client = Client(
            name=session_name,
            api_id=API_ID,
            api_hash=API_HASH,
            phone_number=phone,
            password=password,
            workdir="./"
        )
        
        # 启动客户端
        await client.start()
        
        # 获取用户信息
        me = await client.get_me()
        
        # 添加消息处理器 - 自动抢红包
        @client.on_message()
        async def message_handler(client: Client, message: Message):
            await redpacket_handler(client, message)
        
        # 更新账号信息
        if phone in account_manager.accounts:
            account_manager.accounts[phone]["status"] = "active"
            account_manager.accounts[phone]["user_id"] = me.id
            account_manager.accounts[phone]["first_name"] = me.first_name
            account_manager.accounts[phone]["last_active"] = datetime.now().isoformat()
            account_manager.clients[phone] = client
            account_manager.save_accounts()
        
        logger.info(f"✅ 账号登录成功: {phone} ({me.first_name})")
        
        # 验证目标群组
        for group_id, group_name in TARGET_GROUPS.items():
            await verify_group_id(client, group_id)
        
        return True, f"登录成功！用户: {me.first_name}"
        
    except PhoneNumberInvalid:
        return False, "手机号无效"
    except PhoneCodeInvalid:
        return False, "验证码错误"
    except PasswordHashInvalid:
        return False, "两步验证密码错误"
    except SessionRevoked:
        return False, "Session已撤销，请重新登录"
    except AuthKeyDuplicated:
        return False, "账号在其他地方登录"
    except FloodWait as e:
        return False, f"触发频率限制，请等待 {e.value} 秒"
    except Exception as e:
        logger.error(f"登录失败 {phone}: {e}")
        return False, f"登录失败: {str(e)}"


async def start_all_clients():
    """启动所有已保存的账号"""
    if not account_manager.accounts:
        logger.info("没有配置任何账号")
        return
    
    logger.info(f"🔄 开始自动登录 {len(account_manager.accounts)} 个账号...")
    
    for phone, account in account_manager.accounts.items():
        if account.get("status") == "active":
            try:
                session_name = f"{SESSIONS_DIR}/{phone.replace('+', '')}"
                client = Client(
                    name=session_name,
                    api_id=API_ID,
                    api_hash=API_HASH,
                    workdir="./"
                )
                
                # 启动客户端
                await client.start()
                
                # 添加消息处理器
                @client.on_message()
                async def message_handler(client: Client, message: Message):
                    await redpacket_handler(client, message)
                
                # 验证登录
                me = await client.get_me()
                account["status"] = "active"
                account["user_id"] = me.id
                account["first_name"] = me.first_name
                account["last_active"] = datetime.now().isoformat()
                account_manager.clients[phone] = client
                
                logger.info(f"✅ 自动登录成功: {phone} ({me.first_name})")
                
            except Exception as e:
                logger.error(f"自动登录失败 {phone}: {e}")
                account["status"] = "error"
            
            # 避免同时登录触发风控
            await asyncio.sleep(2)
    
    account_manager.save_accounts()
    logger.info(f"🎯 当前在线账号: {len(account_manager.clients)} 个")


# ==================== FastAPI应用 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时自动登录
    logger.info("🚀 启动红包监控机器人...")
    logger.info(f"🎯 目标群组: {TARGET_GROUPS}")
    asyncio.create_task(start_all_clients())
    yield
    # 关闭时清理
    logger.info("🛑 关闭所有客户端...")
    for client in account_manager.clients.values():
        try:
            await client.stop()
        except:
            pass


app = FastAPI(lifespan=lifespan, title="Telegram多账号红包机器人")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Web管理界面"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram红包机器人</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                margin: 0; 
                padding: 20px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }
            .container { 
                max-width: 1200px; 
                margin: 0 auto; 
            }
            h1 {
                color: white;
                text-align: center;
                margin-bottom: 30px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
            }
            .card { 
                background: white; 
                padding: 25px; 
                margin-bottom: 25px; 
                border-radius: 15px; 
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                transition: transform 0.3s;
            }
            .card:hover {
                transform: translateY(-5px);
            }
            .account { 
                border-left: 4px solid #ccc; 
                padding: 15px; 
                margin: 15px 0; 
                background: #f8f9fa; 
                border-radius: 8px;
                transition: all 0.3s;
            }
            .account:hover {
                background: #e9ecef;
            }
            .account.active { border-left-color: #4CAF50; }
            .account.error { border-left-color: #f44336; }
            .account.pending { border-left-color: #ff9800; }
            .stats { 
                display: grid; 
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); 
                gap: 10px; 
                margin: 15px 0; 
            }
            .stat-box { 
                background: white; 
                padding: 15px; 
                border-radius: 10px; 
                text-align: center; 
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .stat-value { 
                font-size: 28px; 
                font-weight: bold; 
                color: #4CAF50; 
                margin: 5px 0;
            }
            .stat-label {
                color: #666;
                font-size: 14px;
                text-transform: uppercase;
            }
            .log { 
                background: #1e1e2f; 
                color: #fff;
                padding: 15px; 
                border-radius: 10px; 
                max-height: 400px; 
                overflow-y: auto; 
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }
            .log-item { 
                padding: 8px; 
                border-bottom: 1px solid #333; 
                color: #0f0;
            }
            .log-item.success { color: #4CAF50; }
            .log-item.error { color: #f44336; }
            .log-item.warning { color: #ff9800; }
            button { 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; 
                border: none; 
                padding: 10px 20px; 
                border-radius: 8px; 
                cursor: pointer; 
                font-size: 14px;
                transition: all 0.3s;
                margin: 5px;
            }
            button:hover { 
                transform: scale(1.05);
                box-shadow: 0 5px 15px rgba(0,0,0,0.3);
            }
            button.delete {
                background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
            }
            button.logout {
                background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
            }
            input { 
                padding: 12px; 
                margin: 8px 0; 
                border: 2px solid #e0e0e0; 
                border-radius: 8px; 
                width: 100%;
                box-sizing: border-box;
                font-size: 14px;
                transition: border 0.3s;
            }
            input:focus {
                border-color: #667eea;
                outline: none;
            }
            .status-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                margin-left: 10px;
            }
            .status-badge.active { background: #4CAF50; }
            .status-badge.error { background: #f44336; }
            .status-badge.pending { background: #ff9800; }
            .group-info {
                background: #e3f2fd;
                padding: 10px;
                border-radius: 8px;
                margin: 10px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>💰 Telegram 多账号红包机器人</h1>
            
            <div class="card">
                <h2 style="margin-top: 0; color: #333;">🎯 目标群组</h2>
                <div class="group-info">
                    <strong>红包群 ID:</strong> -1003472034414
                </div>
            </div>
            
            <div class="card">
                <h2 style="margin-top: 0; color: #333;">➕ 添加新账号</h2>
                <input type="text" id="phone" placeholder="手机号 (格式: +861234567890)" value="+86">
                <input type="text" id="note" placeholder="备注 (例如: 账号1)">
                <button onclick="addAccount()">添加账号</button>
            </div>
            
            <div class="card">
                <h2 style="margin-top: 0; color: #333;">📱 在线账号 (自动抢包中)</h2>
                <div id="accounts"></div>
            </div>
            
            <div class="card">
                <h2 style="margin-top: 0; color: #333;">📊 红包日志</h2>
                <div class="log" id="logs">加载中...</div>
            </div>
            
            <div class="card">
                <h2 style="margin-top: 0; color: #333;">📈 全局统计</h2>
                <div class="stats" id="globalStats">
                    <div class="stat-box">
                        <div class="stat-value" id="totalAccounts">0</div>
                        <div class="stat-label">总账号数</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value" id="onlineAccounts">0</div>
                        <div class="stat-label">在线账号</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value" id="totalAttempts">0</div>
                        <div class="stat-label">总尝试次数</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value" id="totalSuccess">0</div>
                        <div class="stat-label">成功次数</div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            // 全局变量
            let currentLoginPhone = null;
            
            // 加载所有数据
            async function loadData() {
                try {
                    // 加载账号列表
                    const accRes = await fetch('/api/accounts');
                    const accData = await accRes.json();
                    
                    let totalAttempts = 0;
                    let totalSuccess = 0;
                    let onlineCount = 0;
                    
                    const accountsHtml = accData.accounts.map(acc => {
                        if (acc.status === 'active') onlineCount++;
                        totalAttempts += acc.stats?.total_attempts || 0;
                        totalSuccess += acc.stats?.successful_clicks || 0;
                        
                        return `
                            <div class="account ${acc.status}">
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <div>
                                        <strong style="font-size: 16px;">${acc.phone}</strong>
                                        <span class="status-badge ${acc.status}">${acc.status}</span>
                                        ${acc.first_name ? `<span style="color: #666; margin-left: 10px;">(${acc.first_name})</span>` : ''}
                                        ${acc.note ? `<br><small style="color: #888;">📝 备注: ${acc.note}</small>` : ''}
                                        <br><small style="color: #888;">🕐 最后活跃: ${acc.last_active ? new Date(acc.last_active).toLocaleString() : '从未'}</small>
                                    </div>
                                    <div>
                                        ${acc.status === 'pending' ? 
                                            `<button onclick="startLogin('${acc.phone}')">📱 登录</button>` : 
                                            `<button class="logout" onclick="logoutAccount('${acc.phone}')">🚪 退出</button>`
                                        }
                                        <button class="delete" onclick="removeAccount('${acc.phone}')">🗑️ 删除</button>
                                    </div>
                                </div>
                                <div class="stats">
                                    <div class="stat-box">
                                        <div class="stat-value" style="color: #2196F3;">${acc.stats?.total_attempts || 0}</div>
                                        <div class="stat-label">尝试次数</div>
                                    </div>
                                    <div class="stat-box">
                                        <div class="stat-value" style="color: #4CAF50;">${acc.stats?.successful_clicks || 0}</div>
                                        <div class="stat-label">成功次数</div>
                                    </div>
                                    <div class="stat-box">
                                        <div class="stat-value" style="color: #f44336;">${acc.stats?.failed_clicks || 0}</div>
                                        <div class="stat-label">失败次数</div>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join('');
                    
                    document.getElementById('accounts').innerHTML = accountsHtml || '<p style="text-align: center; color: #666;">暂无账号，请添加</p>';
                    
                    // 更新全局统计
                    document.getElementById('totalAccounts').textContent = accData.accounts.length;
                    document.getElementById('onlineAccounts').textContent = onlineCount;
                    document.getElementById('totalAttempts').textContent = totalAttempts;
                    document.getElementById('totalSuccess').textContent = totalSuccess;
                    
                    // 加载日志
                    const logRes = await fetch('/api/logs');
                    const logData = await logRes.json();
                    
                    const logsHtml = logData.logs.map(log => {
                        let logClass = 'log-item';
                        if (log.result.includes('成功')) logClass += ' success';
                        else if (log.result.includes('失败')) logClass += ' error';
                        else logClass += ' warning';
                        
                        return `
                            <div class="${logClass}">
                                [${new Date(log.time).toLocaleTimeString()}] 
                                ${log.phone} @ ${log.group_name}: ${log.result}
                                ${log.amount ? ` 💰 ${log.amount}U` : ''}
                            </div>
                        `;
                    }).join('');
                    
                    document.getElementById('logs').innerHTML = logsHtml || '<div class="log-item">暂无红包日志</div>';
                    
                } catch (error) {
                    console.error('加载数据失败:', error);
                }
            }
            
            // 添加账号
            async function addAccount() {
                const phone = document.getElementById('phone').value.trim();
                const note = document.getElementById('note').value.trim();
                
                if (!phone) {
                    alert('请输入手机号');
                    return;
                }
                
                try {
                    const res = await fetch('/api/accounts', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({phone, note})
                    });
                    
                    if (res.ok) {
                        document.getElementById('phone').value = '+86';
                        document.getElementById('note').value = '';
                        loadData();
                        alert('✅ 账号添加成功，请点击"登录"完成登录');
                    } else {
                        const data = await res.json();
                        alert('❌ ' + (data.detail || '添加失败'));
                    }
                } catch (error) {
                    alert('❌ 添加失败: ' + error);
                }
            }
            
            // 开始登录流程
            function startLogin(phone) {
                currentLoginPhone = phone;
                const code = prompt('请输入验证码（查看Render日志获取）:', '');
                if (!code) return;
                
                const password = prompt('请输入两步验证密码（如果没有直接点确定）:', '');
                
                loginAccount(phone, code, password || null);
            }
            
            // 执行登录
            async function loginAccount(phone, code, password) {
                try {
                    const res = await fetch('/api/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({phone, code, password})
                    });
                    
                    const data = await res.json();
                    alert(data.message);
                    loadData();
                } catch (error) {
                    alert('❌ 登录失败: ' + error);
                }
            }
            
            // 退出账号
            async function logoutAccount(phone) {
                if (!confirm('确定要退出该账号吗？')) return;
                
                try {
                    await fetch('/api/logout', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({phone})
                    });
                    loadData();
                } catch (error) {
                    alert('❌ 退出失败: ' + error);
                }
            }
            
            // 删除账号
            async function removeAccount(phone) {
                if (!confirm('确定要删除该账号吗？所有session数据将被清除！')) return;
                
                try {
                    await fetch(`/api/accounts/${encodeURIComponent(phone)}`, {
                        method: 'DELETE'
                    });
                    loadData();
                } catch (error) {
                    alert('❌ 删除失败: ' + error);
                }
            }
            
            // 初始加载，每3秒刷新一次
            loadData();
            setInterval(loadData, 3000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/api/accounts")
async def get_accounts():
    """获取所有账号（带统计）"""
    accounts = []
    for phone, info in account_manager.accounts.items():
        accounts.append({
            "phone": phone,
            "status": info.get("status", "pending"),
            "note": info.get("note", ""),
            "first_name": info.get("first_name"),
            "last_active": info.get("last_active"),
            "stats": info.get("stats", {
                "total_attempts": 0, 
                "successful_clicks": 0,
                "failed_clicks": 0
            })
        })
    return {"accounts": accounts}


@app.post("/api/accounts")
async def add_account(request: Request):
    """添加账号"""
    data = await request.json()
    phone = data.get("phone")
    note = data.get("note", "")
    
    if not phone:
        raise HTTPException(status_code=400, detail="手机号不能为空")
    
    if account_manager.add_account(phone, note):
        return {"success": True, "message": "账号已添加"}
    else:
        raise HTTPException(status_code=400, detail="账号已存在")


@app.delete("/api/accounts/{phone:path}")
async def delete_account(phone: str):
    """删除账号"""
    if account_manager.remove_account(phone):
        return {"success": True}
    else:
        raise HTTPException(status_code=404, detail="账号不存在")


@app.post("/api/login")
async def login(request: Request):
    """登录账号"""
    data = await request.json()
    phone = data.get("phone")
    code = data.get("code")
    password = data.get("password")
    
    if not phone:
        raise HTTPException(status_code=400, detail="手机号不能为空")
    
    success, message = await login_account(phone, code, password)
    return {"success": success, "message": message}


@app.post("/api/logout")
async def logout(request: Request):
    """退出账号"""
    data = await request.json()
    phone = data.get("phone")
    
    if phone in account_manager.clients:
        await account_manager.clients[phone].stop()
        del account_manager.clients[phone]
        if phone in account_manager.accounts:
            account_manager.accounts[phone]["status"] = "pending"
            account_manager.save_accounts()
    
    return {"success": True}


@app.get("/api/logs")
async def get_logs():
    """获取红包日志"""
    return {"logs": account_manager.redpacket_logger.logs[-50:]}


@app.get("/health")
async def health_check():
    """健康检查"""
    total_attempts = sum(
        acc.get("stats", {}).get("total_attempts", 0) 
        for acc in account_manager.accounts.values()
    )
    total_success = sum(
        acc.get("stats", {}).get("successful_clicks", 0) 
        for acc in account_manager.accounts.values()
    )
    
    return {
        "status": "healthy",
        "online_accounts": len(account_manager.clients),
        "total_accounts": len(account_manager.accounts),
        "total_attempts": total_attempts,
        "total_success": total_success,
        "target_groups": list(TARGET_GROUPS.keys())
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
