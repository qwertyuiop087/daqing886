"""
Telegram 红包控制系统 - 最终简化版
不用 ConversationHandler，用最简单的状态管理
"""

import os
import json
import asyncio
import logging
import sys
from datetime import datetime

from pyrogram import Client as UserClient
from pyrogram.errors import PhoneNumberInvalid, FloodWait

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ==================== 你的配置 ====================
USER_API_ID = 38596687
USER_API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
YOUR_USER_ID = 7793291484

# 临时存储用户状态 {user_id: {"state": "phone"/"code", "phone": "xxx", "client": xxx}}
user_states = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# =============================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始命令"""
    if update.effective_user.id != YOUR_USER_ID:
        await update.message.reply_text("❌ 无权限")
        return
    
    keyboard = [
        [InlineKeyboardButton("📱 添加账号", callback_data="add")]
    ]
    
    await update.message.reply_text(
        "🤖 红包控制系统\n\n"
        "点击添加账号开始",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return
    
    if query.data == "add":
        # 设置用户状态为等待手机号
        user_states[user_id] = {"state": "waiting_phone"}
        
        await query.edit_message_text(
            "📱 *请输入手机号*\n\n"
            "格式：+国家代码手机号\n"
            "例如：\n"
            "中国：`+8613812345678`\n"
            "柬埔寨：`+855313658901`\n"
            "美国：`+11234567890`\n\n"
            "发送 /cancel 取消",
            parse_mode='Markdown'
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有消息"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return
    
    text = update.message.text.strip()
    
    # 检查用户状态
    if user_id not in user_states:
        await update.message.reply_text("请先发送 /start 开始")
        return
    
    state = user_states[user_id].get("state")
    
    if state == "waiting_phone":
        # 处理手机号输入
        await handle_phone(update, context)
    
    elif state == "waiting_code":
        # 处理验证码输入
        await handle_code(update, context)
    
    else:
        await update.message.reply_text("请先发送 /start 开始")


async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理手机号"""
    user_id = update.effective_user.id
    phone = update.message.text.strip()
    
    logger.info(f"收到手机号: {phone}")
    
    # 验证手机号格式
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 手机号必须以+开头，请重新输入：")
        return
    
    if not phone[1:].isdigit():
        await update.message.reply_text("❌ 手机号只能包含数字和+号，请重新输入：")
        return
    
    # 回复用户
    await update.message.reply_text(f"✅ 已收到手机号：{phone}\n⏳ 正在请求验证码...")
    
    try:
        # 创建临时客户端
        client = UserClient(
            name=f"temp_{phone.replace('+', '')}",
            api_id=USER_API_ID,
            api_hash=USER_API_HASH,
            phone_number=phone,
            in_memory=True
        )
        
        await client.connect()
        sent_code = await client.send_code(phone)
        
        # 保存到用户状态
        user_states[user_id] = {
            "state": "waiting_code",
            "phone": phone,
            "client": client,
            "phone_code_hash": sent_code.phone_code_hash
        }
        
        await update.message.reply_text(
            "✅ 验证码已发送到你的手机\n"
            "📱 请在60秒内输入验证码："
        )
        
        logger.info(f"验证码已发送到 {phone}")
        
    except PhoneNumberInvalid:
        await update.message.reply_text("❌ 手机号无效，请检查格式后重新输入：")
        # 保持等待手机号状态
        user_states[user_id] = {"state": "waiting_phone"}
        
    except FloodWait as e:
        await update.message.reply_text(f"⏳ 请求太频繁，请等待 {e.value} 秒后重试")
        # 重置状态
        user_states.pop(user_id, None)
        
    except Exception as e:
        await update.message.reply_text(f"❌ 请求失败：{str(e)}")
        logger.error(f"验证码请求错误: {e}")
        user_states.pop(user_id, None)


async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理验证码"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    
    user_data = user_states.get(user_id)
    if not user_data:
        await update.message.reply_text("❌ 会话已过期，请重新开始")
        return
    
    phone = user_data.get("phone")
    client = user_data.get("client")
    phone_code_hash = user_data.get("phone_code_hash")
    
    logger.info(f"收到验证码: {code} for {phone}")
    
    try:
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code
        )
        
        me = await client.get_me()
        
        # 保存session
        os.makedirs("sessions", exist_ok=True)
        session_name = f"sessions/{phone.replace('+', '')}"
        await client.storage.save(session_name)
        
        await update.message.reply_text(
            f"✅ 登录成功！\n"
            f"用户: {me.first_name}\n"
            f"ID: {me.id}\n\n"
            "账号已开始监听红包群"
        )
        
        # 清除状态
        user_states.pop(user_id, None)
        
    except Exception as e:
        error_str = str(e)
        if "CODE_INVALID" in error_str:
            await update.message.reply_text("❌ 验证码错误，请重新输入：")
        elif "PASSWORD" in error_str.upper():
            await update.message.reply_text("🔐 需要两步验证密码，请输入：")
            # 可以扩展处理密码
        else:
            await update.message.reply_text(f"❌ 登录失败：{error_str}")
            logger.error(f"登录错误: {error_str}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return
    
    # 清除用户状态
    if user_id in user_states:
        if "client" in user_states[user_id]:
            await user_states[user_id]["client"].disconnect()
        user_states.pop(user_id)
    
    await update.message.reply_text("❌ 已取消操作")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    logger.error(f"错误: {context.error}")


def main():
    """主函数"""
    print("=" * 50)
    print("🚀 红包控制系统启动")
    print("=" * 50)
    
    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 添加处理器
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    # 启动
    print("✅ 机器人已启动，请打开Telegram测试")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 已停止")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
