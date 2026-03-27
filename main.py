import os
import re
import zipfile
import random
import time
import threading
from io import BytesIO
from telebot import TeleBot, types
from flask import Flask

# ========== 核心配置（必须改） ==========
BOT_TOKEN = "8511432045:AAGjwjpk_VHUeNH4hsNX3DVNdTmfV2NoA3A"  # 替换成真实TOKEN
ADMIN_ID = 7793291484           # 替换成你的TG数字ID

# ========== 计费规则 ==========
CHARGE_LINES = 10000
CHARGE_PRICE = 4

# ========== Render 端口配置（自动适配） ==========
PORT = int(os.environ.get("PORT", 10000))
app = Flask(__name__)

# ========== Flask 保活页面（必填） ==========
@app.route("/")
def health_check():
    return "Bot is running ✅", 200

# ========== 初始化机器人（关键：开启回调日志） ==========
bot = TeleBot(BOT_TOKEN, parse_mode="HTML")

# ========== 数据存储 ==========
users = {}
cards = {}
user_session = {}

# 随机姓名库
FIRST_NAMES = ["李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
LAST_NAMES = ["伟", "芳", "娜", "敏", "静", "强", "磊", "军", "洋", "勇"]

# ========== 基础工具函数 ==========
def get_user(user_id):
    """获取/初始化用户信息"""
    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "mode": "TXT",
            "split_lines": 100,
            "username": f"用户{user_id}"
        }
    return users[user_id]

def is_admin(user_id):
    """判断是否为管理员"""
    return str(user_id) == str(ADMIN_ID)  # 转字符串避免类型问题

def random_name():
    return random.choice(FIRST_NAMES) + random.choice(LAST_NAMES)

def calculate_fee(total_lines):
    """计算扣费：1万行4元，不足按1万算"""
    units = (total_lines + CHARGE_LINES - 1) // CHARGE_LINES
    return units * CHARGE_PRICE, units

