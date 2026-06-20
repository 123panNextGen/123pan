"""凭据加密工具模块。

使用操作系统原生密钥环或基于机器标识的对称加密，
保护存储在配置文件中的敏感信息（如密码）。
"""

import base64
import hashlib
import json
import os
import platform
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import CONFIG_DIR
from .log import get_logger

logger = get_logger(__name__)

# 密钥文件路径
_KEY_FILE = CONFIG_DIR / ".keyfile"

# PBKDF2 参数
_SALT_SIZE = 16
_ITERATIONS = 600_000
_KEY_LENGTH = 32  # AES-256


def _derive_key(salt: bytes, machine_id: str) -> bytes:
    """基于机器标识和盐值派生加密密钥。"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(machine_id.encode("utf-8"))


def _get_machine_id() -> str:
    """获取机器唯一标识（不依赖硬件序列号，无需权限）。"""
    parts = [
        platform.node() or "unknown",
        platform.machine() or "unknown",
        platform.processor() or "unknown",
        str(Path.home()),
    ]
    return "|".join(parts)


def _load_or_create_key() -> bytes:
    """加载或创建随机密钥，用机器标识加密后存储。"""
    machine_id = _get_machine_id()
    salt = secrets.token_bytes(_SALT_SIZE)
    derived_key = _derive_key(salt, machine_id)

    if _KEY_FILE.exists():
        try:
            with open(_KEY_FILE, "rb") as f:
                stored_salt = f.read(_SALT_SIZE)
                encrypted_key = f.read()
            dk = _derive_key(stored_salt, machine_id)
            aesgcm = AESGCM(dk)
            nonce = encrypted_key[:12]
            ct = encrypted_key[12:]
            return aesgcm.decrypt(nonce, ct, None)
        except Exception:
            logger.warning("密钥文件损坏，重新生成")

    # 生成新密钥并加密存储
    random_key = secrets.token_bytes(_KEY_LENGTH)
    aesgcm = AESGCM(derived_key)
    nonce = secrets.token_bytes(12)
    encrypted_key = nonce + aesgcm.encrypt(nonce, random_key, None)

    os.makedirs(str(CONFIG_DIR), exist_ok=True)
    # 设置仅用户可读写
    with open(_KEY_FILE, "wb") as f:
        f.write(salt)
        f.write(encrypted_key)
    os.chmod(_KEY_FILE, 0o600)

    return random_key


def encrypt_credential(plaintext: str) -> str:
    """加密凭据字符串，返回 base64 编码的密文。

    Args:
        plaintext: 明文凭据。

    Returns:
        Base64 编码的加密字符串，前缀 "enc:"。
    """
    if not plaintext:
        return ""
    try:
        key = _load_or_create_key()
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return "enc:" + base64.b64encode(nonce + ct).decode("ascii")
    except Exception as e:
        logger.error(f"加密凭据失败: {e}")
        return plaintext


def decrypt_credential(ciphertext: str) -> str:
    """解密凭据字符串。

    Args:
        ciphertext: "enc:" 前缀的 base64 密文，或明文。

    Returns:
        解密后的明文。如果不是加密格式则原样返回。
    """
    if not ciphertext or not ciphertext.startswith("enc:"):
        return ciphertext
    try:
        key = _load_or_create_key()
        aesgcm = AESGCM(key)
        raw = base64.b64decode(ciphertext[4:])
        nonce = raw[:12]
        ct = raw[12:]
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except Exception as e:
        logger.error(f"解密凭据失败: {e}")
        return ciphertext


def encrypt_account_passwords(account_info: dict) -> dict:
    """加密账户信息中的密码字段。

    Args:
        account_info: 包含 passWord 字段的账户信息字典。

    Returns:
        密码已加密的账户信息。
    """
    if not account_info:
        return account_info
    result = dict(account_info)
    pwd = result.get("passWord", "")
    if pwd and not pwd.startswith("enc:"):
        result["passWord"] = encrypt_credential(pwd)
    return result


def decrypt_account_passwords(account_info: dict) -> dict:
    """解密账户信息中的密码字段。

    Args:
        account_info: 可能包含加密密码的账户信息字典。

    Returns:
        密码已解密的账户信息。
    """
    if not account_info:
        return account_info
    result = dict(account_info)
    pwd = result.get("passWord", "")
    if pwd and pwd.startswith("enc:"):
        result["passWord"] = decrypt_credential(pwd)
    return result
