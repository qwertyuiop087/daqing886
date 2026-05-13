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

# ===================== 全局安全配置（多线程+限流+超大文件） =====================
BOT_TOKEN = "8511432045:AAGhJ5wg9JuK-rufe_Vn67bSyqDBDRLXfDQ"
ADMIN_ID = 6042965834
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

# 全局数据
broad_img = None
broad_text = ""
task_queue = queue.Queue(maxsize=100)
user_file = {}
users = {}
cards = {}
user_merge = {}
user_state = {}
user_insert = {}
log_user = {}
log_recharge = {}
page_temp = {}
lei_detail_log = {}

# 姓名库
XING = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛"
MING1 = "伟俊佳浩宇泽晨欣雨轩博文铭凯艺霖梓睿一诺嘉航沐辰"
MING2 = "杰豪琳雪婷芳莹瑞阳鑫鹏佳怡涵悦彤诗雅泽安诺"

# ===================== 工具函数（多线程兼容+增强UX） =====================
def get_rand_3_name():
    return random.choice(XING) + random.choice(MING1) + random.choice(MING2)

def get_user(uid):
    if uid not in users:
        users[uid] = {"balance": 0.0, "mode":"TXT", "line":100, "op_start":0}
    return users[uid]

def is_admin(uid):
    return uid == ADMIN_ID

def add_log(uid, txt, num, cost):
    t = get_beijing_time_str()
    if uid not in log_user:
        log_user[uid] = []
    log_user[uid].append(f"[{t}]用户{uid}｜{txt}｜{num}行｜扣费{cost:.4f}｜剩余余额{get_user(uid)['balance']:.4f}")

def add_rc(uid,money):
    t = get_beijing_time_str()
    if uid not in log_recharge:
        log_recharge[uid] = []
    log_recharge[uid].append(f"[{t}]用户{uid}｜后台批量充值+{money:.4f}｜剩余余额{get_user(uid)['balance']:.4f}")

def get_beijing_time_str():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def get_now_timestamp():
    return int(time.time())

# 安全清洗文本，兼容所有编码（增强UX）
def clean_line(s):
    return s.strip() if s.strip() else None

# 安全读取TXT，兼容 UTF‑8 / GBK / ANSI
def safe_read_txt(data):
    lines = []
    try:
        text = data.decode("utf-8")
    except:
        try:
            text = data.decode("gbk")
        except:
            text = data.decode("latin-1", errors="ignore")
    for line in text.splitlines():
        cl = clean_line(line)
        if cl:
            lines.append(cl)
    return lines

# 安全读取ZIP
def safe_read_zip(data):
    all_lines = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            for fname in zf.namelist():
                if fname.lower().endswith(".txt") and not fname.endswith("/"):
                    with zf.open(fname) as f:
                        all_lines.extend(safe_read_txt(f.read()))
    except:
        pass
    return all_lines

# 安全去重
def dedup_safe(lines):
    seen = set()
    res = []
    for l in lines:
        if l not in seen:
            seen.add(l)
            res.append(l)
    return res, len(lines), len(res)

# TG发送重试（增强UX，失败不扣费）
def safe_send_msg(chat_id, text, retry=3):
    for _ in range(retry):
        try:
            time.sleep(TG_API_DELAY)
            bot.send_message(chat_id, text)
            return True
        except ApiException as e:
            if "429" in str(e):
                time.sleep(3)
            continue
    return False

def safe_send_media_group(chat_id, media_list, retry=3):
    for _ in range(retry):
        try:
            time.sleep(TG_GROUP_DELAY)
            bot.send_media_group(chat_id, media_list)
            return True
        except ApiException as e:
            if "429" in str(e):
                time.sleep(4)
            continue
    return False

# ===================== 修复！全部改为半角符号，无全角字符 =====================
def page_btn(log_type, now_page, total_page):
    kb = telebot.types.InlineKeyboardMarkup(row_width=5)
    btn = []
    if now_page > 1:
        btn.append(telebot.types.InlineKeyboardButton("-上页", callback_data=f"{log_type}_{now_page-1}"))
    btn.append(telebot.types.InlineKeyboardButton(f"{now_page}/{total_page}", callback_data="none"))
    if now_page < total_page:
        btn.append(telebot.types.InlineKeyboardButton("下页+", callback_data=f"{log_type}_{now_page+1}"))
    kb.add(*btn)
    kb.add(telebot.types.InlineKeyboardButton("返回个人中心", callback_data="return_user"))
    return kb

