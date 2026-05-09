import json
import time
import random
import zipfile
import os
from io import BytesIO
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timezone, timedelta

# ====================== 配置 ======================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834

PRICE_SPLIT = 0.0004
PRICE_INSERT = 0.0004
PRICE_MERGE = 0.0002
PRICE_DEDUP = 0.0002

# 永久存档文件（Railway持久化保存）
USER_DB = "user_data.json"
CARD_DB = "card_data.json"
LOG_RECHARGE = "log_recharge.json"
LOG_CONSUME = "log_consume.json"

# 姓名库
XING = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛"
MING1 = "伟俊佳浩宇泽晨欣雨轩博文铭凯艺霖梓睿一诺嘉航沐辰"
MING2 = "杰豪琳雪婷芳莹瑞阳鑫鹏佳怡涵悦彤诗雅泽安诺"

# ====================== 永久读写存档函数 ======================
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 加载所有永久数据
user_data = load_json(USER_DB)
card_list = load_json(CARD_DB)
log_recharge = load_json(LOG_RECHARGE)
log_consume = load_json(LOG_CONSUME)

user_files = {}
user_merge_list = {}
user_state = {}
broad_msg = ""
broad_img = None

# ====================== 工具函数 ======================
def rand_name():
    return random.choice(XING) + random.choice(MING1) + random.choice(MING2)

def get_user(uid):
    uid = str(uid)
    if uid not in user_data:
        user_data[uid] = {"balance": 0.0, "fmt": "TXT", "line": 100}
        save_json(USER_DB, user_data)
    return user_data[uid]

def save_user():
    save_json(USER_DB, user_data)

def is_admin(uid):
    return int(uid) == ADMIN_ID

def beijing_time():
    utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    bj = utc.astimezone(timezone(timedelta(hours=8)))
    return bj.strftime("%Y-%m-%d %H:%M:%S")

def clear_empty_line(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)

def zip_to_txt(bin_data):
    try:
        txt = ""
        zf = zipfile.ZipFile(BytesIO(bin_data))
        for fn in zf.namelist():
            if fn.lower().endswith(".txt") and not fn.endswith("/"):
                txt += zf.read(fn).decode("utf-8", "ignore") + "\n"
        zf.close()
        return clear_empty_line(txt)
    except:
        return ""

# ====================== 机器人初始化 ======================
bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

# ====================== 菜单键盘 ======================
def main_menu(uid):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(f"格式：{get_user(uid)['fmt']}", callback_data="fmt"),
        InlineKeyboardButton(f"每份{get_user(uid)['line']}行", callback_data="setline")
    )
    kb.add(
        InlineKeyboardButton("个人中心", callback_data="user"),
        InlineKeyboardButton("卡密充值", callback_data="cdk")
    )
    kb.add(
        InlineKeyboardButton("文件合并", callback_data="merge"),
        InlineKeyboardButton("号码去重", callback_data="dedup")
    )
    if is_admin(uid):
        kb.add(InlineKeyboardButton("管理后台", callback_data="admin"))
    return kb

def user_submenu(uid):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("我的余额", callback_data="bal"),
        InlineKeyboardButton("充值记录", callback_data="rlog")
    )
    kb.add(
        InlineKeyboardButton("消费记录", callback_data="clog"),
        InlineKeyboardButton("返回主页", callback_data="back")
    )
    return kb

def admin_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("单人加余额", callback_data="addbal"),
        InlineKeyboardButton("单人扣余额", callback_data="subbal")
    )
    kb.add(
        InlineKeyboardButton("生成卡密", callback_data="makecdk"),
        InlineKeyboardButton("用户余额总表", callback_data="userlist")
    )
    kb.add(
        InlineKeyboardButton("全站广播", callback_data="broad"),
        InlineKeyboardButton("批量加余额", callback_data="batchbal")
    )
    kb.add(InlineKeyboardButton("返回", callback_data="back"))
    return kb

