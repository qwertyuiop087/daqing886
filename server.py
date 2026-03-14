from flask import Flask,request
from aiogram import Bot
import asyncio
from database import get_card

BOT_TOKEN="7750611624:AAGihlmQtN9QQqx_fhZlsKqLh85rS0AoWWY"

bot=Bot(token=BOT_TOKEN)

app=Flask(__name__)

@app.route("/")
def home():
    return "bot running"


@app.route("/callback",methods=["POST"])
def callback():

    status=request.form.get("status")
    user=request.form.get("pay_user_id")

    if status=="1":

        card=get_card()

        if card:

            asyncio.run(
                bot.send_message(user,f"支付成功\n卡密:{card}")
            )

    return "success"
