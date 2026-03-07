# -*- coding: utf-8 -*-
import os
import json
import asyncio
import logging
import re
from pathlib import Path
from datetime import datetime
from threading import Thread
from typing import Final

from flask import Flask
from telethon import TelegramClient, events, errors

# =========================
# 凭据配置
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
# Web 服务 (Render 存活检查)
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

manager_bot = TelegramClient('manager_session', API_ID, API_HASH)

# =========================
# UserBot 核心逻辑 (模拟移动端设备)
# =========================

async def start_userbot_session(phone):
    """启动 UserBot 监听"""
    session_str = str(SESSION_DIR / phone)
    
    # 模拟真实设备信息，降低被风控几率
    client = TelegramClient(
        session_str, API_ID, API_HASH,
        device_model="iPhone 15 Pro",
        system_version="17.4.1",
        app_version="10.9.1"
    )
    
    @client.on(events.NewMessage)
    async def packet_handler(event):
        if event.reply_markup:
            db["stats"]["total"] += 1
            try:
                # 尝试点击消息中的第一个内联按钮
                await event.click(0)
                db["stats"]["success"] += 1
                logger.info(f"[{phone}] 成功抢到一个红包！")
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
        logger.error(f"账号 {phone} 异常停止: {e}")
        if phone in db["accounts"]:
            db["accounts"][phone]["status"] = "Offline"
            save_db(db)

# =========================
# 管理端 指令与状态机
# =========================

@manager_bot.on(events.NewMessage(pattern='/start'))
async def cmd_start(event):
    await event.respond("✅ 助手已启动\n/login - 登录新账号\n/list - 查看所有账号\n/stats - 统计信息")

@manager_bot.on(events.NewMessage(pattern='/login'))
async def cmd_login(event):
    uid = event.sender_id
    login_states[uid] = {'step': 'phone'}
    await event.respond("请输入您的手机号（带国家代码，例如 `+86138...`）：")

@manager_bot.on(events.NewMessage(pattern='/list'))
async def cmd_list(event):
    accs = db.get("accounts", {})
    if not accs: return await event.respond("暂无账号")
    msg = "\n".join([f"`{ph}` - {info['status']}" for ph, info in accs.items()])
    await event.respond(f"账号列表：\n{msg}")

@manager_bot.on(events.NewMessage(pattern='/stats'))
async def cmd_stats(event):
    s = db["stats"]
    total = s["total"]
    succ = s["success"]
    rate = (succ / total * 100) if total > 0 else 0
    await event.respond(f"📈 统计信息：\n总检测：{total}\n已抢到：{succ}\n成功率：{rate:.2f}%")

@manager_bot.on(events.NewMessage)
async def handle_login(event):
    uid = event.sender_id
    if uid not in login_states: return
    
    state = login_states[uid]
    text = event.text.strip()
    
    if state['step'] == 'phone':
        # 预处理手机号：移除空格和横杠，确保有+号
        phone = re.sub(r'[\s\-()]+', '', text)
        if not phone.startswith('+'):
            return await event.respond("❌ 请确保号码以 `+` 开头，例如 `+86...`")
        
        # 尝试清理可能存在的损坏 Session 文件
        session_file = SESSION_DIR / f"{phone}.session"
        
        # 创建临时 Client 用于获取验证码
        client = TelegramClient(
            str(SESSION_DIR / phone), API_ID, API_HASH,
            device_model="iPhone 15 Pro"
        )
        await client.connect()
        
        try:
            logger.info(f"正在为 {phone} 请求验证码...")
            # 这里的 send_code_request 是关键
            sent_code = await client.send_code_request(phone)
            login_states[uid] = {
                'step': 'code', 'phone': phone, 
                'client': client, 'hash': sent_code.phone_code_hash
            }
            await event.respond(
                f"📩 **验证码已发出！**\n\n"
                "⚠️ **重要提示**：\n"
                "1. 如果你已经在手机或电脑登录了 Telegram，验证码会发送到你的 **Telegram 官方聊天窗口**，请切换回 App 查看。\n"
                "2. 只有在没有任何设备登录时，才会发送短信短信。"
            )
        except errors.FloodWaitError as e:
            await event.respond(f"❌ 频繁请求，请在 {e.seconds} 秒后再试。")
            await client.disconnect()
            del login_states[uid]
        except Exception as e:
            await event.respond(f"❌ 失败: {e}\n请确认号码是否正确。")
            await client.disconnect()
            del login_states[uid]

    elif state['step'] == 'code':
        client, phone = state['client'], state['phone']
        try:
            # 提交验证码
            await client.sign_in(phone, text, phone_code_hash=state['hash'])
            db["accounts"][phone] = {"status": "Online", "added": str(datetime.now())}
            save_db(db)
            await event.respond(f"✅ 账号 {phone} 登录成功！监控已开启。")
            asyncio.create_task(start_userbot_session(phone))
            del login_states[uid]
        except errors.SessionPasswordNeededError:
            state['step'] = 'password'
            await event.respond("🔐 此账号开启了两步验证，请输入两步验证密码：")
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
            await event.respond(f"✅ {phone} 登录成功 (2FA)！")
            asyncio.create_task(start_userbot_session(phone))
            del login_states[uid]
        except Exception as e:
            await event.respond(f"❌ 密码验证失败: {e}")

# =========================
# 启动
# =========================

async def main():
    # 启动管理机器人
    await manager_bot.start(bot_token=BOT_TOKEN)
    logger.info("Manager Bot Started.")
    
    # 拉起存量账号
    for phone in list(db["accounts"].keys()):
        asyncio.create_task(start_userbot_session(phone))
    
    await manager_bot.run_until_disconnected()

if __name__ == "__main__":
    Thread(target=run_web_server, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass
