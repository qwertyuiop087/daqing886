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

# ===================== 全局安全配置 =====================
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

# ===================== 工具函数 =====================
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

def clean_empty_line(text):
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        strip_line = line.strip()
        if strip_line:
            new_lines.append(strip_line)
    return "\n".join(new_lines)

def dedup_phone_list(lines):
    seen = set()
    new_lines = []
    for line in lines:
        pure = line.strip()
        if pure and pure not in seen:
            seen.add(pure)
            new_lines.append(pure)
    return new_lines, len(lines), len(new_lines)

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
    except Exception:
        return ""

# TG发送：重试3次，失败返回False，**绝不自动跳过**
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

def safe_send_photo(chat_id, photo_id, caption, retry=3):
    for i in range(retry):
        try:
            time.sleep(TG_API_DELAY)
            bot.send_photo(chat_id, photo_id, caption=caption)
            return True
        except ApiException as e:
            if "429" in str(e):
                time.sleep(3)
                continue
            return False
    return False

# 关键：批量文件发送，**任意一批失败 → 整单失败，不扣费**
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

def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("➕单人加余额",callback_data="addbal"),
           telebot.types.InlineKeyboardButton("➖单人扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("🎟️批量生成卡密",callback_data="card"),
           telebot.types.InlineKeyboardButton("📊用户余额总表",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("📋全站充值记录",callback_data="rc_page_1"),
           telebot.types.InlineKeyboardButton("📋全站消费记录",callback_data="use_page_1"))
    kb.add(telebot.types.InlineKeyboardButton("📢全站广播",callback_data="broad"),
           telebot.types.InlineKeyboardButton("🔥批量加余额",callback_data="batch_addbal_start"))
    kb.add(telebot.types.InlineKeyboardButton("🎫有效卡密",callback_data="check_all_cdk"),
           telebot.types.InlineKeyboardButton("🗑️作废卡密",callback_data="del_cdk"))
    kb.add(telebot.types.InlineKeyboardButton("📤导出卡密",callback_data="export_cdk"),
           telebot.types.InlineKeyboardButton("🔙返回",callback_data="back"))
    return kb

def select_menu():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("⚡插雷分包",callback_data="ins"),
           telebot.types.InlineKeyboardButton("📄纯净分包",callback_data="noins"))
    return kb

# ===================== 核心业务：插雷（严格按你要求：失败不扣费、提示重试） =====================
def ins_num(m):
    uid=m.from_user.id
    try:
        num=int(m.text)
        user_insert[uid]={"num":num,"txt":user_file[uid]['txt']}
        lei_detail_log[uid] = []
        bot.send_message(m.chat.id,"⚡请发送雷号，一行一个")
        bot.register_next_step_handler(m, ins_phone)
    except:
        bot.send_message(m.chat.id,"❌请输入纯数字")

def ins_phone(m):
    uid=m.from_user.id
    if uid not in user_insert:
        return bot.send_message(m.chat.id,"❌流程失效，请重新上传文件")
    phones=re.findall(r"\d+",m.text)
    if len(phones)==0:
        bot.send_message(m.chat.id,"❌未识别号码，请重发")
        bot.register_next_step_handler(m, ins_phone)
        return
    user_insert[uid]['phone']=phones
    bot.send_message(m.chat.id,"📄请输入文件前缀名（例如：插雷成品）")
    bot.register_next_step_handler(m, ins_done)

