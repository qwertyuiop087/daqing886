import os
import re
import random
import time
from io import BytesIO
from telebot import TeleBot, types
import logging

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ====================== 你的TOKEN ======================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834
# ======================================================

# 价格标准 严格按你要求
PRICE_SPLIT = 0.0004    # 分割、插入号码 每行
PRICE_MERGE = 0.0002    # 合并txt 每行
PRICE_DEDUP = 0.0002    # 去重 每行

SEND_BATCH = 10 # 每10个文件发送一次

user_file = {}
users = {}
cards = {}
user_merge_temp = {}
user_state = {}
user_insert_info = {}

user_log = {}
user_recharge_log = {}

# ====================== 基础函数 ======================
def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0.0, "mode": "TXT", "split_lines": 100}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

# ========== 文件处理消费日志 ==========
def add_log(uid, operate, line_num, cost):
    now_time = time.strftime("%Y-%m-%d %H:%M:%S")
    if uid not in user_log:
        user_log[uid] = []
    user_log[uid].append(f"【{now_time}】\n操作：{operate}\n总行数：{line_num}\n扣费：{cost:.4f}元\n剩余余额：{get_user(uid)['balance']:.4f}元\n——————————")

# ========== 充值&扣款流水日志 ==========
def add_recharge_log(uid, amount, way):
    now_time = time.strftime("%Y-%m-%d %H:%M:%S")
    if uid not in user_recharge_log:
        user_recharge_log[uid] = []
    user_recharge_log[uid].append(f"【{now_time}】\n操作方式：{way}\n变动金额：{amount:.4f}元\n当前余额：{get_user(uid)['balance']:.4f}元\n——————————")

# 查看个人余额
def show_user_balance(cid, uid):
    bal = get_user(uid)['balance']
    bot.send_message(cid, f"💰 个人余额\n当前剩余：{bal:.4f} 元")

# 查看个人充值记录
def show_recharge_log(cid, uid):
    if uid not in user_recharge_log or len(user_recharge_log[uid]) == 0:
        bot.send_message(cid, "📭 暂无任何充值记录")
        return
    txt = "💳 个人充值扣款历史\n"
    txt += "\n".join(user_recharge_log[uid])
    if len(txt) > 4000:
        txt = txt[:3800]
    bot.send_message(cid, txt)

# 查看个人文件消费记录
def show_user_log(cid, uid):
    if uid not in user_log or len(user_log[uid]) == 0:
        bot.send_message(cid, "📭 暂无文件处理消费记录")
        return
    txt = "📜 文件处理消费记录\n"
    txt += "\n".join(user_log[uid])
    if len(txt) > 4000:
        txt = txt[:3800]
    bot.send_message(cid, txt)

# 管理员查看全站所有充值扣款流水
def show_all_admin_recharge_log(cid):
    txt = "📋 全站用户充值扣款总流水\n"
    for uid, logs in user_recharge_log.items():
        txt += f"\n===== 用户ID：{uid} =====\n"
        txt += "\n".join(logs)
    if len(txt) > 4000:
        bot.send_message(cid, "⚠️ 日志过多，已精简展示")
        txt = txt[:3800]
    bot.send_message(cid, txt)

def show_all_admin_log(cid):
    txt = "📋 全站用户文件处理消费流水\n"
    for uid, logs in user_log.items():
        txt += f"\n===== 用户ID：{uid} =====\n"
        txt += "\n".join(logs)
    if len(txt) > 4000:
        bot.send_message(cid, "⚠️ 日志过多，已精简展示")
        txt = txt[:3800]
    bot.send_message(cid, txt)

# ====================== 主菜单 ======================
def main_menu(uid):
    user = get_user(uid)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(f"📂 格式模式：{user['mode']}", callback_data="switch_mode"),
        types.InlineKeyboardButton(f"📏 分割行数：{user['split_lines']}", callback_data="set_lines")
    )
    kb.add(
        types.InlineKeyboardButton("👤 个人中心", callback_data="user_center"),
        types.InlineKeyboardButton("💳 卡密充值", callback_data="redeem")
    )
    kb.add(
        types.InlineKeyboardButton("📎 TXT文件合并", callback_data="merge_txt"),
        types.InlineKeyboardButton("🧹 号码去重清理", callback_data="deduplicate")
    )
    if is_admin(uid):
        kb.add(types.InlineKeyboardButton("🔧 管理员后台", callback_data="admin"))
    return kb

