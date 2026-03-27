import os
import re
import zipfile
import random
import time
import threading
from io import BytesIO
from telebot import TeleBot, types
from flask import Flask

# ========== 端口固定（Render自动识别） ==========
PORT = int(os.environ.get("PORT", 10000))

# ========== 你的配置 ==========
BOT_TOKEN = "8511432045:AAGjwjpk_VHUeNH4hsNX3DVNdTmfV2NoA3A"
ADMIN_ID = 7793291484

# ========== 计费：1万行扣4元 ==========
CHARGE_LINES = 10000
CHARGE_PRICE = 4

# ========== Flask 端口监听（解决 No open ports） ==========
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running ✅"

# ========== 机器人初始化 ==========
bot = TeleBot(BOT_TOKEN)

# ========== 数据存储 ==========
users = {}
cards = {}
user_session = {}

FIRST_NAMES = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "军", "洋", "勇"]

def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "mode": "TXT",
            "split_lines": 100,
            "username": f"用户{user_id}"
        }
    return users[user_id]

def is_admin(user_id):
    return user_id == ADMIN_ID

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

def calculate_fee(total_lines):
    units = (total_lines + CHARGE_LINES - 1) // CHARGE_LINES
    fee = units * CHARGE_PRICE
    return fee, units

# ========== 菜单 ==========
def main_menu(user_id):
    user = get_user(user_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(f"📂 切换模式（{user['mode']}）", callback_data="switch_mode"),
        types.InlineKeyboardButton(f"📏 分包行数（{user['split_lines']}）", callback_data="set_lines")
    )
    kb.add(
        types.InlineKeyboardButton("💰 我的余额", callback_data="show_balance"),
        types.InlineKeyboardButton("💳 卡密充值", callback_data="redeem_card")
    )
    if is_admin(user_id):
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

def filename_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义文件名", callback_data="custom_name"),
        types.InlineKeyboardButton("❌ 使用原文件名", callback_data="origin_name")
    )
    return kb

# ========== /start ==========
@bot.message_handler(commands=["start"])
def start_bot(msg):
    user_id = msg.from_user.id
    get_user(user_id)
    bot.send_message(msg.chat.id, "✅ 机器人已在线\n💸 1万行数据扣费4元", reply_markup=main_menu(user_id))

# ========== 按钮回调 ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    bot.answer_callback_query(call.id)

    if call.data == "switch_mode":
        user = get_user(user_id)
        user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
        bot.edit_message_text(chat_id, msg_id, f"✅ 已切换 {user['mode']} 模式", reply_markup=main_menu(user_id))

    elif call.data == "set_lines":
        bot.send_message(chat_id, "✏️ 输入每个文件行数：")
        bot.register_next_step_handler(call.message, set_lines_handler, user_id)

    elif call.data == "show_balance":
        bal = get_user(user_id)["balance"]
        bot.edit_message_text(chat_id, msg_id, f"💰 余额：{bal} 元", reply_markup=main_menu(user_id))

    elif call.data == "redeem_card":
        bot.send_message(chat_id, "💳 输入卡密：")
        bot.register_next_step_handler(call.message, redeem_card_handler, user_id)

    elif call.data == "admin_panel":
        if is_admin(user_id):
            bot.edit_message_text(chat_id, msg_id, "🔧 管理员面板", reply_markup=admin_menu())
        else:
            bot.send_message(chat_id, "❌ 无权限")

    elif call.data == "back_main":
        bot.edit_message_text(chat_id, msg_id, "✅ 主菜单", reply_markup=main_menu(user_id))

    elif call.data == "add_balance":
        bot.send_message(chat_id, "➕ 格式：用户ID 金额")
        bot.register_next_step_handler(call.message, add_balance_handler)

    elif call.data == "deduct_balance":
        bot.send_message(chat_id, "➖ 格式：用户ID 金额")
        bot.register_next_step_handler(call.message, deduct_balance_handler)

    elif call.data == "gen_card":
        bot.send_message(chat_id, "📛 输入：数量 金额")
        bot.register_next_step_handler(call.message, gen_card_handler)

    elif call.data == "user_list":
        txt = "📊 用户余额：\n"
        for uid, info in users.items():
            txt += f"{uid} | {info['balance']} 元\n"
        bot.send_message(chat_id, txt)

    elif call.data == "broadcast":
        bot.send_message(chat_id, "📢 输入广播内容：")
        bot.register_next_step_handler(call.message, broadcast_handler)

    elif call.data == "custom_name":
        bot.send_message(chat_id, "✏️ 输入文件名前缀：")
        bot.register_next_step_handler(call.message, custom_name_handler)

    elif call.data == "origin_name":
        if user_id in user_session:
            s = user_session[user_id]
            send_files(chat_id, user_id, s["content"], s["mode"], s["lines"], s["original_name"])
            del user_session[user_id]

# ========== 逻辑函数 ==========
def set_lines_handler(msg, user_id):
    try:
        lines = int(msg.text.strip())
        get_user(user_id)["split_lines"] = lines
        bot.send_message(msg.chat.id, f"✅ 已设为 {lines} 行", reply_markup=main_menu(user_id))
    except:
        bot.send_message(msg.chat.id, "❌ 请输入数字")

