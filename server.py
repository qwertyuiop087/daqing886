from flask import Flask, request
from aiogram import Bot
import asyncio
from database import get_card

BOT_TOKEN = "7750611624:AAHlHYVD7aXqQr1aZw3FOWxKO_msw5G0DJU"

bot = Bot(token=BOT_TOKEN)

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot running"


@app.route("/callback", methods=["POST"])
def callback():

    data = request.form

    status = data.get("status")
    user_id = data.get("pay_user_id")

    if status == "1":

        card = get_card()

        if card:

            asyncio.run(
                bot.send_message(
                    user_id,
                    f"支付成功\n\n你的卡密：\n{card}"
                )
            )

    return "success"
