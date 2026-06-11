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
BROAD_DELAY = 0.15
BROAD_BATCH = 50
MAX_WORKERS = 4
OP_TIMEOUT = 180       # 合并操作超时3分钟，超时自动作废
CHUNK_READ_SIZE = 65536
MERGE_MAX_CACHE = 500000  # 合并单次最大缓存行数，防止爆内存

# 全局数据
broad_text = ""
task_queue = queue.Queue(maxsize=100)
user_file = {}
users = {}
cards = {}
time_cards = {}
user_merge = {}  # 存储合并文件数据 {uid: {"lines":[], count:已上传文件数, start_time:开始时间}}
user_state = {}
user_insert = {}
log_user = {}
log_recharge = {}
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

def is_vip_valid(uid):
    u = get_user(uid)
    now = int(time.time())
    return u["vip_expire"] > now

def get_vip_expire_time_str(uid):
    u = get_user(uid)
    now = int(time.time())
    if u["vip_expire"] <= now:
        return "已过期/未开通"
    return datetime.fromtimestamp(u["vip_expire"], tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def get_vip_days_remaining(uid):
    u = get_user(uid)
    now = int(time.time())
    if u["vip_expire"] <= now:
        return 0
    return (u["vip_expire"] - now) // 86400

def add_log(uid, txt, num, cost):
    t = get_beijing_time_str()
    if uid not in log_user:
        log_user[uid] = []
    log_user[uid].insert(0, f"[{t}]｜{txt}｜{num}行｜扣费{cost:.4f}｜剩余{get_user(uid)['balance']:.4f}")

def add_rc(uid, money):
    t = get_beijing_time_str()
    if uid not in log_recharge:
        log_recharge[uid] = []
    log_recharge[uid].insert(0, f"[{t}]｜充值+{money:.4f}｜剩余{get_user(uid)['balance']:.4f}")

def get_beijing_time_str():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def get_now_timestamp():
    return int(time.time())

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
    return new_lines, len(raw_lines), len(new_lines)

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
        except Exception:
            continue
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
        except Exception:
            continue
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

def admin_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(telebot.types.InlineKeyboardButton("➕单人加余额",callback_data="addbal"),
           telebot.types.InlineKeyboardButton("➖单人扣余额",callback_data="subbal"))
    kb.add(telebot.types.InlineKeyboardButton("🗑️清空用户余额",callback_data="clear_bal"))
    kb.add(telebot.types.InlineKeyboardButton("⏰扣除VIP天数",callback_data="deduct_vip_days"))
    kb.add(telebot.types.InlineKeyboardButton("🎟️余额卡密",callback_data="card"),
           telebot.types.InlineKeyboardButton("⏰时间卡密",callback_data="time_card"))
    kb.add(telebot.types.InlineKeyboardButton("📊用户余额总表",callback_data="ulist"))
    kb.add(telebot.types.InlineKeyboardButton("📋全站充值记录",callback_data="rc_page_1"),
           telebot.types.InlineKeyboardButton("📋全站消费记录",callback_data="use_page_1"))
    kb.add(telebot.types.InlineKeyboardButton("📢全站广播",callback_data="broad"))
    kb.add(telebot.types.InlineKeyboardButton("🔥批量加余额",callback_data="batch_addbal_start"))
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

# ===================== 业务功能逻辑 =====================
def ins_num(m):
    uid = m.from_user.id
    try:
        num = int(m.text)
        user_insert[uid] = {"num": num, "txt_lines": user_file[uid]}
        lei_detail_log[uid] = []
        safe_send_msg(m.chat.id, "⚡请发送雷号，一行一个")
        bot.register_next_step_handler(m, ins_phone)
    except:
        safe_send_msg(m.chat.id, "❌请输入纯数字")

def ins_phone(m):
    uid = m.from_user.id
    if uid not in user_insert:
        safe_send_msg(m.chat.id, "❌流程失效，请重新上传文件")
        return
    phones = re.findall(r"\d+", m.text)
    if len(phones) == 0:
        safe_send_msg(m.chat.id, "❌未识别号码，请重发")
        bot.register_next_step_handler(m, ins_phone)
        return
    user_insert[uid]['phone'] = phones
    safe_send_msg(m.chat.id, "📄请输入文件前缀名（例如：插雷成品）")
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
            safe_send_msg(cid, f"❌余额不足｜需要{total_fee:.4f}元｜当前{u['balance']:.4f}元")
            return
        safe_send_msg(cid, f"✅余额校验通过，文件行数：{total}行，正在后台处理+生成插雷明细，请耐心等待...")
    else:
        safe_send_msg(cid, f"✅VIP用户免余额校验，文件行数：{total}行，正在后台处理+生成插雷明细，请耐心等待...")

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
                name = get_rand_3_name()
                vcf += f"BEGIN:VCARD\nVERSION:3.0\nN:{name};;;\nTEL:{p}\nEND:VCARD\n"
            bio = BytesIO(vcf.encode())
            bio.name = f"{file_prefix}_{file_idx}.vcf"
        else:
            bio = BytesIO("\n".join(temp_list).encode())
            bio.name = f"{file_prefix}_{file_idx}.txt"
        media.append(InputMediaDocument(bio))

        if len(media) >= 10:
            safe_send_msg(cid, f"📤正在发送第{batch_num}批｜文件 {file_idx-9}～{file_idx}")
            ok = safe_send_media_group(cid, media)
            if not ok:
                send_all_success = False
                break
            media = []
            batch_num += 1
        file_idx += 1

    if send_all_success and len(media) > 0:
        last_start = file_idx - len(media)
        safe_send_msg(cid, f"📤正在发送第{batch_num}批｜文件 {last_start}～{file_idx-1}")
        ok = safe_send_media_group(cid, media)
        if not ok:
            send_all_success = False

    if send_all_success:
        if not is_vip_valid(uid):
            u['balance'] -= total_fee
            add_log(uid, f"插雷分包｜每份{info['num']}个雷｜雷号池{len(phones)}个｜总行数{total}", total, total_fee)
        lei_detail_log[uid] = detail_lines
        detail_txt = "📝插雷位置明细（可核对每一个雷号位置）\n" + "\n".join(detail_lines)
        if len(detail_txt) > 3800:
            bio = BytesIO(detail_txt.encode("utf-8-sig"))
            bio.name = f"{file_prefix}_插雷位置明细.txt"
            bot.send_document(cid, bio)
        else:
            safe_send_msg(cid, detail_txt)
        if is_vip_valid(uid):
            safe_send_msg(cid, f"✅插雷分包全部完成（时长VIP免费）｜共{file_idx-1}个文件")
        else:
            safe_send_msg(cid, f"✅插雷分包全部完成｜扣费{total_fee:.4f}元｜剩余{u['balance']:.4f}元｜共{file_idx-1}个文件")
    else:
        safe_send_msg(cid, "❌文件发送失败（重试3次后仍失败），本次操作不扣费，请稍后重试！")

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
        safe_send_msg(cid, f"✅余额校验通过，文件行数：{total}行，正在生成文件，请耐心等待...")
    else:
        safe_send_msg(cid, f"✅VIP用户免余额校验，文件行数：{total}行，正在生成文件，请耐心等待...")

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
                vcf += f"BEGIN:VCARD\nVERSION:3.0\nN:{n};;;\nTEL:{p}\nEND:VCARD\n"
            bio = BytesIO(vcf.encode())
            bio.name = f"{name}_{file_idx}.vcf"
        else:
            bio = BytesIO("\n".join(c).encode())
            bio.name = f"{name}_{file_idx}.txt"
        media.append(InputMediaDocument(bio))

        if len(media) >= 10:
            safe_send_msg(cid, f"📤正在发送第{batch_num}批｜文件 {file_idx-9}～{file_idx}")
            ok = safe_send_media_group(cid, media)
            if not ok:
                send_all_success = False
                break
            media = []
            batch_num += 1
        file_idx += 1

    if send_all_success and len(media) > 0:
        last_start = file_idx - len(media)
        safe_send_msg(cid, f"📤正在发送第{batch_num}批｜文件 {last_start}～{file_idx-1}")
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
            safe_send_msg(cid, f"✅纯净分包完成｜扣费{fee:.4f}元｜剩余{u['balance']:.4f}元")
    else:
        safe_send_msg(cid, "❌发送失败，本次不扣费，请重试！")

    if uid in user_file:
        del user_file[uid]

# ===================== 管理员功能 =====================
def wait_clear_balance_user(m):
    try:
        target_uid = int(m.text.strip())
        u = get_user(target_uid)
        old_bal = u["balance"]
        u["balance"] = 0.0
        safe_send_msg(m.chat.id, f"✅操作成功\n用户ID：{target_uid}\n原余额：{old_bal:.4f}\n当前余额：0.0000")
    except ValueError:
        safe_send_msg(m.chat.id, "❌请输入纯数字用户ID！")

def wait_deduct_vip_days(m):
    try:
        parts = m.text.strip().split()
        target_uid = int(parts[0])
        days = int(parts[1])
        u = get_user(target_uid)
        now = get_now_timestamp()
        old_days = get_vip_days_remaining(target_uid)
        if u["vip_expire"] <= now:
            safe_send_msg(m.chat.id, f"❌用户{target_uid}暂无有效VIP，无法扣除")
            return
        new_expire = max(now, u["vip_expire"] - days * 86400)
        u["vip_expire"] = new_expire
        new_days = get_vip_days_remaining(target_uid)
        safe_send_msg(m.chat.id, f"✅操作成功\n用户ID：{target_uid}\n扣除天数：{days}天\n原剩余：{old_days}天\n新剩余：{new_days}天\n到期时间：{get_vip_expire_time_str(target_uid)}")
    except (ValueError, IndexError):
        safe_send_msg(m.chat.id, "❌格式错误！示例：123456 3")

# 后台广播带进度
def broadcast_task(admin_cid, content):
    user_list = list(users.keys())
    total = len(user_list)
    success = 0
    fail = 0
    progress_msg = None
    try:
        progress_msg = bot.send_message(admin_cid, f"📢 开始全站广播\n总用户数：{total}\n正在发送...")
    except:
        return
    for idx, user_id in enumerate(user_list, 1):
        try:
            time.sleep(BROAD_DELAY)
            bot.send_message(user_id, f"📢【全站公告】\n{content}")
            success += 1
        except Exception:
            fail += 1
        if idx % BROAD_BATCH == 0:
            percent = round(idx / total * 100, 1)
            try:
                bot.edit_message_text(
                    f"📢 广播进行中\n进度：{idx}/{total}（{percent}%）\n成功：{success} | 失败：{fail}",
                    admin_cid, progress_msg.message_id
                )
            except:
                pass
    try:
        bot.edit_message_text(
            f"✅ 全站广播已完成\n总用户：{total}\n发送成功：{success}\n发送失败：{fail}",
            admin_cid, progress_msg.message_id
        )
    except:
        safe_send_msg(admin_cid, f"✅ 全站广播已完成\n总用户：{total}\n发送成功：{success}\n发送失败：{fail}")

def do_broadcast(m):
    uid = m.from_user.id
    cid = m.chat.id
    if not is_admin(uid):
        return
    content = m.text.strip()
    if not content:
        safe_send_msg(cid, "❌广播内容不能为空")
        return
    if len(users) == 0:
        safe_send_msg(cid, "❌暂无任何使用过机器人的用户，无需广播")
        return
    threading.Thread(target=broadcast_task, args=(cid, content), daemon=True).start()

# ===================== 卡密充值 =====================
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
        safe_send_msg(cid, f"✅余额卡密兑换成功\n到账金额：{val}")
    elif cdk in time_cards:
        days = time_cards.pop(cdk)
        now = get_now_timestamp()
        expire = now + days * 86400
        get_user(uid)["vip_expire"] = expire
        safe_send_msg(cid, f"✅时长VIP兑换成功\n有效时长：{days}天\n到期时间：{get_vip_expire_time_str(uid)}")
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

# ===================== 回调事件 =====================
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
        def set_line(m):
            if m.text.isdigit():
                get_user(uid)["line"] = int(m.text)
                bot.send_message(cid, "✅行数设置完成", reply_markup=menu(uid))
            else:
                safe_send_msg(cid, "❌请输入数字")
        bot.register_next_step_handler(call.message, set_line)

    elif data == "user":
        bot.edit_message_text("👤个人中心", cid, call.message.message_id, reply_markup=user_menu(uid))

    elif data == "bal":
        u = get_user(uid)
        vip_status = "✅生效中" if is_vip_valid(uid) else "❌已过期/未开通"
        expire_time = get_vip_expire_time_str(uid)
        remain_days = get_vip_days_remaining(uid)
        safe_send_msg(cid, f"💰当前余额：{u['balance']:.4f}\n⏰VIP状态：{vip_status}\n📅到期时间：{expire_time}\n剩余时长：{remain_days}天")

    elif data == "back":
        bot.edit_message_text("🏠返回主页", cid, call.message.message_id, reply_markup=menu(uid))

    elif data == "hebing":
        # 初始化合并记录，记录开始时间防超时
        user_state[uid] = "hebing"
        user_merge[uid] = {
            "lines": [],
            "count": 0,
            "start_time": get_now_timestamp()
        }
        safe_send_msg(cid, "📎已进入文件合并模式，请逐个上传TXT/ZIP文件\n✅每上传一个会提示序号，全部上传完成发送【完成】，随时发送【取消】终止")

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

    elif data == "broad":
        if not is_admin(uid):
            return
        safe_send_msg(cid, "📢请输入要全站广播的内容（文字/表情）：")
        bot.register_next_step_handler(call.message, do_broadcast)

    elif data == "clear_bal":
        safe_send_msg(cid, "🗑️请输入要清空余额的【用户纯数字ID】：")
        bot.register_next_step_handler(call.message, wait_clear_balance_user)

    elif data == "deduct_vip_days":
        safe_send_msg(cid, "⏰格式：用户ID 天数（例：123456 3）")
        bot.register_next_step_handler(call.message, wait_deduct_vip_days)

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
        safe_send_msg(cid, "🎟️格式：卡密 面额（例：ABC123 10）")
        bot.register_next_step_handler(call.message, create_balance_card)

    elif data == "time_card":
        safe_send_msg(cid, "⏰格式：卡密 天数（例：XYZ789 7）")
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
        txt = "余额卡密：\n" + "\n".join(cards.keys()) + "\n\n时长卡密：\n" + "\n".join(time_cards.keys())
        bio = BytesIO(txt.encode())
        bio.name = "全部卡密.txt"
        bot.send_document(cid, bio)

    elif data == "ins":
        safe_send_msg(cid, "⚡请输入每个文件插入雷号数量（纯数字）")
        bot.register_next_step_handler(call.message, ins_num)

    elif data == "noins":
        if uid not in user_file:
            safe_send_msg(cid, "❌请先上传文件")
            return
        safe_send_msg(cid, "📄请输入文件前缀名")
        bot.register_next_step_handler(call.message, lambda m: split_send_clean(cid, uid, user_file[uid], m.text.strip()))

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

# ===================== 文件接收处理（修复合并逻辑） =====================
@bot.message_handler(content_types=['document'])
def handle_doc(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    # 合并超时自动清空状态
    if user_state.get(uid) == "hebing":
        merge_info = user_merge.get(uid, {})
        start_time = merge_info.get("start_time", 0)
        if get_now_timestamp() - start_time > OP_TIMEOUT:
            del user_state[uid]
            if uid in user_merge:
                del user_merge[uid]
            safe_send_msg(cid, "⏱️合并操作超时已自动取消，请重新进入合并")
            return

    try:
        safe_send_msg(cid, "📥正在解析文件，若是超大文件请耐心等待...")
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

        state = user_state.get(uid, "")
        if state == "hebing":
            # 合并：累加文件计数+总行数提示
            merge_info = user_merge[uid]
            merge_info["count"] += 1
            merge_info["lines"].extend(lines)
            total_lines = len(merge_info["lines"])
            safe_send_msg(cid, f"✅已接收【第{merge_info['count']}个】文件\n当前汇总总行数：{total_lines}\n继续上传文件，全部完成发送【完成】")
            # 限制最大缓存行数，防止内存爆炸
            if len(merge_info["lines"]) > MERGE_MAX_CACHE:
                safe_send_msg(cid, "⚠️文件行数过多，建议分批合并，避免服务卡顿")
            return

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
            user_file[uid] = lines
            bot.send_message(cid, f"✅文件解析完成，总行数：{len(lines)}，请选择分包模式", reply_markup=select_menu())
    except Exception as e:
        safe_send_msg(cid, "❌文件解析失败，已自动重置状态")
        if uid in user_state:
            del user_state[uid]

# 文本指令 完成/取消/start
@bot.message_handler(func=lambda m: True)
def text_msg(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    txt = msg.text.strip()

    # 合并完成 修复分批发送大合并文件
    if txt == "完成" and user_state.get(uid) == "hebing":
        merge_info = user_merge.get(uid, {})
        all_lines = merge_info.get("lines", [])
        file_count = merge_info.get("count", 0)
        total = len(all_lines)
        if total == 0:
            safe_send_msg(cid, "❌没有收到任何文件，合并取消")
            del user_state[uid]
            if uid in user_merge:
                del user_merge[uid]
            return

        fee = total * PRICE_MERGE
        u = get_user(uid)
        if not is_vip_valid(uid) and u["balance"] < fee:
            safe_send_msg(cid, f"❌余额不足｜需扣费{fee:.4f}｜当前余额{u['balance']:.4f}")
            return
        safe_send_msg(cid, f"📎开始合并{file_count}个文件，总行数{total}，正在生成文件...")

        # 大文件分批打包发送，不会卡死
        send_success = True
        media = []
        batch_num = 1
        file_name = "全部文件合并完成.txt"
        # 超大行拆分多个合并文件
        split_merge = [all_lines[i:i+50000] for i in range(0, total, 50000)]
        for idx, line_chunk in enumerate(split_merge, 1):
            bio = BytesIO("\n".join(line_chunk).encode())
            bio.name = f"合并文件_{idx}.txt"
            media.append(InputMediaDocument(bio))
            if len(media) >= 10:
                safe_send_msg(cid, f"📤发送合并文件 第{batch_num}批")
                ok = safe_send_media_group(cid, media)
                if not ok:
                    send_success = False
                    break
                media = []
                batch_num += 1
        if send_success and media:
            safe_send_msg(cid, f"📤发送合并文件 第{batch_num}批")
            safe_send_media_group(cid, media)

        if send_success:
            if not is_vip_valid(uid):
                u["balance"] -= fee
                add_log(uid, f"文件合并｜共{file_count}个源文件", total, fee)
            if is_vip_valid(uid):
                safe_send_msg(cid, f"✅合并完成（VIP免费）\n合并源文件：{file_count}个\n总数据行数：{total}")
            else:
                safe_send_msg(cid, f"✅合并完成\n合并源文件：{file_count}个\n总数据行数：{total}\n扣费{fee:.4f}｜剩余余额：{u['balance']:.4f}")
        else:
            safe_send_msg(cid, "❌合并文件发送失败，本次不扣费，请重新合并")

        # 清空合并状态
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
        safe_send_msg(cid, "✅已取消当前所有操作，状态已重置")

    elif txt == "/start":
        get_user(uid)
        user_state[uid] = "idle"
        lei_detail_log.pop(uid, None)
        now = get_beijing_time_str()
        welcome_text = (
            "🤖 大晴机器人 | 正常运行中✅\n"
            f"⏰ 北京时间：{now}"
        )
        bot.send_message(cid, welcome_text, reply_markup=menu(uid))

if __name__ == "__main__":
    print("🤖 机器人启动成功")
    bot.infinity_polling()
