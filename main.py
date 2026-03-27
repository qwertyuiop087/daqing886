import os
import re
import zipfile
import random
import time
import threading
from io import BytesIO
from telebot import TeleBot, types
from flask import Flask

# ====================== 你只改这里 ======================
BOT_TOKEN = "8511432045:AAGjwjpk_VHUeNH4hsNX3DVNdTmfV2NoA3A"
ADMIN_ID = 7793291484  # 你的TG数字ID
# ======================================================

PORT = int(os.environ.get("PORT", 10000))
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running", 200

# 初始化机器人
bot = TeleBot(BOT_TOKEN)

users = {}
cards = {}
user_session = {}

FIRST_NAMES = ["李", "王", "张", "刘", "陈"]
LAST_NAMES = ["伟", "芳", "强", "磊", "军"]

def get_user(uid):
    if uid not in users:
        users[uid] = {"balance":0, "mode":"TXT", "split_lines":100}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

def calculate_fee(lines):
    unit = (lines + 9999) // 10000
    return unit * 4

# ====================== 菜单 ======================
def main_menu(uid):
    user = get_user(uid)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(f"📂 模式:{user['mode']}", callback_data="switch"),
        types.InlineKeyboardButton(f"📏 行数:{user['split_lines']}", callback_data="setlines")
    )
    kb.add(
        types.InlineKeyboardButton("💰 余额", callback_data="balance"),
        types.InlineKeyboardButton("💳 充值", callback_data="redeem")
    )
    if is_admin(uid):
        kb.add(types.InlineKeyboardButton("🔧 管理", callback_data="admin"))
    return kb

def admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ 加钱", callback_data="addbal"),
        types.InlineKeyboardButton("➖ 扣钱", callback_data="deductbal")
    )
    kb.add(
        types.InlineKeyboardButton("📛 制卡", callback_data="gencard"),
        types.InlineKeyboardButton("📊 用户", callback_data="userlist")
    )
    kb.add(
        types.InlineKeyboardButton("📢 广播", callback_data="broadcast"),
        types.InlineKeyboardButton("🔙 返回", callback_data="back")
    )
    return kb

def file_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义名称", callback_data="custom"),
        types.InlineKeyboardButton("❌ 原文件名", callback_data="original")
    )
    return kb

# ====================== /start ======================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    bot.send_message(msg.chat.id, "✅ 机器人已启动\n💸 1万行数据扣费4元", reply_markup=main_menu(uid))

# ====================== 按钮回调 ======================
@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.id
    act = call.data
    bot.answer_callback_query(call.id)

    user = get_user(uid)

    if act == "switch":
        user['mode'] = "VCF" if user['mode']=="TXT" else "TXT"
        bot.edit_message_text("✅ 模式已切换", cid, mid, reply_markup=main_menu(uid))

    elif act == "setlines":
        bot.send_message(cid, "✏️ 输入每个文件行数：")
        bot.register_next_step_handler(call.message, lambda m: set_lines(m, uid))

    elif act == "balance":
        bot.edit_message_text(f"💰 余额：{user['balance']} 元", cid, mid, reply_markup=main_menu(uid))

    elif act == "redeem":
        bot.send_message(cid, "💳 输入卡密：")
        bot.register_next_step_handler(call.message, lambda m: redeem(m, uid))

    elif act == "admin" and is_admin(uid):
        bot.edit_message_text("🔧 管理员面板", cid, mid, reply_markup=admin_menu())

    elif act == "back":
        bot.edit_message_text("✅ 主菜单", cid, mid, reply_markup=main_menu(uid))

    elif act == "custom":
        bot.send_message(cid, "✏️ 输入前缀：")
        bot.register_next_step_handler(call.message, lambda m: go_file(m, uid, custom=True))

    elif act == "original":
        go_file(None, uid, custom=False)

# ====================== 逻辑 ======================
def set_lines(msg, uid):
    try:
        n = int(msg.text)
        get_user(uid)['split_lines'] = n
        bot.send_message(msg.chat.id, f"✅ 已设为 {n} 行", reply_markup=main_menu(uid))
    except:
        bot.send_message(msg.chat.id, "❌ 输入数字")

def redeem(msg, uid):
    card = msg.text.strip()
    user = get_user(uid)
    if card in cards and not cards[card]['used']:
        user['balance'] += cards[card]['amount']
        cards[card]['used'] = True
        bot.send_message(msg.chat.id, "✅ 充值成功", reply_markup=main_menu(uid))
    else:
        bot.send_message(msg.chat.id, "❌ 卡密无效", reply_markup=main_menu(uid))

# ====================== 文件处理 ======================
@bot.message_handler(content_types=['document'])
def on_file(msg):
    uid = msg.from_user.id
    user = get_user(uid)
    try:
        f = bot.get_file(msg.document.file_id)
        data = bot.download_file(f.file_path)
        name = msg.document.file_name.rsplit('.',1)[0]

        content = ""
        if msg.document.file_name.endswith('.txt'):
            content = data.decode('utf-8', 'ignore')
        elif msg.document.file_name.endswith('.zip'):
            with zipfile.ZipFile(BytesIO(data)) as z:
                for fn in z.namelist():
                    if fn.endswith('.txt'):
                        content += z.read(fn).decode('utf-8','ignore')+'\n'

        lines = len(content.splitlines())
        fee = calculate_fee(lines)

        if user['balance'] < fee:
            bot.send_message(msg.chat.id, f"❌ 需扣费 {fee} 元，余额不足")
            return

        user_session[uid] = {"c":content, "n":name, "fee":fee}
        bot.send_message(msg.chat.id, f"✅ 需扣费 {fee} 元", reply_markup=file_menu())
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 错误：{e}")

def go_file(msg, uid, custom):
    if uid not in user_session: return
    d = user_session[uid]
    del user_session[uid]
    cid = msg.chat.id if msg else None

    user = get_user(uid)
    user['balance'] -= d['fee']

    prefix = msg.text.strip() if custom else d['n']
    mode = user['mode']
    step = user['split_lines']
    content = d['c']

    files = []
    if mode == "TXT":
        lines = content.splitlines()
        for i in range(0, len(lines), step):
            b = BytesIO("\n".join(lines[i:i+step]).encode())
            b.name = f"{prefix}_{i//step+1}.txt"
            files.append(b)
    else:
        phones = re.findall(r'1[3-9]\d{9}', content)
        for i in range(0, len(phones), step):
            vcf = ""
            for p in phones[i:i+step]:
                vcf += f"BEGIN:VCARD\nFN:{random_name()}\nTEL:{p}\nEND:VCARD\n"
            b = BytesIO(vcf.encode())
            b.name = f"{prefix}_{i//step+1}.vcf"
            files.append(b)

    if cid:
        bot.send_message(cid, f"✅ 已扣费 {d['fee']} 元")
        for f in files:
            bot.send_document(cid, f)
            time.sleep(0.5)

# ====================== 启动 ======================
def run_web():
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("✅ 机器人启动")
    bot.infinity_polling(skip_pending=True)
