import os
import re
import zipfile
import random
import time
from io import BytesIO
from telebot import TeleBot, types

# ====================== 你的配置 ======================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 7793291484
# ======================================================

user_file = {}
users = {}
cards = {}

# ====================== 基础函数 ======================
def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0, "mode": "TXT", "split_lines": 100}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

def random_name():
    first = ["李", "王", "张", "刘", "陈"]
    last = ["伟", "芳", "强", "磊", "军"]
    return random.choice(first) + random.choice(last)

# ====================== 菜单生成 ======================
def main_menu(uid):
    user = get_user(uid)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(f"📂 模式：{user['mode']}", callback_data="switch_mode"),
        types.InlineKeyboardButton(f"📏 行数：{user['split_lines']}", callback_data="set_lines")
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
    kb.add(types.InlineKeyboardButton("📥 批量加余额", callback_data="batch_add_bal"))
    return kb

def file_name_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义名称", callback_data="file_custom"),
        types.InlineKeyboardButton("❌ 原文件名", callback_data="file_original")
    )
    return kb

# ====================== 机器人初始化 ======================
bot = TeleBot(BOT_TOKEN, skip_pending=True)

# ====================== 启动命令 ======================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    bot.send_message(msg.chat.id, "✅ 机器人已启动", reply_markup=main_menu(uid))

# ====================== 统一回调处理（核心修复） ======================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        mid = call.message.id
        act = call.data
        # 必须先响应回调，避免按钮转圈
        bot.answer_callback_query(call.id, text="处理中...", show_alert=False)

        # 权限检查
        admin_actions = ["addbal", "deductbal", "gencard", "userlist", "broadcast", "batch_add_bal"]
        if not is_admin(uid) and act in admin_actions:
            bot.send_message(cid, "❌ 无管理员权限")
            return

        # 主菜单功能
        if act == "switch_mode":
            user = get_user(uid)
            user['mode'] = "VCF" if user['mode'] == "TXT" else "TXT"
            bot.edit_message_text("✅ 模式已切换", cid, mid, reply_markup=main_menu(uid))

        elif act == "set_lines":
            bot.send_message(cid, "✏️ 输入每个文件行数：")
            bot.register_next_step_handler(call.message, lambda m: set_lines(m, uid))

        elif act == "balance":
            user = get_user(uid)
            bot.edit_message_text(f"💰 余额：{user['balance']} 元", cid, mid, reply_markup=main_menu(uid))

        elif act == "redeem":
            bot.send_message(cid, "💳 输入卡密：")
            bot.register_next_step_handler(call.message, lambda m: redeem(m, uid))

        elif act == "admin":
            bot.edit_message_text("🔧 管理员面板", cid, mid, reply_markup=admin_menu())

        elif act == "back":
            bot.edit_message_text("✅ 主菜单", cid, mid, reply_markup=main_menu(uid))

        # 管理员功能
        elif act == "addbal":
            bot.send_message(cid, "➕ 格式：用户ID 金额")
            bot.register_next_step_handler(call.message, add_balance)

        elif act == "deductbal":
            bot.send_message(cid, "➖ 格式：用户ID 金额")
            bot.register_next_step_handler(call.message, deduct_balance)

        elif act == "gencard":
            bot.send_message(cid, "📛 格式：数量 金额")
            bot.register_next_step_handler(call.message, gen_card)

        elif act == "userlist":
            txt = "📊 用户列表\n"
            for u in users:
                txt += f"{u} → {users[u]['balance']}元\n"
            bot.send_message(cid, txt)

        elif act == "broadcast":
            bot.send_message(cid, "📢 输入广播内容：")
            bot.register_next_step_handler(call.message, broadcast)

        elif act == "batch_add_bal":
            bot.send_message(cid, "📥 格式：\n用户ID 金额\n用户ID 金额")
            bot.register_next_step_handler(call.message, batch_add_balance)

        # ====================== 核心修复：文件按钮回调 ======================
        elif act == "file_custom" or act == "file_original":
            if uid not in user_file:
                bot.send_message(cid, "❌ 请先上传文件")
                return
            
            session = user_file[uid]
            del user_file[uid]  # 清理会话，避免重复

            if act == "file_custom":
                bot.send_message(cid, "✏️ 输入文件名前缀：")
                bot.register_next_step_handler(call.message, lambda m: process_file(m, uid, session, m.text.strip()))
            else:
                process_file(None, uid, session, session["filename"])

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ 操作失败：{str(e)}")
        print(f"回调错误：{e}")

# ====================== 功能实现 ======================
def set_lines(msg, uid):
    try:
        n = int(msg.text)
        get_user(uid)['split_lines'] = n
        bot.send_message(msg.chat.id, f"✅ 已设为 {n} 行")
    except:
        bot.send_message(msg.chat.id, "❌ 输入有效数字")

def redeem(msg, uid):
    card = msg.text.strip()
    user = get_user(uid)
    if card in cards and not cards[card]['used']:
        user['balance'] += cards[card]['amount']
        cards[card]['used'] = True
        bot.send_message(msg.chat.id, "✅ 充值成功")
    else:
        bot.send_message(msg.chat.id, "❌ 卡密无效")

