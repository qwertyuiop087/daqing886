import os
import re
import zipfile
import random
import time
import traceback
import threading
from io import BytesIO
from flask import Flask
from telebot import TeleBot, types
from requests.exceptions import ReadTimeout, ConnectionError
import logging

# 关闭 Flask 警告
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
os.environ['FLASK_ENV'] = 'production'

# ====================== 你的TOKEN配置 ======================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834
# ======================================================

# 全局数据
user_file = {}
users = {}
cards = {}
user_merge_temp = {}
user_state = {}
# 新增插入手机号临时变量
user_insert_info = {}
# ========== 新增：用户操作处理日志 ==========
user_log = {}

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

# ========== 新增：日志写入函数 ==========
def add_log(uid, operate, line_num, cost):
    now_time = time.strftime("%Y-%m-%d %H:%M:%S")
    if uid not in user_log:
        user_log[uid] = []
    user_log[uid].append(f"【{now_time}】\n操作：{operate}\n处理行数：{line_num}\n扣费：{cost}元\n剩余余额：{get_user(uid)['balance']}\n——————————")

# 用户查看自身记录
def show_user_log(cid, uid):
    if uid not in user_log or len(user_log[uid]) == 0:
        bot.send_message(cid, "📭 暂无任何处理记录")
        return
    txt = "📜 你的历史处理记录\n"
    txt += "\n".join(user_log[uid][-20:])
    if len(txt) > 4000:
        txt = txt[:3800]
    bot.send_message(cid, txt)

# 管理员查看全部用户日志
def show_all_admin_log(cid):
    txt = "📋 全站所有用户处理流水\n"
    for uid, logs in user_log.items():
        txt += f"\n===== 用户ID：{uid} =====\n"
        txt += "\n".join(logs[-5:])
    if len(txt) > 4000:
        bot.send_message(cid, "⚠️ 日志过多，已精简展示")
        txt = txt[:3800]
    bot.send_message(cid, txt)

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
    kb.add(
        types.InlineKeyboardButton("📎 合并Txt", callback_data="merge_txt"),
        types.InlineKeyboardButton("🧹 号码去重", callback_data="deduplicate")
    )
    # 新增处理记录按钮
    kb.add(types.InlineKeyboardButton("📜 处理记录", callback_data="my_log"))
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
    # 新增管理员全站日志
    kb.add(types.InlineKeyboardButton("📋 全部处理日志", callback_data="admin_log_all"))
    kb.add(types.InlineKeyboardButton("📥 批量加余额", callback_data="batch_add_bal"))
    return kb

# 新增 插入选择菜单
def insert_choose_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ 插入手机号", callback_data="open_insert"),
        types.InlineKeyboardButton("❌ 不插入，直接分割", callback_data="skip_insert")
    )
    return kb

# ====================== 机器人初始化 ======================
bot = TeleBot(BOT_TOKEN, skip_pending=True)

# ====================== 启动命令 ======================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    user_state[uid] = "idle"
    bot.send_message(msg.chat.id, "✅ 机器人已启动", reply_markup=main_menu(uid))

