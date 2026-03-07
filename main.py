# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import random
from pathlib import Path
from threading import Thread

# 必须确保在 requirements.txt 中安装了: telethon, flask, python-socks
from flask import Flask
from telethon import TelegramClient, events, errors
from telethon.tl.types import ReplyInlineMarkup

# =========================
# 1. 基础配置 (请检查配置是否正确)
# =========================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484

# 分布式部署建议：如果环境无法访问 Telegram 官方 IP，请配置代理
# PROXY = ("socks5", "127.0.0.1", 1080)
PROXY = None 

PORT = int(os.getenv("PORT", "8080"))
# 确保 session 目录具有写入权限
BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# 日志格式增强：方便定位 Exit 1 的原因
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("RedPacketSystem")

# =========================
# 2. Render 生存维持 (Flask)
# =========================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot System is Running...", 200

def run_flask():
    """在独立线程中运行 Flask 以避免阻塞事件循环"""
    try:
        # 必须绑定 0.0.0.0 否则外部无法访问
        app.run(host='0.0.0.0', port=PORT, threaded=True)
    except Exception as e:
        logger.error(f"Flask Web Server 启动失败: {e}")

# =========================
# 3. UserBot 核心业务 (红包点击器)
# =========================
active_workers = {}

async def run_worker(phone):
    """处理单个个人账号的监听逻辑"""
    session_name = str(SESSION_DIR / f"worker_{phone}")
    client = TelegramClient(
        session_name, API_ID, API_HASH,
        proxy=PROXY,
        device_model="iPhone 15 Pro",
        system_version="17.4"
    )

    try:
        await client.start()
        active_workers[phone] = client
        logger.info(f"账号 {phone} 已激活并进入监控状态。")

        @client.on(events.NewMessage)
        async def on_new_message(event):
            # 逻辑：消息含有内联按钮 (Inline Buttons)
            if event.reply_markup and isinstance(event.reply_markup, ReplyInlineMarkup):
                # 随机延迟，极致模拟真人操作
                await asyncio.sleep(random.uniform(0.3, 1.2))
                try:
                    # 尝试点击消息的第一个按钮
                    await event.click(0)
                    logger.info(f"账号 {phone} 成功执行点击操作。")
                except errors.FloodWaitError as fe:
                    logger.warning(f"账号 {phone} 触发频率限制，需等待 {fe.seconds} 秒")
                except Exception as e:
                    logger.debug(f"账号 {phone} 点击按钮尝试失败")

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"账号 {phone} 运行中发生错误: {e}")
    finally:
        active_workers.pop(phone, None)

# =========================
# 4. 管理端 BOT 逻辑
# =========================
manager_session = str(SESSION_DIR / "manager_bot")
manager = TelegramClient(manager_session, API_ID, API_HASH, proxy=PROXY)
pending_logins = {}

@manager.on(events.NewMessage(pattern='/status', from_users=ADMIN_ID))
async def cmd_status(event):
    msg = f"✅ **系统在线**\n当前运行账号数量: `{len(active_workers)}`"
    await event.respond(msg)

@manager.on(events.NewMessage(pattern='/add', from_users=ADMIN_ID))
async def cmd_add(event):
    pending_logins[event.sender_id] = {'step': 'phone'}
    await event.respond("请输入手机号 (国际格式，如 +86138...)：")

@manager.on(events.NewMessage(from_users=ADMIN_ID))
async def login_handler(event):
    uid = event.sender_id
    if uid not in pending_logins: return
    
    state = pending_logins[uid]
    text = event.text.strip()

    try:
        if state['step'] == 'phone':
            # 临时生成 Client 用于验证
            tmp_client = TelegramClient(str(SESSION_DIR / f"worker_{text}"), API_ID, API_HASH, proxy=PROXY)
            await tmp_client.connect()
            sent_code = await tmp_client.send_code_request(text)
            pending_logins[uid] = {
                'step': 'code', 'phone': text, 'client': tmp_client, 
                'hash': sent_code.phone_code_hash
            }
            await event.respond("📝 请回复收到的 **Telegram 验证码**：")

        elif state['step'] == 'code':
            client = state['client']
            await client.sign_in(state['phone'], text, phone_code_hash=state['hash'])
            await event.respond(f"🎊 {state['phone']} 登录成功，已加入监控池！")
            asyncio.create_task(run_worker(state['phone']))
            del pending_logins[uid]

    except errors.SessionPasswordNeededError:
        state['step'] = '2fa'
        await event.respond("🔐 此账号开启了两步验证，请输入密码：")
    except errors.FloodWaitError as e:
        await event.respond(f"❌ 频繁请求，已被锁定。请在 {e.seconds} 秒后再试。")
        del pending_logins[uid]
    except Exception as e:
        await event.respond(f"❌ 运行错误: {e}")
        del pending_logins[uid]

# =========================
# 5. 主程序启动入口
# =========================
async def start_system():
    # A. 启动管理机器人
    logger.info("正在启动管理机器人...")
    await manager.start(bot_token=BOT_TOKEN)
    logger.info("管理机器人启动成功。")

    # B. 加载历史 Session (自动重连)
    for session_file in SESSION_DIR.glob("worker_*.session"):
        phone = session_file.stem.replace("worker_", "")
        if phone:
            logger.info(f"正在自动恢复账号: {phone}")
            asyncio.create_task(run_worker(phone))
            await asyncio.sleep(2) # 间隔启动防止被封 IP

    # C. 维持主进程
    await manager.run_until_disconnected()

if __name__ == "__main__":
    # 1. 启动 Web 保活线程
    web_thread = Thread(target=run_flask, daemon=True)
    web_thread.start()

    # 2. 启动异步主逻辑
    try:
        asyncio.run(start_system())
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序手动停止。")
    except Exception as e:
        logger.critical(f"系统因不可控异常崩溃: {e}")
