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
    try:
        r = requests.post(
            "https://okpay.com/api/deposit",
            json=data,
            timeout=10  # 添加超时，避免卡死
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        # 打印错误日志（实际应使用 logging）
        print(f"OKPay 请求失败: {e}")
        return {"error": "请求失败"}