# ====================== 统一按钮回调 ======================
@bot.callback_query_handler(func=lambda call: True)
def handle_all(call):
    try:
        uid = call.from_user.id
        cid = call.message.chat.id
        mid = call.message.id
        act = call.data
        bot.answer_callback_query(call.id)

        admin_list = ["addbal","deductbal","gencard","userlist","broadcast","batch_add_bal","admin_log_all"]
        if not is_admin(uid) and act in admin_list:
            bot.send_message(cid, "❌ 无权限")
            return

        user_state[uid] = "idle"

        if act == "switch_mode":
            u = get_user(uid)
            u['mode'] = "VCF" if u['mode']=="TXT" else "TXT"
            bot.edit_message_text("✅ 模式已切换",cid,mid,reply_markup=main_menu(uid))
        elif act == "set_lines":
            bot.send_message(cid,"✏️ 输入行数：")
            bot.register_next_step_handler(call.message,lambda m:set_lines(m,uid))
        elif act == "balance":
            bot.edit_message_text(f"💰 余额：{get_user(uid)['balance']}",cid,mid,reply_markup=main_menu(uid))
        elif act == "redeem":
            bot.send_message(cid,"💳 输入卡密：")
            bot.register_next_step_handler(call.message,lambda m:redeem(m,uid))
        elif act == "admin":
            bot.edit_message_text("🔧 管理面板",cid,mid,reply_markup=admin_menu())
        elif act == "back":
            bot.edit_message_text("✅ 主菜单",cid,mid,reply_markup=main_menu(uid))
        elif act == "merge_txt":
            user_merge_temp[uid] = []
            user_state[uid] = "merging"
            bot.send_message(cid, "📎 请依次发送需要合并的 TXT 文件\n发送完毕后回复：完成")
        elif act == "deduplicate":
            user_state[uid] = "dedup"
            bot.send_message(cid, "🧹 请发送需要去重的号码 TXT 文件")
        # 新增日志回调
        elif act == "my_log":
            show_user_log(cid, uid)
        elif act == "admin_log_all":
            show_all_admin_log(cid)

        elif act == "addbal":
            bot.send_message(cid,"➕ ID 金额")
            bot.register_next_step_handler(call.message,add_balance)
        elif act == "deductbal":
            bot.send_message(cid,"➖ ID 金额")
            bot.register_next_step_handler(call.message,deduct_balance)
        elif act == "gencard":
            bot.send_message(cid,"📛 数量 金额")
            bot.register_next_step_handler(call.message,gen_card)
        elif act == "userlist":
            txt = "📊 用户\n"
            for i in users: txt+=f"{i} → {users[i]['balance']}元\n"
            bot.send_message(cid,txt)
        elif act == "broadcast":
            bot.send_message(cid,"📢 输入内容：")
            bot.register_next_step_handler(call.message,broadcast)
        elif act == "batch_add_bal":
            bot.send_message(cid,"📥 格式：\nID 金额\nID 金额")
            bot.register_next_step_handler(call.message,batch_add_balance)

        # 新增插入手机号流程
        elif act == "open_insert":
            bot.send_message(cid,"📌 请输入**每个分割文件插入多少个手机号**\n输入错误请回复：取消")
            bot.register_next_step_handler(call.message, insert_get_num_count)
        elif act == "skip_insert":
            if uid not in user_file:
                bot.send_message(cid, "❌ 文件已失效，请重新上传")
                return
            bot.send_message(cid,"✏️ 输入前缀：")
            data = user_file[uid]
            del user_file[uid]
            bot.register_next_step_handler(call.message, lambda m: go_normal(cid, uid, data, m.text.strip()))

        elif act == "custom":
            if uid not in user_file:
                bot.send_message(cid, "❌ 请先上传文件")
                return
            bot.send_message(cid,"✏️ 输入前缀：")
            data = user_file[uid]
            del user_file[uid]
            bot.register_next_step_handler(call.message, lambda m: go(cid, uid, data, m.text.strip()))
        elif act == "original":
            if uid not in user_file:
                bot.send_message(cid, "❌ 请先上传文件")
                return
            data = user_file[uid]
            del user_file[uid]
            go(cid, uid, data, data['n'])
    except Exception as e:
        print(f"按钮错误: {e}")
        bot.send_message(call.message.chat.id, "❌ 操作失败，请重试")

# ====================== 功能函数 ======================
def set_lines(m,uid):
    passwd = m.text.strip()
    if passwd == "取消":
        bot.send_message(m.chat.id,"✅ 已取消操作，请重新上传文件")
        return
    try:
        get_user(uid)['split_lines']=int(m.text)
        bot.send_message(m.chat.id,"✅ 已设置")
    except:
        bot.send_message(m.chat.id,"❌ 请输入数字")

def redeem(m,uid):
    c=m.text.strip()
    if c in cards and not cards[c]['used']:
        get_user(uid)['balance']+=cards[c]['amount']
        cards[c]['used']=True
        bot.send_message(m.chat.id,"✅ 充值成功")
    else:
        bot.send_message(m.chat.id,"❌ 卡密无效")

