# -*- coding: utf-8 -*-
import os
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from threading import Thread
from typing import Final

# 引入必要的库
from flask import Flask
from telethon import TelegramClient, events, errors

# =========================
# 配置部分 (使用用户提供的凭据)
# =========================

API_ID: Final = 38596687
API_HASH: Final = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN: Final = "7750611624:AAGk0mqxsBkcSbVpQA37KAQbQnQbxUCV2ww"

# Render 部署环境所需端口配置
PORT = int(os.getenv("PORT", "8080"))

# 系统路径配置
SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)
DATA_FILE = Path("account_stats.json")

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RedPacketBot")

# =========================
# Web 服务 (用于绕过 Render 端口检测)
# =========================

app = Flask(__name__)

@app.route('/')
def index():
    # Render 要求必须监听端口并返回 200，否则会判定部署失败
    return "Bot is running perfectly.", 200

def run_web_server():
    app.run(host='0.0.0.0', port=PORT)

# =========================
# 数据持久化处理
# =========================

def load_db():
    """从本地加载统计数据和账号状态"""
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"accounts": {}, "stats": {"total": 0, "success": 0}}

def save_db(data):
    """保存数据到本地 JSON 文件"""
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# 全局内存变量
db = load_db()
active_userbots = {}  # 存放运行中的 UserBot 实例
login_states = {}     # 存放临时登录步骤信息

# =========================
# UserBot 红包抢夺逻辑
# =========================

async def start_userbot_session(phone):
    """为每一个手机号创建一个独立的 UserBot 监听任务"""
    session_str = str(SESSION_DIR / phone)
    # 使用 Telethon 的客户端连接
    client = TelegramClient(session_str, API_ID, API_HASH)
    
    @client.on(events.NewMessage)
    async def hongbao_handler(event):
        """核心：红包消息检测与自动点击"""
        msg_text = event.raw_text or ""
        # 匹配红包特征：包含关键词或包含内联按钮
        is_packet = any(kw in msg_text for kw in ["红包", "🧧", "抢红包", "Red Packet"])
        has_button = event.reply_markup is not None
        
        if is_packet or has_button:
            db["stats"]["total"] += 1
            try:
                # 模拟点击消息中的第一个按钮（通常是“抢”或“开”）
                await event.click(0)
                db["stats"]["success"] += 1
                logger.info(f"账号 {phone} 成功捕捉并点击红包按钮。")
            except Exception as e:
                logger.error(f"账号 {phone} 点击红包失败: {e}")
            save_db(db)

    try:
        await client.start()
        active_userbots[phone] = client
        db["accounts"][phone]["status"] = "Running"
        save_db(db)
        # 持续运行监听
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"账号 {phone} 停止运行: {e}")
        if phone in db["accounts"]:
            db["accounts"][phone]["status"] = "Offline"
            save_db(db)

# =========================
# Bot 管理端 (控制机器人)
# =========================

# 创建主管理机器人实例
manager_bot = TelegramClient('manager_session', API_ID, API_HASH)

@manager_bot.on(events.NewMessage(pattern='/start'))
async def cmd_start(event):
    welcome = (
        "🤖 Telegram 多账号红包自动助手\n\n"
        "1️⃣ /login - 开始登录新账号\n"
        "2️⃣ /list - 查看当前账号列表及状态\n"
        "3️⃣ /delete <手机号> - 移除指定账号\n"
        "4️⃣ /stats - 查看全局抢红包统计\n"
    )
    await event.respond(welcome)

@manager_bot.on(events.NewMessage(pattern='/login'))
async def cmd_login(event):
    uid = event.sender_id
    login_states[uid] = {'step': 'phone'}
    await event.respond("请输入您要登录的手机号 (格式示例: +8613800000000)：")

@manager_bot.on(events.NewMessage(pattern='/list'))
async def cmd_list(event):
    if not db["accounts"]:
        return await event.respond("目前没有任何已登录账号。")
    
    lines = ["📱 已保存的账号列表："]
    for ph, info in db["accounts"].items():
        lines.append(f"- `{ph}` | 状态: {info.get('status', '未知')}")
    await event.respond("\n".join(lines))

