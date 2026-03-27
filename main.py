import os
import re
import zipfile
import random
import time
import threading
from io import BytesIO
from telebot import TeleBot, types
from flask import Flask
import signal
import sys

# ====================== 你的配置 ======================
BOT_TOKEN = "8511432045:AAGdV9Ylw7crSFvAFwrZyJuYwNtYC81qYmU"
ADMIN_ID = 7793291484
# ======================================================

# 全局变量：控制机器人运行状态
bot_running = True
PORT = int(os.environ.get("PORT", 10000))
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Bot Running ✅", 200

# 初始化机器人：移除旧版本不支持的参数，保证兼容
bot = TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    skip_pending=True  # 跳过待处理的更新（关键：解决多实例冲突）
)

# 数据存储
users = {}
cards = {}
file_session = {}

FIRST_NAMES = ["李", "王", "张", "刘", "陈"]
LAST_NAMES = ["伟", "芳", "强", "磊", "军"]

# ====================== 基础函数 ======================
def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0, "mode": "TXT", "split_lines": 100}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

def calculate_fee(total_lines):
    units = (total_lines + 9999) // 10000
    return units * 4

# ====================== 菜单 ======================
def main_menu(uid):
    user = get_user(uid)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(f"📂 模式：{user['mode']}", callback_data="switch_mode"),
        types.InlineKeyboardButton(f"📏 分包行数：{user['split_lines']}", callback_data="set_lines")
    )
    kb.add(
        types.InlineKeyboardButton("💰 我的余额", callback_data="show_balance"),
        types.InlineKeyboardButton("💳 卡密充值", callback_data="redeem_card")
    )
    if is_admin(uid):
        kb.add(types.InlineKeyboardButton("🔧 管理员面板", callback_data="admin_panel"))
    return kb

def admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ 增加余额", callback_data="add_balance"),
        types.InlineKeyboardButton("➖ 扣除余额", callback_data="deduct_balance")
    )
    kb.add(
        types.InlineKeyboardButton("📛 生成卡密", callback_data="gen_card"),
        types.InlineKeyboardButton("📊 用户列表", callback_data="user_list")
    )
    kb.add(
        types.InlineKeyboardButton("📢 全员广播", callback_data="broadcast"),
        types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")
    )
    return kb

def file_name_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义文件名", callback_data=f"custom_name_{uid}"),
        types.InlineKeyboardButton("❌ 使用原文件名", callback_data=f"origin_name_{uid}")
    )
    return kb

