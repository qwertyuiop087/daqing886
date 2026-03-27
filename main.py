import os
import re
import zipfile
import random
import time
from io import BytesIO
from telebot import TeleBot, types

# ========== 配置（必须改这里！） ==========
BOT_TOKEN = "8511432045:AAH3vlvLLuSlRkpHyNF5d6uIQPfiCSQzYVs"  # 替换成@BotFather给的token
ADMIN_ID = 7793291484           # 替换成你的TG纯数字ID

# ========== 先初始化bot（核心修复：确保bot变量提前定义） ==========
bot = TeleBot(BOT_TOKEN)

# ========== 存储 ==========
users = {}
cards = {}  # 结构：{卡密: {"used": False, "amount": 金额}}
user_session = {}

# ========== 随机姓名库 ==========
FIRST_NAMES = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "军", "洋", "勇"]

# ========== 工具函数 ==========
def get_user(user_id):
    """获取/初始化用户信息"""
    if user_id not in users:
        users[user_id] = {
            "balance": 10,
            "mode": "TXT",
            "split_lines": 100,
            "username": f"用户{user_id}"
        }
    return users[user_id]

def is_admin(user_id):
    """判断是否是管理员"""
    return user_id == ADMIN_ID

def random_name():
    """生成随机中文名"""
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

# ---------------------- 内联按钮 ----------------------
def main_menu(user_id):
    """主菜单按钮"""
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
    """管理员面板按钮"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ 增加余额", callback_data="add_balance"),
        types.InlineKeyboardButton("➖ 扣除余额", callback_data="deduct_balance")
    )
    kb.add(
        types.InlineKeyboardButton("📛 生成卡密（自定义金额）", callback_data="gen_card"),
        types.InlineKeyboardButton("📊 用户余额列表", callback_data="user_list")
    )
    kb.add(
        types.InlineKeyboardButton("📢 全员广播", callback_data="broadcast"),
        types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")
    )
    return kb

def filename_menu():
    """文件名选择按钮"""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义文件名", callback_data="custom_name"),
        types.InlineKeyboardButton("❌ 使用原文件名", callback_data="origin_name")
    )
    return kb

# ---------------------- 启动命令 ----------------------
@bot.message_handler(commands=["start"])
def start_bot(msg):
    """启动机器人，显示主菜单"""
    user_id = msg.from_user.id
    get_user(user_id)
    bot.send_message(
        chat_id=msg.chat.id,
        text="✅ 机器人已启动\n点击下方按钮操作：",
        reply_markup=main_menu(user_id)
    )

# ---------------------- 按钮回调 ----------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """处理所有按钮点击"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    bot.answer_callback_query(call.id)
    
    # 1. 切换模式
    if call.data == "switch_mode":
        user = get_user(user_id)
        user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=f"✅ 已切换为 {user['mode']} 模式",
            reply_markup=main_menu(user_id)
        )
    
    # 2. 设置分包行数
    elif call.data == "set_lines":
        bot.send_message(chat_id, "✏️ 请输入每个文件的行数：")
        bot.register_next_step_handler(call.message, set_lines_handler, user_id)
    
    # 3. 查看余额
    elif call.data == "show_balance":
        balance = get_user(user_id)["balance"]
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=f"💰 你的余额：{balance}",
            reply_markup=main_menu(user_id)
        )
    
    # 4. 卡密充值（适配自定义金额）
    elif call.data == "redeem_card":
        bot.send_message(chat_id, "💳 请输入卡密：")
        bot.register_next_step_handler(call.message, redeem_card_handler, user_id)
    
    # 5. 管理员面板
    elif call.data == "admin_panel":
        if is_admin(user_id):
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text="🔧 管理员面板",
                reply_markup=admin_menu()
            )
        else:
            bot.send_message(chat_id, "❌ 你不是管理员！", reply_markup=main_menu(user_id))
    
    # 6. 返回主菜单
    elif call.data == "back_main":
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text="✅ 回到主菜单",
            reply_markup=main_menu(user_id)
        )
    
    # 7. 管理员：增加余额
    elif call.data == "add_balance":
        if is_admin(user_id):
            bot.send_message(chat_id, "➕ 格式：用户ID 金额（例：123456 10）")
            bot.register_next_step_handler(call.message, add_balance_handler)
        else:
            bot.send_message(chat_id, "❌ 无权限！", reply_markup=main_menu(user_id))
    
    # 8. 管理员：扣除余额
    elif call.data == "deduct_balance":
        if is_admin(user_id):
            bot.send_message(chat_id, "➖ 格式：用户ID 金额（例：123456 10）")
            bot.register_next_step_handler(call.message, deduct_balance_handler)
        else:
            bot.send_message(chat_id, "❌ 无权限！", reply_markup=main_menu(user_id))
    
    # 9. 管理员：生成卡密（自定义金额）
    elif call.data == "gen_card":
        if is_admin(user_id):
            bot.send_message(chat_id, "📛 请输入【数量 金额】（例：5 10 = 生成5个10元卡密）")
            bot.register_next_step_handler(call.message, gen_card_handler)
        else:
            bot.send_message(chat_id, "❌ 无权限！", reply_markup=main_menu(user_id))
    
    # 10. 管理员：用户余额列表
    elif call.data == "user_list":
        if is_admin(user_id):
            list_text = "📊 所有用户余额列表：\n\n"
            for uid, info in users.items():
                list_text += f"ID：{uid} | 余额：{info['balance']}\n"
            bot.send_message(chat_id, list_text)
        else:
            bot.send_message(chat_id, "❌ 无权限！", reply_markup=main_menu(user_id))
    
    # 11. 管理员：全员广播
    elif call.data == "broadcast":
        if is_admin(user_id):
            bot.send_message(chat_id, "📢 请输入广播内容：")
            bot.register_next_step_handler(call.message, broadcast_handler)
        else:
            bot.send_message(chat_id, "❌ 无权限！", reply_markup=main_menu(user_id))
    
    # 12. 文件：自定义文件名
    elif call.data == "custom_name":
        bot.send_message(chat_id, "✏️ 请输入自定义文件名前缀：")
        bot.register_next_step_handler(call.message, custom_name_handler)
    
    # 13. 文件：使用原文件名
    elif call.data == "origin_name":
        if user_id in user_session:
            session = user_session[user_id]
            send_files_batch(chat_id, user_id, session["content"], 
                           session["mode"], session["lines"], session["original_name"])
            del user_session[user_id]