def redeem_card_handler(msg, user_id):
    card = msg.text.strip()
    user = get_user(user_id)
    if card not in cards or cards[card]["used"]:
        bot.send_message(msg.chat.id, "❌ 卡密无效或已使用", reply_markup=main_menu(user_id))
        return
    amt = cards[card]["amount"]
    cards[card]["used"] = True
    user["balance"] += amt
    bot.send_message(msg.chat.id, f"✅ 充值成功 +{amt} 元", reply_markup=main_menu(user_id))

def add_balance_handler(msg):
    try:
        uid, num = msg.text.split()
        get_user(int(uid))["balance"] += int(num)
        bot.send_message(msg.chat.id, "✅ 增加成功", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def deduct_balance_handler(msg):
    try:
        uid, num = msg.text.split()
        get_user(int(uid))["balance"] -= int(num)
        bot.send_message(msg.chat.id, "✅ 扣除成功", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def gen_card_handler(msg):
    try:
        cnt, amt = msg.text.split()
        cnt, amt = int(cnt), int(amt)
        res = []
        for i in range(cnt):
            c = f"CARD_{int(time.time())}_{random.randint(1000,9999)}"
            cards[c] = {"used": False, "amount": amt}
            res.append(f"{c} | {amt}元")
        bot.send_message(msg.chat.id, "\n".join(res), reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def broadcast_handler(msg):
    t = msg.text
    c = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 广播\n{t}")
            c += 1
        except:
            pass
    bot.send_message(msg.chat.id, f"✅ 发送成功 {c} 人", reply_markup=admin_menu())

def custom_name_handler(msg):
    uid = msg.from_user.id
    if uid in user_session:
        s = user_session[uid]
        send_files(msg.chat.id, uid, s["content"], s["mode"], s["lines"], msg.text.strip())
        del user_session[uid]

# ========== 文件处理 ==========
@bot.message_handler(content_types=["document"])
def handle_file(msg):
    uid = msg.from_user.id
    user = get_user(uid)
    try:
        file = bot.get_file(msg.document.file_id)
        data = bot.download_file(file.file_path)
        name = msg.document.file_name.rsplit(".",1)[0]
        content = ""

        if msg.document.file_name.lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(data)) as zf:
                for f in zf.namelist():
                    if f.lower().endswith(".txt"):
                        content += zf.read(f).decode("utf-8","ignore") + "\n"
        elif msg.document.file_name.lower().endswith(".txt"):
            content = data.decode("utf-8","ignore")
        else:
            bot.send_message(msg.chat.id, "❌ 仅支持 txt/zip")
            return

        total = len(content.splitlines())
        fee, _ = calculate_fee(total)

        if user["balance"] < fee:
            bot.send_message(msg.chat.id, f"❌ 余额不足，需扣费 {fee} 元")
            return

        bot.send_message(msg.chat.id, f"✅ 需扣费 {fee} 元")
        user_session[uid] = {
            "content": content,
            "mode": user["mode"],
            "lines": user["split_lines"],
            "original_name": name,
            "fee": fee
        }
        bot.send_message(msg.chat.id, "请选择文件名方式", reply_markup=filename_menu())
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 错误：{e}")

def send_files(chat_id, uid, content, mode, lines, base):
    user = get_user(uid)
    fee = user_session[uid]["fee"]
    user["balance"] -= fee

    files = []
    if mode == "TXT":
        lines_list = content.splitlines()
        chunks = [lines_list[i:i+lines] for i in range(0, len(lines_list), lines)]
        for i, chunk in enumerate(chunks,1):
            bio = BytesIO("\n".join(chunk).encode("utf-8"))
            bio.name = f"{base}_{i}.txt"
            files.append(bio)
    else:
        phones = re.findall(r"1[3-9]\d{9}", content)
        vcf = []
        cur = ""
        cnt = 0
        for p in phones:
            cur += f"BEGIN:VCARD\nVERSION:3.0\nFN:{random_name()}\nTEL;TYPE=CELL:{p}\nEND:VCARD\n"
            cnt += 1
            if cnt >= lines:
                vcf.append(cur)
                cur = ""
                cnt = 0
        if cur:
            vcf.append(cur)
        for i, chunk in enumerate(vcf,1):
            bio = BytesIO(chunk.encode("utf-8"))
            bio.name = f"{base}_{i}.vcf"
            files.append(bio)

    total_files = len(files)
    bot.send_message(chat_id, f"✅ 共生成 {total_files} 个文件，10个一批发送")

    batch_size = 10
    for i in range(0, total_files, batch_size):
        batch = files[i:i+batch_size]
        for f in batch:
            bot.send_document(chat_id, f)
            time.sleep(0.5)
        if i + batch_size < total_files:
            time.sleep(5)

    bot.send_message(chat_id, f"✅ 发送完成\n本次扣费：{fee} 元\n余额：{user['balance']}", reply_markup=main_menu(uid))

# ========== 启动 Flask + Bot ==========
def run_flask():
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ 端口已开放，机器人启动")
    bot.infinity_polling(timeout=30, long_polling_timeout=5)