def ins_done(m):
    uid = m.from_user.id
    cid = m.chat.id
    info = user_insert[uid]
    file_prefix = m.text.strip()
    lines = [x for x in info['txt'].splitlines() if x.strip()]
    total = len(lines)
    fee_split = total * PRICE_SPLIT
    fee_insert = total * PRICE_INSERT
    total_fee = fee_split + fee_insert
    u = get_user(uid)

    # 余额前置校验
    if u['balance'] < total_fee:
        safe_send_msg(cid,f"❌余额不足｜需要{total_fee:.4f}元｜当前{u['balance']:.4f}元")
        return

    # 先不扣费，全部发送成功后再扣费
    safe_send_msg(cid,f"✅余额校验通过，正在生成文件+插雷明细，准备发送...")

    chunk = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
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

        # 生成文件
        if u['mode']=="VCF":
            vcf = ""
            for p in temp_list:
                n=get_rand_3_name()
                vcf+=f"BEGIN:VCARD\nVERSION:3.0\nN:{n};;;\nFN:{n}\nTEL:{p}\nEND:VCARD\n"
            bio=BytesIO(vcf.encode())
            bio.name=f"{file_prefix}_{file_idx}.vcf"
        else:
            bio=BytesIO("\n".join(temp_list).encode())
            bio.name=f"{file_prefix}_{file_idx}.txt"
        media.append(InputMediaDocument(bio))

        # 批量发送，**任意一批失败 → 整单失败，不扣费**
        if len(media) >= 10:
            safe_send_msg(cid,f"📤正在发送第{batch_num}批｜文件 {file_idx-9}～{file_idx}")
            ok = safe_send_media_group(cid, media)
            if not ok:
                send_all_success = False
                break
            media = []
            batch_num += 1
        file_idx += 1

    # 发送剩余文件
    if send_all_success and len(media) > 0:
        last_start = file_idx - len(media)
        safe_send_msg(cid,f"📤正在发送第{batch_num}批｜文件 {last_start}～{file_idx-1}")
        ok = safe_send_media_group(cid, media)
        if not ok:
            send_all_success = False

    # ===================== 严格按你要求：发送成功才扣费，失败不扣费、提示重试 =====================
    if send_all_success:
        # 全部成功 → 扣费+记录日志
        u['balance'] -= total_fee
        add_log(uid,f"插雷分包｜每份{info['num']}个雷｜雷号池{len(info['phone'])}个",total,total_fee)
        # 下发插雷明细
        lei_detail_log[uid] = detail_lines
        detail_txt = "📝插雷位置明细（可核对每一个雷号位置）\n" + "\n".join(detail_lines)
        if len(detail_txt) > 3800:
            bio = BytesIO(detail_txt.encode("utf-8-sig"))
            bio.name = f"{file_prefix}_插雷位置明细.txt"
            bot.send_document(cid, bio)
        else:
            safe_send_msg(cid, detail_txt)
        safe_send_msg(cid,f"✅插雷分包全部完成｜扣费{total_fee:.4f}元｜剩余{u['balance']:.4f}元｜共{file_idx-1}个文件")
    else:
        # 发送失败 → **不扣费！！！提示用户重试**
        safe_send_msg(cid,"❌文件发送失败（重试3次后仍失败），本次操作**不扣费**，请稍后重试！")

    if uid in user_file: del user_file[uid]
    if uid in user_insert: del user_insert[uid]

# 纯净分包
def split_send_clean(cid,uid,txt,name):
    lines=[x for x in txt.splitlines() if x.strip()]
    total=len(lines)
    fee=total*PRICE_SPLIT
    u=get_user(uid)
    if u['balance']<fee:
        safe_send_msg(cid,"❌余额不足")
        return

    safe_send_msg(cid,"✅余额校验通过，正在生成文件...")
    chunk = [lines[i:i+u['line']] for i in range(0,total,u['line'])]
    media=[]
    file_idx=1
    batch_num=1
    send_all_success=True

    for c in chunk:
        if u['mode']=="VCF":
            vcf=""
            for p in c:
                n=get_rand_3_name()
                vcf+=f"BEGIN:VCARD\nVERSION:3.0\nN:{n};;;\nFN:{n}\nTEL:{p}\nEND:VCARD\n"
            bio=BytesIO(vcf.encode())
            bio.name=f"{name}_{file_idx}.vcf"
        else:
            bio=BytesIO("\n".join(c).encode())
            bio.name=f"{name}_{file_idx}.txt"
        media.append(InputMediaDocument(bio))

        if len(media)>=10:
            safe_send_msg(cid,f"📤正在发送第{batch_num}批｜文件 {file_idx-9}～{file_idx}")
            ok = safe_send_media_group(cid,media)
            if not ok:
                send_all_success=False
                break
            media=[]
            batch_num+=1
        file_idx+=1

    if send_all_success and len(media)>0:
        last_start = file_idx - len(media)
        safe_send_msg(cid,f"📤正在发送第{batch_num}批｜文件 {last_start}～{file_idx-1}")
        ok = safe_send_media_group(cid,media)
        if not ok:
            send_all_success=False

    if send_all_success:
        u['balance']-=fee
        add_log(uid,"纯净分包",total,fee)
        safe_send_msg(cid,f"✅纯净分包完成｜扣费{fee:.4f}元｜剩余{u['balance']:.4f}元")
    else:
        safe_send_msg(cid,"❌发送失败，本次**不扣费**，请重试！")

    if uid in temp_split_data:del temp_split_data[uid]
    if uid in user_file:del user_file[uid]

