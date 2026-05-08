import os
import re
import random
import time
from io import BytesIO
import telebot
from telebot.types import InputMediaDocument

# ==================== 你的机器人TOKEN ====================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834
# ========================================================

PRICE_SPLIT = 0.0004
PRICE_MERGE = 0.0002
PRICE_DEDUP = 0.0002
BATCH_NUM = 10 # 每10个打包一起发

# ---------------- 全局缓存 ----------------
user_file = {}
users = {}
cards = {}
user_merge_temp = {}
user_state = {}
user_insert_info = {}
user_log = {}
user_recharge_log = {}

def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0.0, "mode": "TXT", "split_lines": 100}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

def add_log(uid, operate, line_num, cost):
    now_time = time.strftime("%Y-%m-%d %H:%M:%S")
    if uid not in user_log:
        user_log[uid] = []
    user_log[uid].append(f"【{now_time}】\n操作：{operate}\n总行数：{line_num}\n扣费：{cost:.4f}元\n剩余余额：{get_user(uid)['balance']:.4f}元\n——————————")

def add_recharge_log(uid, amount, way):
    now_time = time.strftime("%Y-%m-%d %H:%M:%S")
    if uid not in user_recharge_log:
        user_recharge_log[uid] = []
    user_recharge_log[uid].append(f"【{now_time}】\n操作方式：{way}\n变动金额：{amount:.4f}元\n当前余额：{get_user(uid)['balance']:.4f}元\n——————————")

def show_user_balance(cid, uid):
    bal = get_user(uid)['balance']
    bot.send_message(cid, f"💰 个人余额\n当前剩余：{bal:.4f} 元")

def show_recharge_log(cid, uid):
    if uid not in user_recharge_log or len(user_recharge_log[uid]) == 0:
        bot.send_message(cid, "📭 暂无任何充值记录")
        return
    txt = "💳 个人充值扣款历史\n"
    txt += "\n".join(user_recharge_log[uid])
    if len(txt) > 4000:
        txt = txt[:3800]
    bot.send_message(cid, txt)

def show_user_log(cid, uid):
    if uid not in user_log or len(user_log[uid]) == 0:
        bot.send_message(cid, "📭 暂无文件处理消费记录")
        return
    txt = "📜 文件处理消费记录\n"
    txt += "\n".join(user_log[uid])
    if len(txt) > 4000:
        txt = txt[:3800]
    bot.send_message(cid, txt)

# ==================== 菜单 ====================
def main_menu(uid):
    user = get_user(uid)
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(f"📂 格式模式：{user['mode']}", callback_data="switch_mode"),
        telebot.types.InlineKeyboardButton(f"📏 分割行数：{user['split_lines']}", callback_data="set_lines")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("👤 个人中心", callback_data="user_center"),
        telebot.types.InlineKeyboardButton("💳 卡密充值", callback_data="redeem")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📎 TXT文件合并", callback_data="merge_txt"),
        telebot.types.InlineKeyboardButton("🧹 号码去重清理", callback_data="deduplicate")
    )
    if is_admin(uid):
        kb.add(telebot.types.InlineKeyboardButton("🔧 管理员后台", callback_data="admin"))
    return kb

def user_center_menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("💰 查询余额", callback_data="my_balance"),
        telebot.types.InlineKeyboardButton("💳 充值记录", callback_data="my_recharge")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📜 消费记录", callback_data="my_log"),
        telebot.types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")
    )
    return kb

def admin_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("➕ 用户加余额", callback_data="addbal"),
        telebot.types.InlineKeyboardButton("➖ 用户扣余额", callback_data="deductbal")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📛 生成充值卡密", callback_data="gencard"),
        telebot.types.InlineKeyboardButton("📊 用户余额列表", callback_data="userlist")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📢 全站广播消息", callback_data="broadcast"),
        telebot.types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back")
    )
    kb.add(telebot.types.InlineKeyboardButton("📥 批量增加余额", callback_data="batch_add_bal"))
    return kb

def insert_choose_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("✅ 批量插入手机号", callback_data="open_insert"),
        telebot.types.InlineKeyboardButton("❌ 不插入直接分割", callback_data="skip_insert")
    )
    return kb

bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    user_state[uid] = "idle"
    bot.send_message(msg.chat.id, "✅ 机器人启动成功", reply_markup=main_menu(uid))