# ====================== 开始命令 ======================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id
    get_user(uid)
    user_state[uid] = "idle"
    bot.send_message(msg.chat.id,
f"""🤖 大晴工具机器人 运行正常✅
北京时间：{beijing_time()}
"", reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: m.text == "取消")
def cancel(msg):
    uid = msg.from_user.id
    user_state[uid] = "idle"
    user_files.pop(uid, None)
    user_merge_list.pop(uid, None)
    bot.send_message(msg.chat.id, "✅已清空所有任务缓存")

# ====================== 按钮回调 全异常防护 ======================
@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    try:
        bot.answer_callback_query(c.id)
        uid = c.from_user.id
        cid = c.message.chat.id
        mid = c.message.message_id
        d = c.data

        if d == "fmt":
            u = get_user(uid)
            u['fmt'] = "VCF" if u['fmt'] == "TXT" else "TXT"
            save_user()
            bot.edit_message_text("格式已切换", cid, mid, reply_markup=main_menu(uid))

        elif d == "setline":
            bot.send_message(cid, "请输入分割每份行数")
            bot.register_next_step_handler(c.message, lambda m: set_line(uid, cid, m))

        elif d == "user":
            bot.edit_message_text("个人中心", cid, mid, reply_markup=user_submenu(uid))

        elif d == "bal":
            bot.send_message(cid, f"💰当前余额：{get_user(uid)['balance']:.4f} 元")

        elif d == "rlog":
            txt = "\n".join(log_recharge.get(str(uid), ["暂无记录"]))
            bot.send_message(cid, txt[:4000])

        elif d == "clog":
            txt = "\n".join(log_consume.get(str(uid), ["暂无记录"]))
            bot.send_message(cid, txt[:4000])

        elif d == "back":
            bot.edit_message_text("🏠主菜单", cid, mid, reply_markup=main_menu(uid))

        elif d == "cdk":
            bot.send_message(cid, "请发送你的卡密")
            bot.register_next_step_handler(c.message, use_cdk)

        elif d == "merge":
            user_merge_list[uid] = []
            user_state[uid] = "merge"
            bot.send_message(cid, "请依次发送文件，完成后回复：完成")

        elif d == "dedup":
            user_state[uid] = "dedup"
            bot.send_message(cid, "请发送需要去重的号码文件")

        elif d == "admin" and is_admin(uid):
            bot.edit_message_text("🔧管理员后台", cid, mid, reply_markup=admin_menu())

    except Exception as e:
        print(f"按钮异常：{e}")

# ====================== 文件处理 ======================
@bot.message_handler(content_types=['document'])
def get_file(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    try:
        file = bot.get_file(msg.document.file_id)
        data = bot.download_file(file.file_path)
        txt = zip_to_txt(data) if msg.document.file_name.endswith(".zip") else data.decode("utf-8","ignore")
        user_files[uid] = {"txt": txt}
        bot.send_message(cid, "✅文件读取成功，请选择处理方式", reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("纯净分割", callback_data="split_clean"),
            InlineKeyboardButton("插雷分割", callback_data="split_ins")
        ))
    except:
        bot.send_message(cid, "❌文件解析失败")

# ====================== 缺失函数补全 + 存档写入 ======================
def set_line(uid, cid, msg):
    try:
        num = int(msg.text)
        u = get_user(uid)
        u['line'] = num
        save_user()
        bot.send_message(cid, f"✅分割行数已设置为 {num}")
    except:
        bot.send_message(cid, "请输入纯数字")

def use_cdk(msg):
    cdk = msg.text.strip()
    uid = str(msg.from_user.id)
    cid = msg.chat.id
    if cdk in card_list:
        money = card_list[cdk]
        get_user(uid)['balance'] += money
        save_user()
        del card_list[cdk]
        save_json(CARD_DB, card_list)

        log_recharge[uid] = log_recharge.get(uid, []) + [f"{beijing_time()} 充值{money}元"]
        save_json(LOG_RECHARGE, log_recharge)
        bot.send_message(cid, f"✅充值成功！到账{money}元")
    else:
        bot.send_message(cid, "❌无效或已使用卡密")

def create_cdk(msg):
    try:
        money = float(msg.text)
        cdk = "TK"+str(random.randint(100000,999999))
        card_list[cdk] = money
        save_json(CARD_DB, card_list)
        bot.send_message(msg.chat.id, f"✅卡密生成成功\n{cdk}")
    except:
        bot.send_message(msg.chat.id, "请输入正确金额")

def admin_add_bal(msg):
    try:
        tid, m = msg.text.split()
        tid = str(tid)
        money = float(m)
        get_user(tid)['balance'] += money
        save_user()
        bot.send_message(msg.chat.id, "✅余额添加成功")
    except:
        bot.send_message(msg.chat.id, "格式错误：用户ID 金额")

def send_broadcast(msg):
    text = msg.text
    cnt = 0
    for uid in user_data:
        try:
            bot.send_message(int(uid), text)
            cnt +=1
        except:continue
    bot.send_message(msg.chat.id, f"✅广播完成，已发送{cnt}人")

# ====================== Railway专用无限稳连 永不杀进程 ======================
if __name__ == "__main__":
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=15)
        except Exception as e:
            print("掉线自动重连中...", e)
            time.sleep(3)
            continue
