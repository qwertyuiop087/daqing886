import os
import re
import zipfile
import random
import time
from io import BytesIO
from telebot import TeleBot, types

# ========== 配置 ==========
BOT_TOKEN = "8511432045:AAH3vlvLLuSlRkpHyNF5d6uIQPfiCSQzYVs"
bot = TeleBot(BOT_TOKEN)
admins = [7793291484]

# ========== 存储 ==========
users = {}
cards = {}

FIRST_NAMES = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "军", "洋", "勇"]

def get_user(user_id):
    if user_id not in users:
        users[user_id] = {"balance": 10, "mode": "TXT", "split_lines": 100, "username": ""}
    u = users[user_id]
    u["username"] = f"@{bot.get_chat(user_id).username}" if bot.get_chat(user_id).username else f"user{user_id}"
    return u

def is_admin(user_id):
    return user_id in admins

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

# ---------------------- 按钮菜单 ----------------------
def main_menu(user_id):
    user = get_user(user_id)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📂 切换模式", "📏 设置分包行数")
    kb.row("💰 我的余额", "💳 卡密充值")
    if is_admin(user_id):
        kb.row("🔧 管理员面板")
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ 增加余额", "➖ 扣除余额")
    kb.row("📛 生成卡密", "📢 全员广播")
    kb.row("📊 用户余额列表", "🔙 返回主菜单")
    return kb

