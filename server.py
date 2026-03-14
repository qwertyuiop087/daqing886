from flask import Flask, request
from aiogram import Bot
from aiogram.utils.exceptions import BotBlocked
from database import get_card
import os

BOT_TOKEN = os.getenv("7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY", "你的Token")
bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

@app.route("/callback", methods=["POST"])
def callback():
    status = request.form.get("status")
    user = request.form.get("pay_user_id")

    if status == "1" and user:
        card = get_card()
        if card:
            try:
                import asyncio
                asyncio.run(bot.send_message(chat_id=int(user), text=f"支付成功\n卡密:{card}"))
            except BotBlocked:
                pass
            except Exception as e:
                print(e)
    return "success"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