# ---------------------- 步骤处理函数 ----------------------
def set_lines_handler(msg, user_id):
    """设置分包行数"""
    try:
        lines = int(msg.text.strip())
        get_user(user_id)["split_lines"] = lines
        bot.send_message(msg.chat.id, f"✅ 已设置分包行数：{lines}", reply_markup=main_menu(user_id))
    except:
        bot.send_message(msg.chat.id, "❌ 请输入有效数字！", reply_markup=main_menu(user_id))

def redeem_card_handler(msg, user_id):
    """卡密充值（适配自定义金额）"""
    card = msg.text.strip()
    user = get_user(user_id)
    
    # 检查卡密是否存在
    if card not in cards:
        bot.send_message(msg.chat.id, "❌ 卡密无效！", reply_markup=main_menu(user_id))
        return
    
    # 检查卡密是否已使用
    if cards[card]["used"]:
        bot.send_message(msg.chat.id, "❌ 卡密已使用！", reply_markup=main_menu(user_id))
        return
    
    # 充值（使用卡密对应的金额）
    amount = cards[card]["amount"]
    cards[card]["used"] = True
    user["balance"] += amount
    bot.send_message(msg.chat.id, f"✅ 充值成功！余额+{amount}（当前余额：{user['balance']}）", 
                     reply_markup=main_menu(user_id))