# ===================== 基础回调、接收文件、卡密充值等 =====================
@bot.message_handler(func=lambda msg: msg.text.isdigit())
def jump_page(msg):
    uid = msg.from_user.id
    if uid not in page_temp: return
    log_type = page_temp[uid]
    page = int(msg.text)
    if log_type == "my_rc":
        log = log_recharge.get(uid, ["暂无充值记录"])
    elif log_type == "my_use":
        log = log_user.get(uid, ["暂无消费记录"])
    elif log_type == "rc_page":
        all_log = []
        for i,j in log_recharge.items():
            all_log.extend([f"用户{i}｜{x}" for x in j])
        log = all_log
    elif log_type == "use_page":
        all_log = []
        for i,j in log_user.items():
            all_log.extend([f"用户{i}｜{x}" for x in j])
        log = all_log
    else: return
    total = len(log)
    tp = (total + PAGE_NUM - 1) // PAGE_NUM
    if page < 1 or page > tp:
        safe_send_msg(msg.chat.id, f"❌页码超出范围，最大页数：{tp}")
        return
    st = (page-1)*PAGE_NUM
    ed = page*PAGE_NUM
    txt = f"📖第{page}/{tp}页\n"+"\n".join(log[st:ed])[:4000]
    try:
        bot.edit_message_text(txt, msg.chat.id, msg.message_id-1, reply_markup=page_btn(log_type,page,tp))
    except: pass

@bot.message_handler(commands=['start'])
def s(m):
    uid = m.from_user.id
    get_user(uid)
    user_state[uid]="idle"
    lei_detail_log.pop(uid, None)
    now = get_beijing_time_str()
    safe_send_msg(m.chat.id,f"🤖大晴机器人｜已就绪✅\n⏰北京时间：{now}")
    bot.send_message(m.chat.id,"🏠主菜单",reply_markup=menu(uid))

@bot.message_handler(func=lambda msg: msg.text.strip() == "取消")
def cancel_all(msg):
    uid = msg.from_user.id
    user_state[uid] = "idle"
    user_merge[uid] = []
    lei_detail_log.pop(uid, None)
    if uid in user_insert: del user_insert[uid]
    if uid in user_file: del user_file[uid]
    safe_send_msg(msg.chat.id,"✅已清空缓存，操作已取消")

