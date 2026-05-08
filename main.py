import os
import re
import time
import random
import zipfile
from io import BytesIO
import telebot
from telebot.types import InputMediaDocument
from datetime import datetime, timezone, timedelta

BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834

PRICE_SPLIT = 0.0004
PRICE_INSERT = 0.0004
PRICE_MERGE = 0.0002
PRICE_DEDUP = 0.0002
BATCH_SIZE = 10

user_file = {}
users = {}
cards = {}
user_merge = {}
user_state = {}
user_insert = {}
log_user = {}
log_recharge = {}

def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0.0, "mode":"TXT", "line":100}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

def add_log(uid, txt, num, cost):
    t = get_beijing_time_str()
    log_user[uid] = log_user.get(uid,[]) + [f"[{t}]用户{uid}｜{txt}｜{num}行｜扣费{cost:.4f}｜剩余余额{get_user(uid)['balance']:.4f}"]

def add_rc(uid,money):
    t = get_beijing_time_str()
    log_recharge[uid] = log_recharge.get(uid,[]) + [f"[{t}]用户{uid}｜后台批量充值+{money:.4f}｜剩余余额{get_user(uid)['balance']:.4f}"]

# 标准北京时间
def get_beijing_time_str():
    utc_now = datetime.now(timezone.utc)
    beijing_tz = timezone(timedelta(hours=8))
    beijing_now = utc_now.astimezone(beijing_tz)
    return beijing_now.strftime("%Y-%m-%d %H:%M:%S")

# ========== 新增：解压ZIP+递归读取文件夹所有TXT + 彻底删除空白行 ==========
def clean_empty_line(text):
    """删除空行、纯空格行、首尾多余空格"""
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        strip_line = line.strip()
        if strip_line:
            new_lines.append(strip_line)
    return "\n".join(new_lines)

def extract_txt_from_zip(zip_bytes):
    """解压ZIP，无论几层文件夹，提取全部TXT内容"""
    all_text = ""
    try:
        zip_file = zipfile.ZipFile(BytesIO(zip_bytes))
        # 遍历压缩包里所有文件（含子文件夹）
        for file_name in zip_file.namelist():
            # 只处理txt文件，跳过文件夹
            if file_name.lower().endswith(".txt") and not file_name.endswith("/"):
                data = zip_file.read(file_name)
                txt = data.decode("utf-8", "ignore")
                all_text += txt + "\n"
        zip_file.close()
        # 统一清洗空白无效行
        return clean_empty_line(all_text)
    except Exception as e:
        return ""

bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

# 主菜单
def menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(f"📄格式：{get_user(uid)['mode']}",callback_data="mode"),
        telebot.types.InlineKeyboardButton(f"✏️分割每份{get_user(uid)['line']}",callback_data="line")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("👤个人中心",callback_data="user"),
        telebot.types.InlineKeyboardButton("💳卡密充值",callback_data="user_cdk")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📎文件合并",callback_data="hebing"),
        telebot.types.InlineKeyboardButton("🧹号码去重",callback_data="quchong")
    )
    if is_admin(uid):
        kb.add(telebot.types.InlineKeyboardButton("🔧管理后台",callback_data="admin"))
    return kb

def user_menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("💰个人余额",callback_data="bal"),
        telebot.types.InlineKeyboardButton("💳充值记录",callback_data="rclog")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📜消费记录",callback_data="uselog"),
        telebot.types.InlineKeyboardButton("🔙返回主页",callback_data="back")
    )
    return kb

def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("➕单人手动加余额",callback_data="addbal"),telebot.types.InlineKeyboardButton("➖单人扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("🎟️批量生成卡密",callback_data="card"),telebot.types.InlineKeyboardButton("📊用户余额总表",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("📋充值总记录",callback_data="all_rc_log"),telebot.types.InlineKeyboardButton("📋消费总记录",callback_data="all_use_log"))
    kb.add(telebot.types.InlineKeyboardButton("📢全站广播",callback_data="broad"),telebot.types.InlineKeyboardButton("🔥批量批量加用户余额",callback_data="batch_addbal"))
    kb.add(telebot.types.InlineKeyboardButton("🔙返回",callback_data="back"))
    return kb

def select_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("⚡插入雷号分割",callback_data="ins"),
        telebot.types.InlineKeyboardButton("📄纯净直接分割",callback_data="noins")
    )
    return kb

@bot.message_handler(commands=['start'])
def s(m):
    uid = m.from_user.id
    get_user(uid)
    user_state[uid]="idle"
    now_time = get_beijing_time_str()
    bot.send_message(m.chat.id,f"🤖大晴机器人运行正常✅\n当前北京时间：{now_time}",reply_markup=menu(uid))