def add_balance(m):
    try:
        i,a=m.text.split()
        get_user(int(i))
        users[int(i)]['balance']+=get_user(int(i))
        app.send_message(m.chat.id,"✅ 成功")
    except:
        bot.send_message(m.chat.id,"❌ 格式错误")

def deduct_balance(m):
    try:
        i,a=m.text.split()
        get_user(int(i))['balance']-=int(a)
        bot.send_message(m.chat.id,"✅ 成功")
    except:
        bot.send_message(m.chat.id,"❌ ")

def gen_card(m):
    try:
        c,a=m.text.split()
        l=[]
        for i in range(int(c)):
            k=f"Card{random.randint(100000,999999)}"
            cards[k]={'used':0,'amount':int(a)}
            l.append(k)
        bot.send_message(m.chat.id,"\n".join(l))
    except:
        bot.send_message(m.chat.id,"❌ 格式错误")

def broadcast(m):
    t=0
    for i in users:
        try:
            bot.send_message(i,f"📢 广播\n{m.text}")
            t+=1
        except:
            pass
    bot.send_message(m.chat.id,f"✅ 发送 {t} 人")

def batch_add_balance(m):
    s,f=0,0
    for line in m.text.strip().splitlines():
        try:
            i,a=line.split()
            get_user(int(i))['balance']+=int(a)
            s+=1
        except:
            f+=1
    bot.send_message(m.chat.id,f"✅ 成功{s} 失败{f}")

# ====================== 新增 插入手机号流程 ======================
def insert_get_num_count(m, uid):
    txt = m.text.strip()
    if txt == "取消":
        bot.send_message(m.chat.id, "✅ 已取消插入，请重新上传文件")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    try:
        insert_per_file = int(txt)
        user_insert_info[uid]['per_count'] = insert_per_file
        bot.send_message(m.chat.id, f"📞 请发送需要循环插入的所有手机号\n输入错误回复：取消")
        bot.register_next_step_handler(m, insert_get_phone_list)
    except:
        bot.send_message(m.chat.id, "❌ 请输入纯数字！")
        bot.register_next_step_handler(m, insert_get_num_count)

def insert_get_phone_list(m, uid):
    txt = m.text.strip()
    if txt == "取消":
        bot.send_message(m.chat.id, "✅ 已取消插入，请重新上传文件")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    phones = re.findall(r"1[3-9]\d{9}", txt)
    if len(phones) == 0:
        bot.send_message(m.chat.id, "❌ 未检测到有效手机号，请重新发送")
        bot.register_next_step_handler(m, insert_get_phone_list)
        return
    user_insert_info[uid]['phone_list'] = phones
    bot.send_message(m.chat.id, "✏️ 请输入分割文件自定义名称\n不想改名回复：原文件名")
    bot.register_next_step_handler(m, insert_finish_name)

def insert_finish_name(m, uid):
    name = m.text.strip()
    if name == "取消":
        bot.send_message(m.chat.id, "✅ 已取消插入，请重新上传文件")
        if uid in user_insert_info: del user_insert_info[uid]
        return
    if name == "原文件名":
        fname = user_insert_info[uid]['old_name']
    else:
        fname = name
    go_insert_phone(m.chat.id, uid, fname)

