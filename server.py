from flask import Flask, request
from aiogram import Bot
from aiogram.utils.exceptions import BotBlocked
from database import get_card
import os

BOT_TOKEN = "7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY"
bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "bot running"

@app.route("/callback", methods=["POST"])
def callback():
    status = request.form.get("status")
    user = request.form.get("pay_user_id")
    if status == "1" and user:
        card = get_card()
        if card:
            # 用aiogram同步包装器发送消息，避免循环冲突
            try:
                bot.send_message(chat_id=int(user), text=f"支付成功\n卡密:{card}").wait()
            except BotBlocked:
                pass
            except Exception as e:
                print(f"发送消息失败: {e}")
    return "success"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
