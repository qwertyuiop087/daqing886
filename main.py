import os
import random
import time
import zipfile
import re
import threading
import queue
from io import BytesIO
import telebot
from telebot.types import InputMediaDocument
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from telebot.apihelper import ApiException

# ===================== 读取 Railway 环境变量 =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# 业务价格配置
PRICE_SPLIT = 0.0004
PRICE_INSERT = 0.0004
PRICE_MERGE = 0.0002
PRICE_DEDUP = 0.0002
BATCH_SIZE = 10
PAGE_NUM = 20
TG_API_DELAY = 1.2
TG_GROUP_DELAY = 2.5
MAX_WORKERS = 4
OP_TIMEOUT = 120
CHUNK_READ_SIZE = 65536

# 全局数据
broad_text = ""
task_queue = queue.Queue(maxsize=100)
user_file = {}
users = {}          # 普通用户数据：余额、格式、行数、VIP过期时间
cards = {}          # 余额卡密
time_cards = {}     # 时长VIP卡密
user_merge = {}
user_state = {}
user_insert = {}
log_user = {}       # 消费日志
log_recharge = {}   # 充值日志
page_temp = {}
lei_detail_log = {}
temp_split_data = {}

# 姓名库
XING = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛"
MING1 = "伟俊佳浩宇泽晨欣雨轩博文铭凯艺霖梓睿一诺嘉航沐辰"
MING2 = "杰豪琳雪婷芳莹瑞阳鑫鹏佳怡涵悦彤诗雅泽安诺"

# ===================== 工具函数 =====================
def get_rand_3_name():
    return random.choice(XING) + random.choice(MING1) + random.choice(MING2)

def get_user(uid):
    if uid not in users:
        users[uid] = {
            "balance": 0.0,
            "mode": "TXT",
            "line": 100,
            "op_start": 0,
            "vip_expire": 0
        }
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

# 判断时长VIP是否有效
def is_vip_valid(uid):
    u = get_user(uid)
    now = int(time.time())
    return u["vip_expire"] > now

# 消费日志（倒序存储）
def add_log(uid, txt, num, cost):
    t = get_beijing_time_str()
    if uid not in log_user:
        log_user[uid] = []
    log_user[uid].insert(0, f"[{t}]｜{txt}｜{num}行｜扣费{cost:.4f}｜剩余{get_user(uid)['balance']:.4f}")

# 充值日志（倒序存储）
def add_rc(uid, money):
    t = get_beijing_time_str()
    if uid not in log_recharge:
        log_recharge[uid] = []
    log_recharge[uid].insert(0, f"[{t}]｜充值+{money:.4f}｜剩余{get_user(uid)['balance']:.4f}")

def get_beijing_time_str():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def get_now_timestamp():
    return int(time.time())

# 清洗空白行
def clean_lines(raw_lines):
    clean = []
    for line in raw_lines:
        s = re.sub(r'\s+', '', line.strip())
        if s:
            clean.append(s)
    return clean

def extract_txt_from_zip_large(zip_bytes):
    all_raw = []
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            for file_name in zf.namelist():
                if file_name.lower().endswith(".txt") and not file_name.endswith("/"):
                    with zf.open(file_name) as f:
                        text = f.read().decode("utf-8", errors="ignore")
                        all_raw.extend(text.splitlines())
        return clean_lines(all_raw)
    except Exception:
        return []

def read_txt_large(data):
    text = data.decode("utf-8", errors="ignore")
    raw_lines = text.splitlines()
    return clean_lines(raw_lines)

def dedup_phone_list_large(raw_lines):
    seen = set()
    new_lines = []
    for line in raw_lines:
        pure = re.sub(r'\s+', '', line.strip())
        if pure and pure not in seen:
            seen.add(pure)
            new_lines.append(pure)
    return new_lines, len(raw_lines), len(raw_lines)

# 消息发送
def safe_send_msg(chat_id, text, retry=3):
    for i in range(retry):
        try:
            time.sleep(TG_API_DELAY)
            bot.send_message(chat_id, text)
            return True
        except ApiException as e:
            if "429" in str(e):
                time.sleep(3)
                continue
            return False
    return False