# ==================== 按钮回调 ====================
@bot.callback_query_handler(func=lambda call: True)
def handle_all(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        act = call.data
        bot.answer_callback_query(call.id)

        admin_list = ["addbal","deductbal","gencard","userlist","broadcast","batch_add_bal"]
        if not is_admin(uid) and act in admin_list:
            bot.send_message(cid, "❌ 无权限")
            return

        user_state[uid] = "idle"

        if act == "switch_mode":
            u = get_user(uid)
            u['mode'] = "VCF" if u['mode']=="TXT" else "TXT"
            bot.edit_message_text("✅ 模式已切换",call.message.chat.id,call.message.message_id,reply_markup=main_menu(uid))
        elif act == "set_lines":
            bot.send_message(cid,"✏️ 输入分割行数：")
            bot.register_next_step_handler(call.message, set_lines)
        elif act == "redeem":
            bot.send_message(cid,"💳 输入卡密：")
            bot.register_next_step_handler(call.message, redeem)
        elif act == "user_center":
            bot.edit_message_text("👤 个人中心",cid,call.message.message_id,reply_markup=user_center_menu(uid))
        elif act == "my_balance":
            show_user_balance(cid, uid)
        elif act == "my_recharge":
            show_recharge_log(cid)
        elif act == "my_log":
            show_user_log(cid, uid)
        elif act == "back_main":
            bot.edit_message_text("✅ 主菜单",cid,call.message.message_id,reply_markup=main_menu(uid))
        elif act == "admin":
            bot.edit_message_text("🔧 管理面板",cid,call.message.message_id,reply_markup=admin_menu())
        elif act == "back":
            bot.edit_message_text("✅ 主菜单",cid,call.message.message_id,reply_markup=main_menu(uid))
        elif act == "merge_txt":
            user_merge_temp[uid] = []
            user_state[uid] = "merging"
            bot.send_message(cid, "📎 发TXT，发完回复：完成")
        elif act == "deduplicate":
            user_state[uid] = "dedup"
            bot.send_message(cid, "🧹 发送号码TXT文件")

        elif act == "open_insert":
            bot.send_message(cid,"📌 每个文件插入几个号码？取消=取消")
            bot.register_next_step_handler(call.message, lambda m: insert_get_num_count(m, uid))
        elif act == "skip_insert":
            if uid not in user_file:
                bot.send_message(cid, "❌ 文件过期")
                return
            data = user_file[uid]
            del user_file[uid]
            bot.send_message(cid,"✏️ 文件名称：")
            bot.register_next_step_handler(call.message, lambda m: go_batch_split(cid, uid, data['c'], m.text.strip()))

    except Exception as e:
        print(e)

# ==================== 插入号码流程 ====================
def insert_get_num_count(m, uid):
    txt = m.text.strip()
    if txt == "取消":
        bot.send_message(m.chat.id, "✅ 已取消")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    try:
        num = int(txt)
        user_insert_info[uid] = {"per": num, "old": user_file[uid]['n'], "txt": user_file[uid]['c']}
        bot.send_message(m.chat.id, "📞 发送循环手机号")
        bot.register_next_step_handler(m, insert_get_phone)
    except:
        bot.send_message(m.chat.id, "❌ 请输数字")
        bot.register_next_step_handler(m, lambda mm: insert_get_num_count(mm, uid))

def insert_get_phone(m, uid):
    txt = m.text.strip()
    if txt == "取消":
        bot.send_message(m.chat.id, "✅ 已取消")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    phones = re.findall(r"\d+", txt)
    if not phones:
        bot.send_message(m.chat.id, "❌ 无号码")
        bot.register_next_step_handler(m, lambda mm: insert_get_phone(mm, uid))
        return
    user_insert_info[uid]['list'] = phones
    bot.send_message(m.chat.id, "✏️ 文件名 / 原文件名")
    bot.register_next_step_handler(m, insert_done)

def insert_done(m, uid):
    name = m.text.strip()
    fname = user_insert_info[uid]['old'] if name=="原文件名" else name
    go_insert_batch(m.chat.id, uid, fname)

# ==================== 核心修复：10个打包一起发，不再单发 ====================
def go_batch_split(cid, uid, content, name):
    user = get_user(uid)
    lines = [x for x in content.splitlines() if x.strip()]
    total = len(lines)
    fee = total * PRICE_SPLIT

    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 余额不足：{fee:.4f}元")
        return
    user['balance'] -= fee
    add_log(uid, f"TXT分割", total, fee)
    bot.send_message(cid,f"💸 扣费{fee:.4f}元 | 剩余余额：{user['balance']:.4f}")

    chunks = [lines[i:i+user['split_lines']] for i in range(0, total, user['split_lines'])]
    total_file = len(chunks)
    bot.send_message(cid,f"📄 共{total_file}份 | 每10个批量发送")

    media_list = []
    page = 1
    for chunk in chunks:
        txt = "\n".join(chunk)
        bio = BytesIO(txt.encode())
        bio.name = f"{name}_{page}.txt"
        media_list.append(InputMediaDocument(bio))

        # 满10个 立刻打包发送
        if len(media_list) >= BATCH_NUM:
            bot.send_media_group(cid, media=media_list)
            bot.send_message(cid,f"✅ 已发送 {page}/{total_file} 份")
            media_list = []
            time.sleep(1)
        page += 1

    # 剩余不足10个收尾发送
    if media_list:
        bot.send_media_group(cid, media=media_list)
    bot.send_message(cid,f"🎉 全部{total_file}份发送完毕！")

# 插入号码批量打包发送
def go_insert_batch(cid, uid, fname):
    info = user_insert_info[uid]
    per = info['per']
    phones = info['list']
    content = info['txt']
    lines = [x for x in content.splitlines() if x.strip()]
    total = len(lines)
    user = get_user(uid)
    fee = total * PRICE_SPLIT

    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 余额不足：{fee:.4f}元")
        return
    user['balance'] -= fee
    add_log(uid, f"分割+插入号码", total, fee)
    bot.send_message(cid,f"💸 扣费{fee:.4f}元 | 剩余余额：{user['balance']:.4f}")

    chunks = [lines[i:i+user['split_lines']] for i in range(0, total, user['split_lines'])]
    total_file = len(chunks)
    bot.send_message(cid,f"📄 共{total_file}份 | 每10个批量发送")

    media_list = []
    idx = 0
    page = 1
    for chunk in chunks:
        # 循环插入号码
        add = []
        for _ in range(per):
            add.append(phones[idx % len(phones)])
            idx += 1
        chunk += add

        txt = "\n".join(chunk)
        bio = BytesIO(txt.encode())
        bio.name = f"{fname}_{page}.txt"
        media_list.append(InputMediaDocument(bio))

        if len(media_list) >= BATCH_NUM:
            bot.send_media_group(cid, media=media_list)
            bot.send_message(cid,f"✅ 已发送 {page}/{total_file} 份")
            media_list = []
            time.sleep(1)
        page += 1

    if media_list:
        bot.send_media_group(cid, media=media_list)
    bot.send_message(cid,f"🎉 全部插入分割完成！")
    del user_insert_info[uid]

# ==================== 其他原有功能不变 ====================
def set_lines(msg):
    try:
        get_user(msg.from_user.id)['split_lines'] = int(msg.text)
        bot.send_message(msg.chat.id, "✅ 已设置")
    except:
        bot.send_message(msg.chat.id, "❌ 请输数字")

def redeem(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    card = msg.text.strip()
    if card not in cards:
        bot.send_message(cid, "❌ 无效卡密")
        return
    money = float(cards.pop(card))
    get_user(uid)['balance'] += money
    add_recharge_log(uid, money, "卡密充值")
    bot.send_message(cid, f"✅ 到账{money:.4f} | 余额{get_user(uid)['balance']:.4f}")

@bot.message_handler(content_types=['document'])
def doc(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    try:
        f = bot.get_file(msg.document.file_id)
        txt = bot.download_file(f.file_path).decode('utf-8','ignore')
        if user_state.get(uid) == "merging":
            user_merge_temp[uid].append(txt)
            bot.send_message(cid, "✅ 已收录，回复：完成")
        elif user_state.get(uid) == "dedup":
            old = len(txt.splitlines())
            new = list(set(txt.splitlines()))
            cnt = len(new)
            fee = cnt * PRICE_DEDUP
            u = get_user(uid)
            if u['balance'] < fee:
                bot.send_message(cid, f"❌ 不足{fee:.4f}")
                return
            u['balance'] -= fee
            add_log(uid, "号码去重", old, fee)
            out = BytesIO("\n".join(new).encode())
            out.name = "去重.txt"
            bot.send_document(cid, out)
        else:
            user_file[uid] = {"n": msg.document.file_name, "c": txt}
            bot.send_message(cid, "📄 请选择", reply_markup=insert_choose_menu())
    except:
        bot.send_message(cid, "❌ 文件错误")

bot.polling(none_stop=True)
