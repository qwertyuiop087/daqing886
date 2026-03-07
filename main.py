"""
Telegram 红包控制系统 - 极简测试版
专门测试手机号输入功能
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
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    filters, ContextTypes
)

# ==================== 你的配置 ====================
USER_API_ID = 38596687
USER_API_HASH = "3a2d98dee0760aa201e6e5414dbc5b4d"
BOT_TOKEN = "7750611624:AAEmZzAPDli5mhUrHQsvO7zNmZk61yloUD0"
YOUR_USER_ID = 7793291484

# 对话状态
PHONE, CODE = range(2)

# 日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 临时存储
pending = {}
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
        "🤖 红包控制系统 - 测试版\n点击添加账号",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理按钮"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != YOUR_USER_ID:
        return
    
    if query.data == "add":
        await query.edit_message_text(
            "📱 请输入手机号\n"
            "格式: +国家代码手机号\n"
            "例如:\n"
            "中国: +8613812345678\n"
            "柬埔寨: +855313658901\n"
            "发送 /cancel 取消"
        )
        return PHONE  # 进入手机号输入状态


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理手机号输入"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    phone = update.message.text.strip()
    logger.info(f"收到手机号: {phone}")
    
    # 简单验证
    if not phone.startswith('+'):
        await update.message.reply_text("❌ 必须以+开头，请重新输入:")
        return PHONE
    
    # 保存到context
    context.user_data['phone'] = phone
    
    # 回复用户
    await update.message.reply_text(f"✅ 已收到手机号: {phone}\n正在请求验证码...")
    
    # 尝试请求验证码
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
        
        # 保存到pending
        pending[phone] = {
            'client': client,
            'phone_code_hash': sent_code.phone_code_hash
        }
        
        await update.message.reply_text(
            "✅ 验证码已发送到你的手机\n"
            "请在60秒内输入验证码:"
        )
        
        logger.info(f"验证码已发送到 {phone}")
        return CODE  # 进入验证码输入状态
        
    except PhoneNumberInvalid:
        await update.message.reply_text("❌ 手机号无效，请检查格式")
        return PHONE
    except FloodWait as e:
        await update.message.reply_text(f"⏳ 请求太频繁，请等待 {e.value} 秒")
        return PHONE
    except Exception as e:
        await update.message.reply_text(f"❌ 请求失败: {str(e)}")
        logger.error(f"验证码请求错误: {e}")
        return PHONE


async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理验证码输入"""
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return ConversationHandler.END
    
    code = update.message.text.strip()
    phone = context.user_data.get('phone')
    
    if not phone:
        await update.message.reply_text("❌ 请先输入手机号")
        return ConversationHandler.END
    
    logger.info(f"收到验证码: {code} for {phone}")
    
    if phone not in pending:
        await update.message.reply_text("❌ 请先请求验证码")
        return ConversationHandler.END
    
    try:
        client = pending[phone]['client']
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=pending[phone]['phone_code_hash'],
            phone_code=code
        )
        
        me = await client.get_me()
        await update.message.reply_text(f"✅ 登录成功！用户: {me.first_name}")
        
        # 清理
        del pending[phone]
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(f"❌ 登录失败: {str(e)}")
        return CODE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消"""
    if update.effective_user.id != YOUR_USER_ID:
        return ConversationHandler.END
    
    # 清理pending
    phone = context.user_data.get('phone')
    if phone and phone in pending:
        await pending[phone]['client'].disconnect()
        del pending[phone]
    
    await update.message.reply_text("❌ 已取消")
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    logger.error(f"错误: {context.error}")


def main():
    """主函数"""
    print("=" * 50)
    print("🚀 启动红包系统测试版")
    print("=" * 50)
    
    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 对话处理器 - 极简配置
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, code_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(conv_handler)
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