# ====================== 文本消息处理 ======================
@bot.message_handler(func=lambda msg: True)
def handle_text(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    text = msg.text.strip()

    if uid in user_state and user_state[uid] == "merging" and text == "完成":
        merge_finish(msg)
        return

# ====================== 合并完成 ======================
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
    fee = (total + 9999) // 10000 * 2
    user = get_user(uid)

    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 合并需 {fee} 元",余额不足)
        del user_merge_temp[uid]
        user_state[uid] = "idle"
        return

    user['balance'] -= fee
    # ========== 写入合并日志 ==========
    add_log(uid, "多文件合并整理", total, fee)

    out_content = "\n".join(all_lines)
    bio = BytesIO(out_content.encode('utf-8'))
    bio.name = f"{total}.txt"

    bot.send_document(cid, bio, caption=f"✅ 文件合并成功！\n总行数：{total}\n扣费：{fee} 元\n余额：{user['balance']}")
    del user_merge_temp[uid]
    user_state[uid] = "idle"

# ====================== 处理 ZIP 文件 ======================
def process_zip(msg, zip_data):
    uid = msg.from_user.id
    cid = msg.chat.id
    all_content = []

    try:
        with zipfile.ZipFile(BytesIO(zip_data), 'r') as zf:
            for filename in zf.namelist():
                if filename.lower().endswith('.txt'):
                    try:
                        with zf.open(filename) as f:
                            text = f.read().decode('utf-8', 'ignore')
                            all_content.append(text)
                    except:
                        continue

        if not all_content:
            bot.send_message(cid, "❌ 压缩包内未找到任何 TXT 文件")
            return

        full_text = "\n".join(all_content)
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)
        file_process(msg, clean_text)

    except Exception as e:
        bot.send_message(cid, f"❌ ZIP 处理失败：{str(e)}")

