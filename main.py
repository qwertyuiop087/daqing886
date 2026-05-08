import os
import re
import time
import random
from io import BytesIO
import telebot
from telebot.types import InputMediaDocument

BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834

# 收费标准
PRICE_SPLIT = 0.0004
PRICE_MERGE = 0.0002
PRICE_DEDUP = 0.0002
BATCH_SIZE = 10

# 全局数据存储
user_file = {}
users = {}
cards = {}
user_merge = {}
user_state = {}
user_insert = {}
log_user = {}
log_recharge = {}

# 获取用户信息
def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0.0, "mode":"TXT", "line":100}
    return users[uid]

# 判断是否管理员
def is_admin(uid):
    return uid == ADMIN_ID

# 写入用户消费日志
def add_log(uid, txt, num, cost):
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    log_user[uid] = log_user.get(uid,[]) + [f"[{t}]{txt}｜{num}行｜扣费{cost:.4f}｜余额{get_user(uid)['balance']:.4f}"]

# 写入充值日志
def add_rc(uid,money):
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    log_recharge[uid] = log_recharge.get(uid,[]) + [f"[{t}]充值+{money:.4f}｜余额{get_user(uid)['balance']:.4f}"]

# 初始化机器人
bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

# 主菜单键盘
def menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(f"格式：{get_user(uid)['mode']}",callback_data="mode"),
        telebot.types.InlineKeyboardButton(f"每份{get_user(uid)['line']}行",callback_data="line")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("👤个人中心",callback_data="user"),
        telebot.types.InlineKeyboardButton("💳卡密充值",callback_data="cdk")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📎文件合并",callback_data="hebing"),
        telebot.types.InlineKeyboardButton("🧹号码去重",callback_data="quchong")
    )
    if is_admin(uid):
        kb.add(telebot.types.InlineKeyboardButton("🔧管理后台",callback_data="admin"))
    return kb

# 个人中心菜单
def user_menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("💰余额",callback_data="bal"),
        telebot.types.InlineKeyboardButton("💳充值记录",callback_data="rclog")
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📜消费记录",callback_data="uselog"),
        telebot.types.InlineKeyboardButton("🔙返回",callback_data="back")
    )
    return kb

# 管理员后台菜单
def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("加余额",callback_data="addbal"),telebot.types.InlineKeyboardButton("扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("生成卡密",callback_data="card"),telebot.types.InlineKeyboardButton("用户余额列表",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("全站广播",callback_data="broad"),telebot.types.InlineKeyboardButton("🔙返回",callback_data="back"))
    return kb

# 文件操作选择菜单
def select_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("✅插入号码",callback_data="ins"),telebot.types.InlineKeyboardButton("❌直接分割",callback_data="noins"))
    return kb

# 启动命令
@bot.message_handler(commands=['start'])
def start_message(m):
    uid = m.from_user.id
    get_user(uid)
    user_state[uid]="idle"
    bot.send_message(m.chat.id,"机器人正常运行✅",reply_markup=menu(uid))

