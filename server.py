from flask import Flask, request
from aiogram import Bot
from aiogram.exceptions import BotBlocked  # 修正：v3.x 路径调整
from database import get_card
import os

# 1. 配置机器人令牌（建议替换为你的真实 Token）
BOT_TOKEN = os.getenv("7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY", "你的真实机器人Token")
bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

# 2. 根路径健康检查
@app.route("/")
def home():
    return "Bot Server is Running"

# 3. 支付回调接口
@app.route("/callback", methods=["POST"])
def callback():
    try:
        status = request.form.get("status")
        user_id = request.form.get("pay_user_id")
        
        if status == "1" and user_id:
            card = get_card()
            if card:
                # 修正：使用 asyncio.run_coroutine_threadsafe 或确保正确异步上下文
                # 这里使用简单的同步调用包装，兼容 Render 环境
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(bot.send_message(
                        chat_id=int(user_id),
                        text=f"✅ 支付成功！\n📝 你的卡密是：\n{card}"
                    ))
                    loop.close()
                except BotBlocked:
                    print(f"用户 {user_id} 已屏蔽机器人")
                except Exception as e:
                    print(f"发送消息失败: {e}")
    except Exception as e:
        print(f"回调处理异常: {e}")
    return "success"

# 4. 启动服务
if __name__ == "__main__":
    # Render 要求强制使用环境变量 PORT
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