# ====================== 个人中心菜单 ======================
def user_center_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 查询余额", callback_data="my_balance"),
        types.InlineKeyboardButton("💳 充值记录", callback_data="my_recharge")
    )
    kb.add(
        types.InlineKeyboardButton("📜 消费记录", callback_data="my_log"),
        types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back_main")
    )
    return kb

def admin_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ 用户加余额", callback_data="addbal"),
        types.InlineKeyboardButton("➖ 用户扣余额", callback_data="deductbal")
    )
    kb.add(
        types.InlineKeyboardButton("📛 生成充值卡密", callback_data="gencard"),
        types.InlineKeyboardButton("📊 用户余额列表", callback_data="userlist")
    )
    kb.add(
        types.InlineKeyboardButton("📢 全站广播消息", callback_data="broadcast"),
        types.InlineKeyboardButton("🔙 返回主菜单", callback_data="back")
    )
    kb.add(
        types.InlineKeyboardButton("📋 全部处理日志", callback_data="admin_log_all"),
        types.InlineKeyboardButton("💳 全部充值流水", callback_data="admin_recharge_all")
    )
    kb.add(types.InlineKeyboardButton("📥 批量增加余额", callback_data="batch_add_bal"))
    return kb

def insert_choose_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 批量插入手机号", callback_data="open_insert"),
        types.InlineKeyboardButton("❌ 不插入直接分割", callback_data="skip_insert")
    )
    return kb

# ====================== 机器人初始化 ======================
bot = TeleBot(BOT_TOKEN, skip_pending=True)

@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    user_state[uid] = "idle"
    bot.send_message(msg.chat.id, "✅ 机器人启动成功", reply_markup=main_menu(uid))

