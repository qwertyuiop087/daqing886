import os
import re
import zipfile
import random
import time
from io import BytesIO
from telebot import TeleBot, types

# ========== 配置 ==========
BOT_TOKEN = "8511432045:AAH3vlvLLuSlRkpHyNF5d6uIQPfiCSQzYVs"  # 改这里
bot = TeleBot(BOT_TOKEN)
admins = [7793291484]  # 改这里

# ========== 存储 ==========
users = {}
cards = {}
user_session = {}

# ========== 随机姓名库 ==========
FIRST_NAMES = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "军", "洋", "勇"]

# ========== 工具函数 ==========
def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "balance": 10,
            "mode": "TXT",
            "split_lines": 100,
            "username": ""
        }
    try:
        chat = bot.get_chat(user_id)
        users[user_id]["username"] = chat.username if chat.username else f"用户{user_id}"
    except:
        users[user_id]["username"] = f"用户{user_id}"
    return users[user_id]

def is_admin(user_id):
    return user_id in admins

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

# ---------------------- 真正的内联按钮（点击式） ----------------------
def get_main_inline(user_id):
    """主菜单：点击式按钮"""
    user = get_user(user_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    
    # 按钮1：切换模式
    mode_btn = types.InlineKeyboardButton(
        f"📂 切换模式（当前：{user['mode']}）",
        callback_data="switch_mode"
    )
    
    # 按钮2：设置行数
    lines_btn = types.InlineKeyboardButton(
        f"📏 分包行数（{user['split_lines']}）",
        callback_data="set_lines"
    )
    
    # 按钮3：我的余额
    balance_btn = types.InlineKeyboardButton(
        "💰 我的余额",
        callback_data="show_balance"
    )
    
    # 按钮4：卡密充值
    redeem_btn = types.InlineKeyboardButton(
        "💳 卡密充值",
        callback_data="redeem_card"
    )
    
    kb.add(mode_btn, lines_btn)
    kb.add(balance_btn, redeem_btn)
    
    # 管理员额外按钮
    if is_admin(user_id):
        admin_btn = types.InlineKeyboardButton(
            "🔧 管理员面板",
            callback_data="admin_panel"
        )
        kb.add(admin_btn)
    
    return kb

def get_admin_inline():
    """管理员面板：点击式按钮"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ 增加余额", callback_data="add_balance"),
        types.InlineKeyboardButton("➖ 扣除余额", callback_data="deduct_balance")
    )
    kb.add(
        types.InlineKeyboardMarkup("📛 生成卡密", callback_data="gen_card"),
        types.InlineKeyboardButton("📊 用户余额列表", callback_data="user_list")
    )
    kb.add(
        types.InlineKeyboardButton("📢 全员广播", callback_data="broadcast"),
        types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")
    )
    return kb

def get_filename_inline():
    """文件名选择按钮"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义文件名", callback_data="custom_name"),
        types.InlineKeyboardButton("❌ 使用原文件名", callback_data="origin_name")
    )
    return kb

# ---------------------- 启动/主菜单 ----------------------
@bot.message_handler(commands=["start"])
def start(msg):
    get_user(msg.from_user.id)
    bot.send_message(
        msg.chat.id,
        "✅ 机器人已启动\n点击下方按钮操作：",
        reply_markup=get_main_inline(msg.from_user.id)
    )