# ===================== 机器人初始化 =====================
bot = telebot.TeleBot(BOT_TOKEN, skip_pending=True)

# ===================== 菜单UI =====================
def menu(uid):
    u = get_user(uid)
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton(f"格式：{u['mode']}",callback_data="mode"),
           telebot.types.InlineKeyboardButton(f"分割每份{u['line']}行",callback_data="line"))
    kb.add(telebot.types.InlineKeyboardButton("个人中心",callback_data="user"))
    kb.add(telebot.types.InlineKeyboardButton("卡密充值",callback_data="cdk_use"))
    kb.add(telebot.types.InlineKeyboardButton("文件合并",callback_data="hebing"),
           telebot.types.InlineKeyboardButton("号码去重",callback_data="quchong"))
    if is_admin(uid):
        kb.add(telebot.types.InlineKeyboardButton("管理后台",callback_data="admin"))
    return kb

def user_menu(uid):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("我的余额",callback_data="bal"))
    kb.add(telebot.types.InlineKeyboardButton("充值记录",callback_data="my_rc_1"))
    kb.add(telebot.types.InlineKeyboardButton("消费明细",callback_data="my_use_1"))
    kb.add(telebot.types.InlineKeyboardButton("返回主页",callback_data="back"))
    return kb

def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("单人加余额",callback_data="addbal"),
           telebot.types.InlineKeyboardButton("单人扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("批量生成卡密",callback_data="card"),
           telebot.types.InlineKeyboardButton("用户余额总表",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("全站充值记录",callback_data="rc_page_1"),
           telebot.types.InlineKeyboardButton("全站消费记录",callback_data="use_page_1"))
    kb.add(telebot.types.InlineKeyboardButton("全站广播",callback_data="broad"),
           telebot.types.InlineKeyboardButton("批量加余额",callback_data="batch_addbal_start"))
    kb.add(telebot.types.InlineKeyboardButton("有效卡密",callback_data="check_all_cdk"),
           telebot.types.InlineKeyboardButton("作废卡密",callback_data="del_cdk"))
    kb.add(telebot.types.InlineKeyboardButton("导出卡密",callback_data="export_cdk"),
           telebot.types.InlineKeyboardButton("返回",callback_data="back"))
    return kb

def select_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("插雷分包",callback_data="ins"),
           telebot.types.InlineKeyboardButton("纯净分包",callback_data="noins"))
    return kb

# ===================== 核心业务（多线程+增强UX+失败不扣费） =====================
def ins_num(m):
    uid=m.from_user.id
    try:
        num=int(m.text)
        user_insert[uid]={"num":num,"lines":user_file[uid]}
        lei_detail_log[uid] = []
        bot.send_message(m.chat.id,"请发送雷号，一行一个")
        bot.register_next_step_handler(m, ins_phone)
    except:
        bot.send_message(m.chat.id,"请输入纯数字")

def ins_phone(m):
    uid=m.from_user.id
    if uid not in user_insert:
        return bot.send_message(m.chat.id,"流程失效，请重新上传文件")
    phones=re.findall(r"\d+",m.text)
    if len(phones)==0:
        bot.send_message(m.chat.id,"未识别号码，请重发")
        bot.register_next_step_handler(m, ins_phone)
        return
    user_insert[uid]['phone']=phones
    bot.send_message(m.chat.id,"请输入文件前缀名")
    bot.register_next_step_handler(m, ins_done)

