import hashlib
import requests
import config


def sign(data):

    text = "&".join(f"{k}={v}" for k, v in data.items())

    text += config.SHOP_TOKEN

    return hashlib.md5(text.encode()).hexdigest()


def create_order(order_id, amount):

    data = {
        "shopId": config.SHOP_ID,
        "orderId": order_id,
        "amount": amount,
        "coin": "USDT"
    }

    data["sign"] = sign(data)

    r = requests.post(
        "https://okpay.com/api/deposit",
        json=data
    )

    return r.json()
