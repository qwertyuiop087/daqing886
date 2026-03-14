from flask import Flask, request
from aiogram import Bot
from aiogram.utils.exceptions import BotBlocked
from database import get_card
import os
import asyncio

# 关键：强制指定使用 httpx 作为底层 HTTP 客户端（无需编译）
bot = Bot(
    token=os.getenv("7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY", "你的机器人Token"),
    session=lambda: httpx.AsyncClient()
)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Server Running"

@app.route("/callback", methods=["POST"])
def callback():
    status = request.form.get("status")
    user = request.form.get("pay_user_id")
    
    if status == "1" and user:
        card = get_card()
        if card:
            try:
                # 简化异步调用
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(bot.send_message(
                    chat_id=int(user),
                    text=f"✅ 支付成功！\n📝 卡密：{card}"
                ))
                loop.close()
            except BotBlocked:
                pass
            except Exception as e:
                print("发送消息失败:", e)
    return "success"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
