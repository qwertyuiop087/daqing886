import hashlib
import aiohttp
import config

# 签名函数（按key升序，修复原无序问题，加值转义）
def sign(data: dict) -> str:
    sorted_data = sorted(data.items(), key=lambda x: x[0])
    text = "&".join(f"{k}={str(v).replace('&', '%26').replace('=', '%3D')}" for k, v in sorted_data)
    text += config.SHOP_TOKEN
    return hashlib.md5(text.encode("utf-8")).hexdigest()

# 异步创建支付订单（替换原同步requests，加超时）
async def create_order(order_id: str, amount_usdt: float) -> dict | None:
    data = {
        "shopId": config.SHOP_ID,
        "orderId": order_id,
        "amount": round(amount_usdt, 6),
        "coin": config.PAY_COIN
    }
    data["sign"] = sign(data)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(
                config.PAY_API_URL,
                json=data,
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except aiohttp.ClientError:
        return None
    except Exception:
        return None