# ====================== 核心回调 ======================
@bot.message_handler(commands=['start'])
def start_handler(msg):
    uid = msg.from_user.id
    get_user(uid)
    bot.send_message(
        msg.chat.id, 
        "✅ 机器人已就绪\n💸 计费规则：每1万行数据扣4元（不足1万行按1万算）",
        reply_markup=main_menu(uid)
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        act = call.data
        bot.answer_callback_query(call.id, text="处理中...", show_alert=False)

        # 主菜单功能
        if act == "switch_mode":
            user = get_user(uid)
            user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
            bot.edit_message_text(
                f"✅ 模式已切换为：{user['mode']}",
                cid, call.message.id,
                reply_markup=main_menu(uid)
            )

        elif act == "set_lines":
            bot.send_message(cid, "✏️ 请输入每个文件的行数（如：100）：")
            bot.register_next_step_handler(call.message, set_lines_handler, uid)

        elif act == "show_balance":
            user = get_user(uid)
            bot.edit_message_text(
                f"💰 你的当前余额：{user['balance']} 元",
                cid, call.message.id,
                reply_markup=main_menu(uid)
            )

        elif act == "redeem_card":
            bot.send_message(cid, "💳 请输入卡密：")
            bot.register_next_step_handler(call.message, redeem_card_handler, uid)

        elif act == "admin_panel":
            if is_admin(uid):
                bot.edit_message_text(
                    "🔧 管理员面板",
                    cid, call.message.id,
                    reply_markup=admin_menu()
                )
            else:
                bot.send_message(cid, "❌ 无管理员权限")

        # 管理员功能
        elif act == "add_balance":
            if is_admin(uid):
                bot.send_message(cid, "➕ 请输入：用户ID 金额（如：123456 10）")
                bot.register_next_step_handler(call.message, add_balance_handler)
            else:
                bot.send_message(cid, "❌ 无权限")

        elif act == "deduct_balance":
            if is_admin(uid):
                bot.send_message(cid, "➖ 请输入：用户ID 金额（如：123456 10）")
                bot.register_next_step_handler(call.message, deduct_balance_handler)
            else:
                bot.send_message(cid, "❌ 无权限")

        elif act == "gen_card":
            if is_admin(uid):
                bot.send_message(cid, "📛 请输入：卡密数量 单张金额（如：5 10）")
                bot.register_next_step_handler(call.message, gen_card_handler)
            else:
                bot.send_message(cid, "❌ 无权限")

        elif act == "user_list":
            if is_admin(uid):
                if not users:
                    bot.send_message(cid, "📊 暂无用户数据")
                else:
                    txt = "📊 所有用户余额：\n"
                    for u, d in users.items():
                        txt += f"ID：{u} | 余额：{d['balance']} 元\n"
                    bot.send_message(cid, txt)
            else:
                bot.send_message(cid, "❌ 无权限")

        elif act == "broadcast":
            if is_admin(uid):
                bot.send_message(cid, "📢 请输入广播内容：")
                bot.register_next_step_handler(call.message, broadcast_handler)
            else:
                bot.send_message(cid, "❌ 无权限")

        elif act == "back_main":
            bot.edit_message_text(
                "✅ 已返回主菜单",
                cid, call.message.id,
                reply_markup=main_menu(uid)
            )

        # 文件处理
        elif act.startswith("origin_name_"):
            uid = int(act.split("_")[-1])
            if uid in file_session:
                batch_send_files(cid, uid, file_session[uid], file_session[uid]["filename"])
                del file_session[uid]
            else:
                bot.send_message(cid, "❌ 无文件数据，请先上传文件")

        elif act.startswith("custom_name_"):
            uid = int(act.split("_")[-1])
            bot.send_message(cid, "✏️ 请输入文件名前缀：")
            bot.register_next_step_handler(call.message, custom_name_handler, uid)

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ 操作失败：{str(e)}")
        print(f"回调错误：{e}")

# ====================== 文件上传 ======================
@bot.message_handler(content_types=['document'])
def file_upload_handler(msg):
    uid = msg.from_user.id
    user = get_user(uid)
    cid = msg.chat.id
    try:
        f = bot.get_file(msg.document.file_id)
        data = bot.download_file(f.file_path)
        name = msg.document.file_name.rsplit(".",1)[0]

        content = ""
        if msg.document.file_name.lower().endswith(".txt"):
            content = data.decode("utf-8","ignore")
        elif msg.document.file_name.lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(data)) as zf:
                for fn in zf.namelist():
                    if fn.lower().endswith(".txt"):
                        content += zf.read(fn).decode("utf-8","ignore") + "\n"
        else:
            bot.send_message(cid, "❌ 仅支持 TXT/ZIP 文件")
            return

        lines = len(content.splitlines())
        fee = calculate_fee(lines)
        if user["balance"] < fee:
            bot.send_message(cid, f"❌ 余额不足！需扣费 {fee} 元，当前余额 {user['balance']} 元")
            return

        file_session[uid] = {
            "content": content,
            "filename": name,
            "fee": fee,
            "split_lines": user["split_lines"],
            "mode": user["mode"]
        }
        bot.send_message(cid, f"✅ 文件解析成功！需扣费 {fee} 元", reply_markup=file_name_menu(uid))
    except Exception as e:
        bot.send_message(cid, f"❌ 文件上传失败：{str(e)}")
        print(f"文件上传错误：{e}")

# ====================== 批量发送文件（10个一批） ======================
def batch_send_files(cid, uid, session, prefix):
    try:
        user = get_user(uid)
        user["balance"] -= session["fee"]

        content = session["content"]
        step = session["split_lines"]
        mode = session["mode"]

        # 生成文件列表
        files = []
        if mode == "TXT":
            lines = content.splitlines()
            for i in range(0, len(lines), step):
                b = BytesIO("\n".join(lines[i:i+step]).encode())
                b.name = f"{prefix}_{i//step+1}.txt"
                files.append(b)
        else:
            phones = re.findall(r"1[3-9]\d{9}", content)
            for i in range(0, len(phones), step):
                vcf = ""
                for p in phones[i:i+step]:
                    vcf += f"BEGIN:VCARD\nFN:{random_name()}\nTEL:{p}\nEND:VCARD\n"
                b = BytesIO(vcf.encode())
                b.name = f"{prefix}_{i//step+1}.vcf"
                files.append(b)

        total = len(files)
        if total == 0:
            bot.send_message(cid, "❌ 未生成任何文件（内容为空）")
            return

        bot.send_message(cid, f"✅ 已扣费 {session['fee']} 元，共 {total} 个文件，10个一批发送")

        # 批量发送核心逻辑
        batch_size = 10
        for batch_idx in range(0, total, batch_size):
            current_batch = files[batch_idx:batch_idx+batch_size]
            media_group = []
            
            # 构建媒体组
            for file in current_batch:
                media_group.append(types.InputMediaDocument(file))
            
            # 发送整批文件
            bot.send_media_group(chat_id=cid, media=media_group)
            
            # 发送进度
            sent = min(batch_idx + batch_size, total)
            bot.send_message(cid, f"✅ 已发送 {sent}/{total} 个文件")
            
            # 休息3秒（最后一批不休息）
            if batch_idx + batch_size < total:
                bot.send_message(cid, "⏸ 休息3秒继续发送...")
                time.sleep(3)

        bot.send_message(cid, f"✅ 全部发送完成！当前余额：{user['balance']} 元")
    except Exception as e:
        bot.send_message(cid, f"❌ 文件发送失败：{str(e)}")
        print(f"发送错误：{e}")

