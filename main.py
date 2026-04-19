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

# ====================== 你的配置 ======================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834
# ======================================================

# 全局数据
user_file = {}
users = {}
cards = {}

# 合并功能临时存储
merge_temp = {}

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
    # 新增功能按钮
    kb.add(
        types.InlineKeyboardButton("📎 合并Txt", callback_data="merge_txt"),
        types.InlineKeyboardButton("🧹 号码去重", callback_data="deduplicate")
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

# ====================== 机器人初始化 ======================
bot = TeleBot(BOT_TOKEN)

# ====================== 启动命令 ======================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
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

        admin_list = ["addbal","deductbal","gencard","userlist","broadcast","batch_add_bal"]
        if not is_admin(uid) and act in admin_list:
            bot.send_message(cid, "❌ 无权限")
            return

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

        # ====== 新增功能 ======
        elif act == "merge_txt":
            merge_temp[uid] = []
            bot.send_message(cid, "📎 请依次发送需要合并的 TXT 文件\n发送完毕后回复：完成")
        elif act == "deduplicate":
            bot.send_message(cid, "🧹 请发送需要去重的号码 TXT 文件")

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
        get_user(int(i))['balance']+=int(a)
        bot.send_message(m.chat.id,"✅ 成功")
    except:
        bot.send_message(m.chat.id,"❌ 格式错误")

def deduct_balance(m):
    try:
        i,a=m.text.split()
        get_user(int(i))['balance']-=int(a)
        bot.send_message(m.chat.id,"✅ 成功")
    except:
        bot.send_message(m.chat.id,"❌ 格式错误")

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

# ====================== 合并 TXT 功能 ======================
@bot.message_handler(func=lambda m: m.from_user.id in merge_temp and m.text and m.text.strip() == "完成")
def merge_finish(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    if uid not in merge_temp or len(merge_temp[uid]) == 0:
        bot.send_message(cid, "❌ 未收集到任何文件")
        return

    all_lines = []
    for content in merge_temp[uid]:
        lines = [x.strip() for x in content.splitlines() if x.strip()]
        all_lines.extend(lines)

    total = len(all_lines)
    fee =(total + 9999) // 10000 * 2

    user = get_user(uid)
    if user['balance'] < fee:
        bot.send_message(cid, f"❌ 合并需 {fee} 元，余额不足")
        del merge_temp[uid]
        return

    # 扣费
    user['balance'] -= fee

    # 生成文件
    out_content = "\n".join(all_lines)
    bio = BytesIO(out_content.encode('utf-8'))
    bio.name = f"{total}.txt"

    bot.send_document(cid, bio, caption=f"✅ 文件合并成功！\n总行数：{total}\n扣费：{fee} 元\n剩余余额：{user['balance']}")
    del merge_temp[uid]

# ====================== 号码去重功能 ======================
@bot.message_handler(content_types=['document'])
def handle_file(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    try:
        # 先处理原有分割功能
        if uid not in merge_temp:
            file_process(msg)
            return

        # 处理合并收集
        if not msg.document.file_name.endswith('.txt'):
            bot.send_message(cid, "❌ 仅支持 TXT 文件")
            return

        file_info = bot.get_file(msg.document.file_id)
        data = bot.download_file(file_info.file_path)
        text = data.decode('utf-8', 'ignore')
        merge_temp[uid].append(text)
        bot.send_message(cid, f"✅ 已接收第 {len(merge_temp[uid])} 个文件\n继续发送或回复：完成")

    except Exception as e:
        bot.send_message(cid, f"❌ 处理失败：{e}")

# ====================== 去重处理 ======================
@bot.message_handler(content_types=['document'], func=lambda m: m.document.file_name.endswith('.txt'))
def dedup_process(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    user = get_user(uid)

    try:
        file_info = bot.get_file(msg.document.file_id)
        data = bot.download_file(file_info.file_path)
        text = data.decode('utf-8', 'ignore')

        # 提取手机号
        phones = re.findall(r"1[3-9]\d{9}", text)
        total_raw = len(phones)

        # 去重
        unique_phones = sorted(list(set(phones)))
        total_unique = len(unique_phones)

        # 计费：1万行1元
        fee =(total_raw + 9999) // 10000 * 1

        if user['balance'] < fee:
            bot.send_message(cid, f"❌ 去重需 {fee} 元，余额不足")
            return

        user['balance'] -= fee

        out_content = "\n".join(unique_phones)
        bio = BytesIO(out_content.encode('utf-8'))
        bio.name = f"去重_{total_unique}.txt"

        bot.send_document(
            cid, bio,
            caption=f"✅ 去重完成！\n原行数：{total_raw}\n去重后：{total_unique}\n扣费：{fee} 元\n余额：{user['balance']}"
        )

    except Exception as e:
        bot.send_message(cid, f"❌ 去重失败：{e}")

# ====================== 原有文件处理 ======================
def file_process(msg):
    try:
        uid=msg.from_user.id
        u=get_user(uid)
        if uid in user_file: del user_file[uid]
            
        f=bot.get_file(msg.document.file_id)
        d=bot.download_file(f.file_path)
        n=msg.document.file_name.rsplit('.',1)[0]
        c=""
        
        if msg.document.file_name.endswith('.txt'):
            c=d.decode('utf-8','ignore')
        elif msg.document.file_name.endswith('.zip'):
            with zipfile.ZipFile(BytesIO(d)) as zf:
                for fn in zf.namelist():
                    if fn.endswith('.txt'):
                        c+=zf.read(fn).decode('utf-8','ignore')
                        
        lines=[x.strip() for x in c.splitlines() if x.strip()]
        c="\n".join(lines)
        fee=(len(lines)+9999)//10000*4
        
        if u['balance']<fee:
            bot.send_message(msg.chat.id,f"❌ 需{fee}元，余额不足")
            return
            
        user_file[uid]={'c':c,'n':n,'fee':fee}
        
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("自定义名称",callback_data="custom"),
            types.InlineKeyboardButton("原文件名",callback_data="original")
        )
        bot.send_message(msg.chat.id,f"✅ 需扣费 {fee} 元",reply_markup=kb)
        
    except Exception as e:
        bot.send_message(msg.chat.id,f"❌ 文件处理失败：{e}")

# ====================== 发送：10个一批，间隔3秒 ======================
def go(cid, uid, s, p):
    try:
        u = get_user(uid)
        u['balance'] -= s['fee']
        
        con = s['c']
        step = u['split_lines']
        mode = u['mode']
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
            media_group = []
            for f in batch:
                media_group.append(types.InputMediaDocument(f))
            bot.send_media_group(cid, media=media_group)
            sent_num = min(i+batch_size, total)
            bot.send_message(cid, f"✅ 已发送 {sent_num}/{total}")
            if i + batch_size < total:
                time.sleep(3)
        
        bot.send_message(cid, f"✅ 发送完成！余额：{u['balance']}")
        
    except Exception as e:
        bot.send_message(cid, f"❌ 发送失败：{e}")

# ====================== 机器人运行（自动重启） ======================
def run_bot():
    while True:
        try:
            print("✅ 机器人启动成功")
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except (ReadTimeout, ConnectionError, Exception) as e:
            print(f"网络错误：{e}")
            traceback.print_exc()
            time.sleep(10)
            continue

# ====================== 核心：端口监听（解决Render端口检测） ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    print(f"✅ 端口监听: 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ====================== 启动 ======================
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_web()
