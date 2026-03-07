# -*- coding: utf-8 -*-
import os
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from threading import Thread
from typing import Final

from flask import Flask
from telethon import TelegramClient, events, errors

# =========================
# 配置确认 (用户提供)
# =========================

API_ID: Final = 38596687
API_HASH: Final = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN: Final = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"

# Render 端口配置
PORT = int(os.getenv("PORT", "8080"))

# 系统路径配置
SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)
DATA_FILE = Path("account_stats.json")

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RedPacketBot")

# =========================
# Web 服务 (用于 Render 健康检查)
# =========================

app = Flask(__name__)

@app.route('/')
def index():
    return "Service Running", 200

def run_web_server():
    # 必须绑定 0.0.0.0 和 Render 提供的 PORT
    app.run(host='0.0.0.0', port=PORT)

# =========================
# 数据持久化
# =========================

def load_db():
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"accounts": {}, "stats": {"total": 0, "success": 0}}

def save_db(data):
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# 全局变量
db = load_db()
active_userbots = {}
login_states = {}

# =========================
# 管理端机器人定义 (全局实例化但不启动)
# =========================

# 仅实例化，不在全局作用域启动
manager_bot = TelegramClient('manager_session', API_ID, API_HASH)

# =========================
# UserBot 红包监听逻辑
# =========================

async def start_userbot_session(phone):
    """启动单个手机号的 UserBot 监控任务"""
    session_str = str(SESSION_DIR / phone)
    # 创建 UserBot 客户端
    client = TelegramClient(session_str, API_ID, API_HASH)
    
    @client.on(events.NewMessage)
    async def packet_handler(event):
        """红包点击逻辑"""
        # 判断消息含金量：有按钮即触发
        if event.reply_markup:
            db["stats"]["total"] += 1
            try:
                # 触发第一个内联按钮（通常是“抢”）
                await event.click(0)
                db["stats"]["success"] += 1
                logger.info(f"[{phone}] 成功触发一个点击。")
            except Exception as e:
                logger.error(f"[{phone}] 点击异常: {e}")
            save_db(db)

    try:
        await client.start()
        active_userbots[phone] = client
        db["accounts"][phone]["status"] = "Running"
        save_db(db)
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"账号 {phone} 停止: {e}")
        if phone in db["accounts"]:
            db["accounts"][phone]["status"] = "Offline"
            save_db(db)

# =========================
# 管理端交互逻辑
# =========================

@manager_bot.on(events.NewMessage(pattern='/start'))
async def cmd_start(event):
    await event.respond("✅ 监控系统在线。\n/login - 登录新号\n/list - 查看状态\n/stats - 统计数据")

@manager_bot.on(events.NewMessage(pattern='/login'))
async def cmd_login(event):
    uid = event.sender_id
    login_states[uid] = {'step': 'phone'}
    await event.respond("请输入手机号 (必须带国家代码，例如: +86138...)：")

@manager_bot.on(events.NewMessage(pattern='/list'))
async def cmd_list(event):
    accs = db.get("accounts", {})
    if not accs:
        return await event.respond("当前无已登录账号。")
    msg = "📱 账号列表：\n" + "\n".join([f"`{p}` - {info['status']}" for p, info in accs.items()])
    await event.respond(msg)

@manager_bot.on(events.NewMessage(pattern='/stats'))
async def cmd_stats(event):
    s = db["stats"]
    total = s["total"]
    succ = s["success"]
    rate = (succ / total * 100) if total > 0 else 0
    await event.respond(f"📊 抢红包统计：\n总检测：{total}\n成功数：{succ}\n成功率：{rate:.2f}%")

@manager_bot.on(events.NewMessage)
async def handle_login(event):
    """登录状态机：处理手机号、验证码、2FA"""
    uid = event.sender_id
    if uid not in login_states: return
    
    state = login_states[uid]
    text = event.text.strip()
    
    # 第一步：发送手机号
    if state['step'] == 'phone':
        phone = text
        if not phone.startswith('+'):
            return await event.respond("❌ 手机号必须以 '+' 开头。")
        
        client = TelegramClient(str(SESSION_DIR / phone), API_ID, API_HASH)
        await client.connect()
        try:
            sent_code = await client.send_code_request(phone)
            login_states[uid] = {
                'step': 'code', 'phone': phone, 
                'client': client, 'hash': sent_code.phone_code_hash
            }
            await event.respond(f"📩 验证码已发送至 {phone}，请输入：\n(如已登录官方App，请查看App内通知)")
        except Exception as e:
            await event.respond(f"❌ 发送失败: {e}")
            await client.disconnect()
            del login_states[uid]

    # 第二步：输入验证码
    elif state['step'] == 'code':
        client, phone = state['client'], state['phone']
        try:
            await client.sign_in(phone, text, phone_code_hash=state['hash'])
            db["accounts"][phone] = {"status": "Online", "added": str(datetime.now())}
            save_db(db)
            await event.respond(f"✅ {phone} 登录成功！监控已开启。")
            asyncio.create_task(start_userbot_session(phone))
            del login_states[uid]
        except errors.SessionPasswordNeededError:
            state['step'] = 'password'
            await event.respond("🔐 请输入两步验证 (2FA) 密码：")
        except Exception as e:
            await event.respond(f"❌ 登录失败: {e}")
            await client.disconnect()
            del login_states[uid]

    # 第三步：输入两步验证密码
    elif state['step'] == 'password':
        try:
            await state['client'].sign_in(password=text)
            phone = state['phone']
            db["accounts"][phone] = {"status": "Online", "added": str(datetime.now())}
            save_db(db)
            await event.respond(f"✅ {phone} (2FA) 成功登录！")
            asyncio.create_task(start_userbot_session(phone))
            del login_states[uid]
        except Exception as e:
            await event.respond(f"❌ 密码错误: {e}")

# =========================
# 主程序启动
# =========================

async def main():
    logger.info("正在启动服务...")
    
    # 1. 初始化启动管理端 Bot
    # 修复：必须在有事件循环的情况下调用 start
    await manager_bot.start(bot_token=BOT_TOKEN)
    logger.info("Manager Bot 已连接")

    # 2. 自动拉起已保存的所有 UserBot
    for phone in list(db["accounts"].keys()):
        asyncio.create_task(start_userbot_session(phone))
    
    # 3. 阻塞保持运行
    logger.info("系统全功能就绪。")
    await manager_bot.run_until_disconnected()

if __name__ == "__main__":
    # 在后台启动 Web 服务满足 Render 存活要求
    Thread(target=run_web_server, daemon=True).start()
    
    # 使用标准 asyncio.run 启动主入口
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