# ========== 菜单生成（强化按钮标识） ==========
def main_menu(user_id):
    user = get_user(user_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    # 按钮增加唯一标识，避免回调冲突
    kb.add(
        types.InlineKeyboardButton(
            f"📂 模式：{user['mode']}", 
            callback_data=f"switch_mode_{user_id}"
        ),
        types.InlineKeyboardButton(
            f"📏 分包：{user['split_lines']}行", 
            callback_data=f"set_lines_{user_id}"
        )
    )
    kb.add(
        types.InlineKeyboardButton("💰 我的余额", callback_data=f"show_balance_{user_id}"),
        types.InlineKeyboardButton("💳 卡密充值", callback_data=f"redeem_card_{user_id}")
    )
    if is_admin(user_id):
        kb.add(
            types.InlineKeyboardButton("🔧 管理员面板", callback_data=f"admin_panel_{user_id}")
        )
    return kb

def admin_menu(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ 增加余额", callback_data=f"add_balance_{user_id}"),
        types.InlineKeyboardButton("➖ 扣除余额", callback_data=f"deduct_balance_{user_id}")
    )
    kb.add(
        types.InlineKeyboardButton("📛 生成卡密", callback_data=f"gen_card_{user_id}"),
        types.InlineKeyboardButton("📊 用户列表", callback_data=f"user_list_{user_id}")
    )
    kb.add(
        types.InlineKeyboardButton("📢 全员广播", callback_data=f"broadcast_{user_id}"),
        types.InlineKeyboardButton("🔙 返回主菜单", callback_data=f"back_main_{user_id}")
    )
    return kb

def filename_menu(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 自定义文件名", callback_data=f"custom_name_{user_id}"),
        types.InlineKeyboardButton("❌ 使用原文件名", callback_data=f"origin_name_{user_id}")
    )
    return kb

# ========== 启动命令（重置菜单） ==========
@bot.message_handler(commands=["start"])
def start_handler(msg):
    user_id = msg.from_user.id
    get_user(user_id)
    # 发送新消息（避免编辑旧消息导致按钮失效）
    bot.send_message(
        chat_id=msg.chat.id,
        text="✅ 机器人已就绪\n💸 计费规则：每1万行数据扣4元（不足1万行按1万算）",
        reply_markup=main_menu(user_id)
    )

# ========== 核心：回调处理（强化响应+错误捕获） ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        # 解析回调数据（分离功能+用户ID）
        callback_parts = call.data.split("_")
        action = callback_parts[0]
        user_id = int(callback_parts[-1])  # 最后一位是用户ID
        chat_id = call.message.chat.id
        msg_id = call.message.message_id

        # 1. 必须先响应回调（否则按钮会一直转圈）
        bot.answer_callback_query(call.id, text="处理中...", show_alert=False)

        # ========== 主菜单按钮逻辑 ==========
        if action == "switch_mode":
            user = get_user(user_id)
            user["mode"] = "VCF" if user["mode"] == "TXT" else "TXT"
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"✅ 模式已切换为：<code>{user['mode']}</code>",
                reply_markup=main_menu(user_id)
            )

        elif action == "set_lines":
            # 发送新消息接收输入（避免编辑导致按钮失效）
            bot.send_message(chat_id, "✏️ 请输入每个文件的行数（如：100）：")
            # 注册下一步处理
            bot.register_next_step_handler(call.message, set_lines_step, user_id)

        elif action == "show_balance":
            user = get_user(user_id)
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"💰 你的当前余额：<code>{user['balance']} 元</code>",
                reply_markup=main_menu(user_id)
            )

        elif action == "redeem_card":
            bot.send_message(chat_id, "💳 请输入卡密：")
            bot.register_next_step_handler(call.message, redeem_card_step, user_id)

        elif action == "admin_panel":
            if is_admin(user_id):
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text="🔧 管理员面板",
                    reply_markup=admin_menu(user_id)
                )
            else:
                bot.answer_callback_query(call.id, text="❌ 无管理员权限", show_alert=True)

        # ========== 管理员面板按钮逻辑 ==========
        elif action == "add_balance":
            if is_admin(user_id):
                bot.send_message(chat_id, "➕ 请输入：用户ID 金额（如：123456 10）")
                bot.register_next_step_handler(call.message, add_balance_step, user_id)
            else:
                bot.answer_callback_query(call.id, text="❌ 无权限", show_alert=True)

        elif action == "deduct_balance":
            if is_admin(user_id):
                bot.send_message(chat_id, "➖ 请输入：用户ID 金额（如：123456 10）")
                bot.register_next_step_handler(call.message, deduct_balance_step, user_id)
            else:
                bot.answer_callback_query(call.id, text="❌ 无权限", show_alert=True)

        elif action == "gen_card":
            if is_admin(user_id):
                bot.send_message(chat_id, "📛 请输入：卡密数量 单张金额（如：5 10）")
                bot.register_next_step_handler(call.message, gen_card_step, user_id)
            else:
                bot.answer_callback_query(call.id, text="❌ 无权限", show_alert=True)

        elif action == "user_list":
            if is_admin(user_id):
                if not users:
                    user_list_text = "📊 暂无用户数据"
                else:
                    user_list_text = "📊 所有用户余额：\n"
                    for uid, info in users.items():
                        user_list_text += f"ID：{uid} | 余额：{info['balance']} 元\n"
                bot.send_message(chat_id, user_list_text)
            else:
                bot.answer_callback_query(call.id, text="❌ 无权限", show_alert=True)

        elif action == "broadcast":
            if is_admin(user_id):
                bot.send_message(chat_id, "📢 请输入广播内容：")
                bot.register_next_step_handler(call.message, broadcast_step, user_id)
            else:
                bot.answer_callback_query(call.id, text="❌ 无权限", show_alert=True)

        elif action == "back_main":
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text="✅ 已返回主菜单",
                reply_markup=main_menu(user_id)
            )

        # ========== 文件处理按钮逻辑 ==========
        elif action == "custom_name":
            bot.send_message(chat_id, "✏️ 请输入文件名前缀：")
            bot.register_next_step_handler(call.message, custom_name_step, user_id)

        elif action == "origin_name":
            if user_id in user_session:
                session = user_session[user_id]
                send_files_batch(chat_id, user_id, session["content"], session["mode"], 
                                session["lines"], session["original_name"])
                del user_session[user_id]
            else:
                bot.answer_callback_query(call.id, text="❌ 无文件数据", show_alert=True)

    except Exception as e:
        # 捕获所有错误，避免回调卡死
        bot.answer_callback_query(call.id, text=f"❌ 操作失败：{str(e)}", show_alert=True)
        print(f"回调错误：{e}")