# 全部按钮响应处理
@bot.callback_query_handler(func=lambda c:True)
def callback_handle(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    cid = c.message.chat.id
    d = c.data

    # 格式切换
    if d=="mode":
        u=get_user(uid)
        u['mode']="VCF" if u['mode']=="TXT" else "TXT"
        bot.edit_message_text("已切换格式",cid,c.message.message_id,reply_markup=menu(uid))
    
    # 设置分割行数
    elif d=="line":
        bot.send_message(cid,"请输入每份分割行数")
        bot.register_next_step_handler(c.message,set_line)
    
    # 卡密充值
    elif d=="cdk":
        bot.send_message(cid,"请输入你的卡密")
        bot.register_next_step_handler(c.message,use_cdk)
    
    # 进入个人中心
    elif d=="user":
        bot.edit_message_text("👤个人中心",cid,c.message.message_id,reply_markup=user_menu(uid))
    
    # 查询余额
    elif d=="bal":
        bot.send_message(cid,f"💰当前余额：{get_user(uid)['balance']:.4f}元")
    
    # 充值记录
    elif d=="rclog":
        txt="\n".join(log_recharge.get(uid,["暂无充值记录"]))
        bot.send_message(cid,txt[:4000])
    
    # 消费记录
    elif d=="uselog":
        txt="\n".join(log_user.get(uid,["暂无消费记录"]))
        bot.send_message(cid,txt[:4000])
    
    # 返回主菜单
    elif d=="back":
        bot.edit_message_text("🏠主菜单",cid,c.message.message_id,reply_markup=menu(uid))
    
    # 文件合并
    elif d=="hebing":
        user_merge[uid]=[]
        user_state[uid]="hebing"
        bot.send_message(cid,"发送多个TXT文件，全部发完回复：完成")
    
    # 号码去重
    elif d=="quchong":
        user_state[uid]="quchong"
        bot.send_message(cid,"发送需要去重的号码文件")

    # 管理员后台入口
    elif d=="admin" and is_admin(uid):
        bot.edit_message_text("🔧管理员后台",cid,c.message.message_id,reply_markup=admin_kb())
    
    # 管理员手动加用户余额
    elif d=="addbal" and is_admin(uid):
        bot.send_message(cid,"请输入：用户ID 金额")
        bot.register_next_step_handler(c.message, admin_add_balance)
    
    # 管理员扣除用户余额
    elif d=="subbal" and is_admin(uid):
        bot.send_message(cid,"请输入：用户ID 金额")
        bot.register_next_step_handler(c.message, admin_sub_balance)
    
    # 生成充值卡密
    elif d=="card" and is_admin(uid):
        bot.send_message(cid,"请输入卡密面值金额")
        bot.register_next_step_handler(c.message, make_card)
    
    # 查看所有用户余额
    elif d=="ulist" and is_admin(uid):
        msg = "📊所有用户余额\n"
        for u_id,info in users.items():
            msg+=f"ID:{u_id} | 余额:{info['balance']:.4f}\n"
        bot.send_message(cid,msg[:4000])
    
    # 全站广播消息
    elif d=="broad" and is_admin(uid):
        bot.send_message(cid,"请输入要广播的内容")
        bot.register_next_step_handler(c.message, admin_broadcast)

    # 分割插入号码
    elif d=="ins":
        bot.send_message(cid,"每份文件插入几个号码？")
        bot.register_next_step_handler(c.message,ins_num)
    
    # 直接分割不插号
    elif d=="noins":
        if uid not in user_file:
            return bot.send_message(cid,"文件已过期，请重新上传")
        bot.send_message(cid,"请输入自定义文件名")
        bot.register_next_step_handler(c.message,lambda m:split_send(cid,uid,user_file[uid]['txt'],m.text))

# 管理员添加用户余额函数
def admin_add_balance(msg):
    try:
        u_id,money = msg.text.split()
        u_id=int(u_id)
        money=float(money)
        get_user(u_id)['balance']+=money
        add_rc(u_id,money)
        bot.send_message(msg.chat.id,f"✅成功给用户{u_id}加余额：{money:.4f}")
    except:
        bot.send_message(msg.chat.id,"格式错误，请输入：用户ID 金额")

# 管理员扣除用户余额函数
def admin_sub_balance(msg):
    try:
        u_id,money = msg.text.split()
        u_id=int(u_id)
        money=float(money)
        get_user(u_id)['balance']-=money
        bot.send_message(msg.chat.id,f"✅成功扣除用户{u_id}余额：{money:.4f}")
    except:
        bot.send_message(msg.chat.chat.id,"格式错误，请输入：用户ID 金额")

# 随机生成卡密函数
def make_card(msg):
    try:
        money = float(msg.text)
        cdk = "TK"+''.join(random.sample('0123456789ABCDEF',12))
        cards[cdk] = money
        bot.send_message(msg.chat.id,f"✅生成卡密成功\n卡密：{cdk}\n面值：{money:.4f}元")
    except:
        bot.send_message(msg.chat.id,"请输入正确数字金额")

# 全站广播函数
def admin_broadcast(msg):
    txt = msg.text
    count=0
    for u_id in users.keys():
        try:
            bot.send_message(u_id,txt)
            count+=1
        except:pass
    bot.send_message(msg.chat.id,f"✅广播完成，已发送{count}位用户")

# 设置每份分割行数
def set_line(m):
    try:
        get_user(m.from_user.id)['line']=int(m.text)
        bot.send_message(m.chat.id,"✅分割行数设置成功")
    except:
        bot.send_message(m.chat.id,"❌请输入纯数字")

# 用户使用卡密充值
def use_cdk(m):
    cdk=m.text.strip()
    if cdk not in cards:
        bot.send_message(m.chat.id,"❌无效卡密或已使用")
        return
    money=cards.pop(cdk)
    get_user(m.from_user.id)['balance']+=money
    add_rc(m.from_user.id,money)
    bot.send_message(m.chat.id,f"✅充值成功\n到账：{money:.4f}元\n当前余额：{get_user(m.from_user.id)['balance']:.4f}")

# 设置插入号码数量
def ins_num(m):
    try:
        num=int(m.text)
        user_insert[m.from_user.id]={"num":num,"file":user_file[m.from_user.id]}
        bot.send_message(m.chat.id,"请发送循环插入手机号")
        bot.register_next_step_handler(m,ins_phone)
    except:
        bot.send_message(m.chat.id,"❌请输入数字")

# 读取插入手机号
def ins_phone(m):
    phones=re.findall(r"\d+",m.text)
    user_insert[m.from_user.id]['phone']=phones
    bot.send_message(m.chat.id,"请输入文件名称")
    bot.register_next_step_handler(m,ins_done)

# 插号分割收尾
def ins_done(m):
    uid=m.from_user.id
    info=user_insert[uid]
    split_send_ins(m.chat.id,uid,info['file']['txt'],m.text,info['num'],info['phone'])

# 正常分割批量发送
def split_send(cid,uid,txt,name):
    lines=[x for x in txt.splitlines() if x]
    total=len(lines)
    fee=total*PRICE_SPLIT
    u=get_user(uid)
    if u['balance']<fee:
        return bot.send_message(cid,"❌余额不足")
    u['balance']-=fee
    add_log(uid,"文件分割",total,fee)
    bot.send_message(cid,f"💸扣费{fee:.4f}｜剩余{u['balance']:.4f}")

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
    bot.send_message(cid,"🎉全部文件发送完成")

# 带插入号码分割批量发送
def split_send_ins(cid,uid,txt,name,pn,phones):
    lines=[x for x in txt.splitlines() if x]
    total=len(lines)
    fee=total*PRICE_SPLIT
    u=get_user(uid)
    if u['balance']<fee:
        return bot.send_message(cid,"❌余额不足")
    u['balance']-=fee
    add_log(uid,"分割+插号",total,fee)
    bot.send_message(cid,f"💸扣费{fee:.4f}｜剩余{u['balance']:.4f}")

    chunk = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media=[]
    idx=1
    ph_idx=0
    for c in chunk:
        for _ in range(pn):
            c.append(phones[ph_idx%len(phones)])
            ph_idx+=1
        bio=BytesIO("\n".join(c).encode())
        bio.name=f"{name}_{idx}.txt"
        media.append(InputMediaDocument(bio))
        if len(media)>=BATCH_SIZE:
            bot.send_media_group(cid,media)
            media=[]
            time.sleep(1)
        idx+=1
    if media:bot.send_media_group(cid,media)
    bot.send_message(cid,"🎉插号分割全部完成")

# 多文件合并处理
@bot.message_handler(func=lambda m:user_state.get(m.from_user.id)=="hebing" and m.text=="完成")
def hebing_file(m):
    uid=m.from_user.id
    txt="\n".join(user_merge[uid])
    ls=len(txt.splitlines())
    fee=ls*PRICE_MERGE
    u=get_user(uid)
    if u['balance']<fee:
        return bot.send_message(m.chat.id,"❌余额不足")
    u['balance']-=fee
    add_log(uid,"文件合并",ls,fee)
    bio=BytesIO(txt.encode())
    bio.name="合并.txt"
    bot.send_document(m.chat.id,bio)
    user_state[uid]="idle"

# 接收上传文件
@bot.message_handler(content_types=['document'])
def get_document(m):
    uid=m.from_user.id
    try:
        f=bot.get_file(m.document.file_id)
        txt=bot.download_file(f.file_path).decode("utf-8","ignore")
        if user_state.get(uid)=="hebing":
            user_merge[uid].append(txt)
            bot.send_message(m.chat.id,"✅文件已收录，回复：完成")
        elif user_state.get(uid)=="quchong":
            old=len(txt.splitlines())
            new=list(set(txt.splitlines()))
            fee=len(new)*PRICE_DEDUP
            u=get_user(uid)
            if u['balance']<fee:
                return bot.send_message(m.chat.id,"❌余额不足")
            u['balance']-=fee
            add_log(uid,"号码去重",old,fee)
            bio=BytesIO("\n".join(new).encode())
            bot.send_document(m.chat.id,bio)
        else:
            user_file[uid]={"name":m.document.file_name,"txt":txt}
            bot.send_message(m.chat.id,"请选择操作",reply_markup=select_menu())
    except:
        bot.send_message(m.chat.id,"❌文件读取失败")

# 持续运行
bot.polling(none_stop=True)