def safe_send_media_group(chat_id, media_list, retry=3):
    for i in range(retry):
        try:
            time.sleep(TG_GROUP_DELAY)
            bot.send_media_group(chat_id, media_list)
            return True
        except ApiException as e:
            if "429" in str(e):
                time.sleep(4)
                continue
            return False
    return False

# 分页按钮组件
def page_btn(log_type, now_page, total_page):
    kb = telebot.types.InlineKeyboardMarkup(row_width=5)
    btn = []
    if now_page > 1:
        btn.append(telebot.types.InlineKeyboardButton("⏮首页", callback_data=f"{log_type}_1"))
        btn.append(telebot.types.InlineKeyboardButton("⬅上页", callback_data=f"{log_type}_{now_page-1}"))
    btn.append(telebot.types.InlineKeyboardButton(f"{now_page}/{total_page}", callback_data="none"))
    if now_page < total_page:
        btn.append(telebot.types.InlineKeyboardButton("下页➡", callback_data=f"{log_type}_{now_page+1}"))
        btn.append(telebot.types.InlineKeyboardButton("⏭尾页", callback_data=f"{log_type}_{total_page}"))
    kb.add(*btn)
    kb.add(telebot.types.InlineKeyboardButton("🔙返回个人中心", callback_data="return_user"))
    kb.add(telebot.types.InlineKeyboardButton("📘发数字直接跳转页码", callback_data="none"))
    return kb

# ===================== 机器人初始化 =====================
if not BOT_TOKEN or ADMIN_ID == 0:
    print("错误：请在 Railway 环境变量配置 BOT_TOKEN 和 ADMIN_ID")
    exit()

bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

# ===================== 菜单UI =====================
def menu(uid):
    u = get_user(uid)
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton(f"📄格式：{u['mode']}",callback_data="mode"),
           telebot.types.InlineKeyboardButton(f"💰分割每份{u['line']}行",callback_data="line"))
    kb.add(telebot.types.InlineKeyboardButton("👤个人中心",callback_data="user"))
    kb.add(telebot.types.InlineKeyboardButton("💳卡密充值",callback_data="cdk_use"))
    kb.add(telebot.types.InlineKeyboardButton("📎文件合并",callback_data="hebing"),
           telebot.types.InlineKeyboardButton("🧹号码去重",callback_data="quchong"))
    if is_admin(uid):
        kb.add(telebot.types.InlineKeyboardButton("🔧管理后台",callback_data="admin"))
    return kb

def user_menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("💰我的余额",callback_data="bal"))
    kb.add(telebot.types.InlineKeyboardButton("💳充值记录",callback_data="my_rc_1"))
    kb.add(telebot.types.InlineKeyboardButton("📜消费明细",callback_data="my_use_1"))
    kb.add(telebot.types.InlineKeyboardButton("🔙返回主页",callback_data="back"))
    return kb

