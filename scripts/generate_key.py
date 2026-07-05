#!/usr/bin/env python3
"""
认证密钥生成器
生成加密安全的随机密钥，用于 CHATGPT2API_AUTH_KEY
"""

import secrets
import string
import hashlib
import time
import uuid


def generate_secret_key(length: int = 32) -> str:
    """
    生成加密安全的随机密钥
    
    Args:
        length: 密钥长度（默认 32 字符）
    
    Returns:
        随机生成的安全密钥字符串
    """
    # 使用 secrets 模块生成加密安全的随机字符串
    # 包含大小写字母、数字和特殊字符
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generate_uuid_key() -> str:
    """
    生成 UUID 格式的密钥
    
    Returns:
        UUID 格式的密钥
    """
    return str(uuid.uuid4())


def generate_token_key(prefix: str = "sk") -> str:
    """
    生成带前缀的 token 格式密钥（类似 API key 格式）
    
    Args:
        prefix: 密钥前缀（默认 "sk"）
    
    Returns:
        带前缀的 token 密钥
    """
    random_part = secrets.token_urlsafe(32)
    return f"{prefix}-{random_part}"


def generate_hashed_key(seed: str = None) -> str:
    """
    基于种子生成哈希密钥（可选，如果需要可重现的密钥）
    
    Args:
        seed: 种子字符串（可选，如果不提供则使用当前时间戳）
    
    Returns:
        SHA-256 哈希密钥（64 字符十六进制）
    """
    if seed is None:
        seed = f"{time.time()}-{secrets.token_hex(16)}"
    
    return hashlib.sha256(seed.encode()).hexdigest()


def main():
    """主函数：生成并显示各种格式的密钥"""
    print("=" * 60)
    print("🔐 认证密钥生成器")
    print("=" * 60)
    print()
    
    # 生成不同类型的密钥
    secret_key = generate_secret_key(32)
    uuid_key = generate_uuid_key()
    token_key = generate_token_key("sk")
    hashed_key = generate_hashed_key()
    
    print("✅ 已生成以下密钥（选择其中一个使用）：")
    print()
    
    print("1️⃣  随机密钥 (32 字符，推荐):")
    print(f"   CHATGPT2API_AUTH_KEY={secret_key}")
    print()
    
    print("2️⃣  UUID 密钥:")
    print(f"   CHATGPT2API_AUTH_KEY={uuid_key}")
    print()
    
    print("3️⃣  Token 格式密钥:")
    print(f"   CHATGPT2API_AUTH_KEY={token_key}")
    print()
    
    print("4️⃣  哈希密钥 (64 字符):")
    print(f"   CHATGPT2API_AUTH_KEY={hashed_key}")
    print()
    
    print("=" * 60)
    print("💡 使用说明:")
    print("   - 将选中的密钥添加到 config.json 或环境变量")
    print("   - 密钥应保密，不要提交到版本控制")
    print("   - 建议定期轮换密钥")
    print("=" * 60)
    
    # 返回推荐的密钥
    return secret_key


if __name__ == "__main__":
    generate_secret_key()
    main()