# ========== 步骤处理函数（独立拆分，避免冲突） ==========
def set_lines_step(msg, user_id):
    try:
        lines = int(msg.text.strip())
        if lines <= 0:
            bot.send_message(msg.chat.id, "❌ 行数必须大于0")
            return
        get_user(user_id)["split_lines"] = lines
        bot.send_message(
            msg.chat.id,
            f"✅ 分包行数已设置为：<code>{lines}</code> 行",
            reply_markup=main_menu(user_id)
        )
    except:
        bot.send_message(msg.chat.id, "❌ 请输入有效数字（如：100）")

def redeem_card_step(msg, user_id):
    card = msg.text.strip()
    user = get_user(user_id)
    if card not in cards:
        bot.send_message(msg.chat.id, "❌ 卡密无效")
        return
    if cards[card]["used"]:
        bot.send_message(msg.chat.id, "❌ 卡密已使用")
        return
    amount = cards[card]["amount"]
    cards[card]["used"] = True
    user["balance"] += amount
    bot.send_message(
        msg.chat.id,
        f"✅ 充值成功！\n💸 到账金额：{amount} 元\n💰 当前余额：{user['balance']} 元",
        reply_markup=main_menu(user_id)
    )

def add_balance_step(msg, user_id):
    try:
        uid, amount = msg.text.strip().split()
        uid = int(uid)
        amount = int(amount)
        get_user(uid)["balance"] += amount
        bot.send_message(
            msg.chat.id,
            f"✅ 已为用户 {uid} 增加 {amount} 元",
            reply_markup=admin_menu(user_id)
        )
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误（正确：用户ID 金额）")

def deduct_balance_step(msg, user_id):
    try:
        uid, amount = msg.text.strip().split()
        uid = int(uid)
        amount = int(amount)
        get_user(uid)["balance"] -= amount
        bot.send_message(
            msg.chat.id,
            f"✅ 已为用户 {uid} 扣除 {amount} 元",
            reply_markup=admin_menu(user_id)
        )
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误（正确：用户ID 金额）")

def gen_card_step(msg, user_id):
    try:
        count, amount = msg.text.strip().split()
        count = int(count)
        amount = int(amount)
        if count <= 0 or amount <= 0:
            bot.send_message(msg.chat.id, "❌ 数量/金额必须大于0")
            return
        card_list = []
        for i in range(count):
            card_code = f"CARD_{int(time.time())}_{random.randint(100000, 999999)}"
            cards[card_code] = {"used": False, "amount": amount}
            card_list.append(f"{card_code} | {amount} 元")
        bot.send_message(
            msg.chat.id,
            f"📛 生成 {count} 张卡密：\n" + "\n".join(card_list),
            reply_markup=admin_menu(user_id)
        )
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误（正确：数量 金额）")

def broadcast_step(msg, user_id):
    content = msg.text.strip()
    success = 0
    fail = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 管理员广播：\n{content}")
            success += 1
        except:
            fail += 1
    bot.send_message(
        msg.chat.id,
        f"✅ 广播完成\n✅ 成功：{success} 人\n❌ 失败：{fail} 人",
        reply_markup=admin_menu(user_id)
    )

def custom_name_step(msg, user_id):
    prefix = msg.text.strip()
    if user_id in user_session:
        session = user_session[user_id]
        send_files_batch(chat_id=msg.chat.id, user_id=user_id, 
                        content=session["content"], mode=session["mode"],
                        lines=session["lines"], base_name=prefix)
        del user_session[user_id]
    else:
        bot.send_message(msg.chat.id, "❌ 无文件数据")

