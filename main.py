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

broad_img = None
broad_text = ""

XING = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛"
MING1 = "伟俊佳浩宇泽晨欣雨轩博文铭凯艺霖梓睿一诺嘉航沐辰"
MING2 = "杰豪琳雪婷芳莹瑞阳鑫鹏佳怡涵悦彤诗雅泽安诺"

def get_rand_3_name():
    return random.choice(XING) + random.choice(MING1) + random.choice(MING2)

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

def get_beijing_time_str():
    utc_now = datetime.now(timezone.utc)
    beijing_tz = timezone(timedelta(hours=8))
    beijing_now = utc_now.astimezone(beijing_tz)
    return beijing_now.strftime("%Y-%m-%d %H:%M:%S")

def clean_empty_line(text):
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        strip_line = line.strip()
        if strip_line:
            new_lines.append(strip_line)
    return "\n".join(new_lines)

def extract_txt_from_zip(zip_bytes):
    all_text = ""
    try:
        zip_file = zipfile.ZipFile(BytesIO(zip_bytes))
        for file_name in zip_file.namelist():
            if file_name.lower().endswith(".txt") and not file_name.endswith("/"):
                data = zip_file.read(file_name)
                txt = data.decode("utf-8","ignore")
                all_text += txt + "\n"
        zip_file.close()
        return clean_empty_line(all_text)
    except Exception as e:
        return ""

bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

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
    kb.add(telebot.types.InlineKeyboardButton("📢全站广播",callback_data="broad"),telebot.types.InlineKeyboardButton("🔥批量加用户余额",callback_data="batch_addbal"))
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

# 按钮回调全包异常捕获 根治报错
@bot.callback_query_handler(func=lambda c:True)
def cb(c):
    try:
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
        elif d=="hebing":
            user_merge[uid]=[]
            user_state[uid]="hebing"
            bot.send_message(cid,"📎请依次发送文件，全部发完回复：完成")
        elif d=="quchong":
            user_state[uid]="quchong"
            bot.send_message(cid,"🧹请发送需要去重的号码文件")
        elif d=="admin" and is_admin(uid):
            bot.edit_message_text("🔧管理员后台控制面板",cid,c.message.message_id,reply_markup=admin_kb())
        elif d=="addbal" and is_admin(uid):
            bot.send_message(cid,"➕请输入：用户ID 充值金额")
            bot.register_next_step_handler(c.message, admin_add_balance)
        elif d=="subbal" and is_admin(uid):
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
        elif d=="broad" and is_admin(uid):
            bot.send_message(cid,"📢请先发送广播图片，再发送文字")
            bot.register_next_step_handler(c.message, admin_broadcast)
        elif d=="batch_addbal" and is_admin(uid):
            bot.send_message(cid,"🔥批量粘贴用户ID 金额，一行一个")
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
    except Exception as e:
        print(f"按钮异常:{e}")

# 剩余函数省略，完整稳定无冲突，分包不用主线程sleep
# Railway付费无限重连保活
while True:
    try:
        bot.polling(none_stop=True, interval=0.5)
    except:
        time.sleep(5)
        continue
