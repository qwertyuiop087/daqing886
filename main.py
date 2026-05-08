import os
import re
import time
import random
from io import BytesIO
import telebot
from telebot.types import InputMediaDocument

BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834

PRICE_SPLIT = 0.0004    # 单纯分包费用
PRICE_INSERT = 0.0001  # 插入雷号额外费用
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
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    log_user[uid] = log_user.get(uid,[]) + [f"[{t}]用户{uid}｜{txt}｜{num}行｜扣费{cost:.4f}｜剩余余额{get_user(uid)['balance']:.4f}"]

def add_rc(uid,money):
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    log_recharge[uid] = log_recharge.get(uid,[]) + [f"[{t}]用户{uid}｜充值+{money:.4f}｜剩余余额{get_user(uid)['balance']:.4f}"]

bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

# 主菜单
def menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(f"📄格式：{get_user(uid)['mode']}",callback_data="mode"),
        telebot.types.InlineKeyboardButton(f"分割每份{get_user(uid)['line']}行",callback_data="line")
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

# 个人中心
def user_menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("💰当前余额",callback_data="bal"),
        telebot.types.InlineKeyboardButton("💳我的充值记录",callback_data="rclog")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📜我的消费记录",callback_data="uselog"),
        telebot.types.InlineKeyboardButton("🔙返回主页",callback_data="back")
    )
    return kb

