import hashlib
import aiohttp
import config

# 签名函数（按key升序排序，修复无序问题；做值转义，防止&/=篡改）
def sign(data: dict) -> str:
    # 1. 按key升序排序，保证拼接顺序固定
    sorted_items = sorted(data.items(), key=lambda x: x[0])
    # 2. 拼接键值对，值做简单转义（防止含&/=）
    text = "&".join(f"{k}={str(v).replace('&', '%26').replace('=', '%3D')}" for k, v in sorted_items)
    # 3. 拼接商户token并生成MD5签名
    text += config.SHOP_TOKEN
    return hashlib.md5(text.encode("utf-8")).hexdigest()

# 异步创建支付订单
async def create_order(order_id: str, amount_usdt: float) -> dict | None:
    # 构造请求参数
    data = {
        "shopId": config.SHOP_ID,
        "orderId": order_id,
        "amount": round(amount_usdt, 6),  # USDT保留6位小数，符合支付接口规范
        "coin": config.PAY_COIN
    }
    # 生成签名
    data["sign"] = sign(data)
    
    # 异步HTTP请求，设置超时（防止阻塞）
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(
                url=config.PAY_API_URL,
                json=data,
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    # 接口返回非200，打印状态码（方便排查）
                    print(f"支付接口请求失败，状态码：{resp.status}")
                    return None
    except aiohttp.ClientError as e:
        # 捕获网络异常
        print(f"支付接口网络异常：{str(e)}")
        return None
    except Exception as e:
        print(f"支付接口未知异常：{str(e)}")
        return None