@bot.message_handler(func=lambda msg: msg.text.strip() == "取消")
def cancel_all(msg):
    uid = msg.from_user.id
    user_state[uid] = "idle"
    user_merge[uid] = []
    if uid in user_insert: del user_insert[uid]
    if uid in user_file: del user_file[uid]
    bot.send_message(msg.chat.id,"✅已清空所有操作缓存，请重新上传文件")

@bot.message_handler(func=lambda msg: is_admin(msg.from_user.id))
def admin_cmd(msg):
    txt = msg.text.strip()
    if txt.startswith("查询用户充值记录"):
        try:
            uid = int(txt.replace("查询用户充值记录","").strip())
            log = log_recharge.get(uid,["该用户暂无任何充值记录"])
            bot.send_message(msg.chat.id,f"📋 用户{uid} 充值明细\n"+"\n".join(log)[:4000])
        except:
            bot.send_message(msg.chat.id,"❌格式：查询用户充值记录 用户ID")
    elif txt.startswith("查询用户消费记录"):
        try:
            uid = int(txt.replace("查询用户消费记录","").strip())
            log = log_user.get(uid,["该用户暂无消费记录"])
            bot.send_message(msg.chat.id,f"📋 用户{uid} 消费明细\n"+"\n".join(log)[:4000])
        except:
            bot.send_message(msg.chat.id,"❌格式：查询用户消费记录 用户ID")