# ========== 文件处理 + 分批发送 ==========
@bot.message_handler(content_types=["document"])
def file_handler(msg):
    user_id = msg.from_user.id
    user = get_user(user_id)
    try:
        # 获取文件
        file_info = bot.get_file(msg.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        file_name = msg.document.file_name.rsplit(".", 1)[0]

        # 解析文件内容
        content = ""
        if msg.document.file_name.lower().endswith(".zip"):
            with zipfile.ZipFile(BytesIO(file_data)) as zf:
                for fname in zf.namelist():
                    if fname.lower().endswith(".txt"):
                        content += zf.read(fname).decode("utf-8", "ignore") + "\n"
        elif msg.document.file_name.lower().endswith(".txt"):
            content = file_data.decode("utf-8", "ignore")
        else:
            bot.send_message(msg.chat.id, "❌ 仅支持 TXT/ZIP 文件")
            return

        # 计算行数和扣费
        total_lines = len(content.splitlines())
        fee, units = calculate_fee(total_lines)

        # 检查余额
        if user["balance"] < fee:
            bot.send_message(
                msg.chat.id,
                f"❌ 余额不足！\n📊 总行数：{total_lines} 行\n💸 需扣费：{fee} 元（{units}个计费单位）\n💰 当前余额：{user['balance']} 元",
                reply_markup=main_menu(user_id)
            )
            return

        # 保存会话
        user_session[user_id] = {
            "content": content,
            "mode": user["mode"],
            "lines": user["split_lines"],
            "original_name": file_name,
            "fee": fee
        }

        # 发送文件名选择菜单
        bot.send_message(
            msg.chat.id,
            f"✅ 费用确认：\n📊 总行数：{total_lines} 行\n💸 需扣费：{fee} 元\n请选择文件名方式：",
            reply_markup=filename_menu(user_id)
        )

    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ 文件处理失败：{str(e)}")
        print(f"文件处理错误：{e}")

def send_files_batch(chat_id, user_id, content, mode, lines, base_name):
    """分批发送文件（10个一批）"""
    try:
        user = get_user(user_id)
        fee = user_session[user_id]["fee"]
        user["balance"] -= fee  # 扣费

        files = []
        # 生成TXT文件
        if mode == "TXT":
            all_lines = content.splitlines()
            chunks = [all_lines[i:i+lines] for i in range(0, len(all_lines), lines)]
            for idx, chunk in enumerate(chunks, 1):
                bio = BytesIO("\n".join(chunk).encode("utf-8"))
                bio.name = f"{base_name}_{idx}.txt"
                files.append(bio)
        # 生成VCF文件
        else:
            phones = re.findall(r"1[3-9]\d{9}", content)
            chunks = [phones[i:i+lines] for i in range(0, len(phones), lines)]
            for idx, chunk in enumerate(chunks, 1):
                vcf_content = ""
                for phone in chunk:
                    vcf_content += f"BEGIN:VCARD\nVERSION:3.0\nFN:{random_name()}\nTEL;TYPE=CELL:{phone}\nEND:VCARD\n"
                bio = BytesIO(vcf_content.encode("utf-8"))
                bio.name = f"{base_name}_{idx}.vcf"
                files.append(bio)

        # 分批发送（10个一批）
        total_files = len(files)
        batch_size = 10
        bot.send_message(
            chat_id,
            f"✅ 扣费完成！当前余额：{user['balance']} 元\n📤 共生成 {total_files} 个文件，开始分批发送..."
        )

        for batch_idx in range(0, total_files, batch_size):
            batch_files = files[batch_idx:batch_idx+batch_size]
            current_batch = (batch_idx // batch_size) + 1
            bot.send_message(chat_id, f"🚀 发送第 {current_batch} 批（共 {len(batch_files)} 个文件）")
            
            # 发送当前批次
            for f in batch_files:
                bot.send_document(chat_id, f)
                time.sleep(0.5)  # 避免限流
            
            # 批次间隔
            if batch_idx + batch_size < total_files:
                bot.send_message(chat_id, "⏳ 等待5秒发送下一批...")
                time.sleep(5)

        # 发送完成
        bot.send_message(
            chat_id,
            f"✅ 所有文件发送完成！\n💸 本次扣费：{fee} 元\n💰 当前余额：{user['balance']} 元",
            reply_markup=main_menu(user_id)
        )

    except Exception as e:
        bot.send_message(chat_id, f"❌ 发送失败：{str(e)}")
        print(f"文件发送错误：{e}")

# ========== 启动 Flask + 机器人 ==========
def run_flask_server():
    """后台运行Flask（端口监听）"""
    app.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

if __name__ == "__main__":
    # 启动Flask（后台线程）
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()
    print("✅ Flask服务器已启动（端口：", PORT, "）")

    # 启动机器人（关键：开启重试+无超时）
    print("✅ 机器人开始监听...")
    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60,
        skip_pending=True,  # 跳过积压的请求
        retry_after=5       # 出错后重试间隔
    )
