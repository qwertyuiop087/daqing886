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
            bot.register_next_step_handler(call.message, lambda m: go(m, uid, data, m.text))
            
        elif act == "original":
            if uid not in user_file:
                bot.send_message(cid, "❌ 请先上传文件")
                return
            data = user_file[uid]
            del user_file[uid]
            go(None, uid, data, data['n'])
            
    except Exception as e:
        print(e)

# ====================== 功能 ======================
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

# ====================== 文件处理 ======================
@bot.message_handler(content_types=['document'])
def file(msg):
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

# ====================== 发送：10个一批，每批间隔3秒 ======================
def go(m, uid, s, p):
    try:
        cid = m.chat.id if m else None
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

        # 10个一组发送
        batch_size = 10
        for i in range(0, total, batch_size):
            batch = files[i:i+batch_size]
            # 发这一组
            for f in batch:
                bot.send_document(cid, f)
                time.sleep(0.2)
            # 每批停 3 秒
            time.sleep(3)
        
        bot.send_message(cid, f"✅ 发送完成！余额：{u['balance']}")
        
    except Exception as e:
        bot.send_message(cid, f"❌ 发送失败：{e}")

# ====================== 启动 ======================
if __name__ == "__main__":
    print("✅ 机器人启动成功")
    bot.polling(none_stop=True)