@bot.callback_query_handler(func=lambda c:True)
def cb(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    cid = c.message.chat.id
    d = c.data

    if d=="mode":
        u=get_user(uid)
        u['mode']="VCF" if u['mode']=="TXT" else "TXT"
        bot.edit_message_text("✅格式已切换",cid,c.message.message_id,reply_markup=menu(uid))
    elif d=="line":
        bot.send_message(cid,"📏请输入每份分割行数")
        bot.register_next_step_handler(c.message,set_line)
    elif d=="user_cdk":
        bot.send_message(cid,"💳请粘贴你的卡密兑换 购买联系 @sechou")
        bot.register_next_step_handler(c.message,use_cdk)
    elif d=="user":
        bot.edit_message_text("👤个人中心",cid,c.message.message_id,reply_markup=user_menu(uid))
    elif d=="bal":
        bot.send_message(cid,f"💰您当前余额：{get_user(uid)['balance']:.4f}元")
    elif d=="rclog":
        txt="\n".join(log_recharge.get(uid,["暂无充值记录"]))
        bot.send_message(cid,txt[:4000])
    elif d=="uselog":
        txt="\n".join(log_user.get(uid,["暂无消费记录"]))
        bot.send_message(cid,txt[:4000])
    elif d=="back":
        bot.edit_message_text("🏠机器人主菜单",cid,c.message.message_id,reply_markup=menu(uid))

    elif d=="hebing":
        user_merge[uid]=[]
        user_state[uid]="hebing"
        bot.send_message(cid,"📎请依次发送文件，全部发完回复：完成")
    
    elif d=="quchong":
        user_state[uid]="quchong"
        bot.send_message(cid,"🧹请发送需要去重的号码")
    
    elif d=="admin" and is_admin(uid):
        bot.edit_message_text("🔧管理员后台控制面板",cid,c.message.message_id,reply_markup=admin_kb())
    
    elif d=="addbal" and is_admin(uid):
        bot.send_message(cid,"➕请输入：用户ID 充值金额")
        bot.register_next_step_handler(c.message, admin_add_balance)
    elif d=="subbal" and is_admin:
        bot.send_message(cid,"➖请输入：用户ID 扣除金额")
        bot.register_next_step_handler(c.message, admin_sub_balance)
    elif d=="card" and is_admin(uid):
        bot.send_message(cid,"🎟️请输入卡密面值")
        bot.register_next_step_handler(c.message, make_card)
    elif d=="ulist" and is_admin(uid):
        msg = "📊全站用户余额清单\n"
        for u_id,info in users.items():
            msg+=f"用户ID:{u_id} | 余额:{info['balance']:.4f}\n"
        bot.send_message(cid,msg[:4000])
    
    elif d=="all_rc_log" and is_admin(uid):
        all_log = []
        for u_id,logs in log_recharge.items():
            all_log.extend(logs)
        if not all_log:all_log=["暂无充值记录"]
        bot.send_message(cid,"📋全站充值记录\n"+"\n".join(all_log[:4000]))
    
    elif d=="all_use_log" and is_admin(uid):
        all_log = []
        for u_id,logs in log_user.items():
            all_log.extend(logs)
        if not all_log:all_log=["暂无消费记录"]
        bot.send_message(c.message.chat.id,"📋全站消费记录\n"+"\n".join(all_log[:4000]))

    elif d=="broad" and is_admin(uid):
        bot.send_message(cid,"📢请输入广播内容")
        bot.register_next_step_handler(c.message, admin_broadcast)

    elif d=="batch_addbal" and is_admin(uid):
        bot.send_message(cid,"🔥请批量粘贴用户数据\n格式：\n用户ID1 金额\n用户ID2 金额\n一行一个")
        bot.register_next_step_handler(c.message, batch_add_user_balance)

    elif d=="ins":
        if uid not in user_file:
            return bot.send_message(cid,"📭文件已过期，请重新上传")
        bot.send_message(cid,"⚡每份插入几条雷号？")
        bot.register_next_step_handler(c.message,ins_num)

    elif d=="noins":
        if uid not in user_file:
            return bot.send_message(cid,"📭文件已过期，请重新上传")
        bot.send_message(cid,"📄请输入自定义文件名")
        bot.register_next_step_handler(c.message,lambda m:split_send_clean(cid,uid,user_file[uid]['txt'],m.text))

def batch_add_user_balance(msg):
    if not is_admin(msg.from_user.id):return
    lines = msg.text.strip().splitlines()
    success = 0
    fail = []
    for line in lines:
        line = line.strip()
        if not line:continue
        try:
            uid, money = line.split()
            uid = int(uid)
            money = float(money)
            get_user(uid)['balance'] += money
            add_rc(uid, money)
            success +=1
        except:
            fail.append(line)
    reply = f"✅批量充值完成\n成功：{success} 个用户"
    if fail:
        reply += f"\n❌格式错误跳过：{len(fail)} 条"
    bot.send_message(msg.chat.id, reply)

def admin_add_balance(msg):
    try:
        u_id,money = msg.text.split()
        u_id=int(u_id)
        money=float(money)
        get_user(u_id)['balance']+=money
        add_rc(u_id,money)
        bot.send_message(msg.chat.id,f"✅成功充值用户{u_id}：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"格式错误：用户ID 金额")

def admin_sub_balance(msg):
    try:
        u_id,money = msg.text.split()
        u_id=int(u_id)
        money=float(money)
        get_user(u_id)['balance']-=money
        bot.send_message(msg.chat.id,f"✅成功扣除用户{u_id}：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"格式错误：用户ID 金额")

def make_card(msg):
    try:
        money = float(msg.text)
        cdk = "TK"+''.join(random.sample('0123456789ABCDEF',12))
        cards[cdk] = money
        bot.send_message(msg.chat.id,f"✅卡密生成\n{cdk}\n面值：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"请输入正确金额")

def admin_broadcast(msg):
    txt = msg.text
    count=0
    for u_id in users.keys():
        try:
            bot.send_message(u_id,txt)
            count+=1
        except:pass
    bot.send_message(msg.chat.id,f"✅广播推送 {count} 位用户")

def set_line(m):
    try:
        get_user(m.from_user.id)['line']=int(m.text)
        bot.send_message(m.chat.id,"✅分割行数设置成功")
    except:
        bot.send_message(m.chat.id,"❌请输入纯数字")

def use_cdk(m):
    cdk=m.text.strip()
    if cdk not in cards:
        bot.send_message(m.chat.id,"❌卡密无效或已使用")
        return
    money=cards.pop(cdk)
    get_user(m.from_user.id)['balance']+=money
    add_rc(m.from_user.id,money)
    bot.send_message(m.chat.id,f"✅充值到账{money:.4f}元\n余额：{get_user(m.from_user.id)['balance']:.4f}")

def ins_num(m):
    uid=m.from_user.id
    try:
        num=int(m.text)
        user_insert[uid]={"num":num,"txt":user_file[uid]['txt']}
        bot.send_message(m.chat.id,"⚡请发送雷号，一行一个")
        bot.register_next_step_handler(m, ins_phone)
    except:
        bot.send_message(m.chat.id,"❌请输入纯数字，发取消重置")

def ins_phone(m):
    uid=m.from_user.id
    if uid not in user_insert:
        return bot.send_message(m.chat.id,"❌流程失效，请重新上传")
    phones=re.findall(r"\d+",m.text)
    if len(phones)==0:
        bot.send_message(m.chat.id,"❌未识别号码，请重发")
        bot.register_next_step_handler(m, ins_phone)
        return
    user_insert[uid]['phone']=phones
    bot.send_message(m.chat.id,"📄请输入文件前缀名")
    bot.register_next_step_handler(m, ins_done)

def ins_done(m):
    uid=m.from_user.id
    info=user_insert[uid]
    lines=[x for x in info['txt'].splitlines() if x]
    total=len(lines)

    fee_split = total * PRICE_SPLIT
    fee_insert = total * PRICE_INSERT
    total_fee = fee_split + fee_insert

    u=get_user(uid)
    if u['balance'] < total_fee:
        return bot.send_message(m.chat.id,"❌余额不足")
    
    u['balance'] -= total_fee
    add_log(uid,"分包+插入雷号",total,total_fee)
    bot.send_message(m.chat.id,f"💸分包{fee_split:.4f}+插雷{fee_insert:.4f}\n合计：{total_fee:.4f}｜剩余：{u['balance']:.4f}")

    chunk = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media=[]
    idx=1
    ph_idx=0
    phones = info['phone']
    csv_data = "雷号号码,分包文件名,所在行号\n"

    for c in chunk:
        filename = f"{m.text}_{idx}.txt"
        for _ in range(info['num']):
            ph = phones[ph_idx%len(phones)]
            line_num = len(c)+1
            c.append(ph)
            csv_data += f"{ph},{filename},{line_num}\n"
            ph_idx+=1

        bio=BytesIO("\n".join(c).encode())
        bio.name=filename
        media.append(InputMediaDocument(bio))
        if len(media)>=BATCH_SIZE:
            bot.send_media_group(m.chat.id,media)
            media=[]
            time.sleep(1)
        idx=idx+1

    if media:bot.send_media_group(m.chat.id,media)
    csv_bio = BytesIO(csv_data.encode("utf-8-sig"))
    csv_bio.name = "雷号插入位置明细.csv"
    bot.send_document(m.chat.id, csv_bio)

    bot.send_message(m.chat.id,"🎉全部处理完成，附带位置明细表格")
    
    del user_file[uid]
    del user_insert[uid]

def split_send_clean(cid,uid,txt,name):
    lines=[x for x in txt.splitlines() if x]
    total=len(lines)
    fee=total*PRICE_SPLIT
    u=get_user(uid)
    if u['balance']<fee:return bot.send_message(cid,"❌余额不足")
    u['balance']-=fee
    add_log(uid,"纯净分包",total,fee)
    bot.send_message(cid,f"💸扣费：{fee:.4f}元｜剩余：{u['balance']:.4f}")

    chunk = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media=[]
    idx=1
    for c in chunk:
        bio=BytesIO("\n".join(c).encode())
        bio.name=f"{name}_{idx}.txt"
        media.append(InputMediaDocument(bio))
        if len(media)>=BATCH_SIZE:
            bot.send_media_group(cid,media)
            media=[]
            time.sleep(1)
        idx+=1
    if media:bot.send_media_group(cid,media)
    bot.send_message(cid,"🎉纯净分包完成")

    del user_file[uid]

@bot.message_handler(func=lambda m:user_state.get(m.from_user.id)=="hebing" and m.text=="完成")
def heb(m):
    uid=m.from_user.id
    txt="\n".join(user_merge[uid])
    ls=len(txt.splitlines())
    fee=ls*PRICE_MERGE
    u=get_user(uid)
    if u['balance']<fee:return bot.send_message(m.chat.id,"❌余额不足")
    u['balance']-=fee
    add_log(uid,"文件合并",ls,fee)
    bio=BytesIO(txt.encode())
    bio.name="合并成品.txt"
    bot.send_document(m.chat.id,bio)
    user_state[uid]="idle"
    bot.send_message(m.chat.id,f"✅合并完成｜扣费{fee:.4f}元")

# ========== 兼容 TXT + ZIP压缩包上传 ==========
@bot.message_handler(content_types=['document'])
def doc(m):
    uid=m.from_user.id
    try:
        file = bot.get_file(m.document.file_id)
        file_bytes = bot.download_file(file.file_path)
        file_name = m.document.file_name.lower()

        # 处理ZIP压缩包
        if file_name.endswith(".zip"):
            total_txt = extract_txt_from_zip(file_bytes)
            if not total_txt:
                return bot.send_message(m.chat.id,"❌压缩包里未找到任何TXT文本")
            user_file[uid] = {"txt": total_txt}
            bot.send_message(m.chat.id,"✅ZIP解压完成！\n已自动提取所有文件夹TXT\n已清空全部空白无效行",reply_markup=select_menu())
        
        # 处理普通TXT文件
        else:
            txt = file_bytes.decode("utf-8","ignore")
            # 同样自动清洗空白行
            clean_txt = clean_empty_line(txt)
            user_file[uid]={"txt":clean_txt}
            bot.send_message(m.chat.id,"📄文件已保存，已自动清理空白空行",reply_markup=select_menu())

    except Exception as e:
        bot.send_message(m.chat.id,"❌文件读取失败，请上传正常TXT/ZIP压缩包")

bot.polling(none_stop=True)