# ====================== 文件处理 ======================
@bot.message_handler(content_types=['document'])
def handle_all_files(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    try:
        file_info = bot.get_file(msg.document.file_id)
        data = bot.download_file(file_info.file_path)
        name = msg.document.file_name.lower()

        if name.endswith('.zip'):
            process_zip(msg, data)
            return

        if not name.endswith('.txt'):
            bot.send_message(cid, "❌ 仅支持 TXT / ZIP 文件")
            return

        text = data.decode('utf-8', 'ignore')

        if uid in user_state and user_state[uid] == "merging":
            user_merge_temp[uid].append(text)
            bot.send_message(cid, f"✅ 已接收第 {len(user_merge_temp[uid])} 个文件\n继续发送或回复：完成")
            return

        if uid in user_state and user_state[uid] == "dedup":
            dedup_process(msg, text)
            return

        lines = [x.strip() for x in text.splitlines() if x.strip()]
        c = "\n".join(lines)
        fee = (len(lines) + 9999) // 10000 * 4
        u = get_user(uid)
        if u['balance'] < fee:
            bot.send_message(msg.chat.id, f"❌ 需{fee}元，余额不足")
            return

        fname = msg.document.file_name.rsplit('.', 1)[0]
        user_file[uid] = {'c': c, 'n': fname, 'fee': fee}
        user_insert_info[uid] = {"old_name": fname, "content": c}

        bot.send_message(cid, f"✅ 文件解析完成，需扣费 {fee} 元\n请选择操作", reply_markup=insert_choose_menu())

    except Exception as e:
        bot.send_message(cid, f"❌ 处理失败：{e}")

# ====================== 号码去重 ======================
def dedup_process(msg, text):
    uid = msg.from_user.id
    cid = msg.chat.id
    user = get_user(uid)

    phones = re.findall(r"1[3-9]\d{9}", text)
    total_raw = len(lines)
    unique_phones = sorted(list(set(phones)))
    total_unique = len(unique_phones)

    fee = (total_raw + 9999) // 10000
    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 去重需 {fee} 元，余额不足")
        user_state[uid] = "idle"
        return

    user['balance'] -= fee
    # ========== 写入去重日志 ==========
    add_log(uid, "号码去重清理", total_raw, fee)

    out_content = "\n".join(unique_phones)
    bio = BytesIO(out_content.encode('utf-8'))
    bio.name = f"去重_{total_unique}.txt"

    bot.send_document(cid, bio, caption=f"✅ 去重完成！\n原行数：{total_raw}\n去重后：{total_unique}\n扣费：{fee} 元\n余额：{user['balance']}")
    user_state[uid] = "idle"

# ====================== 原有无插入分割 ======================
def go_normal(cid, uid, s, p):
    try:
        u = get_user(uid)
        u['balance'] -= s['fee']
        con = s['c']
        step = u['split_lines']
        mode = u['mode']
        lines = con.splitlines()
        # ========== 写入普通分割日志 ==========
        add_log(uid, "TXT常规分割", len(lines), s['fee'])

        files = []

        if mode == "TXT":
            ls = con.splitlines()
            for i in range(0, len(ls), step):
                b = BytesIO("\n".join(ls[i:i+step]).encode('utf-8'))
                b.name = f"{p}_{i//step+1}.txt"
                files.append(b)
        else:
            ps = re.findall(r"1[3-9]\d{9}", con)
            for i in range(0, len(ps), step):
                v = ""
                for pn in ps[i:i+step]:
                    v += f"BEGIN:VCARD\nFN:{random_name()}\nTEL:{pn}\nEND:VCARD\n"
                b = BytesIO(v.encode('utf-8'))
                b.name = f"{p}_{i//step+1}.vcf"
                files.append(b)

        total = len(files)
        bot.send_message(cid, f"✅ 共 {total} 个，每10个一批发送")
        batch_size = 10
        for i in range(0, total, batch_size):
            batch = files[i:i+batch_size]
            media_group = [types.InputMediaDocument(f) for f in batch]
            bot.send_media_group(cid, media=media_group)
            sent_num = min(i+batch_size, total)
            bot.send_message(cid, f"✅ 已发送 {sent_num}/{total}")
            if i + batch_size < total:
                time.sleep(3)

        bot.send_message(cid, f"✅ 分割完成！余额：{u['balance']}")
    except Exception as e:
        bot.send_message(cid, f"❌ 发送失败：{str(e)}")

# ====================== 循环插入手机号完整版 ======================
def go_insert_phone(cid, uid, filename):
    data = user_insert_info[uid]
    u = get_user(uid)
    content = data['content']
    per_insert = data['per_count']
    phone_list = data['phone_list']
    step = get_user(uid)['split_lines']
    mode = u['mode']

    u['balance'] -= user_file[uid]['fee']
    lines = content.splitlines()
    # ========== 写入插入号码分割日志 ==========
    add_log(uid, "分割+循环追加手机号", len(lines), user_file[uid]['fee'])

    files = []
    log_text = "📋 手机号插入详细统计\n"
    phone_index = 0

    file_no = 1
    for start in range(0, len(lines), step):
        chunk = lines[start : start+step]
        insert_now = []
        for _ in range(per_insert):
            use_phone = phone_list[phone_index % len(phone_list)]
            insert_now.append(use_phone)
            log_text += f"第{file_no}号文件 → 插入号码：{use_phone}\n"
            phone_index += 1

        new_chunk = chunk + insert_now
        file_text = "\n".join(new_chunk)

        bio = BytesIO(file_text.encode('utf-8'))
        bio.name = f"{filename}_{file_no}.txt"
        files.append(bio)
        file_no += 1

    total = len(files)
    bot.send_message(cid, f"✅ 插入处理完成，共{total}个文件，每10个批量发送")

    batch_size = 10
    for i in range(0, total, batch_size):
        batch = files[i:i+batch_size]
        media_group = [types.InputMediaDocument(f) for f in batch]
        bot.send_media_group(cid, media=media_group)
        sent = min(i+batch_size, total)
        bot.send_message(cid, f"✅ 已发送 {sent}/{total}")
        if i+batch_size < total:
            time.sleep(3)

    bot.send_message(cid, log_text)
    bot.send_message(cid, f"✅ 全部文件发送完毕！剩余余额：{u['balance']}")
    del user_insert_info[uid]

# ====================== 原有分割函数 ======================
def go(cid, uid, s, p):
    go_normal(cid, uid, s, p)

# ====================== 机器人运行 ======================
def run_bot():
    while True:
        try:
            print("✅ 机器人启动成功")
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except:
            time.sleep(10)
            continue

# ====================== Flask 端口监听 ======================
app = Flask(__name__)
@app.route("/")
def home():
    return "Bot Running"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ====================== 启动 ======================
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
