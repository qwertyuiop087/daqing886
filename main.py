import os
import json
import time
import random
import zipfile
import hashlib
import fcntl
from flask import Flask, request
from threading import Thread
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaDocument, Update
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler,
    Filters, CallbackQueryHandler, CallbackContext
)
from telegram.error import RetryAfter, BadRequest, TimedOut

# ====================== 固定配置 ======================
EP_URL = "https://mzf.akwl.net"
EP_PID = "10960"
EP_KEY = "x1ZeWaejP810hCmMjRwn"
TOKEN = "8511432045:AAH3vlvLLuSlRkpHyNF5d6uIQPfiCSQzYVs"
ADMIN = 7793291484
DATA_FILE = "user.json"
CARD_FILE = "card.json"
SET_FILE = "set.json"

PRICE = 0.0004
SEND_BATCH = 10
SEND_DELAY = 3

# ====================== 环境配置 ======================
app = Flask(__name__)

@app.route('/')
def index():
    return "大晴分包机器人 最终稳定版"

# 易支付回调接口
@app.route('/pay/callback', methods=['POST'])
def pay_callback():
    data = request.form.to_dict()
    pid = data.get('pid')
    trade_no = data.get('trade_no')
    out_trade_no = data.get('out_trade_no')
    money = data.get('money')
    trade_status = data.get('trade_status')
    sign = data.get('sign')

    if trade_status != 'TRADE_SUCCESS':
        return 'fail'

    s = f"money={money}&name=充值{money}元&out_trade_no={out_trade_no}&pid={pid}&trade_no={trade_no}&trade_status={trade_status}{EP_KEY}"
    my_sign = hashlib.md5(s.encode()).hexdigest()
    if my_sign != sign:
        return 'fail'

    try:
        uid, amount = out_trade_no.split('_')
        uid = int(uid)
        add_balance(uid, int(amount))
        return 'success'
    except:
        return 'fail'

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# ====================== 数据读写 ======================
def load(f):
    if not os.path.exists(f):
        return {}
    try:
        with open(f, 'r', encoding='utf-8') as fp:
            fcntl.flock(fp, fcntl.LOCK_SH)
            data = json.load(fp)
            fcntl.flock(fp, fcntl.LOCK_UN)
            return data
    except:
        return {}

def save(f, d):
    with open(f, 'w', encoding='utf-8') as fp:
        fcntl.flock(fp, fcntl.LOCK_EX)
        json.dump(d, fp, indent=2, ensure_ascii=False)
        fcntl.flock(fp, fcntl.LOCK_UN)

def get_user(): return load(DATA_FILE)
def get_card(): return load(CARD_FILE)
def get_set(): return load(SET_FILE)
def save_user(d): save(DATA_FILE, d)
def save_card(d): save(CARD_FILE, d)
def save_set(d): save(SET_FILE, d)

# 初始化
set_data = get_set()
set_data['price'] = PRICE
save_set(set_data)

state = {}
split_set = {}
file_cache = {}
thunder = {}
name_cache = {}
custom_name = {}
file_step = {}
mode = {}

# ====================== 工具 ======================
def is_admin(uid):
    return uid == ADMIN

def bal(uid):
    user = get_user()
    return user.get(str(uid), {}).get("balance", 0)

def add_balance(uid, amount):
    user = get_user()
    u = str(uid)
    user[u] = user.get(u, {})
    user[u]["balance"] = user[u].get("balance", 0) + amount
    save_user(user)

def batch_add_balance(lines):
    success = 0
    fail = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            fail += 1
            continue
        try:
            t_uid = int(parts[0])
            amt = int(parts[1])
            add_balance(t_uid, amt)
            success += 1
        except:
            fail += 1
    return success, fail

# ====================== 菜单 ======================
def main_menu(uid):
    current_mode = mode.get(uid, "txt")
    mode_text = "📄 TXT 模式" if current_mode == "txt" else "📇 VCF 模式"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 余额", callback_data='bal'),
         InlineKeyboardButton("💳 在线充值", callback_data='pay')],
        [InlineKeyboardButton("🎫 卡密充值", callback_data='card'),
         InlineKeyboardButton("⚙️ 分包行数", callback_data='split')],
        [InlineKeyboardButton(mode_text, callback_data='switch_mode')],
        *([[InlineKeyboardButton("👑 管理", callback_data='admin')]] if is_admin(uid) else [])
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 生成卡密", callback_data='gen_card')],
        [InlineKeyboardButton("👥 用户列表", callback_data='user_list')],
        [InlineKeyboardButton("💵 手动加余额", callback_data='add_balance')],
        [InlineKeyboardButton("💵 批量加余额", callback_data='batch_add')],
        [InlineKeyboardButton("🔙 返回", callback_data='home')]
    ])

# ====================== 指令 ======================
def start(update, context):
    uid = update.effective_user.id
    current_mode = mode.get(uid, "txt")
    update.message.reply_text(
        f"大晴分包机器人🤖\n当前模式：{'📄 TXT' if current_mode == 'txt' else '📇 VCF'}",
        reply_markup=main_menu(uid)
    )