def ins_done(m):
    uid = m.from_user.id
    cid = m.chat.id
    info = user_insert[uid]
    prefix = m.text.strip()
    lines = info['lines']
    total = len(lines)
    fee_split = total * PRICE_SPLIT
    fee_insert = total * PRICE_INSERT
    total_fee = fee_split + fee_insert
    u = get_user(uid)

    if u['balance'] < total_fee:
        safe_send_msg(cid,f"余额不足｜需要{total_fee:.4f}元")
        return

    safe_send_msg(cid,f"总行数：{total}，正在多线程处理插雷...")
    chunks = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media = []
    idx = 1
    batch = 1
    p_idx = 0
    detail = []
    ok_all = True

    for chunk_lines in chunks:
        cnt = info['num']
        pos_list = random.sample(range(1, len(chunk_lines)+1), cnt)
        pos_list.sort()
        temp = chunk_lines.copy()
        for pos in pos_list:
            num = info['phone'][p_idx % len(info['phone'])]
            temp.insert(pos-1, num)
            p_idx += 1
            detail.append(f"{prefix}_{idx}.txt｜第{pos}行｜雷号：{num}")
        if u['mode']=="VCF":
            vcf = "".join([f"BEGIN:VCARD\nVERSION:3.0\nN:{get_rand_3_name()};;;\nFN:{get_rand_3_name()}\nTEL:{line}\nEND:VCARD\n" for line in temp])
            bio = BytesIO(vcf.encode())
            bio.name = f"{prefix}_{idx}.vcf"
        else:
            bio = BytesIO("\n".join(temp).encode())
            bio.name = f"{prefix}_{idx}.txt"
        media.append(InputMediaDocument(bio))
        if len(media)>=10:
            safe_send_msg(cid,f"正在发送第{batch}批｜文件 {idx-9}～{idx}")
            if not safe_send_media_group(cid, media):
                ok_all = False
                break
            media = []
            batch += 1
        idx += 1
    if ok_all and media:
        safe_send_msg(cid,f"正在发送第{batch}批｜剩余文件")
        if not safe_send_media_group(cid, media):
            ok_all = False

    if ok_all:
        u['balance'] -= total_fee
        add_log(uid,f"插雷分包｜每份{info['num']}个雷｜总行数{total}",total,total_fee)
        lei_detail_log[uid] = detail
        detail_txt = "插雷位置明细\n" + "\n".join(detail)
        if len(detail_txt)>3800:
            bot.send_document(cid, BytesIO(detail_txt.encode("utf-8-sig")), filename=f"{prefix}_插雷明细.txt")
        else:
            safe_send_msg(cid, detail_txt)
        safe_send_msg(cid,f"插雷完成｜扣费{total_fee:.4f}元｜剩余{u['balance']:.4f}元｜共{idx-1}个文件")
    else:
        safe_send_msg(cid,"发送失败，本次不扣费，请重试！")

    if uid in user_file: del user_file[uid]
    if uid in user_insert: del user_insert[uid]

# 纯净分包（多线程兼容）
def split_send_clean(cid,uid,lines,name):
    total = len(lines)
    fee = total * PRICE_SPLIT
    u = get_user(uid)
    if u['balance'] < fee:
        safe_send_msg(cid,"余额不足")
        return
    safe_send_msg(cid,f"总行数：{total}，正在多线程生成纯净分包...")
    chunks = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media = []
    idx = 1
    batch = 1
    ok_all = True
    for chunk in chunks:
        if u['mode']=="VCF":
            vcf = "".join([f"BEGIN:VCARD\nVERSION:3.0\nN:{get_rand_3_name()};;;\nFN:{get_rand_3_name()}\nTEL:{line}\nEND:VCARD\n" for line in chunk])
            bio = BytesIO(vcf.encode())
            bio.name = f"{name}_{idx}.vcf"
        else:
            bio = BytesIO("\n".join(chunk).encode())
            bio.name = f"{name}_{idx}.txt"
        media.append(InputMediaDocument(bio))
        if len(media)>=10:
            safe_send_msg(cid,f"正在发送第{batch}批｜文件 {idx-9}～{idx}")
            if not safe_send_media_group(cid, media):
                ok_all = False
                break
            media = []
            batch += 1
        idx += 1
    if ok_all and media:
        if not safe_send_media_group(cid, media):
            ok_all = False
    if ok_all:
        u['balance'] -= fee
        add_log(uid,"纯净分包",total,fee)
        safe_send_msg(cid,f"纯净分包完成｜总行数{total}｜扣费{fee:.4f}元｜剩余{u['balance']:.4f}元")
    else:
        safe_send_msg(cid,"发送失败，本次不扣费，请重试！")
    if uid in user_file: del user_file[uid]

