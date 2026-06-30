import re

_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def mask_phone(phone: str | None) -> str | None:
    """手机号脱敏：138****5005"""
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


def mask_contact_info(info: str | None) -> str | None:
    """联系信息脱敏：自动识别并遮蔽手机号"""
    if not info:
        return info
    return _PHONE_PATTERN.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], info)


def mask_customer_info(info: dict | None) -> dict | None:
    """客户信息 dict 脱敏：遍历所有值，遮蔽手机号和邮箱"""
    if not info:
        return info
    masked = {}
    for k, v in info.items():
        if isinstance(v, str):
            masked[k] = mask_contact_info(v)
            masked[k] = _EMAIL_PATTERN.sub("[邮箱已脱敏]", masked[k])
        else:
            masked[k] = v
    return masked


def sanitize_for_llm(text: str) -> str:
    """替换 PII 为占位符后再发给大模型"""
    text = _PHONE_PATTERN.sub("[电话已脱敏]", text)
    text = _EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    return text