def callback(update, context):
    q = update.callback_query
    uid = q.from_user.id
    d = q.data
    q.answer()

    if d == 'home':
        current_mode = mode.get(uid, "txt")
        q.edit_message_text(f"主菜单", reply_markup=main_menu(uid))
    elif d == 'bal':
        q.edit_message_text(f"💰 余额：{bal(uid)}", reply_markup=main_menu(uid))
    elif d == 'pay':
        state[uid] = 'PAY'
        q.edit_message_text("💳 输入充值金额（元）：")
    elif d == 'card':
        state[uid] = 'CARD'
        q.edit_message_text("🎫 输入卡密：")
    elif d == 'split':
        state[uid] = 'SET_SPLIT'
        q.edit_message_text("⚙️ 输入分包行数：")
    elif d == 'switch_mode':
        mode[uid] = "vcf" if mode.get(uid, "txt") == "txt" else "txt"
        q.edit_message_text(f"✅ 已切换模式", reply_markup=main_menu(uid))
    elif d == 'admin' and is_admin(uid):
        q.edit_message_text("👑 管理面板", reply_markup=admin_menu())
    elif d == 'gen_card' and is_admin(uid):
        state[uid] = 'GEN_CARD'
        q.edit_message_text("➕ 输入：数量 金额")
    elif d == 'user_list' and is_admin(uid):
        user = get_user()
        msg = "👥 用户列表：\n"
        for u, b in user.items():
            msg += f"{u}: {b.get('balance',0)}\n"
        q.edit_message_text(msg)
    elif d == 'add_balance' and is_admin(uid):
        state[uid] = 'ADD_BALANCE'
        q.edit_message_text("💵 输入：用户ID 金额")
    elif d == 'batch_add' and is_admin(uid):
        state[uid] = 'BATCH_ADD'
        q.edit_message_text("💵 批量加余额：一行一个（用户ID 金额）")

# ====================== 文本处理 ======================
def text(update, context):
    uid = update.effective_user.id
    txt = update.message.text.strip()
    s = state.get(uid)
    step = file_step.get(uid, 0)

    if s == 'PAY':
        if not txt.isdigit():
            update.message.reply_text("❌ 请输入有效数字")
            return
        money = int(txt)
        out_trade_no = f"{uid}_{money}"
        sign_str = f"money={money}&name=充值{money}元&out_trade_no={out_trade_no}&pid={EP_PID}{EP_KEY}"
        sign = hashlib.md5(sign_str.encode()).hexdigest()
        pay_link = f"{EP_URL}/xpay/epay/?pid={EP_PID}&type=alipay&out_trade_no={out_trade_no}&name=充值{money}元&money={money}&notify_url=https://你的域名/pay/callback&return_url=https://t.me/your_bot&sign={sign}&sign_type=MD5"
        update.message.reply_text(f"💳 支付链接：\n{pay_link}")
        state.pop(uid)
        return
    elif s == 'CARD':
        card = get_card()
        if txt in card and not card[txt]['used']:
            amt = card[txt]['amount']
            card[txt]['used'] = True
            save_card(card)
            add_balance(uid, amt)
            update.message.reply_text(f"✅ 充值成功 +{amt}")
        else:
            update.message.reply_text("❌ 卡密无效")
        state.pop(uid)
    elif s == 'GEN_CARD' and is_admin(uid):
        try:
            cnt, amt = map(int, txt.split())
            card = get_card()
            codes = []
            for _ in range(cnt):
                c = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=10))
                card[c] = {'amount': amt, 'used': False}
                codes.append(c)
            save_card(card)
            update.message.reply_text("✅ 生成卡密：\n" + '\n'.join(codes))
        except:
            update.message.reply_text("❌ 格式错误，请输入：数量 金额")
        state.pop(uid)
    elif s == 'SET_SPLIT':
        if txt.isdigit():
            split_set[uid] = int(txt)
            update.message.reply_text(f"✅ 分包行数已设置为：{txt}")
        else:
            update.message.reply_text("❌ 请输入有效数字")
        state.pop(uid)
    elif s == 'ADD_BALANCE' and is_admin(uid):
        try:
            t_uid, amt = map(int, txt.split())
            add_balance(t_uid, amt)
            update.message.reply_text(f"✅ 给用户{t_uid} 加余额{amt} 成功")
        except:
            update.message.reply_text("❌ 格式错误，请输入：用户ID 金额")
        state.pop(uid)
    elif s == 'BATCH_ADD' and is_admin(uid):
        lines = txt.split('\n')
        success, fail = batch_add_balance(lines)
        update.message.reply_text(f"✅ 批量加余额完成：成功{success}条，失败{fail}条")
        state.pop(uid)
    elif step == 1:
        thunder[uid] = [] if txt.lower() in ['否', 'no', 'n'] else txt.split()
        file_step[uid] = 2
        update.message.reply_text("📛 自定义文件名（输入否=使用默认文件名）")
    elif step == 2:
        custom_name[uid] = name_cache.get(uid, 'out') if txt.lower() in ['否', 'no', 'n'] else txt
        file_step[uid] = 0
        update.message.reply_text("📦 开始分包...")
        Thread(target=do_split, args=(uid, update.message, context), daemon=True).start()

