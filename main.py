import os
import re
import zipfile
import random
import time
from io import BytesIO
from telebot import TeleBot, types

# ========== 直接把你的机器人TOKEN写在这里 ==========
BOT_TOKEN = "8511432045:AAH3vlvLLuSlRkpHyNF5d6uIQPfiCSQzYVs"

bot = TeleBot(BOT_TOKEN)

# ========== 数据存储 ==========
users = {}
cards = {}
admins = [7793291484]  # 改成你自己的 TG ID

# ========== 随机姓名库 ==========
FIRST_NAMES = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "军", "洋", "勇"]

# ========== 用户工具 ==========
def get_user(user_id):
    if user_id not in users:
        users[user_id] = {"balance": 10, "mode": "TXT", "split_lines": 100}
    return users[user_id]

def is_admin(user_id):
    return user_id in admins

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

# ========== 主菜单按钮 ==========
def main_menu(user_id):
    user = get_user(user_id)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    b1 = types.KeyboardButton(f"📂 模式：{user['mode']}")
    b2 = types.KeyboardButton(f"📏 分包行数({user['split_lines']})")
    b3 = types.KeyboardButton("💰 我的余额")
    b4 = types.KeyboardButton("💳 卡密充值")
    kb.add(b1, b2)
    kb.add(b3, b4)
    if is_admin(user_id):
        kb.add(types.KeyboardButton("🔧 管理员面板"))
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ 单加余额", "➖ 扣除余额")
    kb.add("📛 生成卡密", "📢 全员广播")
    kb.add("🔙 返回主菜单")
    return kb

