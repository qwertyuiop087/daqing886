# -*- coding: utf-8 -*-
import os
import asyncio
import logging
from pathlib import Path
from threading import Thread

from flask import Flask
from telethon import TelegramClient, events, errors
from telethon.tl.types import ReplyInlineMarkup

# =========================
# 1. 基础配置
# =========================
# API_ID/HASH 是“应用程序身份证”，填一次即可登录无数个号码
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
# BOT_TOKEN 是你的“控制面板”，用来指挥系统
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484

PORT = int(os.getenv("PORT", "8080"))
SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("System")

# =========================
# 2. Web 存活支持 (Render 专用)
# =========================
app = Flask(__name__)
@app.route('/')
def health(): return "System Online", 200

def run_server():
    app.run(host='0.0.0.0', port=PORT)

# =========================
# 3. UserBot 逻辑 (执行点击任务)
# =========================
# 存储当前所有已登录并运行的个人账号实例
running_accounts = {}

async def start_user_worker(phone):
    """
    启动一个个人账号的监听任务
    phone: 手机号字符串
    """
    # 路径指向存储好的 .session 文件，实现免登录重启
    session_path = str(SESSION_DIR / phone)
    client = TelegramClient(session_path, API_ID, API_HASH, 
                            device_model="iPhone 15", system_version="17.4")
    
    try:
        await client.start()
        running_accounts[phone] = client
        logger.info(f"账号 {phone} 已成功上线.")

        # 核心点击逻辑：监听所有新消息
        @client.on(events.NewMessage)
        async def click_handler(event):
            # 如果消息包含内联按钮（Inline Buttons）
            if event.reply_markup and isinstance(event.reply_markup, ReplyInlineMarkup):
                try:
                    # 这里的 0 代表尝试点击第一个按钮（通常是抢红包按钮）
                    await event.click(0)
                    logger.info(f"账号 {phone} 成功执行点击动作")
                except Exception as e:
                    logger.error(f"账号 {phone} 点击按钮失败: {e}")

        # 保持该账号在线
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"账号 {phone} 异常离线: {e}")
    finally:
        running_accounts.pop(phone, None)

# =========================
# 4. 管理机器人逻辑 (指挥官)
# =========================
manager = TelegramClient('manager_session', API_ID, API_HASH)
login_context = {}  # 记录当前哪个管理员正在添加哪个账号

@manager.on(events.NewMessage(pattern='/start', from_users=ADMIN_ID))
async def cmd_start(event):
    await event.respond("🛡️ **红包监控系统已就绪**\n\n"
                       "发送 `/add` 开始登录你的第一个个人账号\n"
                       "发送 `/status` 查看当前在线账号数量")

@manager.on(events.NewMessage(pattern='/add', from_users=ADMIN_ID))
async def cmd_add(event):
    login_context[event.sender_id] = {'step': 'phone'}
    await event.respond("📱 请输入你要登录的个人号手机号（带+号）：\n例如：`+8613800000000`")

@manager.on(events.NewMessage(from_users=ADMIN_ID))
async def login_flow(event):
    uid = event.sender_id
    if uid not in login_context: return
    
    user_data = login_context[uid]
    input_text = event.text.strip()

    # 步骤 1: 发送验证码
    if user_data['step'] == 'phone':
        # 为这个新号码创建一个临时的客户端
        tmp_client = TelegramClient(str(SESSION_DIR / input_text), API_ID, API_HASH)
        await tmp_client.connect()
        try:
            # 向 Telegram 请求发送验证码
            sent_code = await tmp_client.send_code_request(input_text)
            login_context[uid] = {
                'step': 'code', 
                'phone': input_text, 
                'client': tmp_client, 
                'hash': sent_code.phone_code_hash
            }
            await event.respond(f"✅ 验证码已发送至 `{input_text}` 的 Telegram 官方会话，请查看并在此回复：")
        except Exception as e:
            await event.respond(f"❌ 失败: {e}")
            await tmp_client.disconnect()
            del login_context[uid]

    # 步骤 2: 输入验证码后的处理
    elif user_data['step'] == 'code':
        client = user_data['client']
        try:
            # 尝试使用验证码登录
            await client.sign_in(user_data['phone'], input_text, phone_code_hash=user_data['hash'])
            await event.respond(f"🎉 账号 {user_data['phone']} 登录成功！已启动自动抢红包。")
            # 登录成功后，将该账号转入后台异步运行
            asyncio.create_task(start_user_worker(user_data['phone']))
            del login_context[uid]
        except errors.SessionPasswordNeededError:
            # 处理二次验证密码
            user_data['step'] = '2fa'
            await event.respond("🔐 该账号开启了两步验证，请输入你的 2FA 密码：")
        except Exception as e:
            await event.respond(f"❌ 登录失败: {e}")
            del login_context[uid]

    # 步骤 3: 处理两步验证密码
    elif user_data['step'] == '2fa':
        try:
            await user_data['client'].sign_in(password=input_text)
            await event.respond(f"🎉 账号 {user_data['phone']} (2FA) 登录成功！")
            asyncio.create_task(start_user_worker(user_data['phone']))
            del login_context[uid]
        except Exception as e:
            await event.respond(f"❌ 密码错误: {e}")

@manager.on(events.NewMessage(pattern='/status', from_users=ADMIN_ID))
async def cmd_status(event):
    count = len(running_accounts)
    msg = f"📊 **系统状态**\n目前共有 `{count}` 个账号正在后台监控红包。"
    await event.respond(msg)

# =========================
# 5. 系统启动入口
# =========================
async def main():
    # A. 启动管理机器人
    await manager.start(bot_token=BOT_TOKEN)
    logger.info("Manager Bot Started.")

    # B. 自动拉起 sessions 文件夹中已有的旧账号
    for session_file in SESSION_DIR.glob("*.session"):
        phone = session_file.stem
        if phone != "manager_session":
            asyncio.create_task(start_user_worker(phone))

    # C. 持续运行
    await manager.run_until_disconnected()

if __name__ == "__main__":
    # 启动端口监听用于 Render 存活
    Thread(target=run_server, daemon=True).start()
    
    # 启动异步主程序
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
