import os
import re
import zipfile
import random
import time
import threading
from io import BytesIO
from telebot import TeleBot, types
from flask import Flask

# ====================== 你的配置 ======================
BOT_TOKEN = "8511432045:AAGjwjpk_VHUeNH4hsNX3DVNdTmfV2NoA3A"
ADMIN_ID = 7793291484
# ======================================================

PORT = int(os.environ.get("PORT", 10000))
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Bot Running ✅", 200

bot = TeleBot(BOT_TOKEN)

users = {}
cards = {}
file_session = {}

FIRST_NAMES = ["李", "王", "张", "刘", "陈"]
LAST_NAMES = ["伟", "芳", "强", "磊", "军"]

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

# ====================== 回调 ======================
@bot.message_handler(commands=['start'])
def start_handler(msg):
    uid = msg.from_user.id
    get_user(uid)
    bot.send_message(msg.chat.id, "✅ 机器人已就绪\n💸 1万行扣4元", reply_markup=main_menu(uid))

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        act = call.data
        bot.answer_callback_query(call.id, text="处理中...")

        if act == "switch_mode":
            user = get_user(uid)
            user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
            bot.edit_message_text(f"✅ 模式：{user['mode']}", cid, call.message.id, reply_markup=main_menu(uid))

        elif act == "set_lines":
            bot.send_message(cid, "✏️ 输入行数：")
            bot.register_next_step_handler(call.message, set_lines_handler, uid)

        elif act == "show_balance":
            user = get_user(uid)
            bot.edit_message_text(f"💰 余额：{user['balance']} 元", cid, call.message.id, reply_markup=main_menu(uid))

        elif act == "redeem_card":
            bot.send_message(cid, "💳 输入卡密：")
            bot.register_next_step_handler(call.message, redeem_card_handler, uid)

        elif act == "admin_panel":
            bot.edit_message_text("🔧 管理员面板", cid, call.message.id, reply_markup=admin_menu())

        elif act == "add_balance":
            bot.send_message(cid, "➕ 用户ID 金额：")
            bot.register_next_step_handler(call.message, add_balance_handler)
        elif act == "deduct_balance":
            bot.send_message(cid, "➖ 用户ID 金额：")
            bot.register_next_step_handler(call.message, deduct_balance_handler)
        elif act == "gen_card":
            bot.send_message(cid, "📛 数量 金额：")
            bot.register_next_step_handler(call.message, gen_card_handler)
        elif act == "user_list":
            txt = "📊 用户:\n"
            for u, d in users.items(): txt += f"{u} → {d['balance']}元\n"
            bot.send_message(cid, txt)
        elif act == "broadcast":
            bot.send_message(cid, "📢 广播内容：")
            bot.register_next_step_handler(call.message, broadcast_handler)
        elif act == "back_main":
            bot.edit_message_text("✅ 主菜单", cid, call.message.id, reply_markup=main_menu(uid))

        elif act.startswith("origin_name_"):
            uid = int(act.split("_")[-1])
            if uid in file_session:
                s = file_session[uid]
                generate_and_send_files(cid, uid, s, s["filename"])
                del file_session[uid]
        elif act.startswith("custom_name_"):
            uid = int(act.split("_")[-1])
            bot.send_message(cid, "✏️ 输入前缀：")
            bot.register_next_step_handler(call.message, custom_name_handler, uid)

    except Exception as e:
        bot.send_message(cid, f"❌ 错误：{e}")

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

        lines = len(content.splitlines())
        fee = calculate_fee(lines)
        if user["balance"] < fee:
            bot.send_message(cid, f"❌ 需{fee}元，余额不足")
            return

        file_session[uid] = {
            "content": content,
            "filename": name,
            "fee": fee,
            "split_lines": user["split_lines"],
            "mode": user["mode"]
        }
        bot.send_message(cid, f"✅ 需扣{fee}元", reply_markup=file_name_menu(uid))
    except Exception as e:
        bot.send_message(cid, f"❌ 错误：{e}")

# ====================== 发送逻辑：10个一批，休息3秒 ======================
def generate_and_send_files(cid, uid, session, prefix):
    try:
        user = get_user(uid)
        user["balance"] -= session["fee"]

        content = session["content"]
        step = session["split_lines"]
        mode = session["mode"]

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
        bot.send_message(cid, f"✅ 已扣费，共{total}个文件，10个一批发送")

        # 一次发10个，每批休息3秒
        batch_size = 10
        for i in range(0, total, batch_size):
            batch = files[i:i+batch_size]
            for f in batch:
                bot.send_document(cid, f)
                time.sleep(0.3)
            # 一批发完，休息3秒
            if i + batch_size < total:
                bot.send_message(cid, "⏸ 休息3秒继续发送")
                time.sleep(3)

        bot.send_message(cid, f"✅ 全部发送完成！余额：{user['balance']}")
    except Exception as e:
        bot.send_message(cid, f"❌ 发送失败：{e}")

# ====================== 其他函数 ======================
def custom_name_handler(msg, uid):
    if uid in file_session:
        generate_and_send_files(msg.chat.id, uid, file_session[uid], msg.text.strip())
        del file_session[uid]

def set_lines_handler(msg, uid):
    try:
        get_user(uid)["split_lines"] = int(msg.text)
        bot.send_message(msg.chat.id, "✅ 设置成功")
    except:
        bot.send_message(msg.chat.id, "❌ 输入数字")

def redeem_card_handler(msg, uid):
    c = msg.text.strip()
    if c in cards and not cards[c]["used"]:
        get_user(uid)["balance"] += cards[c]["amount"]
        cards[c]["used"] = True
        bot.send_message(msg.chat.id, "✅ 充值成功")
    else:
        bot.send_message(msg.chat.id, "❌ 无效卡密")

def add_balance_handler(msg):
    try:
        u, a = msg.text.split()
        get_user(int(u))["balance"] += int(a)
        bot.send_message(msg.chat.id, "✅ 成功")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def deduct_balance_handler(msg):
    try:
        u, a = msg.text.split()
        get_user(int(u))["balance"] -= int(a)
        bot.send_message(msg.chat.id, "✅ 成功")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def gen_card_handler(msg):
    try:
        n, a = msg.text.split()
        res = []
        for _ in range(int(n)):
            code = f"K{random.randint(100000,999999)}"
            cards[code] = {"used":False,"amount":int(a)}
            res.append(code)
        bot.send_message(msg.chat.id, "\n".join(res))
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def broadcast_handler(msg):
    cnt = 0
    for u in users:
        try:
            bot.send_message(u, f"📢 {msg.text}")
            cnt +=1
        except:
            pass
    bot.send_message(msg.chat.id, f"✅ 发送完成 {cnt} 人")

# ====================== 启动 ======================
def run_web():
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