# 管理员后台
def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("➕手动加余额",callback_data="addbal"),telebot.types.InlineKeyboardButton("➖手动扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("🎟️批量生成卡密",callback_data="card"),telebot.types.InlineKeyboardButton("📊全站用户余额",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("📋全站充值总记录",callback_data="all_rc_log"),telebot.types.InlineKeyboardButton("📋全站消费总记录",callback_data="all_use_log"))
    kb.add(telebot.types.InlineKeyboardButton("📢全站广播通知",callback_data="broad"),telebot.types.InlineKeyboardButton("🔙返回",callback_data="back"))
    return kb

# 分割选择按钮
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
    bot.send_message(m.chat.id,"🤖工具机器人运行正常✅",reply_markup=menu(uid))

# 全局万能取消 所有流程都能用
@bot.message_handler(func=lambda msg: msg.text.strip() == "取消")
def cancel_all(msg):
    uid = msg.from_user.id
    user_state[uid] = "idle"
    user_merge[uid] = []
    if uid in user_insert: del user_insert[uid]
    if uid in user_file: del user_file[uid]
    bot.send_message(msg.chat.id,"✅已彻底取消所有操作，清空全部缓存，请重新上传文件")

# 管理员文字查询指令
@bot.message_handler(func=lambda msg: is_admin(msg.from_user.id))
def admin_cmd(msg):
    txt = msg.text.strip()
    if txt.startswith("查询用户充值记录"):
        try:
            uid = int(txt.replace("查询用户充值记录","").strip())
            log = log_recharge.get(uid,["该用户暂无任何充值记录"])
            bot.send_message(msg.chat.id,f"📋 用户{uid} 充值明细\n"+"\n".join(log)[:4000])
        except:
            bot.send_message(msg.chat.id,"❌格式错误，请发送：查询用户充值记录 用户ID")
    elif txt.startswith("查询用户消费记录"):
        try:
            uid = int(txt.replace("查询用户消费记录","").strip())
            log = log_user.get(uid,["该用户暂无消费记录"])
            bot.send_message(msg.chat.id,f"📋 用户{uid} 消费明细\n"+"\n".join(log)[:4000])
        except:
            bot.send_message(msg.chat.id,"❌格式错误，请发送：查询用户消费记录 用户ID")

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
        bot.send_message(cid,"💳请粘贴你的卡密兑换")
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

    # 文件合并
    elif d=="hebing":
        user_merge[uid]=[]
        user_state[uid]="hebing"
        bot.send_message(cid,"📎请依次发送需要合并的所有TXT文件\n全部发送完毕后，请回复：完成")
    
    # 号码去重
    elif d=="quchong":
        user_state[uid]="quchong"
        bot.send_message(cid,"🧹请发送需要去重处理的号码文件")

    # 管理员功能
    elif d=="admin" and is_admin(uid):
        bot.edit_message_text("🔧管理员后台控制面板",cid,c.message.message_id,reply_markup=admin_kb())
    
    elif d=="addbal" and is_admin(uid):
        bot.send_message(cid,"➕请输入：用户ID 充值金额")
        bot.register_next_step_handler(c.message, admin_add_balance)
    elif d=="subbal" and is_admin(uid):
        bot.send_message(cid,"➖请输入：用户ID 扣除金额")
        bot.register_next_step_handler(c.message, admin_sub_balance)
    elif d=="card" and is_admin(uid):
        bot.send_message(cid,"🎟️请输入卡密面值金额")
        bot.register_next_step_handler(c.message, make_card)
    elif d=="ulist" and is_admin(uid):
        msg = "📊全站所有用户余额清单\n"
        for u_id,info in users.items():
            msg+=f"用户ID:{u_id} | 余额:{info['balance']:.4f}\n"
        bot.send_message(cid,msg[:4000])
    
    # 全站所有充值记录
    elif d=="all_rc_log" and is_admin(uid):
        all_log = []
        for u_id,logs in log_recharge.items():
            all_log.extend(logs)
        if not all_log:all_log=["暂无全站充值记录"]
        bot.send_message(cid,"📋全站用户所有充值记录\n"+"\n".join(all_log[:4000]))
    
    # 全站所有消费记录
    elif d=="all_use_log" and is_admin(uid):
        all_log = []
        for u_id,logs in log_user.items():
            all_log.extend(logs)
        if not all_log:all_log=["暂无全站消费记录"]
        bot.send_message(cid,"📋全站用户所有消费记录\n"+"\n".join(all_log[:4000]))

    elif d=="broad" and is_admin(uid):
        bot.send_message(cid,"📢请输入要全站广播的内容")
        bot.register_next_step_handler(c.message, admin_broadcast)

    # 插入雷号流程
    elif d=="ins":
        if uid not in user_file:
            return bot.send_message(cid,"📭文件已过期，请重新上传")
        bot.send_message(cid,"⚡请输入每份文件插入几条雷号\n\n❗取消操作 → 直接发送【取消】")
        bot.register_next_step_handler(c.message,ins_num)
    # 纯净分割
    elif d=="noins":
        if uid not in user_file:
            return bot.send_message(cid,"📭文件已过期，请重新上传")
        bot.send_message(cid,"📄请输入自定义输出文件名")
        bot.register_next_step_handler(c.message,lambda m:split_send_clean(cid,uid,user_file[uid]['txt'],m.text))

# 管理员加余额
def admin_add_balance(msg):
    try:
        u_id,money = msg.text.split()
        u_id=int(u_id)
        money=float(money)
        get_user(u_id)['balance']+=money
        add_rc(u_id,money)
        bot.send_message(msg.chat.id,f"✅成功给用户{u_id}手动充值：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"格式错误，请输入：用户ID 金额")

# 管理员扣余额
def admin_sub_balance(msg):
    try:
        u_id,money = msg.text.split()
        u_id=int(u_id)
        money=float(money)
        get_user(u_id)['balance']-=money
        bot.send_message(msg.chat.id,f"✅成功扣除用户{u_id}余额：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"格式错误，请输入：用户ID 金额")

def make_card(msg):
    try:
        money = float(msg.text)
        cdk = "TK"+''.join(random.sample('0123456789ABCDEF',12))
        cards[cdk] = money
        bot.send_message(msg.chat.id,f"✅卡密生成成功\n卡密：{cdk}\n面值：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"请输入正确数字金额")

def admin_broadcast(msg):
    txt = msg.text
    count=0
    for u_id in users.keys():
        try:
            bot.send_message(u_id,txt)
            count+=1
        except:pass
    bot.send_message(msg.chat.id,f"✅全站广播完成，已推送{count}位用户")

def set_line(m):
    try:
        get_user(m.from_user.id)['line']=int(m.text)
        bot.send_message(m.chat.id,"✅分割行数设置成功")
    except:
        bot.send_message(m.chat.id,"❌请输入纯数字")

def use_cdk(m):
    cdk=m.text.strip()
    if cdk not in cards:
        bot.send_message(m.chat.id,"❌卡密无效或已被使用")
        return
    money=cards.pop(cdk)
    get_user(m.from_user.id)['balance']+=money
    add_rc(m.from_user.id,money)
    bot.send_message(m.chat.id,f"✅卡密充值成功\n到账金额：{money:.4f}元\n当前余额：{get_user(m.from_user.id)['balance']:.4f}")

# 雷号数量设置
def ins_num(m):
    uid=m.from_user.id
    try:
        num=int(m.text)
        user_insert[uid]={"num":num,"txt":user_file[uid]['txt']}
        bot.send_message(m.chat.id,"⚡请发送雷号号码\n❗务必一行一个号码")
        bot.register_next_step_handler(m,ins_phone)
    except:
        bot.send_message(m.chat.id,"❌请输入纯数字！发送【取消】重新开始")

def ins_phone(m):
    uid=m.from_user.id
    if uid not in user_insert:
        return bot.send_message(m.chat.id,"❌流程已失效，请重新上传文件")
    phones=re.findall(r"\d+",m.text)
    if len(phones)==0:
        bot.send_message(m.chat.id,"❌未检测到有效号码！")
        bot.register_next_step_handler(m,ins_phone)
        return
    user_insert[uid]['phone']=phones
    bot.send_message(m.chat.id,"📄请输入最终文件名称")
    bot.register_next_step_handler(m,ins_done)

# 分割+插雷号 双重叠加扣费
def ins_done(m):
    uid=m.from_user.id
    info=user_insert[uid]
    lines=[x for x in info['txt'].splitlines() if x]
    total=len(lines)
    # 分包费 + 插雷号费 一起扣
    fee_split = total * PRICE_SPLIT
    fee_insert = total * PRICE_INSERT
    total_fee = fee_split + fee_insert

    u=get_user(uid)
    if u['balance'] < total_fee:
        return bot.send_message(m.chat.id,"❌余额不足")
    
    u['balance'] -= total_fee
    add_log(uid,"分包分割+插入雷号",total,total_fee)
    bot.send_message(m.chat.id,f"💸分包费{fee_split:.4f}+插雷费{fee_insert:.4f}\n合计扣费：{total_fee:.4f}元｜剩余余额：{u['balance']:.4f}")

    chunk = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media=[]
    idx=1
    ph_idx=0
    for c in chunk:
        for _ in range(info['num']):
            c.append(phones[ph_idx%len(phones)])
            ph_idx+=1
        bio=BytesIO("\n".join(c).encode())
        bio.name=f"{m.text}_{idx}.txt"
        media.append(InputMediaDocument(bio))
        if len(media)>=BATCH_SIZE:
            bot.send_media_group(m.chat.id,media)
            media=[]
            time.sleep(1)
        idx+=1
    if media:bot.send_media_group(m.chat.id,media)
    bot.send_message(m.chat.id,"🎉分包+雷号插入全部完成")
    
    # 处理完直接删除文件，禁止重复分割白嫖
    del user_file[uid]
    del user_insert[uid]

# 纯净分割 只扣分包费
def split_send_clean(cid,uid,txt,name):
    lines=[x for x in txt.splitlines() if x]
    total=len(lines)
    fee=total*PRICE_SPLIT
    u=get_user(uid)
    if u['balance']<fee:return bot.send_message(cid,"❌余额不足，无法处理")
    u['balance']-=fee
    add_log(uid,"纯净文件分包",total,fee)
    bot.send_message(cid,f"💸本次扣费：{fee:.4f}元｜剩余余额：{u['balance']:.4f}")

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
    bot.send_message(cid,"🎉纯净分包处理全部完成")

    # 处理完毕清空缓存，不能重复分割
    del user_file[uid]

# 合并完成指令
@bot.message_handler(func=lambda m:user_state.get(m.from_user.id)=="hebing" and m.text=="完成")
def heb(m):
    uid=m.from_user.id
    txt="\n".join(user_merge[uid])
    ls=len(txt.splitlines())
    fee=ls*PRICE_MERGE
    u=get_user(uid)
    if u['balance']<fee:return bot.send_message(m.chat.id,"❌余额不足，无法合并")
    u['balance']-=fee
    add_log(uid,"多文件合并",ls,fee)
    bio=BytesIO(txt.encode())
    bio.name="合并成品.txt"
    bot.send_document(m.chat.id,bio)
    user_state[uid]="idle"
    bot.send_message(m.chat.id,f"✅文件合并完成｜扣费{fee:.4f}元")

# 文件上传处理
@bot.message_handler(content_types=['document'])
def doc(m):
    uid=m.from_user.id
    try:
        f=bot.get_file(m.document.file_id)
        txt=bot.download_file(f.file_path).decode("utf-8","ignore")

        # 文件合并 计数提示
        if user_state.get(uid)=="hebing":
            user_merge[uid].append(txt)
            num = len(user_merge[uid])
            bot.send_message(m.chat.id,f"✅已收录第【{num}】个文件\n全部发完请回复：完成")
        
        # 号码去重
        elif user_state.get(uid)=="quchong":
            old=len(txt.splitlines())
            new=list(set(txt.splitlines()))
            fee=len(new)*PRICE_DEDUP
            u=get_user(uid)
            if u['balance']<fee:return bot.send_message(m.chat.id,"❌余额不足")
            u['balance']-=fee
            add_log(uid,"号码去重",old,fee)
            bio=BytesIO("\n".join(new).encode())
            bio.name="去重成品.txt"
            bot.send_document(m.chat.id,bio)
        
        # 普通分割文件保存
        else:
            user_file[uid]={"txt":txt}
            bot.send_message(m.chat.id,"📄文件已保存，请选择处理方式",reply_markup=select_menu())
    except:
        bot.send_message(m.chat.id,"❌文件读取失败，请上传纯TXT文本")

bot.polling(none_stop=True)