# ---------------------- 按钮回调处理 ----------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # 1. 切换模式
    if call.data == "switch_mode":
        user = get_user(user_id)
        user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
        bot.edit_message_text(
            f"✅ 已切换为 {user['mode']} 模式",
            chat_id,
            call.message.message_id,
            reply_markup=get_main_inline(user_id)
        )
    
    # 2. 设置分包行数
    elif call.data == "set_lines":
        bot.send_message(chat_id, "✏️ 请输入每个文件的行数：")
        bot.register_next_step_handler(call.message, set_lines_done, user_id)
    
    # 3. 查看余额
    elif call.data == "show_balance":
        bal = get_user(user_id)["balance"]
        bot.edit_message_text(
            f"💰 你的余额：{bal}",
            chat_id,
            call.message.message_id,
            reply_markup=get_main_inline(user_id)
        )
    
    # 4. 卡密充值
    elif call.data == "redeem_card":
        bot.send_message(chat_id, "💳 请输入卡密：")
        bot.register_next_step_handler(call.message, redeem_done, user_id)
    
    # 5. 管理员面板
    elif call.data == "admin_panel":
        if is_admin(user_id):
            bot.edit_message_text(
                "🔧 管理员面板",
                chat_id,
                call.message.message_id,
                reply_markup=get_admin_inline()
            )
        else:
            bot.answer_callback_query(call.id, "❌ 你不是管理员")
    
    # 6. 返回主菜单
    elif call.data == "back_main":
        bot.edit_message_text(
            "✅ 回到主菜单",
            chat_id,
            call.message.message_id,
            reply_markup=get_main_inline(user_id)
        )
    
    # 7. 管理员：增加余额
    elif call.data == "add_balance":
        if is_admin(user_id):
            bot.send_message(chat_id, "➕ 格式：用户ID 金额（例：123456 10）")
            bot.register_next_step_handler(call.message, add_balance_done)
        else:
            bot.answer_callback_query(call.id, "❌ 无权限")
    
    # 8. 管理员：扣除余额
    elif call.data == "deduct_balance":
        if is_admin(user_id):
            bot.send_message(chat_id, "➖ 格式：用户ID 金额（例：123456 10）")
            bot.register_next_step_handler(call.message, deduct_balance_done)
        else:
            bot.answer_callback_query(call.id, "❌ 无权限")
    
    # 9. 管理员：生成卡密
    elif call.data == "gen_card":
        if is_admin(user_id):
            bot.send_message(chat_id, "📛 请输入生成卡密数量：")
            bot.register_next_step_handler(call.message, gen_card_done)
        else:
            bot.answer_callback_query(call.id, "❌ 无权限")
    
    # 10. 管理员：用户余额列表
    elif call.data == "user_list":
        if is_admin(user_id):
            res = "📊 所有用户余额列表：\n\n"
            for uid, info in users.items():
                res += f"ID：{uid} | 用户名：{info['username']} | 余额：{info['balance']}\n"
            bot.send_message(chat_id, res)
        else:
            bot.answer_callback_query(call.id, "❌ 无权限")
    
    # 11. 管理员：全员广播
    elif call.data == "broadcast":
        if is_admin(user_id):
            bot.send_message(chat_id, "📢 请输入广播内容：")
            bot.register_next_step_handler(call.message, broadcast_done)
        else:
            bot.answer_callback_query(call.id, "❌ 无权限")
    
    # 12. 文件处理：自定义文件名
    elif call.data == "custom_name":
        bot.send_message(chat_id, "✏️ 请输入自定义文件名前缀：")
        bot.register_next_step_handler(call.message, custom_name_done)
    
    # 13. 文件处理：原文件名
    elif call.data == "origin_name":
        session = user_session.get(user_id)
        if session:
            process_file(chat_id, user_id, session["content"], session["mode"], 
                         session["lines"], session["original_name"])
            del user_session[user_id]

# ---------------------- 步骤处理函数 ----------------------
def set_lines_done(msg, user_id):
    try:
        lines = int(msg.text.strip())
        get_user(user_id)["split_lines"] = lines
        bot.send_message(msg.chat.id, f"✅ 已设置分包行数：{lines}", 
                         reply_markup=get_main_inline(user_id))
    except:
        bot.send_message(msg.chat.id, "❌ 请输入有效数字！", 
                         reply_markup=get_main_inline(user_id))

def redeem_done(msg, user_id):
    card = msg.text.strip()
    user = get_user(user_id)
    if card not in cards:
        bot.send_message(msg.chat.id, "❌ 卡密无效！", 
                         reply_markup=get_main_inline(user_id))
        return
    if cards[card]["used"]:
        bot.send_message(msg.chat.id, "❌ 卡密已使用！", 
                         reply_markup=get_main_inline(user_id))
        return
    cards[card]["used"] = True
    user["balance"] += 1
    bot.send_message(msg.chat.id, "✅ 充值成功！余额+1", 
                     reply_markup=get_main_inline(user_id))

def add_balance_done(msg):
    try:
        uid, num = msg.text.strip().split()
        uid = int(uid)
        num = int(num)
        get_user(uid)["balance"] += num
        bot.send_message(msg.chat.id, f"✅ 已给用户 {uid} 增加 {num} 余额",
                         reply_markup=get_admin_inline())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误！例：123456 10",
                         reply_markup=get_admin_inline())

def deduct_balance_done(msg):
    try:
        uid, num = msg.text.strip().split()
        uid = int(uid)
        num = int(num)
        get_user(uid)["balance"] -= num
        bot.send_message(msg.chat.id, f"✅ 已扣除用户 {uid} {num} 余额",
                         reply_markup=get_admin_inline())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误！例：123456 10",
                         reply_markup=get_admin_inline())