# ====================== 按钮回调处理 ======================
@bot.callback_query_handler(func=lambda call: True)
def handle_all(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        mid = call.message.id
        act = call.data
        bot.answer_callback_query(call.id)

        admin_list = ["addbal","deductbal","gencard","userlist","broadcast","batch_add_bal","admin_log_all","admin_recharge_all"]
        if not is_admin(uid) and act in admin_list:
            bot.send_message(cid, "❌ 您暂无管理员权限")
            return

        user_state[uid] = "idle"

        if act == "switch_mode":
            u = get_user(uid)
            u['mode'] = "VCF"
            bot.edit_message_text("✅ 文件格式模式已切换",cid,mid,reply_markup=main_menu(uid))
        elif act == "set_lines":
            bot.send_message(cid,"✏️ 请输入单次分割行数：")
            bot.register_next_step_handler(call.message, set_lines)
        elif act == "redeem":
            bot.send_message(cid,"💳 请输入您的充值卡密：")
            bot.register_next_step_handler(call.message, redeem)
        
        # 个人中心功能
        elif act == "user_center":
            bot.edit_message_text("👤 用户个人中心",cid,mid,reply_markup=user_center_menu(uid))
        elif act == "my_balance":
            show_user_balance(cid, uid)
        elif act == "my_recharge":
            show_recharge_log(cid, uid)
        elif act == "my_log":
            show_user_log(cid, uid)
        elif act == "back_main":
            bot.edit_message_text("✅ 返回机器人主菜单",cid,mid,reply_markup=main_menu(uid))

        elif act == "admin":
            bot.edit_message_text("🔧 管理员后台管理面板",cid,mid,reply_markup=admin_menu())
        elif act == "back":
            bot.edit_message_text("✅ 返回主菜单",cid,mid,reply_markup=main_menu(uid))
        elif act == "merge_txt":
            user_merge_temp[uid] = []
            user_state[uid] = "merging"
            bot.send_message(cid, "📎 依次发送所有TXT文件\n全部发送完毕后回复：完成")
        elif act == "deduplicate":
            user_state[uid] = "dedup"
            bot.send_message(cid, "🧹 请发送需要去重的号码TXT文件")
        elif act == "admin_log_all":
            show_all_admin_log(cid)
        elif act == "admin_recharge_all":
            show_all_admin_recharge_log(cid)

        elif act == "addbal":
            bot.send_message(cid,"➕ 格式：用户ID 充值金额")
            bot.register_next_step_handler(call.message,add_balance)
        elif act == "deductbal":
            bot.send_message(cid,"➖ 格式：用户ID 扣除金额")
            bot.register_next_step_handler(call.message,deduct_balance)
        elif act == "gencard":
            bot.send_message(cid,"📛 格式：生成数量 单张面额")
            bot.register_next_step_handler(call.message,gen_card)
        elif act == "userlist":
            txt = "📊 全部用户余额清单\n"
            for i in users: txt+=f"{i} → {users[i]['balance']:.4f}元\n"
            bot.send_message(cid,txt)
        elif act == "broadcast":
            bot.send_message(cid,"📢 请输入全站广播内容：")
            bot.register_next_step_handler(call.message,broadcast)
        elif act == "batch_add_bal":
            bot.send_message(cid,"📥 格式：\nID 金额\n每行一条")
            bot.register_next_step_handler(call.message,batch_add_balance)

        elif act == "open_insert":
            bot.send_message(cid,"📌 每个文件插入多少个号码？\n取消请回复：取消")
            bot.register_next_step_handler(call.message, lambda m: insert_get_num_count(m, uid))

        elif act == "skip_insert":
            if uid not in user_file:
                bot.send_message(cid, "❌ 文件已过期，请重新上传")
                return
            bot.send_message(cid,"✏️ 请输入分割文件前缀名称：")
            data = user_file[uid]
            del user_file[uid]
            bot.register_next_step_handler(call.message, lambda m: go_normal_batch(cid, uid, data['c'], m.text.strip()))

    except Exception as e:
        print(f"按钮错误: {e}")
        bot.send_message(call.message.chat.id, "❌ 操作失败，请重试")

# ====================== 插入号码流程 ======================
def insert_get_num_count(m, uid):
    txt = m.text.strip()
    if txt == "取消":
        bot.send_message(m.chat.id, "✅ 已取消插入操作")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    try:
        num = int(txt)
        user_insert_info[uid] = {"per_count": num, "old_name": user_file[uid]['n'], "content": user_file[uid]['c']}
        bot.send_message(m.chat.id, "📞 请发送要循环插入的手机号\n取消回复：取消")
        bot.register_next_step_handler(m, insert_get_phone_list)
    except:
        bot.send_message(m.chat.id, "❌ 请输入纯数字！")
        bot.register_next_step_handler(m, lambda mm: insert_get_num_count(mm, uid))

def insert_get_phone_list(m, uid):
    txt = m.text.strip()
    if txt == "取消":
        bot.send_message(m.chat.id, "✅ 已取消插入操作")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    phones = re.findall(r"1[3-9]\d{9}", txt)
    if len(phones) == 0:
        bot.send_message(m.chat.id, "❌ 未识别到有效手机号，请重新发送")
        bot.register_next_step_handler(m, lambda mm: insert_get_phone_list(mm, uid))
        return
    user_insert_info[uid]['phone_list'] = phones
    bot.send_message(m.chat.id, "✏️ 请输入生成文件名称\n原文件名请回复：原文件名")
    bot.register_next_step_handler(m, insert_finish_name)

def insert_finish_name(m, uid):
    name = m.text.strip()
    if name == "取消":
        bot.send_message(m.chat.id, "✅ 已取消插入操作")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    if name == "原文件名":
        fname = user_insert_info[uid]['old_name']
    else:
        fname = name
    go_insert_phone_batch(m.chat.id, uid, fname)

# ====================== 批量10个一组发送+进度提示 ======================
def go分割批量发送(cid, uid, content, name):
    user = get_user(uid)
    lines = [x for x in content.splitlines() if x.strip()]
    total = len(lines)
    fee = total * PRICE_SPLIT

    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 余额不足，本次分割扣费：{fee:.4f} 元")
        return

    user['balance'] -= fee
    add_log(uid, f"TXT分割{user['split_lines']}行", total, fee)

    chunks = [lines[i:i+user['split_lines']] for i in range(0, total, user['split_lines'])]
    total_page = len(chunks)
    bot.send_message(cid,f"📄 开始分割，总共{total_page}份文件\n每10份批量发送一次")

    send_now = 0
    for idx, chunk in enumerate(chunks, 1):
        send_now +=1
        txt = "\n".join(chunk)
        f = BytesIO(txt.encode())
        f.name = f"{name}_{idx}.txt"
        bot.send_document(cid, f)
        
        # 每满10个提示一次进度
        if send_now % SEND_BATCH == 0:
            bot.send_message(cid,f"✅ 已发送 {send_now} 份 / 总计{total_page}份")
    
    # 收尾提示剩余全部发完
    bot.send_message(cid,f"🎉 全部分割完成！累计发送 {total_page} 份文件")

def go_normal_batch(cid, uid, content, name):
    go分割批量发送(cid, uid, content, name)

def go_insert_phone_batch(cid, uid, fname):
    info = user_insert_info[uid]
    per = info['per_count']
    phones = info['phone_list']
    content = info['content']
    lines = [x for x in content.splitlines() if x.strip()]
    total = len(lines)
    user = get_user(uid)
    fee = total * PRICE_SPLIT

    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 余额不足，本次扣费：{fee:.4f} 元")
        return

    user['balance'] -= fee
    add_log(uid, f"分割+插入号码{per}条", total, fee)

    chunks = [lines[i:i+user['split_lines']] for i in range(0, total, user['split_lines'])]
    total_page = len(chunks)
    bot.send_message(cid,f"📄 开始分割插入，总共{total_page}份文件\n每10份批量发送一次")
    
    send_now = 0
    for idx, chunk in enumerate(chunks, 1):
        send_now +=1
        add_list = random.sample(phones, per)
        chunk += add_list
        txt = "\n".join(chunk)
        f = BytesIO(txt.encode())
        f.name = f"{fname}_{idx}.txt"
        bot.send_document(cid, f)

        if send_now % SEND_BATCH == 0:
            bot.send_message(cid,f"✅ 已发送 {send_now} 份 / 总计{total_page}份")
    
    bot.send_message(cid,f"🎉 全部插入分割完成！累计发送 {total_page} 份")
    del user_insert_info[uid]

# ====================== 文本全局监听 ======================
@bot.message_handler(func=lambda msg: True)
def handle_text(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    text = msg.text.strip()

    if uid in user_state and user_state[uid] == "merging" and text == "完成":
        merge_finish(msg)
        return

# ====================== 卡密充值 ======================
def redeem(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    card = msg.text.strip()
    global cards
    if card not in cards:
        bot.send_message(cid, "❌ 无效卡密，请重新输入")
        return
    money = float(cards[card])
    del cards[card]
    get_user(uid)['balance'] += money
    add_recharge_log(uid, money, "卡密自助充值")
    bot.send_message(cid, f"✅ 充值成功！\n到账金额：{money:.4f} 元\n当前余额：{get_user(uid)['balance']:.4f}")

# 管理员手动加余额
def add_balance(msg):
    try:
        uid, num = msg.text.split()
        uid = int(uid)
        num = float(num)
        get_user(uid)['balance'] += num
        add_recharge_log(uid, num, "管理员手动加款")
        bot.send_message(msg.chat.id, f"✅ 已给用户{uid}增加{num:.4f}元，已记录后台流水")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误：ID 金额")

# 管理员手动扣余额
def deduct_balance(msg):
    try:
        uid, num = msg.text.split()
        uid = int(uid)
        num = float(num)
        get_user(uid)['balance'] -= num
        add_recharge_log(uid, -num, "管理员手动扣款")
        bot.send_message(msg.chat.id, f"✅ 已扣除用户{uid}{num:.4f}元，已记录后台流水")
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误：ID 金额")

# 批量加款
def batch_add_balance(msg):
    lines = msg.text.strip().splitlines()
    for line in lines:
        try:
            uid, num = line.split()
            uid = int(uid)
            num = float(num)
            get_user(uid)['balance'] += num
            add_recharge_log(uid, num, "管理员批量加款")
        except:
            continue
    bot.send_message(msg.chat.id, "余额操作完成，全部已记录流水")

# 生成卡密
def gen_card(msg):
    try:
        count, money = msg.text.split()
        count = int(count)
        money = float(money)
        global cards
        txt = ""
        for i in range(count):
            c = ''.join(random.sample('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ',12))
            cards[c] = money
            txt += c+"\n"
        bot.send_message(msg.chat.id, f"✅ 生成{count}张 {money:.4f}元卡密\n"+txt)
    except:
        bot.send_message(msg.chat.id, "❌ 格式错误：数量 金额")

# 全站广播
def broadcast(msg):
    all_uid = users.keys()
    succ = 0
    for u in all_uid:
        try:
            bot.send_message(u, msg.text)
            succ +=1
        except:
            continue
    bot.send_message(msg.chat.id,f"📢 广播发送完成，成功送达{succ}位用户")

# 设置分割行数
def set_lines(msg):
    try:
        num = int(msg.text.strip())
        get_user(msg.from_user.id)['split_lines'] = num
        bot.send_message(msg.chat.id, f"✅ 分割行数已设置为 {num}")
    except:
        bot.send_message(msg.chat.id, "❌ 请输入数字")

# ====================== 文件合并处理 ======================
def merge_finish(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    if uid not in user_merge_temp or len(user_merge_temp[uid]) == 0:
        bot.send_message(cid, "❌ 未收集到任何文件")
        user_state[uid] = "idle"
        return

    all_lines = []
    for content in user_merge_temp[uid]:
        lines = [x.strip() for x in content.splitlines() if x.strip()]
        all_lines.extend(lines)

    total = len(all_lines)
    fee = total * PRICE_MERGE
    bot_user = get_user(uid)

    if bot_user['balance'] < fee:
        bot.send_message(cid, f"❌ 合并需 {fee:.4f} 元，余额不足")
        del user_merge_temp[uid]
        user_state[uid] = "idle"
        return

    bot_user['balance'] -= fee
    add_log(uid, "多文件TXT合并", total, fee)

    out_content = "\n".join(all_lines)
    file = BytesIO(out_content.encode('utf-8'))
    file.name = f"合并结果_{int(time.time())}.txt"
    bot.send_document(cid, file)
    
    del user_merge_temp[uid]
    user_state[uid] = "idle"

@bot.message_handler(content_types=['document'])
def get_doc(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    try:
        file_info = bot.get_file(msg.document.file_id)
        down = bot.download_file(file_info.file_path)
        text = down.decode('utf-8', errors='ignore')

        if user_state.get(uid) == "merging":
            user_merge_temp[uid].append(text)
            bot.send_message(cid, "✅ 文件已收录，请继续发送或回复：完成")
        elif user_state.get(uid) == "dedup":
            old = len(text.splitlines())
            new = list(set(text.splitlines()))
            new_cnt = len(new)
            fee = new_cnt * PRICE_DEDUP
            u = get_user(uid)
            if u['balance'] < fee:
                bot.send_message(cid, f"❌ 余额不足，去重扣费{fee:.4f}元")
                return
            u['balance'] -= fee
            add_log(uid, "号码去重", old, fee)
            out = "\n".join(new)
            f = BytesIO(out.encode())
            f.name = "去重结果.txt"
            bot.send_document(cid, f)
            user_state[uid] = "idle"
        else:
            lines = [x for x in text.splitlines() if x.strip()]
            user_file[uid] = {"n": msg.document.file_name, "c": text}
            bot.send_message(cid, "📄 文件已读取，请选择操作", reply_markup=insert_choose_menu())
    except Exception as e:
        print(e)
        bot.send_message(cid, "❌ 文件读取失败")

bot.polling(none_stop=True)
