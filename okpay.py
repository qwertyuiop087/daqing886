import hashlib
import requests
import config

def sign(data):
    s = sorted(data.items())
    text = "&".join(f"{k}={v}" for k, v in s) + config.SHOP_TOKEN
    return hashlib.md5(text.encode()).hexdigest()

def pay_link(order_id, usdt):
    data = {
        "shopId": config.SHOP_ID,
        "orderId": order_id,
        "amount": round(usdt, 2),
        "coin": "USDT"
    }
    data["sign"] = sign(data)
    try:
        r = requests.post(config.PAY_API, json=data, timeout=10)
        return r.json()["data"]["payLink"]
    except:
        return None