def gen_card_done(msg):
    try:
        count = int(msg.text.strip())
        res = "📛 生成的卡密：\n\n"
        for i in range(count):
            card = f"CARD_{int(time.time())}_{i}"
            cards[card] = {"used": False}
            res += f"{card}\n"
        bot.send_message(msg.chat.id, res, reply_markup=get_admin_inline())
    except:
        bot.send_message(msg.chat.id, "❌ 请输入有效数字！",
                         reply_markup=get_admin_inline())

def broadcast_done(msg):
    content = msg.text.strip()
    success = 0
    fail = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 管理员广播：\n{content}")
            success += 1
        except:
            fail += 1
    bot.send_message(msg.chat.id, f"✅ 广播完成\n成功：{success} | 失败：{fail}",
                     reply_markup=get_admin_inline())

def custom_name_done(msg):
    user_id = msg.from_user.id
    custom_name = msg.text.strip()
    session = user_session.get(user_id)
    if session:
        process_file(msg.chat.id, user_id, session["content"], session["mode"],
                     session["lines"], custom_name)
        del user_session[user_id]

# ---------------------- 文件处理核心 ----------------------
@bot.message_handler(content_types=["document"])
def handle_document(msg):
    user_id = msg.from_user.id
    user = get_user(user_id)
    
    # 检查余额
    if user["balance"] < 1:
        bot.send_message(msg.chat.id, "❌ 余额不足！请先充值",
                         reply_markup=get_main_inline(user_id))
        return
    
    # 获取文件
    try:
        file_info = bot.get_file(msg.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        original_filename = msg.document.file_name.rsplit(".", 1)[0]  # 去掉后缀
        
        # 处理ZIP/TXT
        content = ""
        if msg.document.file_name.lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(file_data)) as zf:
                for fname in zf.namelist():
                    if fname.lower().endswith(".txt"):
                        content += zf.read(fname).decode("utf-8", errors="ignore") + "\n"
        elif msg.document.file_name.lower().endswith(".txt"):
            content = file_data.decode("utf-8", errors="ignore")
        else:
            bot.send_message(msg.chat.id, "❌ 仅支持 TXT/ZIP 文件！",
                             reply_markup=get_main_inline(user_id))
            return
        
        # 保存会话
        user_session[user_id] = {
            "content": content,
            "mode": user["mode"],
            "lines": user["split_lines"],
            "original_name": original_filename
        }
        
        # 询问文件名
        bot.send_message(
            msg.chat.id,
            "📛 请选择文件名方式：",
            reply_markup=get_filename_inline()
        )
        
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 文件处理失败：{str(e)}",
                         reply_markup=get_main_inline(user_id))

def process_file(chat_id, user_id, content, mode, lines, base_name):
    """处理文件分包并发送"""
    user = get_user(user_id)
    user["balance"] -= 1  # 扣余额
    files = []
    
    # TXT模式
    if mode == "TXT":
        all_lines = content.splitlines()
        chunks = [all_lines[i:i+lines] for i in range(0, len(all_lines), lines)]
        for i, chunk in enumerate(chunks, 1):
            bio = BytesIO("\n".join(chunk).encode("utf-8"))
            bio.name = f"{base_name}_{i}.txt"
            files.append(bio)
    
    # VCF模式
    else:
        phones = re.findall(r"1[3-9]\d{9}", content)
        vcf_content = ""
        for phone in phones:
            vcf_content += f"""BEGIN:VCARD
VERSION:3.0
FN:{random_name()}
TEL;TYPE=CELL:{phone}
END:VCARD
"""
        # 按行数分包（每行≈1个VCF，这里按500个VCF/文件）
        chunks = [vcf_content[i:i+lines*500] for i in range(0, len(vcf_content), lines*500)]
        for i, chunk in enumerate(chunks, 1):
            bio = BytesIO(chunk.encode("utf-8"))
            bio.name = f"{base_name}_{i}.vcf"
            files.append(bio)
    
    # 发送文件（每10个一批，间隔3秒）
    bot.send_message(chat_id, f"✅ 生成 {len(files)} 个文件，开始发送...")
    batch = []
    for f in files:
        batch.append(f)
        if len(batch) == 10:
            for file in batch:
                bot.send_document(chat_id, file)
                time.sleep(0.5)
            batch = []
            time.sleep(3)  # 批间隔3秒
    # 发送剩余文件
    if batch:
        for file in batch:
            bot.send_document(chat_id, file)
            time.sleep(0.5)
    
    bot.send_message(chat_id, "✅ 所有文件发送完成！",
                     reply_markup=get_main_inline(user_id))

# ---------------------- 启动 ----------------------
if __name__ == "__main__":
    print("✅ 机器人已启动（内联按钮版）")
    bot.infinity_polling()
