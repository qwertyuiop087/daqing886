# -*- coding: utf-8 -*-
import os
import json
import asyncio
import logging
import threading
from pathlib import Path
from datetime import datetime

# 引入 Flask 用于 Render 端口保活
from flask import Flask
# 引入 Pyrogram
from pyrogram import Client, filters, enums
from pyrogram.errors import (
    PhoneNumberInvalid, FloodWait, PhoneCodeInvalid, 
    SessionPasswordNeeded, PhoneCodeExpired
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# =========================
# 1. 核心配置 (用户同步)
# =========================
API_ID = 38596687
API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
ADMIN_ID = 7793291484

# Render 端口
PORT = int(os.getenv("PORT", "8080"))

# 持久化路径
SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)
DB_FILE = "accounts_db.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RedPacketBot")

# =========================
# 2. Render 保活服务 (Flask)
# =========================
web_app = Flask(__name__)

@web_app.route('/')
def health():
    return "Bot is Running", 200

def run_flask():
    web_app.run(host='0.0.0.0', port=PORT)

# =========================
# 3. 数据层
# =========================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"running_phones": [], "stats": {"total": 0, "success": 0}}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

db = load_db()
user_states = {}  # 存放临时登录状态数据
active_clients = {} # 存放运行中的 Client 实例

# =========================
# 4. 核心功能: 抢红包监听
# =========================
async def start_red_packet_monitor(phone):
    """为每个账号开启独立的抢红包任务"""
    # 模拟真实移动端设备信息提高稳定性
    client = Client(
        name=f"{SESSION_DIR}/{phone}",
        api_id=API_ID,
        api_hash=API_HASH,
        device_model="iPhone 15 Pro",
        system_version="iOS 17.4"
    )
    
    @client.on_message(filters.group)
    async def hongbao_handler(c, msg):
        # 简单逻辑：如果消息有内联键盘，则尝试点击
        if msg.reply_markup:
            db["stats"]["total"] += 1
            try:
                # 模拟点击第一个按钮
                await msg.click(0)
                db["stats"]["success"] += 1
                logger.info(f"[{phone}] 成功尝试领取红包")
            except Exception as e:
                logger.error(f"[{phone}] 领取失败: {e}")
            save_db(db)

    try:
        await client.start()
        active_clients[phone] = client
        if phone not in db["running_phones"]:
            db["running_phones"].append(phone)
            save_db(db)
        logger.info(f"账号 {phone} 监控已启动")
        # 保持运行
        await asyncio.Event().wait()
    except Exception as e:
        logger.error(f"账号 {phone} 运行异常: {e}")
    finally:
        if phone in active_clients: del active_clients[phone]

# =========================
# 5. 管理 Bot 逻辑
# =========================
bot = Client(
    "manager_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

@bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def cmd_start(c, m):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ 添加账号", callback_data="add_acc"),
        InlineKeyboardButton("📊 运行状态", callback_data="view_status")
    ]])
    await m.reply_text("🏮 欢迎使用红包监控管理系统\n请点击下方按钮操作：", reply_markup=keyboard)

@bot.on_callback_query(filters.user(ADMIN_ID))
async def handle_query(c, q):
    if q.data == "add_acc":
        user_states[q.from_user.id] = {"step": "phone"}
        await q.message.edit_text("📱 请输入手机号 (格式: +86138...)：")
    
    elif q.data == "view_status":
        s = db["stats"]
        msg = (f"📈 运行中账号: {len(active_clients)}\n"
               f"🧧 已尝试领取: {s['total']}\n"
               f"✅ 成功命中: {s['success']}")
        await q.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("返回", callback_data="back_main")
        ]]))
    
    elif q.data == "back_main":
        await cmd_start(c, q.message)

@bot.on_message(filters.user(ADMIN_ID) & filters.text)
async def login_flow(c, m):
    uid = m.from_user.id
    if uid not in user_states: return
    
    state = user_states[uid]
    text = m.text.strip()
    
    # 步骤 1: 发送验证码 (模仿核心逻辑)
    if state["step"] == "phone":
        phone = text
        if not phone.startswith("+"):
            return await m.reply("❌ 格式错误，必须以 + 开头")
        
        temp_client = Client(
            f"{SESSION_DIR}/{phone}", 
            API_ID, API_HASH,
            device_model="iPhone 15 Pro"
        )
        await temp_client.connect()
        try:
            # 发送验证码
            sent_code = await temp_client.send_code(phone)
            user_states[uid] = {
                "step": "code", "phone": phone, 
                "client": temp_client, "hash": sent_code.phone_code_hash
            }
            await m.reply(f"📩 验证码已发送至 {phone}\n请在下方输入验证码：\n\n(注意: 请检查 Telegram 官方会话消息)")
        except FloodWait as e:
            await m.reply(f"⚠️ 频繁操作，请等待 {e.value} 秒")
            await temp_client.disconnect()
            del user_states[uid]
        except Exception as e:
            await m.reply(f"❌ 发送失败: {e}")
            await temp_client.disconnect()
            del user_states[uid]

    # 步骤 2: 校验验证码
    elif state["step"] == "code":
        try:
            client = state["client"]
            phone = state["phone"]
            await client.sign_in(phone, state["hash"], text)
            
            # 登录成功
            await m.reply(f"✅ 账号 {phone} 登录成功，正在开启监控...")
            asyncio.create_task(start_red_packet_monitor(phone))
            del user_states[uid]
        except SessionPasswordNeeded:
            state["step"] = "2fa"
            await m.reply("🔐 此账号需要两步验证密码，请输入：")
        except PhoneCodeInvalid:
            await m.reply("❌ 验证码错误，请检查并重新输入：")
        except PhoneCodeExpired:
            await m.reply("❌ 验证码已过期，请重新登录。")
            del user_states[uid]
        except Exception as e:
            await m.reply(f"❌ 登录失败: {e}")
            del user_states[uid]

    # 步骤 3: 两步验证
    elif state["step"] == "2fa":
        try:
            await state["client"].check_password(text)
            phone = state["phone"]
            await m.reply(f"✅ {phone} 登录成功！")
            asyncio.create_task(start_red_packet_monitor(phone))
            del user_states[uid]
        except Exception as e:
            await m.reply(f"❌ 密码错误: {e}")

# =========================
# 6. 系统启动入口
# =========================
async def main():
    # A. 启动管理 Bot
    await bot.start()
    logger.info("Bot Manager Started")

    # B. 断线重连已保存的账号
    for phone in db["running_phones"]:
        asyncio.create_task(start_red_packet_monitor(phone))
    
    # C. 防止主任务退出
    await asyncio.Event().wait()

if __name__ == "__main__":
    # 1. 启动 Flask 保活线程 (满足 Render 端口需求)
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. 启动异步主逻辑
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
