
# Flask 保活
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running", 200

# 机器人初始化（最稳定版本）
bot = TeleBot(BOT_TOKEN, skip_pending=True)

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

# ====================== 菜单 ======================
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
    # 批量加余额（你要的功能）
    kb.add(types.InlineKeyboardButton("📥 批量加余额", callback_data="batch_add_bal"))
    return kb

# ====================== 回调 ======================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    bot.send_message(msg.chat.id, "✅ 机器人已启动", reply_markup=main_menu(uid))

@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        mid = call.message.id
        act = call.data
        bot.answer_callback_query(call.id)

        # 权限检查
        if not is_admin(uid) and act in ["addbal","deductbal","gencard","userlist","broadcast","batch_add_bal"]:
            bot.send_message(cid, "❌ 无权限")
            return

        # 主菜单
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

        # 批量加余额（你要的功能）
        elif act == "batch_add_bal":
            bot.send_message(cid, "📥 格式：用户ID1 金额\n用户ID2 金额\n...")
            bot.register_next_step_handler(call.message, batch_add_balance)

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ 错误：{e}")

# ====================== 功能实现 ======================
def set_lines(msg, uid):
    try:
        n = int(msg.text)
        get_user(uid)['split_lines'] = n
        bot.send_message(msg.chat.id, f"✅ 已设为 {n} 行")
    except:
        bot.send_message(msg.chat.id, "❌ 输入数字")

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
        uid = int(uid)
        amt = int(amt)
        get_user(uid)['balance'] += amt
        bot.send_message(msg.chat.id, f"✅ 成功给 {uid} 加 {amt} 元")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误：用户ID 金额")

def deduct_balance(msg):
    try:
        uid, amt = msg.text.split()
        uid = int(uid)
        amt = int(amt)
        get_user(uid)['balance'] -= amt
        bot.send_message(msg.chat.id, f"✅ 成功给 {uid} 扣 {amt} 元")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误：用户ID 金额")

def gen_card(msg):
    try:
        cnt, amt = msg.text.split()
        cnt = int(cnt)
        amt = int(amt)
        res = []
        for i in range(cnt):
            code = f"Card{random.randint(100000,999999)}"
            cards[code] = {"used":False, "amount":amt}
            res.append(f"{code} → {amt}元")
        bot.send_message(msg.chat.id, "\n".join(res))
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误：数量 金额")

def broadcast(msg):
    text = msg.text
    ok = 0
    for u in users:
        try:
            bot.send_message(u, f"📢 广播\n{text}")
            ok +=1
        except:
            continue
    bot.send_message(msg.chat.id, f"✅ 发送完成：{ok} 人")

# 批量加余额（完整功能）
def batch_add_balance(msg):
    lines = msg.text.strip().splitlines()
    success = 0
    fail = 0
    for line in lines:
        try:
            uid, amt = line.split()
            uid = int(uid)
            amt = int(amt)
            get_user(uid)['balance'] += amt
            success +=1
        except:
            fail +=1
    bot.send_message(msg.chat.id, f"✅ 批量加余额完成：成功 {success} 人，失败 {fail} 人")

# ====================== 文件处理（彻底修复） ======================
@bot.message_handler(content_types=['document'])
def on_file(msg):
    uid = msg.from_user.id
    user = get_user(uid)
    try:
        # 清理旧数据（关键！防止卡死）
        if uid in user_file:
            del user_file[uid]

        f = bot.get_file(msg.document.file_id)
        data = bot.download_file(f.file_path)
        name = msg.document.file_name.rsplit('.',1)[0]
        content = ""
        if msg.document.file_name.endswith('.txt'):
            content = data.decode('utf-8','ignore')
        elif msg.document.file_name.endswith('.zip'):
            with zipfile.ZipFile(BytesIO(data)) as z:
                for fn in z.namelist():
                    if fn.endswith('.txt'):
                        content += z.read(fn).decode('utf-8','ignore')+'\n'
        lines = len(content.splitlines())
        fee = (lines + 9999) // 10000 * 4
        if user['balance'] < fee:
            bot.send_message(msg.chat.id, f"❌ 需扣费 {fee} 元，余额不足")
            return
        user_file[uid] = {"c":content,"n":name,"fee":fee}
        bot.send_message(msg.chat.id, f"✅ 需扣费 {fee} 元", reply_markup=file_menu())
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 错误：{e}")

def file_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义名称", callback_data="custom"),
        types.InlineKeyboardButton("❌ 原文件名", callback_data="original")
    )
    return kb

# ====================== 启动 ======================
def run_web():
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(skip_pending=True)