# ---------------------- 菜单 ----------------------
@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.from_user.id)
    bot.send_message(msg.chat.id, "✅ 机器人已启动", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🔙 返回主菜单")
def back(msg):
    bot.send_message(msg.chat.id, "主菜单", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📂 切换模式")
def switch_mode(msg):
    user = get_user(msg.from_user.id)
    user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
    bot.send_message(msg.chat.id, f"✅ 已切换：{user['mode']}", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📏 设置分包行数")
def set_lines(msg):
    ask = bot.send_message(msg.chat.id, "输入分包行数：")
    bot.register_next_step_handler(ask, set_lines_ok)

def set_lines_ok(msg):
    try:
        get_user(msg.from_user.id)["split_lines"] = int(msg.text)
        bot.send_message(msg.chat.id, "✅ 设置成功", reply_markup=main_menu(msg.from_user.id))
    except:
        bot.send_message(msg.chat.id, "❌ 输入数字", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "💰 我的余额")
def balance(msg):
    bot.send_message(msg.chat.id, f"💰 余额：{get_user(msg.from_user.id)['balance']}", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "💳 卡密充值")
def redeem(msg):
    ask = bot.send_message(msg.chat.id, "输入卡密：")
    bot.register_next_step_handler(ask, redeem_ok)

def redeem_ok(msg):
    c = msg.text.strip()
    user = get_user(msg.from_user.id)
    if c not in cards or cards[c]["used"]:
        bot.send_message(msg.chat.id, "❌ 卡密无效/已使用", reply_markup=main_menu(msg.from_user.id))
        return
    cards[c]["used"] = True
    user["balance"] += 1
    bot.send_message(msg.chat.id, "✅ 充值成功 +1", reply_markup=main_menu(msg.from_user.id))

# ---------------------- 管理员 ----------------------
@bot.message_handler(func=lambda m: m.text == "🔧 管理员面板")
def admin(msg):
    if is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "管理员面板", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "📊 用户余额列表")
def user_list(msg):
    if not is_admin(msg.from_user.id): return
    res = "📊 用户余额列表\n\n"
    for uid, u in users.items():
        res += f"{u['username']} | {uid} | 余额：{u['balance']}\n"
    bot.send_message(msg.chat.id, res, reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "➕ 增加余额")
def add(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "格式：ID 金额")
    bot.register_next_step_handler(ask, add_ok)

def add_ok(msg):
    try:
        uid, num = msg.text.split()
        get_user(int(uid))["balance"] += int(num)
        bot.send_message(msg.chat.id, "✅ 成功", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "➖ 扣除余额")
def deduct(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "格式：ID 金额")
    bot.register_next_step_handler(ask, deduct_ok)

def deduct_ok(msg):
    try:
        uid, num = msg.text.split()
        get_user(int(uid))["balance"] -= int(num)
        bot.send_message(msg.chat.id, "✅ 成功", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "📛 生成卡密")
def gen(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "生成数量：")
    bot.register_next_step_handler(ask, gen_ok)

def gen_ok(msg):
    try:
        res = []
        for i in range(int(msg.text)):
            c = f"CARD{int(time.time())}{i}"
            cards[c] = {"used": False}
            res.append(c)
        bot.send_message(msg.chat.id, "\n".join(res), reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 数字", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "📢 全员广播")
def broadcast(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "内容：")
    bot.register_next_step_handler(ask, broadcast_ok)

def broadcast_ok(msg):
    for uid in users:
        try: bot.send_message(uid, msg.text)
        except: pass
    bot.send_message(msg.chat.id, "✅ 完成", reply_markup=admin_menu())

# ---------------------- 文件处理 ----------------------
session = {}

@bot.message_handler(content_types=["document"])
def file(msg):
    user = get_user(msg.from_user.id)
    if user["balance"] < 1:
        bot.send_message(msg.chat.id, "❌ 余额不足", reply_markup=main_menu(msg.from_user.id))
        return

    file = bot.get_file(msg.document.file_id)
    data = bot.download_file(file.file_path)
    fname = msg.document.file_name

    try:
        if fname.lower().endswith(".zip"):
            zf = zipfile.ZipFile(BytesIO(data))
            content = ""
            for f in zf.namelist():
                if f.lower().endswith(".txt"):
                    content += zf.read(f).decode("utf-8","ignore")+"\n"
        elif fname.lower().endswith(".txt"):
            content = data.decode("utf-8","ignore")
        else:
            bot.send_message(msg.chat.id, "❌ 仅支持 TXT/ZIP")
            return
    except:
        bot.send_message(msg.chat.id, "❌ 文件读取失败")
        return

    original_name = fname.rsplit(".",1)[0]
    session[msg.from_user.id] = {
        "content": content,
        "mode": user["mode"],
        "lines": user["split_lines"],
        "original": original_name
    }

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("是", "否")
    ask = bot.send_message(msg.chat.id, "📛 是否自定义文件名？", reply_markup=kb)
    bot.register_next_step_handler(ask, ask_name)

def ask_name(msg):
    s = session.get(msg.from_user.id)
    if not s: return
    if msg.text not in ["是","否"]:
        bot.send_message(msg.chat.id, "请按按钮选择")
        bot.register_next_step_handler(msg, ask_name)
        return

    if msg.text == "是":
        ask = bot.send_message(msg.chat.id, "输入基础文件名：", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(ask, go_custom)
    else:
        go_default(msg)

def go_custom(msg):
    s = session.pop(msg.from_user.id,None)
    if not s: return
    process(msg, s["content"], s["mode"], s["lines"], msg.text.strip())

def go_default(msg):
    s = session.pop(msg.from_user.id,None)
    if not s: return
    process(msg, s["content"], s["mode"], s["lines"], s["original"])

def process(msg, content, mode, lines, base):
    user = get_user(msg.from_user.id)
    user["balance"] -= 1
    files = []

    if mode == "TXT":
        lines_all = content.splitlines()
        chunks = [lines_all[i:i+lines] for i in range(0,len(lines_all),lines)]
        for i,c in enumerate(chunks,1):
            b = BytesIO("\n".join(c).encode("utf-8"))
            b.name = f"{base}_{i}.txt"
            files.append(b)
    else:
        phones = re.findall(r"1[3-9]\d{9}", content)
        vcf = ""
        for p in phones:
            vcf += f"BEGIN:VCARD\nVERSION:3.0\nFN:{random_name()}\nTEL:{p}\nEND:VCARD\n"
        chunks = [vcf[i:i+lines*500] for i in range(0,len(vcf),lines*500)]
        for i,c in enumerate(chunks,1):
            b = BytesIO(c.encode("utf-8"))
            b.name = f"{base}_{i}.vcf"
            files.append(b)

    bot.send_message(msg.chat.id, f"✅ 生成 {len(files)} 个", reply_markup=main_menu(msg.from_user.id))
    batch = []
    for f in files:
        batch.append(f)
        if len(batch) == 10:
            send_batch(msg.chat.id, batch)
            batch = []
            time.sleep(3)
    if batch:
        send_batch(msg.chat.id, batch)
    bot.send_message(msg.chat.id, "✅ 全部发送完成")

def send_batch(chat_id, files):
    for f in files:
        bot.send_document(chat_id, f)
        time.sleep(0.5)

if __name__ == "__main__":
    print("✅ 运行中")
    bot.infinity_polling()