# ========== 启动 ==========
@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.from_user.id)
    bot.send_message(msg.chat.id, "✅ 机器人已启动", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🔙 返回主菜单")
def back(msg):
    bot.send_message(msg.chat.id, "🔙 主菜单", reply_markup=main_menu(msg.from_user.id))

# ========== 切换模式 ==========
@bot.message_handler(func=lambda m: m.text and m.text.startswith("📂 模式"))
def switch_mode(msg):
    user = get_user(msg.from_user.id)
    user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
    bot.send_message(msg.chat.id, f"✅ 已切换：{user['mode']}", reply_markup=main_menu(msg.from_user.id))

# ========== 设置行数 ==========
@bot.message_handler(func=lambda m: m.text and m.text.startswith("📏 分包行数"))
def set_lines(msg):
    ask = bot.send_message(msg.chat.id, "✏️ 输入每个文件行数：")
    bot.register_next_step_handler(ask, set_lines_done)

def set_lines_done(msg):
    try:
        num = int(msg.text)
        get_user(msg.from_user.id)["split_lines"] = num
        bot.send_message(msg.chat.id, f"✅ 已设置：{num}行", reply_markup=main_menu(msg.from_user.id))
    except:
        bot.send_message(msg.chat.id, "❌ 请输入数字", reply_markup=main_menu(msg.from_user.id))

# ========== 余额 / 充值 ==========
@bot.message_handler(func=lambda m: m.text == "💰 我的余额")
def show_balance(msg):
    bal = get_user(msg.from_user.id)["balance"]
    bot.send_message(msg.chat.id, f"💰 余额：{bal}", reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "💳 卡密充值")
def redeem(msg):
    ask = bot.send_message(msg.chat.id, "✏️ 输入卡密：")
    bot.register_next_step_handler(ask, redeem_done)

def redeem_done(msg):
    card = msg.text.strip()
    user = get_user(msg.from_user.id)
    if card not in cards:
        bot.send_message(msg.chat.id, "❌ 无效卡密", reply_markup=main_menu(msg.from_user.id))
        return
    if cards[card]["used"]:
        bot.send_message(msg.chat.id, "❌ 已使用", reply_markup=main_menu(msg.from_user.id))
        return
    cards[card]["used"] = True
    user["balance"] += 1
    bot.send_message(msg.chat.id, "✅ 充值成功 +1", reply_markup=main_menu(msg.from_user.id))

# ========== 管理员 ==========
@bot.message_handler(func=lambda m: m.text == "🔧 管理员面板")
def admin_panel(msg):
    if not is_admin(msg.from_user.id): return
    bot.send_message(msg.chat.id, "🔧 管理员菜单", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "➕ 单加余额")
def add_balance(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "格式：用户ID 金额")
    bot.register_next_step_handler(ask, add_done)

def add_done(msg):
    try:
        uid, num = msg.text.split()
        get_user(int(uid))["balance"] += int(num)
        bot.send_message(msg.chat.id, "✅ 成功", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "➖ 扣除余额")
def deduct(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "格式：用户ID 金额")
    bot.register_next_step_handler(ask, deduct_done)

def deduct_done(msg):
    try:
        uid, num = msg.text.split()
        get_user(int(uid))["balance"] -= int(num)
        bot.send_message(msg.chat.id, "✅ 成功", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "📛 生成卡密")
def gen_card(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "生成数量：")
    bot.register_next_step_handler(ask, gen_done)

def gen_done(msg):
    try:
        n = int(msg.text)
        res = []
        for i in range(n):
            c = f"CARD{int(time.time())}{i}"
            cards[c] = {"used": False, "user": None}
            res.append(c)
        bot.send_message(msg.chat.id, "\n".join(res), reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 输入数字", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "📢 全员广播")
def broadcast(msg):
    if not is_admin(msg.from_user.id): return
    ask = bot.send_message(msg.chat.id, "输入广播内容：")
    bot.register_next_step_handler(ask, broadcast_send)

def broadcast_send(msg):
    for uid in users:
        try:
            bot.send_message(uid, msg.text)
        except:
            pass
    bot.send_message(msg.chat.id, "✅ 广播完成", reply_markup=admin_menu())

# ========== 文件处理 ==========
user_session = {}

@bot.message_handler(content_types=["document"])
def handle_file(msg):
    try:
        user = get_user(msg.from_user.id)
        if user["balance"] < 1:
            bot.send_message(msg.chat.id, "❌ 余额不足", reply_markup=main_menu(msg.from_user.id))
            return

        file = bot.get_file(msg.document.file_id)
        data = bot.download_file(file.file_path)
        name = msg.document.file_name.lower()
        content = ""

        if name.endswith(".zip"):
            zf = zipfile.ZipFile(BytesIO(data))
            for fname in zf.namelist():
                if fname.lower().endswith(".txt"):
                    content += zf.read(fname).decode("utf-8", errors="ignore") + "\n"
        elif name.endswith(".txt"):
            content = data.decode("utf-8", errors="ignore")
        else:
            bot.send_message(msg.chat.id, "❌ 仅支持 TXT/ZIP", reply_markup=main_menu(msg.from_user.id))
            return

        user_session[msg.from_user.id] = {
            "content": content,
            "mode": user["mode"],
            "lines": user["split_lines"]
        }

        ask = bot.send_message(msg.chat.id, "📛 是否自定义文件名？（是/否）")
        bot.register_next_step_handler(ask, ask_filename)

    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 错误：{str(e)}", reply_markup=main_menu(msg.from_user.id))

def ask_filename(msg):
    if msg.text not in ["是", "否"]:
        bot.send_message(msg.chat.id, "请输入：是 / 否")
        bot.register_next_step_handler(msg, ask_filename)
        return

    if msg.text == "是":
        ask = bot.send_message(msg.chat.id, "✏️ 输入基础名称：")
        bot.register_next_step_handler(ask, process_custom)
    else:
        process_default(msg)

def process_custom(msg):
    base = msg.text.strip()
    session = user_session.pop(msg.from_user.id, None)
    if not session: return
    process_file(msg, session["content"], session["mode"], session["lines"], base)

def process_default(msg):
    session = user_session.pop(msg.from_user.id, None)
    if not session: return
    process_file(msg, session["content"], session["mode"], session["lines"], "split")

def process_file(msg, content, mode, lines, base):
    user = get_user(msg.from_user.id)
    user["balance"] -= 1
    files = []

    if mode == "TXT":
        lines_all = content.splitlines()
        chunks = [lines_all[i:i+lines] for i in range(0, len(lines_all), lines)]
        for i, c in enumerate(chunks, 1):
            bio = BytesIO("\n".join(c).encode("utf-8"))
            bio.name = f"{base}_{i}.txt"
            files.append(bio)
    else:
        phones = re.findall(r"1[3-9]\d{9}", content)
        vcf = ""
        for p in phones:
            name = random_name()
            vcf += f"BEGIN:VCARD\nVERSION:3.0\nFN:{name}\nTEL:{p}\nEND:VCARD\n"
        chunks = [vcf[i:i+lines*500] for i in range(0, len(vcf), lines*500)]
        for i, c in enumerate(chunks, 1):
            bio = BytesIO(c.encode("utf-8"))
            bio.name = f"{base}_{i}.vcf"
            files.append(bio)

    bot.send_message(msg.chat.id, f"✅ 生成 {len(files)} 个文件，开始发送...")
    batch = []
    for f in files:
        batch.append(f)
        if len(batch) >= 10:
            send_batch(msg.chat.id, batch)
            batch = []
            time.sleep(3)
    if batch:
        send_batch(msg.chat.id, batch)
    bot.send_message(msg.chat.id, "✅ 全部发送完成！", reply_markup=main_menu(msg.from_user.id))

def send_batch(chat_id, files):
    for f in files:
        bot.send_document(chat_id, f)
        time.sleep(0.5)

# ========== 启动 ==========
if __name__ == "__main__":
    print("✅ 机器人运行中...")
    bot.infinity_polling()