@bot.message_handler(func=lambda m:user_state.get(m.from_user.id)=="hebing" and m.text=="完成")
def heb(m):
    uid=m.from_user.id
    if len(user_merge[uid])==0:
        safe_send_msg(m.chat.id,"❌未上传任何文件")
        return
    txt="\n".join(user_merge[uid])
    lines = [x for x in txt.splitlines() if x.strip()]
    ls=len(lines)
    fee=ls*PRICE_MERGE
    u=get_user(uid)
    if u['balance']<fee:
        safe_send_msg(m.chat.id,f"❌余额不足｜需要{fee:.4f}元")
        return
    safe_send_msg(m.chat.id,"✅余额校验通过，正在生成合并文件...")
    if u['mode']=="VCF":
        vcf_all = ""
        for phone in lines:
            name = get_rand_3_name()
            vcf_all += f"BEGIN:VCARD\nVERSION:3.0\nN:{name};;;\nFN:{name}\nTEL;TYPE=CELL:{phone}\nEND:VCARD\n"
        bio=BytesIO(vcf_all.encode())
        bio.name="合并通讯录.vcf"
    else:
        bio=BytesIO("\n".join(lines).encode())
        bio.name="合并成品.txt"
    try:
        bot.send_document(m.chat.id,bio)
        u['balance']-=fee
        add_log(uid,"文件合并",ls,fee)
        safe_send_msg(m.chat.id,f"✅合并完成｜扣费{fee:.4f}元｜剩余{u['balance']:.4f}元")
    except:
        safe_send_msg(m.chat.id,"❌发送失败，本次不扣费，请重试！")
    user_state[uid]="idle"

@bot.message_handler(func=lambda msg: is_admin(msg.from_user.id))
def admin_cmd(msg):
    txt = msg.text.strip()
    if txt.startswith("查询用户充值记录"):
        try:
            uid = int(txt.replace("查询用户充值记录","").strip())
            log = log_recharge.get(uid,["该用户暂无充值记录"])
            safe_send_msg(msg.chat.id,f"📋 用户{uid} 充值明细\n"+"\n".join(log)[:4000])
        except:
            safe_send_msg(msg.chat.id,"❌格式：查询用户充值记录 用户ID")
    elif txt.startswith("查询用户消费记录"):
        try:
            uid = int(txt.replace("查询用户消费记录","").strip())
            log = log_user.get(uid,["该用户暂无消费记录"])
            safe_send_msg(msg.chat.id,f"📋 用户{uid} 消费明细\n"+"\n".join(log)[:4000])
        except:
            safe_send_msg(msg.chat.id,"❌格式：查询用户消费记录 用户ID")

@bot.message_handler(content_types=['photo'])
def broadcast_photo(msg):
    if not is_admin(msg.from_user.id): return
    global broad_img
    broad_img = msg.photo[-1].file_id
    safe_send_msg(msg.chat.id,"✅图片已保存，请发送广播文字")

def broadcast_worker(uid_list, img_id, text):
    def send_task(uid):
        try:
            if img_id:
                safe_send_photo(uid, img_id, text)
            else:
                safe_send_msg(uid, text)
            return 1
        except: return 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        res = executor.map(send_task, uid_list)
    return sum(res)

@bot.message_handler(func=lambda msg: broad_img is not None)
def admin_broadcast(msg):
    global broad_img, broad_text
    broad_text = msg.text
    user_list = list(users.keys())
    total = len(user_list)
    safe_send_msg(msg.chat.id,f"📢开始全站广播｜总用户{total}人，后台发送中...")
    send_count = broadcast_worker(user_list, broad_img, broad_text)
    safe_send_msg(msg.chat.id,f"🎉广播完成｜成功送达{send_count}人｜失败{total-send_count}人｜{get_beijing_time_str()}")
    broad_img = None
    broad_text = ""

