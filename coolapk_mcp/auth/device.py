"""设备码生成 — 数盟 ShuzlmID 设备码（2026-10-24 实测解锁 detail/replyList 风控）

设备码明文结构（9 字段，; 分隔，第 5-9 字段带前导空格）：
    ShuzlmID; ; ; ; {manufacturer}; {brand}; {model}; {display}; null
编码：base64(utf8) → 字符串反转 → 去 '='。

风控结论（实测矩阵）：
- 随机 UUID / 公共共享码：detail/replyList 触发 err_request_captcha_v2；
  公共共享码额外触发 -415"设备下登录账号过多"（多账号关联）
- 数盟 ShuzlmID 设备码 + 登录 Cookie：detail/replyList 直接放行（同 IP 生效）
- ShuzlmID 获取：root 设备读取官方 App 的
  /data/data/com.coolapk.market/shared_prefs/coolapk_preferences_v7.xml 中 SHUZILM_DID
- 机型参数取 getprop：ro.product.manufacturer/brand/model，display 用
  ro.build.display_id（为空可用 ro.build.version.incremental）
"""

import base64
import uuid

# 旧公共设备码，仅留档对照（已因多账号风控被拉黑，勿再使用）
LEGACY_SHARED_DEVICE_CODE = (
    "AZmV2N4UzN0UmZ3kDOzEzYgsjMwAjL2IjMwUjMuE0MRFEI7MkMxITM4AjMyAyOp1GZlJFI7kWbvFWaYByO"
    "gsDI7AyOzYGO3okVq1GWOlEez8WYLlkWKVWbllzX3pUTjFTcjx2aPVFR"
)


def encode_device_code(
    shuzlm_id: str, manufacturer: str, brand: str, model: str, display: str
) -> str:
    """用真实数盟 ShuzlmID + 机型参数构造设备码（需与官方 App 所在设备一致）"""
    plain = f"{shuzlm_id}; ; ; ; {manufacturer}; {brand}; {model}; {display}; null"
    return base64.b64encode(plain.encode()).decode()[::-1].replace("=", "")


def decode_device_code(code: str) -> str:
    """还原设备码明文（调试用）"""
    rev = code[::-1]
    rev += "=" * (-len(rev) % 4)
    return base64.b64decode(rev).decode("utf-8", errors="replace")


def generate_device_code() -> str:
    """无数盟 ID 时的兜底：返回本安装独享 UUID（AppConfig 持久化，仅生成一次）。

    注意：UUID 设备码下 detail/replyList 会被验证码拦截（正文走作者动态回落），
    有条件请用 encode_device_code 构造数盟身份设备码。
    """
    return str(uuid.uuid4())
