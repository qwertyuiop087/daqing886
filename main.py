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
# 配置确认
# =========================

API_ID: Final = 38596687
API_HASH: Final = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN: Final = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"

PORT = int(os.getenv("PORT", "8080"))

SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)
DATA_FILE = Path("account_stats.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RedPacketBot")

# =========================
# Web 服务 (健康检查)
# =========================

app = Flask(__name__)

@app.route('/')
def index():
    return "Service Active", 200

def run_web_server():
    app.run(host='0.0.0.0', port=PORT)

# =========================
# 数据持久化
# =========================

def load_db():
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"accounts": {}, "stats": {"total": 0, "success": 0}}

def save_db(data):
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

db = load_db()
active_userbots = {}
login_states = {}

# =========================
# UserBot 核心逻辑
# =========================

async def start_userbot_session(phone):
    """启动 UserBot 监听"""
    session_str = str(SESSION_DIR / phone)
    # 增加连接重试机制
    client = TelegramClient(session_str, API_ID, API_HASH, connection_retries=5)
    
    @client.on(events.NewMessage)
    async def hongbao_handler(event):
        if event.reply_markup:
            # 简化逻辑：只要有按钮的消息，尝试点击
            db["stats"]["total"] += 1
            try:
                await event.click(0)
                db["stats"]["success"] += 1
                logger.info(f"[{phone}] 点击成功")
            except Exception as e:
                logger.error(f"[{phone}] 点击失败: {e}")
            save_db(db)

    try:
        await client.start()
        active_userbots[phone] = client
        db["accounts"][phone]["status"] = "Running"
        save_db(db)
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"账号 {phone} 异常: {e}")
        if phone in db["accounts"]:
            db["accounts"][phone]["status"] = "Offline"
            save_db(db)

# =========================
# 管理端 指令
# =========================

manager_bot = TelegramClient('manager_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@manager_bot.on(events.NewMessage(pattern='/start'))
async def cmd_start(event):
    await event.respond("✅ 机器人已就绪\n/login - 登录账号\n/list - 查看账号\n/stats - 统计信息")

@manager_bot.on(events.NewMessage(pattern='/login'))
async def cmd_login(event):
    uid = event.sender_id
    login_states[uid] = {'step': 'phone'}
    await event.respond("请输入手机号\n⚠️ 注意：必须带国家代码，例如 `+8613812345678`")

@manager_bot.on(events.NewMessage(pattern='/list'))
async def cmd_list(event):
    msg = "\n".join([f"`{ph}` [{info['status']}]" for ph, info in db["accounts"].items()]) or "无账号"
    await event.respond(f"账号列表：\n{msg}")

@manager_bot.on(events.NewMessage(pattern='/stats'))
async def cmd_stats(event):
    st = db["stats"]
    total, succ = st["total"], st["success"]
    rate = (succ / total * 100) if total > 0 else 0
    await event.respond(f"📊 统计：\n检测：{total}\n成功：{succ}\n率：{rate:.2f}%")

# =========================
# 登录状态机 (核心修复部分)
# =========================

@manager_bot.on(events.NewMessage)
async def handle_login(event):
    uid = event.sender_id
    if uid not in login_states: return
    
    state = login_states[uid]
    text = event.text.strip()
    
    if state['step'] == 'phone':
        # 修复 1: 强制检查手机号格式
        if not text.startswith('+'):
            return await event.respond("❌ 格式错误！必须以 `+` 开头，例如 `+86...`。请重新输入：")
        
        phone = text
        session_name = str(SESSION_DIR / phone)
        # 修复 2: 重新登录前先断开可能存在的残留连接
        client = TelegramClient(session_name, API_ID, API_HASH)
        await client.connect()
        
        try:
            # 修复 3: 请求验证码
            logger.info(f"正在向 {phone} 请求验证码...")
            sent_code = await client.send_code_request(phone)
            login_states[uid] = {
                'step': 'code', 'phone': phone, 
                'client': client, 'hash': sent_code.phone_code_hash
            }
            await event.respond(f"📩 验证码已发送！\n请注意：验证码通常会发送到你【已经在登录中的 Telegram 官方 App】上，请去 App 内查看。")
        except errors.FloodWaitError as e:
            await event.respond(f"❌ 请求太频繁，请在 {e.seconds} 秒后再试。")
            await client.disconnect()
            del login_states[uid]
        except Exception as e:
            await event.respond(f"❌ 发送失败: {e}")
            await client.disconnect()
            del login_states[uid]

    elif state['step'] == 'code':
        client, phone = state['client'], state['phone']
        try:
            await client.sign_in(phone, text, phone_code_hash=state['hash'])
            db["accounts"][phone] = {"status": "Online", "added": str(datetime.now())}
            save_db(db)
            await event.respond(f"✅ 账号 {phone} 登录成功！")
            asyncio.create_task(start_userbot_session(phone))
            del login_states[uid]
        except errors.SessionPasswordNeededError:
            state['step'] = 'password'
            await event.respond("🔐 该账号开启了两步验证，请输入两步验证密码：")
        except Exception as e:
            await event.respond(f"❌ 登录失败: {e}\n请重新 /login")
            await client.disconnect()
            del login_states[uid]

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
# 入口
# =========================

async def main():
    for phone in list(db["accounts"].keys()):
        asyncio.create_task(start_userbot_session(phone))
    await manager_bot.run_until_disconnected()

if __name__ == "__main__":
    Thread(target=run_web_server, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass
