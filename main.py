# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import random
from pathlib import Path
from threading import Thread

from flask import Flask
from telethon import TelegramClient, events, errors
from telethon.tl.types import ReplyInlineMarkup

# =========================
# 1. 基础配置
# =========================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484

# 如果你在 Render 上运行，建议使用代理 (SOCKS5 格式)
# PROXY = ("代理IP", 端口, "用户名", "密码")
PROXY = None 

PORT = int(os.getenv("PORT", "8080"))
SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("SafeSystem")

# =========================
# 2. Web 存活支持
# =========================
app = Flask(__name__)
@app.route('/')
def health(): return "System Operating", 200

def run_server():
    app.run(host='0.0.0.0', port=PORT)

# =========================
# 3. 核心 UserBot 逻辑
# =========================
running_accounts = {}

async def start_user_worker(phone):
    """启动个人账号监听"""
    session_path = str(SESSION_DIR / phone)
    
    # 增加 proxy 参数
    client = TelegramClient(
        session_path, API_ID, API_HASH,
        proxy=PROXY,
        device_model="iPhone 15 Pro",
        system_version="17.4"
    )
    
    try:
        await client.start()
        running_accounts[phone] = client
        logger.info(f"账号 {phone} 已成功上线.")

        @client.on(events.NewMessage)
        async def click_handler(event):
            # 抢红包：检测到有 Inline 按钮的消息
            if event.reply_markup and isinstance(event.reply_markup, ReplyInlineMarkup):
                # 随机延迟 0.5-1.5 秒，模拟真人操作减少封号风险
                await asyncio.sleep(random.uniform(0.5, 1.5))
                try:
                    await event.click(0)
                    logger.info(f"账号 {phone} 成功点击红包按钮")
                except errors.FloodWaitError as fe:
                    logger.warning(f"账号 {phone} 点击过快，需等待 {fe.seconds} 秒")
                except Exception as e:
                    logger.error(f"点击失败: {e}")

        await client.run_until_disconnected()
    except errors.FloodWaitError as e:
        logger.error(f"账号 {phone} 被封锁，请等待 {e.seconds} 秒后操作")
    except Exception as e:
        logger.error(f"账号 {phone} 运行异常: {e}")
    finally:
        running_accounts.pop(phone, None)

# =========================
# 4. 管理端逻辑
# =========================
manager = TelegramClient('manager_session', API_ID, API_HASH, proxy=PROXY)
login_context = {}

@manager.on(events.NewMessage(pattern='/start', from_users=ADMIN_ID))
async def cmd_start(event):
    await event.respond("🛡️ **多账号安全监控中心**\n使用 /add 添加账号，/status 查看。")

@manager.on(events.NewMessage(pattern='/add', from_users=ADMIN_ID))
async def cmd_add(event):
    login_context[event.sender_id] = {'step': 'phone'}
    await event.respond("📱 请发送手机号：")

@manager.on(events.NewMessage(from_users=ADMIN_ID))
async def login_flow(event):
    uid = event.sender_id
    if uid not in login_context: return
    
    state = login_context[uid]
    text = event.text.strip()

    try:
        if state['step'] == 'phone':
            tmp_client = TelegramClient(str(SESSION_DIR / text), API_ID, API_HASH, proxy=PROXY)
            await tmp_client.connect()
            # 尝试发送验证码
            sent_code = await tmp_client.send_code_request(text)
            login_context[uid] = {
                'step': 'code', 'phone': text, 'client': tmp_client, 
                'hash': sent_code.phone_code_hash
            }
            await event.respond("📩 验证码已发，请回复：")

        elif state['step'] == 'code':
            client = state['client']
            await client.sign_in(state['phone'], text, phone_code_hash=state['hash'])
            await event.respond(f"✅ {state['phone']} 成功登录")
            asyncio.create_task(start_user_worker(state['phone']))
            del login_context[uid]

    except errors.FloodWaitError as e:
        # 当遇到此类错误时，给出清晰的提示
        await event.respond(f"❌ 触发洪水限制！Telegram 强制要求等待 {e.seconds} 秒 ({e.seconds // 3600} 小时)。请稍后再试，**期间不要再尝试登录**。")
        del login_context[uid]
    except Exception as e:
        await event.respond(f"❌ 错误: {e}")
        del login_context[uid]

# =========================
# 5. 入口
# =========================
async def main():
    await manager.start(bot_token=BOT_TOKEN)
    logger.info("Manager Ready.")

    # 自动重连已有账号，每个账号之间间隔 5 秒，防止批量启动被封
    for session_file in SESSION_DIR.glob("*.session"):
        phone = session_file.stem
        if phone != "manager_session":
            asyncio.create_task(start_user_worker(phone))
            await asyncio.sleep(5) 

    await manager.run_until_disconnected()

if __name__ == "__main__":
    Thread(target=run_server, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