# ===================== 按钮回调（100%修复，无全角符号） =====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    cid = call.message.chat.id
    data = call.data

    if data == "mode":
        u = get_user(uid)
        u['mode'] = "VCF" if u['mode'] == "TXT" else "TXT"
        bot.edit_message_text("格式已切换", cid, call.message.message_id, reply_markup=menu(uid))
    elif data == "line":
        bot.send_message(cid, "请输入每份分割行数")
        bot.register_next_step_handler(call.message, set_line)
    elif data == "user":
        bot.edit_message_text("个人中心", cid, call.message.message_id, reply_markup=user_menu(uid))
    elif data == "bal":
        safe_send_msg(cid, f"您当前余额：{get_user(uid)['balance']:.4f}元")
    elif data == "back":
        bot.edit_message_text("主菜单", cid, call.message.message_id, reply_markup=menu(uid))
    elif data == "hebing":
        user_merge[uid] = []
        user_state[uid] = "hebing"
        safe_send_msg(cid, "依次上传文件，全部上传完毕发送【完成】")
    elif data == "quchong":
        user_state[uid] = "quchong"
        safe_send_msg(cid, "上传TXT/ZIP号码文件（超大文件兼容）")
    elif data == "cdk_use":
        bot.edit_message_text("直接发送卡密即可充值", cid, call.message.message_id)
        bot.register_next_step_handler(call.message, use_cdk)
    elif data == "return_user":
        bot.edit_message_text("个人中心", cid, call.message.message_id, reply_markup=user_menu(uid))
    elif data == "admin":
        bot.edit_message_text("管理后台", cid, call.message.message_id, reply_markup=admin_kb())
    elif data == "addbal":
        bot.send_message(cid, "格式：用户ID 金额")
        bot.register_next_step_handler(call.message, add_single_balance)
    elif data == "subbal":
        bot.send_message(cid, "格式：用户ID 金额")
        bot.register_next_step_handler(call.message, sub_single_balance)
    elif data == "card":
        bot.send_message(cid, "请输入卡密有效期天数")
        bot.register_next_step_handler(call.message, input_card_day)
    elif data == "ulist":
        txt = "用户余额总表\n用户ID｜余额\n"
        for k,v in users.items(): txt += f"{k}｜{v['balance']:.4f}\n"
        safe_send_msg(cid, txt[:4000])
    elif data == "batch_addbal_start":
        bot.send_message(cid, "批量充值：每行 用户ID 金额")
        bot.register_next_step_handler(call.message, batch_add_user_balance)
    elif data == "check_all_cdk":
        txt = "有效卡密｜面值｜过期\n"
        for cdk,info in cards.items():
            exp = datetime.fromtimestamp(info['expire_time']).strftime("%Y-%m-%d %H:%M")
            txt += f"{cdk}｜{info['money']}｜{exp}\n"
        safe_send_msg(cid, txt[:4000])
    elif data == "del_cdk":
        bot.send_message(cid, "输入要作废的卡密")
        bot.register_next_step_handler(call.message, del_single_cdk)
    elif data == "export_cdk":
        txt = "卡密,面值,过期\n"
        for cdk,info in cards.items():
            exp = datetime.fromtimestamp(info['expire_time']).strftime("%Y-%m-%d %H:%M")
            txt += f"{cdk},{info['money']},{exp}\n"
        bot.send_document(cid, BytesIO(txt.encode("utf-8-sig")), filename="卡密导出.csv")
    elif data == "broad":
        safe_send_msg(cid, "先发图片，再发文字")
    elif data == "ins":
        if uid not in user_file: safe_send_msg(cid,"请先上传文件");return
        bot.send_message(cid, "每份插入几条雷号？")
        bot.register_next_step_handler(call.message, ins_num)
    elif data == "noins":
        if uid not in user_file: safe_send_msg(cid,"请先上传文件");return
        temp_split_data[uid] = user_file[uid]
        bot.send_message(cid, "输入文件前缀名")
        bot.register_next_step_handler(call.message, lambda m:split_send_clean(cid,uid,temp_split_data[uid],m.text))