# ====================== 文件处理 ======================
def file(update, context):
    uid = update.effective_user.id
    if bal(uid) <= 0:
        return update.message.reply_text("❌ 余额不足，请先充值")
    doc = update.message.document
    fname = doc.file_name.lower()
    if not fname.endswith(('.txt', '.zip', '.vcf')):
        return update.message.reply_text("仅支持 TXT / ZIP / VCF 格式文件")
    tmp = f"tmp_{uid}"
    try:
        context.bot.get_file(doc.file_id).download(tmp)
        lines = []
        if fname.endswith(('.txt', '.vcf')):
            with open(tmp, 'r', encoding='utf-8', errors='ignore') as f:
                lines = [l.strip() for l in f if l.strip()]
        else:
            with zipfile.ZipFile(tmp, 'r') as zf:
                for n in zf.namelist():
                    if n.lower().endswith(('.txt', '.vcf')):
                        with zf.open(n) as f:
                            lines.extend([l.strip() for l in f.read().decode('utf-8', errors='ignore').splitlines() if l.strip()])
        os.remove(tmp)
        if not lines:
            return update.message.reply_text("❌ 文件无有效内容")
        file_cache[uid] = lines
        name_cache[uid] = os.path.splitext(doc.file_name)[0]
        file_step[uid] = 1
        update.message.reply_text("⚡ 输入雷号（空格分隔，输入否=不插雷）")
    except Exception as e:
        os.remove(tmp)
        return update.message.reply_text(f"❌ 文件读取失败：{str(e)}")

# ====================== 分包发送（失败无限重试，绝不跳过） ======================
def do_split(uid, msg, context):
    try:
        lines = file_cache.pop(uid, [])
        if not lines:
            return msg.reply_text("❌ 数据失效，请重新上传文件")

        per = split_set.get(uid, 50)
        cost = len(lines) * PRICE
        user_balance = bal(uid)
        if user_balance < cost:
            return msg.reply_text(f"❌ 余额不足，本次需扣费 {cost:.4f}，当前余额 {user_balance:.4f}")

        user = get_user()
        u_key = str(uid)
        user[u_key] = user.get(u_key, {})
        user[u_key]["balance"] = user[u_key].get("balance", 0) - cost
        save_user(user)

        t_list = thunder.get(uid, [])
        if t_list:
            lines += t_list
            random.shuffle(lines)

        chunks = [lines[i:i+per] for i in range(0, len(lines), per)]
        total_packs = len(chunks)
        prefix = custom_name.get(uid, name_cache.get(uid, 'out'))
        current_mode = mode.get(uid, "txt")
        ext = ".vcf" if current_mode == "vcf" else ".txt"

        file_list = []
        for idx in range(total_packs):
            chunk = chunks[idx]
            fn = f"{prefix}_{idx+1}{ext}"
            with open(fn, 'w', encoding='utf-8') as f:
                if current_mode == "vcf":
                    for line in chunk:
                        if ':' in line:
                            nm, ph = line.split(':', 1)
                            nm, ph = nm.strip(), ph.strip()
                        else:
                            nm = f"Contact_{random.randint(1000,9999)}"
                            ph = line.strip()
                        f.write(f"BEGIN:VCARD\nVERSION:3.0\nFN:{nm}\nTEL:{ph}\nEND:VCARD\n")
                else:
                    f.write('\n'.join(chunk))
            file_list.append(fn)

        msg.reply_text(f"✅ 开始发送，共 {total_packs} 个文件，10个一组，失败自动重试")

        # 10个一组，失败无限重试，绝不跳过
        for i in range(0, len(file_list), SEND_BATCH):
            batch = file_list[i:i+SEND_BATCH]
            group = [InputMediaDocument(open(fn, 'rb')) for fn in batch]

            # 无限重试，直到成功
            while True:
                try:
                    context.bot.send_media_group(msg.chat.id, group)
                    break
                except RetryAfter as e:
                    time.sleep(e.retry_after + 1)
                except:
                    time.sleep(2)

            msg.reply_text(f"✅ 已发送：{i+1} ~ {min(i+SEND_BATCH, total_packs)}")
            time.sleep(SEND_DELAY)

        for fn in file_list:
            try:
                os.remove(fn)
            except:
                pass

        msg.reply_text("🏁 全部发送完成！")

    except Exception as e:
        msg.reply_text(f"❌ 分包异常：{str(e)}")

# ====================== 启动 ======================
def main():
    Thread(target=run_web, daemon=True).start()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CallbackQueryHandler(callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text))
    dp.add_handler(MessageHandler(Filters.document, file))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