def add_balance(msg):
    try:
        uid, amt = msg.text.split()
        get_user(int(uid))['balance'] += int(amt)
        bot.send_message(msg.chat.id, "✅ 成功")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def deduct_balance(msg):
    try:
        uid, amt = msg.text.split()
        get_user(int(uid))['balance'] -= int(amt)
        bot.send_message(msg.chat.id, "✅ 成功")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def gen_card(msg):
    try:
        cnt, amt = msg.text.split()
        res = []
        for i in range(int(cnt)):
            code = f"Card{random.randint(100000,999999)}"
            cards[code] = {"used":False, "amount":int(amt)}
            res.append(code)
        bot.send_message(msg.chat.id, "\n".join(res))
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误")

def broadcast(msg):
    ok = 0
    for u in users:
        try:
            bot.send_message(u, f"📢 广播\n{msg.text}")
            ok +=1
        except:
            pass
    bot.send_message(msg.chat.id, f"✅ 发送完成 {ok} 人")

def batch_add_balance(msg):
    lines = msg.text.strip().splitlines()
    success = 0
    fail = 0
    for line in lines:
        try:
            uid, amt = line.split()
            get_user(int(uid))['balance'] += int(amt)
            success +=1
        except:
            fail +=1
    bot.send_message(msg.chat.id, f"✅ 批量完成：成功 {success} 人，失败 {fail} 人")

# ====================== 文件处理（无空行 + 按钮修复） ======================
@bot.message_handler(content_types=['document'])
def on_file(msg):
    uid = msg.from_user.id
    user = get_user(uid)
    try:
        # 清理旧会话
        if uid in user_file:
            del user_file[uid]

        # 读取文件
        f = bot.get_file(msg.document.file_id)
        data = bot.download_file(f.file_path)
        filename = msg.document.file_name.rsplit('.',1)[0]
        content = ""

        # 解析TXT/ZIP
        if msg.document.file_name.lower().endswith('.txt'):
            content = data.decode('utf-8','ignore')
        elif msg.document.file_name.lower().endswith('.zip'):
            with zipfile.ZipFile(BytesIO(data)) as zf:
                for fn in zf.namelist():
                    if fn.lower().endswith('.txt'):
                        content += z.read(fn).decode('utf-8','ignore')

        # ✅ 彻底清理空行、空格
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        content = "\n".join(lines)
        lines_count = len(lines)

        # 计算扣费
        fee = (lines_count + 9999) // 10000 * 4
        if user['balance'] < fee:
            bot.send_message(msg.chat.id, f"❌ 需扣费 {fee} 元，余额不足")
            return

        # 保存会话
        user_file[uid] = {
            "content": content,
            "filename": filename,
            "fee": fee,
            "mode": user['mode'],
            "split_lines": user['split_lines']
        }

        # 发送文件选择菜单
        bot.send_message(
            msg.chat.id,
            f"✅ 需扣费 {fee} 元",
            reply_markup=file_name_menu()
        )

    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 文件处理失败：{str(e)}")
        print(f"文件错误：{e}")

# ====================== 文件分包发送 ======================
def process_file(msg, uid, session, prefix):
    cid = msg.chat.id if msg else None
    try:
        user = get_user(uid)
        # 扣费
        user['balance'] -= session['fee']

        content = session['content']
        split_lines = session['split_lines']
        mode = session['mode']
        files = []

        # TXT模式分包
        if mode == "TXT":
            lines = content.splitlines()
            for i in range(0, len(lines), split_lines):
                chunk = lines[i:i+split_lines]
                bio = BytesIO("\n".join(chunk).encode('utf-8'))
                bio.name = f"{prefix}_{i//split_lines+1}.txt"
                files.append(bio)
        # VCF模式分包
        else:
            phones = re.findall(r"1[3-9]\d{9}", content)
            for i in range(0, len(phones), split_lines):
                vcf_content = ""
                for p in phones[i:i+split_lines]:
                    vcf_content += f"BEGIN:VCARD\nVERSION:3.0\nFN:{random_name()}\nTEL;TYPE=CELL:{p}\nEND:VCARD\n"
                bio = BytesIO(vcf_content.encode('utf-8'))
                bio.name = f"{prefix}_{i//split_lines+1}.vcf"
                files.append(bio)

        # 批量发送（10个一批）
        total = len(files)
        bot.send_message(cid, f"✅ 共 {total} 个文件，10个一批发送")

        batch_size = 10
        for i in range(0, total, batch_size):
            batch = files[i:i+batch_size]
            for f in batch:
                bot.send_document(cid, f)
                time.sleep(0.2)
            if i + batch_size < total:
                time.sleep(3)

        bot.send_message(cid, f"✅ 全部发送完成！当前余额：{user['balance']} 元")

    except Exception as e:
        bot.send_message(cid, f"❌ 发送失败：{str(e)}")
        print(f"发送错误：{e}")

# ====================== 启动机器人 ======================
if __name__ == "__main__":
    print("✅ 机器人启动中...")
    bot.infinity_polling(skip_pending=True)