def add_balance_handler(msg):
    """管理员增加余额"""
    try:
        uid, num = msg.text.strip().split()
        get_user(int(uid))["balance"] += int(num)
        bot.send_message(msg.chat.id, f"✅ 余额增加成功！", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误！例：123456 10", reply_markup=admin_menu())

def deduct_balance_handler(msg):
    """管理员扣除余额"""
    try:
        uid, num = msg.text.strip().split()
        get_user(int(uid))["balance"] -= int(num)
        bot.send_message(msg.chat.id, f"✅ 余额扣除成功！", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误！例：123456 10", reply_markup=admin_menu())

def gen_card_handler(msg):
    """生成卡密（自定义金额）"""
    try:
        # 解析数量和金额（格式：数量 金额）
        count, amount = msg.text.strip().split()
        count = int(count)
        amount = int(amount)
        
        # 验证输入有效性
        if count <= 0 or amount <= 0:
            bot.send_message(msg.chat.id, "❌ 数量和金额必须大于0！", reply_markup=admin_menu())
            return
        
        # 生成卡密
        card_list = []
        for i in range(count):
            card = f"CARD_{int(time.time())}_{random.randint(1000,9999)}_{i}"  # 增加随机数，避免重复
            cards[card] = {
                "used": False,
                "amount": amount  # 存储卡密对应的金额
            }
            card_list.append(f"{card} | 金额：{amount}")
        
        # 发送卡密列表
        bot.send_message(
            msg.chat.id, 
            f"📛 生成 {count} 个卡密（每个金额：{amount}）：\n\n" + "\n".join(card_list), 
            reply_markup=admin_menu()
        )
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误！例：5 10（生成5个10元卡密）", reply_markup=admin_menu())

def broadcast_handler(msg):
    """全员广播"""
    content = msg.text.strip()
    success = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 管理员广播：\n{content}")
            success += 1
        except:
            continue
    bot.send_message(msg.chat.id, f"✅ 广播完成！成功发送给 {success} 个用户", reply_markup=admin_menu())

def custom_name_handler(msg):
    """自定义文件名"""
    user_id = msg.from_user.id
    if user_id in user_session:
        session = user_session[user_id]
        send_files_batch(msg.chat.id, user_id, session["content"], 
                       session["mode"], session["lines"], msg.text.strip())
        del user_session[user_id]

# ---------------------- 文件处理（10个一批发送） ----------------------
@bot.message_handler(content_types=["document"])
def handle_file(msg):
    """接收文件并初始化处理"""
    user_id = msg.from_user.id
    user = get_user(user_id)
    
    # 检查余额
    if user["balance"] < 1:
        bot.send_message(msg.chat.id, "❌ 余额不足！请先充值", reply_markup=main_menu(user_id))
        return
    
    try:
        # 获取文件信息
        file_info = bot.get_file(msg.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        original_name = msg.document.file_name.rsplit(".", 1)[0]
        
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
            bot.send_message(msg.chat.id, "❌ 仅支持 TXT/ZIP 文件！", reply_markup=main_menu(user_id))
            return
        
        # 保存会话
        user_session[user_id] = {
            "content": content,
            "mode": user["mode"],
            "lines": user["split_lines"],
            "original_name": original_name
        }
        
        # 询问文件名
        bot.send_message(msg.chat.id, "📛 请选择文件名方式：", reply_markup=filename_menu())
        
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 文件处理失败：{str(e)}", reply_markup=main_menu(user_id))

def send_files_batch(chat_id, user_id, content, mode, lines, base_name):
    """10个文件一批发送，间隔3秒"""
    user = get_user(user_id)
    user["balance"] -= 1  # 扣除余额
    files = []
    
    # 生成分包文件
    if mode == "TXT":
        all_lines = content.splitlines()
        chunks = [all_lines[i:i+lines] for i in range(0, len(all_lines), lines)]
        for idx, chunk in enumerate(chunks, 1):
            bio = BytesIO("\n".join(chunk).encode("utf-8"))
            bio.name = f"{base_name}_{idx}.txt"
            files.append(bio)
    else:  # VCF模式
        phones = re.findall(r"1[3-9]\d{9}", content)
        vcf_chunks = []
        current_vcf = ""
        count = 0
        for phone in phones:
            current_vcf += f"""BEGIN:VCARD
VERSION:3.0
FN:{random_name()}
TEL;TYPE=CELL:{phone}
END:VCARD
"""
            count += 1
            if count >= lines:
                vcf_chunks.append(current_vcf)
                current_vcf = ""
                count = 0
        if current_vcf:
            vcf_chunks.append(current_vcf)
        for idx, chunk in enumerate(vcf_chunks, 1):
            bio = BytesIO(chunk.encode("utf-8"))
            bio.name = f"{base_name}_{idx}.vcf"
            files.append(bio)
    
    # 分批发送
    bot.send_message(chat_id, f"✅ 共生成 {len(files)} 个文件，开始分批发送...")
    batch_size = 10
    for i in range(0, len(files), batch_size):
        batch = files[i:i+batch_size]
        for file in batch:
            bot.send_document(chat_id, file)
            time.sleep(0.3)
        if i + batch_size < len(files):
            bot.send_message(chat_id, f"⏳ 第 {i//batch_size + 1} 批发送完成，等待3秒发送下一批...")
            time.sleep(3)
    
    bot.send_message(chat_id, "✅ 所有文件发送完成！", reply_markup=main_menu(user_id))

# ---------------------- 启动机器人 ----------------------
if __name__ == "__main__":
    print("✅ 机器人已启动（最终修复版）- 无NameError错误")
    bot.infinity_polling(timeout=30, long_polling_timeout=5)