@bot.message_handler(content_types=['document'])
def doc(m):
    uid=m.from_user.id
    state = user_state.get(uid,"idle")
    try:
        file = bot.get_file(m.document.file_id)
        data = bot.download_file(file.file_path)
        name = m.document.file_name.lower()

        if state=="hebing":
            txt=extract_txt_from_zip(data) if name.endswith(".zip") else data.decode("utf-8","ignore")
            txt=clean_empty_line(txt)
            user_merge[uid].append(txt)
            safe_send_msg(m.chat.id,f"✅已收录第{len(user_merge[uid])}个文件，继续上传或发送【完成】")
            return

        if state=="quchong":
            txt=extract_txt_from_zip(data) if name.endswith(".zip") else data.decode("utf-8","ignore")
            txt=clean_empty_line(txt)
            raw_lines = txt.splitlines()
            new_lines, old_cnt, new_cnt = dedup_phone_list(raw_lines)
            fee=new_cnt*PRICE_DEDUP
            u=get_user(uid)
            if u['balance']<fee:
                safe_send_msg(m.chat.id,f"❌余额不足｜需要{fee:.4f}元")
                return
            safe_send_msg(m.chat.id,"✅余额校验通过，正在去重...")
            bio=BytesIO("\n".join(new_lines).encode())
            bio.name="去重纯净号码.txt"
            try:
                bot.send_document(m.chat.id,bio)
                u['balance']-=fee
                add_log(uid,f"号码去重｜原{old_cnt}→{new_cnt}行",new_cnt,fee)
                safe_send_msg(m.chat.id,f"✅去重完成｜扣费{fee:.4f}元｜剩余{u['balance']:.4f}元")
            except:
                safe_send_msg(m.chat.id,"❌发送失败，本次不扣费，请重试！")
            user_state[uid]="idle"
            return

        txt=extract_txt_from_zip(data) if name.endswith(".zip") else data.decode("utf-8","ignore")
        txt=clean_empty_line(txt)
        user_file[uid]={"txt":txt}
        safe_send_msg(m.chat.id,"✅文件解析完成，请选择分包模式",reply_markup=select_menu())
    except Exception as e:
        safe_send_msg(m.chat.id,f"❌文件处理异常：{str(e)[:100]}")