@manager_bot.on(events.NewMessage(pattern='/stats'))
async def cmd_stats(event):
    st = db["stats"]
    total = st["total"]
    succ = st["success"]
    rate = (succ / total * 100) if total > 0 else 0
    msg = (
        "💰 自动抢红包统计：\n"
        f"- 累计检测：{total} 次\n"
        f"- 成功点击：{succ} 次\n"
        f"- 综合成功率：{rate:.2f}%"
    )
    await event.respond(msg)

@manager_bot.on(events.NewMessage(pattern='/delete'))
async def cmd_del(event):
    parts = event.text.split()
    if len(parts) < 2:
        return await event.respond("请使用：`/delete +86...`")
    
    phone = parts[1]
    if phone in db["accounts"]:
        # 断开 UserBot 连接
        if phone in active_userbots:
            await active_userbots[phone].disconnect()
            del active_userbots[phone]
        # 删除持久化记录
        del db["accounts"][phone]
        save_db(db)
        # 删除物理 Session 文件
        s_file = SESSION_DIR / f"{phone}.session"
        if s_file.exists(): s_file.unlink()
        await event.respond(f"✅ 账号 {phone} 的数据已删除。")
    else:
        await event.respond("未找到该账号。")

@manager_bot.on(events.NewMessage)
async def handle_login_steps(event):
    """处理账号登录的交互式状态机"""
    uid = event.sender_id
    if uid not in login_states: return
    
    state = login_states[uid]
    text = event.text.strip()
    
    # 步骤 1：处理手机号输入并发送验证码
    if state['step'] == 'phone':
        phone = text
        client = TelegramClient(str(SESSION_DIR / phone), API_ID, API_HASH)
        await client.connect()
        try:
            sent_code = await client.send_code_request(phone)
            login_states[uid] = {
                'step': 'code', 'phone': phone, 
                'client': client, 'hash': sent_code.phone_code_hash
            }
            await event.respond(f"验证码已向 {phone} 发送，请输入验证码：")
        except Exception as e:
            await event.respond(f"发送验证码失败: {e}\n请重新 /login")
            await client.disconnect()
            del login_states[uid]

    # 步骤 2：校验验证码完成登录
    elif state['step'] == 'code':
        try:
            client = state['client']
            phone = state['phone']
            await client.sign_in(phone, text, phone_code_hash=state['hash'])
            
            # 登录成功，记录数据
            db["accounts"][phone] = {"status": "Online", "added": str(datetime.now())}
            save_db(db)
            
            await event.respond(f"✅ 账号 {phone} 登录成功，正在启动红包监控...")
            asyncio.create_task(start_userbot_session(phone)) # 启动背景监控
            del login_states[uid]
        except errors.SessionPasswordNeededError:
            # 账号开启了二步验证 (2FA)
            login_states[uid]['step'] = 'password'
            await event.respond("此账号需要两步验证密码，请输入：")
        except Exception as e:
            await event.respond(f"登录失败: {e}")
            await state['client'].disconnect()
            del login_states[uid]

    # 步骤 3：处理两步验证密码
    elif state['step'] == 'password':
        try:
            phone = state['phone']
            await state['client'].sign_in(password=text)
            db["accounts"][phone] = {"status": "Online", "added": str(datetime.now())}
            save_db(db)
            await event.respond(f"✅ 账号 {phone} (2FA) 登录成功！")
            asyncio.create_task(start_userbot_session(phone))
            del login_states[uid]
        except Exception as e:
            await event.respond(f"密码错误或登录失败: {e}")

# =========================
# 程序主入口
# =========================

async def main():
    logger.info("主程序正在启动...")

    # 1. 初始化并自动拉起已有的 UserBot 账号
    for phone in list(db["accounts"].keys()):
        asyncio.create_task(start_userbot_session(phone))
    
    # 2. 启动管理机器人
    await manager_bot.start(bot_token=BOT_TOKEN)
    logger.info("管理端 Bot 处于运行状态...")
    
    # 3. 阻塞运行，直到机器人停止
    await manager_bot.run_until_disconnected()

if __name__ == "__main__":
    # 在独立线程运行 Flask 服务以满足 Render 的健康检查
    Thread(target=run_web_server, daemon=True).start()
    
    # 运行 asyncio 循环
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