# 管理员菜单：新增【🗑️清空用户余额】
def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("➕单人加余额",callback_data="addbal"),
           telebot.types.InlineKeyboardButton("➖单人扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("🗑️清空用户余额",callback_data="clear_bal"))
    kb.add(telebot.types.InlineKeyboardButton("🎟️余额卡密",callback_data="card"),
           telebot.types.InlineKeyboardButton("⏰时间卡密",callback_data="time_card"))
    kb.add(telebot.types.InlineKeyboardButton("📊用户余额总表",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("📋全站充值记录",callback_data="rc_page_1"),
           telebot.types.InlineKeyboardButton("📋全站消费记录",callback_data="use_page_1"))
    kb.add(telebot.types.InlineKeyboardButton("📢全站广播",callback_data="broad"),
           telebot.types.InlineKeyboardButton("🔥批量加余额",callback_data="batch_addbal_start"))
    kb.add(telebot.types.InlineKeyboardButton("🎫有效余额卡密",callback_data="check_all_cdk"),
           telebot.types.InlineKeyboardButton("🗑️作废卡密",callback_data="del_cdk"))
    kb.add(telebot.types.InlineKeyboardButton("⏰有效时间卡密",callback_data="check_time_card"))
    kb.add(telebot.types.InlineKeyboardButton("📤导出卡密",callback_data="export_cdk"),
           telebot.types.InlineKeyboardButton("🔙返回",callback_data="back"))
    return kb

def select_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("⚡插雷分包",callback_data="ins"),
           telebot.types.InlineKeyboardButton("📄纯净分包",callback_data="noins"))
    return kb

# ===================== 业务功能逻辑（分包/插雷/合并/去重） =====================
def ins_num(m):
    uid = m.from_user.id
    try:
        num = int(m.text)
        user_insert[uid] = {"num": num, "txt_lines": user_file[uid]}
        lei_detail_log[uid] = []
        bot.send_message(m.chat.id, "⚡请发送雷号，一行一个")
        bot.register_next_step_handler(m, ins_phone)
    except:
        bot.send_message(m.chat.id, "❌请输入纯数字")

def ins_phone(m):
    uid = m.from_user.id
    if uid not in user_insert:
        return bot.send_message(m.chat.id, "❌流程失效，请重新上传文件")
    phones = re.findall(r"\d+", m.text)
    if len(phones) == 0:
        bot.send_message(m.chat.id, "❌未识别号码，请重发")
        bot.register_next_step_handler(m, ins_phone)
        return
    user_insert[uid]['phone'] = phones
    bot.send_message(m.chat.id, "📄请输入文件前缀名（例如：插雷成品）")
    bot.register_next_step_handler(m, ins_done)

def ins_done(m):
    uid = m.from_user.id
    cid = m.chat.id
    info = user_insert[uid]
    file_prefix = m.text.strip()
    lines = info['txt_lines']
    total = len(lines)
    fee_split = total * PRICE_SPLIT
    fee_insert = total * PRICE_INSERT
    total_fee = fee_split + fee_insert
    u = get_user(uid)

    if not is_vip_valid(uid):
        if u['balance'] < total_fee:
            safe_send_msg(cid, f"❌余额不足｜需要{total_fee:.4f}｜当前{u['balance']:.4f}")
            return

    safe_send_msg(cid, f"✅开始处理，总行数：{total}行，请耐心等待...")
    chunk = [lines[i:i+u['line']] for i in range(0, total, u['line'])]
    media = []
    file_idx = 1
    batch_num = 1
    ph_idx = 0
    phones = info['phone']
    detail_lines = []
    send_all_success = True

    for chunk_lines in chunk:
        chunk_len = len(chunk_lines)
        insert_count = info['num']
        insert_pos_list = random.sample(range(1, chunk_len+1), insert_count)
        insert_pos_list.sort()
        temp_list = chunk_lines.copy()

        for pos in insert_pos_list:
            lei_num = phones[ph_idx % len(phones)]
            temp_list.insert(pos-1, lei_num)
            ph_idx += 1
            detail_lines.append(f"📁{file_prefix}_{file_idx}.txt｜第{pos}行｜雷号：{lei_num}")

        if u['mode'] == "VCF":
            vcf = ""
            for p in temp_list:
                n = get_rand_3_name()
                vcf += f"BEGIN:VCARD\nVERSION:3.0\nN:{n};;;\nFN:{n}\nTEL:{p}\nEND:VCARD\n"
            bio = BytesIO(vcf.encode())
            bio.name = f"{file_prefix}_{file_idx}.vcf"
        else:
            bio = BytesIO("\n".join(temp_list).encode())
            bio.name = f"{file_prefix}_{file_idx}.txt"
        media.append(InputMediaDocument(bio))

        if len(media) >= 10:
            safe_send_msg(cid, f"📤第{batch_num}批：文件 {file_idx-9}～{file_idx}")
            ok = safe_send_media_group(cid, media)
            if not ok:
                send_all_success = False
                break
            media = []
            batch_num += 1
        file_idx += 1

    if send_all_success and len(media) > 0:
        last_start = file_idx - len(media)
        safe_send_msg(cid, f"📤第{batch_num}批：文件 {last_start}～{file_idx-1}")
        ok = safe_send_media_group(cid, media)
        if not ok:
            send_all_success = False

    if send_all_success:
        if not is_vip_valid(uid):
            u['balance'] -= total_fee
            add_log(uid, f"插雷分包｜每份{info['num']}个雷", total, total_fee)
        lei_detail_log[uid] = detail_lines
        detail_txt = "📝插雷位置明细：\n" + "\n".join(detail_lines)
        if len(detail_txt) > 3800:
            bio = BytesIO(detail_txt.encode("utf-8-sig"))
            bio.name = "插雷明细.txt"
            bot.send_document(cid, bio)
        else:
            safe_send_msg(cid, detail_txt)
        if is_vip_valid(uid):
            safe_send_msg(cid, f"✅插雷完成（时长VIP免费）｜共{file_idx-1}个文件")
        else:
            safe_send_msg(cid, f"✅插雷完成｜扣费{total_fee:.4f}｜剩余{u['balance']:.4f}")
    else:
        safe_send_msg(cid, "❌发送失败，本次不扣费，请稍后重试")

    if uid in user_file:
        del user_file[uid]
    if uid in user_insert:
        del user_insert[uid]

def split_send_clean(cid, uid, txt_lines, name):
    lines = txt_lines
    total = len(lines)
    fee = total * PRICE_SPLIT
    u = get_user(uid)

    if not is_vip_valid(uid):
        if u['balance'] < fee:
            safe_send_msg(cid, "❌余额不足")
            return

    safe_send_msg(cid, f"✅开始生成，总行数：{total}行")
    chunk = [lines[i:i+u['line']] for i in range(0, total, u['line'])]
    media = []
    file_idx = 1
    batch_num = 1
    send_all_success = True

    for c in chunk:
        if u['mode'] == "VCF":
            vcf = ""
            for p in c:
                n = get_rand_3_name()
                vcf += f"BEGIN:VCARD\nVERSION:3.0\nN:{n};;;\nFN:{n}\nTEL:{p}\nEND:VCARD\n"
            bio = BytesIO(vcf.encode())
            bio.name = f"{name}_{file_idx}.vcf"
        else:
            bio = BytesIO("\n".join(c).encode())
            bio.name = f"{name}_{file_idx}.txt"
        media.append(InputMediaDocument(bio))

        if len(media) >= 10:
            safe_send_msg(cid, f"📤第{batch_num}批：文件 {file_idx-9}～{file_idx}")
            ok = safe_send_media_group(cid, media)
            if not ok:
                send_all_success = False
                break
            media = []
            batch_num += 1
        file_idx += 1

    if send_all_success and len(media) > 0:
        last_start = file_idx - len(media)
        safe_send_msg(cid, f"📤第{batch_num}批：文件 {last_start}～{file_idx-1}")
        ok = safe_send_media_group(cid, media)
        if not ok:
            send_all_success = False

    if send_all_success:
        if not is_vip_valid(uid):
            u['balance'] -= fee
            add_log(uid, "纯净分包", total, fee)
        if is_vip_valid(uid):
            safe_send_msg(cid, f"✅纯净分包完成（时长VIP免费）｜共{file_idx-1}个文件")
        else:
            safe_send_msg(cid, f"✅纯净分包完成｜扣费{fee:.4f}｜剩余{u['balance']:.4f}")
    else:
        safe_send_msg(cid, "❌发送失败，本次不扣费")

    if uid in user_file:
        del user_file[uid]

# ===================== 新增：清空指定用户余额 流程 =====================
def wait_clear_balance_user(m):
    try:
        target_uid = int(m.text.strip())
        u = get_user(target_uid)
        old_bal = u["balance"]
        u["balance"] = 0.0
        safe_send_msg(m.chat.id, f"✅操作成功\n用户ID：{target_uid}\n原余额：{old_bal:.4f}\n当前余额：0.0000")
    except ValueError:
        safe_send_msg(m.chat.id, "❌请输入纯数字用户ID！")

# ===================== 回调事件（核心入口） =====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    data = call.data
    bot.answer_callback_query(call.id)

    if data == "mode":
        u = get_user(uid)
        u["mode"] = "VCF" if u["mode"] == "TXT" else "TXT"
        bot.edit_message_text("✅格式已切换", cid, call.message.message_id, reply_markup=menu(uid))

    elif data == "line":
        bot.send_message(cid, "📏请输入单文件分割行数（纯数字）")
        bot.register_next_step_handler(call.message, lambda m: (get_user(uid).__setitem__("line", int(m.text)) if m.text.isdigit() else safe_send_msg(cid, "❌请输入数字"), bot.send_message(cid, "✅行数设置完成", reply_markup=menu(uid))))

    elif data == "user":
        bot.edit_message_text("👤个人中心", cid, call.message.message_id, reply_markup=user_menu(uid))

    elif data == "bal":
        u = get_user(uid)
        vip_status = "✅生效中" if is_vip_valid(uid) else "❌已过期/未开通"
        bot.send_message(cid, f"💰当前余额：{u['balance']:.4f}\n⏰时长VIP状态：{vip_status}")

    elif data == "back":
        bot.edit_message_text("🏠返回主页", cid, call.message.message_id, reply_markup=menu(uid))

    elif data == "hebing":
        user_state[uid] = "hebing"
        safe_send_msg(cid, "📎请上传需要合并的 TXT/ZIP 文件")

    elif data == "quchong":
        user_state[uid] = "quchong"
        safe_send_msg(cid, "🧹请上传需要去重的 TXT/ZIP 文件")

    elif data == "cdk_use":
        safe_send_msg(cid, "💳请发送卡密进行兑换")
        bot.register_next_step_handler(call.message, use_cdk)

    elif data == "admin":
        if not is_admin(uid):
            safe_send_msg(cid, "❌无管理员权限")
            return
        bot.edit_message_text("🔧管理后台", cid, call.message.message_id, reply_markup=admin_kb())

    # ========== 新增：清空用户余额 ==========
    elif data == "clear_bal":
        safe_send_msg(cid, "🗑️请输入要清空余额的【用户纯数字ID】：")
        bot.register_next_step_handler(call.message, wait_clear_balance_user)

    elif data == "addbal":
        safe_send_msg(cid, "➕格式：用户ID 金额（一行一条）")
        bot.register_next_step_handler(call.message, add_single_balance)

    elif data == "subbal":
        safe_send_msg(cid, "➖格式：用户ID 金额（一行一条）")
        bot.register_next_step_handler(call.message, sub_single_balance)

    elif data == "batch_addbal_start":
        safe_send_msg(cid, "🔥批量充值格式：\n用户ID 金额\n一行一条")
        bot.register_next_step_handler(call.message, batch_add_user_balance)

    elif data == "card":
        safe_send_msg(cid, "🎟️请输入卡密内容、面额（例：ABC123 10）")
        bot.register_next_step_handler(call.message, create_balance_card)

    elif data == "time_card":
        safe_send_msg(cid, "⏰创建时长卡密：格式 卡密 天数（例：XYZ789 7）")
        bot.register_next_step_handler(call.message, create_time_card)

    elif data == "check_all_cdk":
        txt = "🎫有效余额卡密列表：\n"
        for k,v in cards.items():
            txt += f"{k} | 面额：{v}\n"
        safe_send_msg(cid, txt[:4000])

    elif data == "check_time_card":
        txt = "⏰有效时长卡密列表：\n"
        for k,v in time_cards.items():
            txt += f"{k} | 有效期：{v}天\n"
        safe_send_msg(cid, txt[:4000])

    elif data == "del_cdk":
        safe_send_msg(cid, "🗑️请输入要作废的卡密")
        bot.register_next_step_handler(call.message, del_cdk)

    elif data == "export_cdk":
        txt = "余额卡密：\n" + "\n".join(cards.keys()) + "\n时长卡密：\n" + "\n".join(time_cards.keys())
        bio = BytesIO(txt.encode())
        bio.name = "全部卡密.txt"
        bot.send_document(cid, bio)

    elif data == "ins":
        safe_send_msg(cid, "⚡请输入每个文件插入雷号数量（纯数字）")
        bot.register_next_step_handler(call.message, ins_num)

    elif data == "noins":
        safe_send_msg(cid, "📄请输入输出文件前缀名称")
        bot.register_next_step_handler(call.message, lambda m: split_send_clean(cid, uid, user_file[uid], m.text.strip()) if uid in user_file else safe_send_msg(cid, "❌请先上传文件"))

    # ========== 用户余额总表（分页） ==========
    elif data == "ulist":
        all_user_list = list(users.items())
        page_temp[uid] = "ulist"
        page = 1
        total = len(all_user_list)
        if total == 0:
            safe_send_msg(cid, "📊暂无用户数据")
            return
        total_page = (total + PAGE_NUM - 1) // PAGE_NUM
        start = (page - 1) * PAGE_NUM
        end = page * PAGE_NUM
        page_data = all_user_list[start:end]
        text = f"📊用户余额总表 第{page}/{total_page}页\n用户ID | 余额\n"
        for uid_key, info in page_data:
            text += f"{uid_key} | {info['balance']:.4f}\n"
        bot.edit_message_text(text, cid, call.message.message_id, reply_markup=page_btn("ulist", page, total_page))

    # ========== 所有分页路由（充值/消费/个人/余额列表） ==========
    elif data.startswith(("rc_page_","use_page_","my_rc_","my_use_","ulist_")):
        page = int(data.split("_")[-1])
        p_type = "_".join(data.split("_")[:-1])
        page_temp[uid] = p_type
        if p_type == "rc_page":
            all_log = []
            for u_id, logs in log_recharge.items():
                for l in logs:
                    all_log.append(f"用户{u_id} {l}")
            total = len(all_log)
            if total == 0:
                bot.edit_message_text("📋暂无充值记录", cid, call.message.message_id)
                return
            total_page = (total + PAGE_NUM -1) // PAGE_NUM
            s = (page-1)*PAGE_NUM
            e = page*PAGE_NUM
            content = "\n".join(all_log[s:e])
            bot.edit_message_text(f"📋全站充值记录 第{page}/{total_page}页\n{content}", cid, call.message.message_id, reply_markup=page_btn(p_type, page, total_page))
        elif p_type == "use_page":
            all_log = []
            for u_id, logs in log_user.items():
                for l in logs:
                    all_log.append(f"用户{u_id} {l}")
            total = len(all_log)
            if total == 0:
                bot.edit_message_text("📋暂无消费记录", cid, call.message.message_id)
                return
            total_page = (total + PAGE_NUM -1) // PAGE_NUM
            s = (page-1)*PAGE_NUM
            e = page*PAGE_NUM
            content = "\n".join(all_log[s:e])
            bot.edit_message_text(f"📋全站消费记录 第{page}/{total_page}页\n{content}", cid, call.message.message_id, reply_markup=page_btn(p_type, page, total_page))
        elif p_type == "my_rc":
            logs = log_recharge.get(uid, [])
            total = len(logs)
            if total == 0:
                bot.edit_message_text("💳暂无个人充值记录", cid, call.message.message_id)
                return
            total_page = (total + PAGE_NUM -1) // PAGE_NUM
            s = (page-1)*PAGE_NUM
            e = page*PAGE_NUM
            content = "\n".join(logs[s:e])
            bot.edit_message_text(f"💳个人充值记录 第{page}/{total_page}页\n{content}", cid, call.message.message_id, reply_markup=page_btn(p_type, page, total_page))
        elif p_type == "my_use":
            logs = log_user.get(uid, [])
            total = len(logs)
            if total == 0:
                bot.edit_message_text("📜暂无个人消费记录", cid, call.message.message_id)
                return
            total_page = (total + PAGE_NUM -1) // PAGE_NUM
            s = (page-1)*PAGE_NUM
            e = page*PAGE_NUM
            content = "\n".join(logs[s:e])
            bot.edit_message_text(f"📜个人消费记录 第{page}/{total_page}页\n{content}", cid, call.message.message_id, reply_markup=page_btn(p_type, page, total_page))
        elif p_type == "ulist":
            all_user_list = list(users.items())
            total = len(all_user_list)
            total_page = (total + PAGE_NUM -1) // PAGE_NUM
            s = (page-1)*PAGE_NUM
            e = page*PAGE_NUM
            page_data = all_user_list[s:e]
            text = f"📊用户余额总表 第{page}/{total_page}页\n用户ID | 余额\n"
            for uid_key, info in page_data:
                text += f"{uid_key} | {info['balance']:.4f}\n"
            bot.edit_message_text(text, cid, call.message.message_id, reply_markup=page_btn(p_type, page, total_page))

    elif data == "return_user":
        bot.edit_message_text("👤个人中心", cid, call.message.message_id, reply_markup=user_menu(uid))

# ===================== 卡密、充值、扣费、文件处理函数 =====================
def create_balance_card(m):
    try:
        parts = m.text.strip().split()
        cdk = parts[0]
        val = float(parts[1])
        cards[cdk] = val
        safe_send_msg(m.chat.id, f"✅余额卡密创建成功\n卡密：{cdk}\n面额：{val}")
    except:
        safe_send_msg(m.chat.id, "❌格式错误！示例：ABC123 10")

def create_time_card(m):
    try:
        parts = m.text.strip().split()
        cdk = parts[0]
        days = int(parts[1])
        time_cards[cdk] = days
        safe_send_msg(m.chat.id, f"✅时长卡密创建成功\n卡密：{cdk}\n有效天数：{days}天")
    except:
        safe_send_msg(m.chat.id, "❌格式错误！示例：XYZ789 7")

def use_cdk(m):
    uid = m.from_user.id
    cdk = m.text.strip()
    cid = m.chat.id
    if cdk in cards:
        val = cards.pop(cdk)
        get_user(uid)["balance"] += val
        add_rc(uid, val)
        safe_send_msg(cid, f"✅余额卡密兑换成功\n到账：{val}元")
    elif cdk in time_cards:
        days = time_cards.pop(cdk)
        now = get_now_timestamp()
        expire = now + days * 86400
        get_user(uid)["vip_expire"] = expire
        safe_send_msg(cid, f"✅时长VIP兑换成功\n有效时长：{days}天\n有效期内免费使用所有功能！")
    else:
        safe_send_msg(cid, "❌卡密无效或已使用")

def del_cdk(m):
    cdk = m.text.strip()
    if cdk in cards:
        del cards[cdk]
        safe_send_msg(m.chat.id, "✅余额卡密已作废")
    elif cdk in time_cards:
        del time_cards[cdk]
        safe_send_msg(m.chat.id, "✅时长卡密已作废")
    else:
        safe_send_msg(m.chat.id, "❌未找到该卡密")

def add_single_balance(m):
    try:
        uid, money = m.text.strip().split()
        uid = int(uid)
        money = float(money)
        get_user(uid)["balance"] += money
        add_rc(uid, money)
        safe_send_msg(m.chat.id, f"✅成功给用户{uid}充值 {money}")
    except:
        safe_send_msg(m.chat.id, "❌格式错误，请按：用户ID 金额 发送")

def sub_single_balance(m):
    try:
        uid, money = m.text.strip().split()
        uid = int(uid)
        money = float(money)
        u = get_user(uid)
        if u["balance"] >= money:
            u["balance"] -= money
            add_log(uid, "管理员扣余额", 0, money)
            safe_send_msg(m.chat.id, f"✅成功扣除用户{uid}余额 {money}")
        else:
            safe_send_msg(m.chat.id, "❌用户余额不足")
    except:
        safe_send_msg(m.chat.id, "❌格式错误，请按：用户ID 金额 发送")

def batch_add_user_balance(m):
    lines = m.text.strip().splitlines()
    succ = 0
    fail = 0
    for line in lines:
        try:
            uid, money = line.strip().split()
            uid = int(uid)
            money = float(money)
            get_user(uid)["balance"] += money
            add_rc(uid, money)
            succ += 1
        except:
            fail += 1
    safe_send_msg(m.chat.id, f"🔥批量充值完成\n成功：{succ} 条\n失败：{fail} 条")

# 文件接收处理
@bot.message_handler(content_types=['document'])
def handle_doc(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    try:
        file_info = bot.get_file(msg.document.file_id)
        data = bot.download_file(file_info.file_path)
        name = msg.document.file_name.lower()
        if name.endswith(".zip"):
            lines = extract_txt_from_zip_large(data)
        else:
            lines = read_txt_large(data)
        if not lines:
            safe_send_msg(cid, "❌文件内无有效内容")
            return
        user_file[uid] = lines
        state = user_state.get(uid, "")
        if state == "hebing":
            safe_send_msg(cid, "✅文件已接收，请继续上传下一个，全部上传完毕后发送【完成】")
            if uid not in user_merge:
                user_merge[uid] = []
            user_merge[uid].extend(lines)
        elif state == "quchong":
            total_old = len(lines)
            new_lines, _, total_new = dedup_phone_list_large(lines)
            fee = total_old * PRICE_DEDUP
            u = get_user(uid)
            if not is_vip_valid(uid) and u["balance"] < fee:
                safe_send_msg(cid, "❌余额不足")
                return
            if not is_vip_valid(uid):
                u["balance"] -= fee
                add_log(uid, "号码去重", total_old, fee)
            bio = BytesIO("\n".join(new_lines).encode())
            bio.name = "去重完成.txt"
            bot.send_document(cid, bio)
            if is_vip_valid(uid):
                safe_send_msg(cid, f"✅去重完成（VIP免费）\n原{total_old}条 → 现{total_new}条")
            else:
                safe_send_msg(cid, f"✅去重完成\n原{total_old}条 → 现{total_new}条\n扣费{fee:.4f}")
            if uid in user_state:
                del user_state[uid]
        else:
            bot.send_message(cid, "✅文件接收完成，请选择功能", reply_markup=select_menu())
    except Exception as e:
        safe_send_msg(cid, "❌文件解析失败")

# 文本指令：合并完成、取消
@bot.message_handler(func=lambda m: True)
def text_msg(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    txt = msg.text.strip()
    if txt == "完成" and user_state.get(uid) == "hebing":
        all_lines = user_merge.get(uid, [])
        total = len(all_lines)
        fee = total * PRICE_MERGE
        u = get_user(uid)
        if not is_vip_valid(uid) and u["balance"] < fee:
            safe_send_msg(cid, "❌余额不足")
            return
        if not is_vip_valid(uid):
            u["balance"] -= fee
            add_log(uid, "文件合并", total, fee)
        bio = BytesIO("\n".join(all_lines).encode())
        bio.name = "合并完成.txt"
        bot.send_document(cid, bio)
        if is_vip_valid(uid):
            safe_send_msg(cid, f"✅合并完成（VIP免费），共{total}行")
        else:
            safe_send_msg(cid, f"✅合并完成，共{total}行，扣费{fee:.4f}")
        if uid in user_merge:
            del user_merge[uid]
        if uid in user_state:
            del user_state[uid]
    elif txt == "取消":
        if uid in user_file:
            del user_file[uid]
        if uid in user_merge:
            del user_merge[uid]
        if uid in user_state:
            del user_state[uid]
        safe_send_msg(cid, "✅已取消当前操作")
    elif txt == "/start":
        bot.send_message(cid, "🤖 工具机器人已就绪，请选择功能", reply_markup=menu(uid))

if __name__ == "__main__":
    print("🤖 机器人启动成功")
    bot.infinity_polling()