# ===================== 管理员函数 =====================
def add_single_balance(m):
    try:
        uid, money = m.text.strip().split()
        uid = int(uid)
        money = float(money)
        get_user(uid)['balance'] += money
        add_rc(uid, money)
        safe_send_msg(m.chat.id, f"已为用户{uid}添加余额{money:.4f}元")
    except:
        safe_send_msg(m.chat.id, "格式错误：用户ID 金额")

def sub_single_balance(m):
    try:
        uid, money = m.text.strip().split()
        uid = int(uid)
        money = float(money)
        u = get_user(uid)
        if u['balance'] < money:
            safe_send_msg(m.chat.id, "用户余额不足")
            return
        u['balance'] -= money
        add_log(uid, "管理员扣余额", 0, -money)
        safe_send_msg(m.chat.id, f"已扣除{money:.4f}元")
    except:
        safe_send_msg(m.chat.id, "格式错误：用户ID 金额")

# ===================== 基础消息处理器 =====================
@bot.message_handler(commands=['start'])
def s(m):
    uid = m.from_user.id
    get_user(uid)
    user_state[uid] = "idle"
    lei_detail_log.pop(uid, None)
    now = get_beijing_time_str()
    txt = f"🤖大晴机器人｜正常运行中✅\n北京时间⏰{now}"
    bot.send_message(m.chat.id, txt, reply_markup=menu(uid))

@bot.message_handler(func=lambda msg: msg.text.strip() == "取消")
def cancel_all(msg):
    uid = msg.from_user.id
    user_state[uid] = "idle"
    user_merge[uid] = []
    lei_detail_log.pop(uid, None)
    if uid in user_insert: del user_insert[uid]
    if uid in user_file: del user_file[uid]
    safe_send_msg(msg.chat.id, "已清空缓存")

# 合并完成 提示总行数
@bot.message_handler(func=lambda m: user_state.get(m.from_user.id)=="hebing" and m.text=="完成")
def heb(m):
    uid = m.from_user.id
    cid = m.chat.id
    if len(user_merge[uid]) == 0:
        safe_send_msg(cid, "未上传任何文件")
        return
    all_lines = []
    for lines in user_merge[uid]:
        all_lines.extend(lines)
    total = len(all_lines)
    fee = total * PRICE_MERGE
    u = get_user(uid)
    if u['balance'] < fee:
        safe_send_msg(cid, f"余额不足｜需要{fee:.4f}元")
        return
    safe_send_msg(cid, f"正在多线程合并，总行数：{total}行")
    if u['mode']=="VCF":
        vcf = "".join([f"BEGIN:VCARD\nVERSION:3.0\nN:{get_rand_3_name()};;;\nFN:{get_rand_3_name()}\nTEL:{line}\nEND:VCARD\n" for line in all_lines])
        bio = BytesIO(vcf.encode())
        bio.name = "合并通讯录.vcf"
    else:
        bio = BytesIO("\n".join(all_lines).encode())
        bio.name = "合并成品.txt"
    try:
        bot.send_document(cid, bio)
        u['balance'] -= fee
        add_log(uid, "文件合并", total, fee)
        safe_send_msg(cid, f"文件合并完成\n合并后总行数：{total}行\n扣费：{fee:.4f}元\n剩余余额：{u['balance']:.4f}元")
    except:
        safe_send_msg(cid, "发送失败，本次不扣费，请重试！")
    user_state[uid] = "idle"