@bot.callback_query_handler(func=lambda c:True)
def cb(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    cid = c.message.chat.id
    d = c.data

    if d == "cdk_use":
        bot.edit_message_text("💳请直接发送卡密即可充值",cid,c.message.message_id)
        bot.register_next_step_handler(c.message, use_cdk)
        return
    if d == "return_user":
        bot.edit_message_text("👤个人中心",cid,c.message.message_id,reply_markup=user_menu(uid))
        return
    if d == "batch_addbal_start":
        bot.edit_message_text("🔥批量充值格式：\n用户ID 金额\n一行一个",cid,c.message.message_id)
        bot.register_next_step_handler(c.message, batch_add_user_balance)
        return
    if d.startswith("my_rc"):
        page = int(d.split("_")[-1])
        page_temp[uid] = "my_rc"
        log = log_recharge.get(uid, [])
        total = len(log)
        tp = (total + PAGE_NUM - 1) // PAGE_NUM
        st=(page-1)*PAGE_NUM
        ed=page*PAGE_NUM
        txt=f"💳我的充值记录 第{page}/{tp}页\n"+"\n".join(log[st:ed])[:4000]
        bot.edit_message_text(txt,cid,c.message.message_id,reply_markup=page_btn("my_rc",page,tp))
        return
    if d.startswith("my_use"):
        page = int(d.split("_")[-1])
        page_temp[uid] = "my_use"
        log = log_user.get(uid, [])
        total = len(log)
        tp = (total + PAGE_NUM - 1) // PAGE_NUM
        st=(page-1)*PAGE_NUM
        ed=page*PAGE_NUM
        txt=f"📜我的消费明细 第{page}/{tp}页\n"+"\n".join(log[st:ed])[:4000]
        bot.edit_message_text(txt,cid,c.message.message_id,reply_markup=page_btn("my_use",page,tp))
        return
    if d=="mode":
        u=get_user(uid)
        u['mode']="VCF" if u['mode']=="TXT" else "TXT"
        bot.edit_message_text("✅格式已切换",cid,c.message.message_id,reply_markup=menu(uid))
    elif d=="line":
        bot.send_message(cid,"📏请输入每份分割行数")
        bot.register_next_step_handler(c.message,set_line)
    elif d=="user":
        bot.edit_message_text("👤个人中心",cid,c.message.message_id,reply_markup=user_menu(uid))
    elif d=="bal":
        safe_send_msg(cid,f"💰您当前余额：{get_user(uid)['balance']:.4f}元")
    elif d=="back":
        bot.edit_message_text("🏠主菜单",cid,c.message.message_id,reply_markup=menu(uid))
    elif d=="hebing":
        user_merge[uid]=[]
        user_state[uid]="hebing"
        safe_send_msg(cid,"📎依次上传文件，完毕发【完成】")
    elif d=="quchong":
        user_state[uid]="quchong"
        safe_send_msg(cid,"🧹上传号码文件（TXT/ZIP）")
    elif d=="admin" and is_admin(uid):
        bot.edit_message_text("🔧管理后台",cid,c.message.message_id,reply_markup=admin_kb())
    elif d=="ins":
        if uid not in user_file:
            safe_send_msg(cid,"❌请先上传文件")
            return
        bot.send_message(cid,"⚡每份插入几条雷号？（纯数字）")
        bot.register_next_step_handler(c.message, ins_num)
    elif d=="noins":
        if uid not in user_file:
            safe_send_msg(cid,"❌请先上传文件")
            return
        temp_split_data[uid]=user_file[uid]['txt']
        bot.send_message(cid,"📄请输入文件前缀名")
        bot.register_next_step_handler(c.message,lambda m:split_send_clean(cid,uid,temp_split_data[uid],m.text))

# 卡密、充值、批量充值
def get_page(s):
    return s.split("_")[-1]

def del_single_cdk(msg):
    cdk=msg.text.strip()
    if cdk in cards:
        del cards[cdk]
        safe_send_msg(msg.chat.id,f"✅卡密 {cdk} 已作废")
    else:
        safe_send_msg(msg.chat.id,"❌卡密不存在")

def input_card_day(msg):
    try:
        day=int(msg.text)
        safe_send_msg(msg.chat.id,f"✅有效期{day}天，请输入卡密面值")
        bot.register_next_step_handler(msg, lambda m:make_card(m,day))
    except:
        safe_send_msg(msg.chat.id,"❌请输入纯数字天数")

def make_card(msg,day):
    try:
        money = float(msg.text)
        import string
        expire = get_now_timestamp() + day * 86400
        cdk = "TK"+''.join(random.choices(string.ascii_uppercase+string.digits,k=12))
        cards[cdk] = {"money":money,"expire_time":expire}
        expire_str = datetime.fromtimestamp(expire).strftime("%Y-%m-%d %H:%M:%S")
        safe_send_msg(msg.chat.id,f"✅卡密生成成功\n{cdk}\n面值：{money}\n过期：{expire_str}")
    except:
        safe_send_msg(msg.chat.id,"请输入正确金额")

def use_cdk(m):
    cdk=m.text.strip()
    now=get_now_timestamp()
    if cdk not in cards:
        safe_send_msg(m.chat.id,"❌无效/已用/过期")
        return
    info=cards[cdk]
    if info['expire_time']<now:
        del cards[cdk]
        safe_send_msg(m.chat.id,"❌卡密已过期")
        return
    money = info['money']
    cards.pop(cdk)
    get_user(m.from_user.id)['balance']+=money
    add_rc(m.from_user.id,money)
    safe_send_msg(m.chat.id,f"✅充值到账{money:.4f}元｜余额{get_user(m.from_user.id)['balance']:.4f}")

def batch_add_user_balance(msg):
    if not is_admin(msg.from_user.id):return
    cid = msg.chat.id
    lines = msg.text.strip().splitlines()
    success=0;fail=[]
    for line in lines:
        line=line.strip()
        if not line:continue
        try:
            uid,money=line.split()
            uid=int(uid);money=float(money)
            get_user(uid)['balance']+=money
            add_rc(uid,money)
            success+=1
        except:fail.append(line)
    safe_send_msg(cid,f"✅批量充值完成｜成功{success}｜失败{len(fail)}")

def set_line(m):
    try:
        get_user(m.from_user.id)['line']=int(m.text)
        safe_send_msg(m.chat.id,"✅分割行数设置成功")
    except:
        safe_send_msg(m.chat.id,"❌请输入纯数字")

# 常驻运行
while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        print(f"运行异常: {e}")
        time.sleep(3)