# ====================== 其他功能函数 ======================
def custom_name_handler(msg, uid):
    prefix = msg.text.strip()
    if not prefix:
        bot.send_message(msg.chat.id, "❌ 文件名前缀不能为空")
        return
    if uid in file_session:
        batch_send_files(msg.chat.id, uid, file_session[uid], prefix)
        del file_session[uid]
    else:
        bot.send_message(msg.chat.id, "❌ 无文件数据，请先上传文件")

def set_lines_handler(msg, uid):
    try:
        lines = int(msg.text.strip())
        if lines <= 0:
            bot.send_message(msg.chat.id, "❌ 行数必须大于0")
            return
        get_user(uid)["split_lines"] = lines
        bot.send_message(msg.chat.id, f"✅ 分包行数已设置为：{lines} 行")
    except:
        bot.send_message(msg.chat.id, "❌ 请输入有效数字（如：100）")

def redeem_card_handler(msg, uid):
    card = msg.text.strip()
    if card not in cards:
        bot.send_message(msg.chat.id, "❌ 卡密无效")
        return
    if cards[card]["used"]:
        bot.send_message(msg.chat.id, "❌ 卡密已使用")
        return
    amount = cards[card]["amount"]
    cards[card]["used"] = True
    get_user(uid)["balance"] += amount
    bot.send_message(msg.chat.id, f"✅ 充值成功！到账 {amount} 元")

def add_balance_handler(msg):
    try:
        uid, amt = msg.text.strip().split()
        get_user(int(uid))["balance"] += int(amt)
        bot.send_message(msg.chat.id, f"✅ 已为用户 {uid} 增加 {amt} 元")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误（正确：用户ID 金额）")

def deduct_balance_handler(msg):
    try:
        uid, amt = msg.text.strip().split()
        get_user(int(uid))["balance"] -= int(amt)
        bot.send_message(msg.chat.id, f"✅ 已为用户 {uid} 扣除 {amt} 元")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误（正确：用户ID 金额）")

def gen_card_handler(msg):
    try:
        count, amt = msg.text.strip().split()
        count = int(count)
        amt = int(amt)
        if count <= 0 or amt <= 0:
            bot.send_message(msg.chat.id, "❌ 数量/金额必须大于0")
            return
        res = []
        for _ in range(count):
            code = f"CARD_{random.randint(100000,999999)}"
            cards[code] = {"used": False, "amount": amt}
            res.append(f"{code} | {amt} 元")
        bot.send_message(msg.chat.id, f"📛 生成 {count} 张卡密：\n" + "\n".join(res))
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误（正确：数量 金额）")

def broadcast_handler(msg):
    content = msg.text.strip()
    success = 0
    fail = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 管理员广播：\n{content}")
            success += 1
        except:
            fail += 1
    bot.send_message(msg.chat.id, f"✅ 广播完成！成功：{success} 人，失败：{fail} 人")

# ====================== 优雅退出处理（解决多实例冲突） ======================
def signal_handler(signal_num, frame):
    """处理程序退出信号，确保机器人正常停止"""
    global bot_running
    bot_running = False
    print("⚠️ 收到退出信号，正在停止机器人...")
    bot.stop_polling()
    sys.exit(0)

# 注册退出信号
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ====================== 启动函数 ======================
def run_flask():
    """启动Flask（仅用于Render端口监听）"""
    app.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

def run_bot():
    """启动机器人（单实例）"""
    global bot_running
    print("🚀 机器人启动中...")
    while bot_running:
        try:
            # 单实例轮询配置（兼容旧版本）
            bot.infinity_polling(
                long_polling_timeout=10,
                skip_pending=True,
                restart_on_change=False  # 禁止自动重启
            )
        except Exception as e:
            print(f"⚠️ 轮询出错：{e}，5秒后重试...")
            time.sleep(5)
            continue

if __name__ == "__main__":
    # 1. 启动Flask（后台线程）
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Flask已启动，端口：{PORT}")

    # 2. 启动机器人（主线程）
    run_bot()