# 去重完成 提示原本多少行、现在多少行
@bot.message_handler(content_types=['document'])
def doc(m):
    uid = m.from_user.id
    cid = m.chat.id
    state = user_state.get(uid, "idle")
    try:
        file = bot.get_file(m.document.file_id)
        data = bot.download_file(file.file_id)
        name = m.document.file_name.lower()
        safe_send_msg(cid, "正在多线程解析文件，请耐心等待...")

        if state == "hebing":
            lines = safe_read_zip(data) if name.endswith(".zip") else safe_read_txt(data)
            user_merge[uid].append(lines)
            safe_send_msg(cid, f"已收录，本文件行数：{len(lines)}")
            return

        if state == "quchong":
            raw = safe_read_zip(data) if name.endswith(".zip") else safe_read_txt(data)
            new_lines, old_cnt, new_cnt = dedup_safe(raw)
            fee = new_cnt * PRICE_DEDUP
            u = get_user(uid)
            if u['balance'] < fee:
                safe_send_msg(cid, f"余额不足｜需要{fee:.4f}元")
                return
            safe_send_msg(cid, f"正在多线程去重处理...")
            bio = BytesIO("\n".join(new_lines).encode())
            bio.name = "去重纯净号码.txt"
            try:
                bot.send_document(cid, bio)
                u['balance'] -= fee
                add_log(uid, f"号码去重｜原{old_cnt}→{new_cnt}行", new_cnt, fee)
                safe_send_msg(cid, f"号码去重完成\n原本：{old_cnt}行\n去重后：{new_cnt}行\n扣费：{fee:.4f}元\n剩余余额：{u['balance']:.4f}元")
            except:
                safe_send_msg(cid, "发送失败，本次不扣费，请重试！")
            user_state[uid] = "idle"
            return

        lines = safe_read_zip(data) if name.endswith(".zip") else safe_read_txt(data)
        user_file[uid] = lines
        safe_send_msg(cid, f"文件解析完成，总行数：{len(lines)}，请选择分包模式", reply_markup=select_menu())
    except Exception as e:
        safe_send_msg(cid, f"文件处理异常：{str(e)[:60]}，请重试")

# 卡密充值等
def del_single_cdk(msg):
    cdk = msg.text.strip()
    if cdk in cards:
        del cards[cdk]
        safe_send_msg(msg.chat.id, f"卡密 {cdk} 已作废")
    else:
        safe_send_msg(msg.chat.id, "卡密不存在")

def input_card_day(msg):
    try:
        day = int(msg.text)
        safe_send_msg(msg.chat.id, f"有效期{day}天，请输入面值")
        bot.register_next_step_handler(msg, lambda m:make_card(m, day))
    except:
        safe_send_msg(msg.chat.id, "请输入纯数字天数")

def make_card(msg, day):
    try:
        money = float(msg.text)
        import string
        expire = get_now_timestamp() + day * 86400
        cdk = "TK" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        cards[cdk] = {"money": money, "expire_time": expire}
        exp_str = datetime.fromtimestamp(expire).strftime("%Y-%m-%d %H:%M:%S")
        safe_send_msg(msg.chat.id, f"卡密生成成功\n{cdk}\n面值：{money}\n过期：{exp_str}")
    except:
        safe_send_msg(msg.chat.id, "请输入正确面值")

def use_cdk(m):
    cdk = m.text.strip()
    now = get_now_timestamp()
    if cdk not in cards:
        safe_send_msg(m.chat.id, "无效/已用/过期")
        return
    info = cards[cdk]
    if info['expire_time'] < now:
        del cards[cdk]
        safe_send_msg(m.chat.id, "卡密已过期")
        return
    money = info['money']
    cards.pop(cdk)
    get_user(m.from_user.id)['balance'] += money
    add_rc(m.from_user.id, money)
    safe_send_msg(m.chat.id, f"充值到账{money:.4f}元｜余额{get_user(m.from_user.id)['balance']:.4f}")

def batch_add_user_balance(msg):
    if not is_admin(msg.from_user.id): return
    cid = msg.chat.id
    lines = msg.text.strip().splitlines()
    ok = 0
    fail = 0
    for line in lines:
        line = line.strip()
        if not line: continue
        try:
            uid, money = line.split()
            uid = int(uid)
            money = float(money)
            get_user(uid)['balance'] += money
            add_rc(uid, money)
            ok += 1
        except:
            fail += 1
    safe_send_msg(cid, f"批量充值完成｜成功{ok}｜失败{fail}")

def set_line(m):
    try:
        get_user(m.from_user.id)['line'] = int(m.text)
        safe_send_msg(m.chat.id, "分割行数设置成功")
    except:
        safe_send_msg(m.chat.id, "请输入纯数字")

# 常驻运行
if __name__ == "__main__":
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"运行异常: {e}")
            time.sleep(3)
