"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import base64
import os
import platform
import secrets
import threading
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .const import CONFIG_DIR
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


# 密钥文件创建/读取的进程内互斥锁，防止并发首次创建互相覆盖
_KEY_LOCK = threading.Lock()


def _read_key_file(machine_id: str) -> bytes:
    """读取并解密已有的密钥文件。任何失败都向上抛出，绝不覆盖原文件。"""
    with open(_KEY_FILE, "rb") as f:
        stored_salt = f.read(_SALT_SIZE)
        encrypted_key = f.read()
    if len(stored_salt) != _SALT_SIZE or len(encrypted_key) <= 12:
        raise ValueError("密钥文件内容不完整")
    dk = _derive_key(stored_salt, machine_id)
    aesgcm = AESGCM(dk)
    nonce = encrypted_key[:12]
    ct = encrypted_key[12:]
    return aesgcm.decrypt(nonce, ct, None)


def _write_all(fd: int, data: bytes) -> None:
    """循环写入直到全部写完（os.write 可能只写入部分字节）。"""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("写入密钥文件失败")
        view = view[written:]


def _create_key_file(machine_id: str) -> bytes:
    """原子创建新的密钥文件（O_CREAT|O_EXCL）。

    并发情况下若文件已被其他线程/进程创建，则等待并读取现有密钥，绝不覆盖；
    若创建者写入失败并清理了文件，则重试自己创建。
    """
    random_key = secrets.token_bytes(_KEY_LENGTH)
    salt = secrets.token_bytes(_SALT_SIZE)
    derived_key = _derive_key(salt, machine_id)
    aesgcm = AESGCM(derived_key)
    nonce = secrets.token_bytes(12)
    encrypted_key = nonce + aesgcm.encrypt(nonce, random_key, None)
    payload = salt + encrypted_key

    os.makedirs(str(CONFIG_DIR), exist_ok=True)
    # Windows 下 os.open 默认文本模式，会把 0x0A 写成 0x0D 0x0A，
    # 而读取用二进制模式，字节错位会导致密钥无法解密，故必须加 O_BINARY
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    last_error = None
    for _ in range(50):
        try:
            fd = os.open(str(_KEY_FILE), flags, 0o600)
        except FileExistsError:
            # 并发：等待对方写完并读取。对方若写入失败并清理了文件，
            # 则下一轮 os.open 会成功，由自己创建。
            try:
                return _read_key_file(machine_id)
            except Exception as e:  # noqa: BLE001 - ValueError/OSError/InvalidTag 等
                last_error = e
                time.sleep(0.02)
                continue
        try:
            _write_all(fd, payload)
        except BaseException:
            # 写入失败（如磁盘满）时清理残留的不完整文件，
            # 否则下次会因“文件存在但内容不完整”而被永久锁死
            os.close(fd)
            try:
                os.unlink(str(_KEY_FILE))
            except OSError as e:
                logger.warning("清理不完整的密钥文件失败: %s", e)
            raise
        # fsync 尽力而为：完整数据已在页缓存中，其他进程可正常读取；
        # 若此时删除文件，反而会让刚加密的凭据变成无法解密的孤儿
        try:
            os.fsync(fd)
        except OSError as e:
            logger.warning("密钥文件 fsync 失败（忽略）: %s", e)
        os.close(fd)
        return random_key
    raise RuntimeError("并发创建密钥文件超时（文件始终不可读）") from last_error


def _load_or_create_key() -> bytes:
    """加载或创建随机密钥，用机器标识加密后存储。

    已存在的密钥文件**绝不会被静默覆盖**：读取或解密失败时抛出异常，
    由调用方处理（避免销毁此前加密的所有凭据）。
    """
    machine_id = _get_machine_id()
    with _KEY_LOCK:
        if not _KEY_FILE.exists():
            return _create_key_file(machine_id)
        try:
            return _read_key_file(machine_id)
        except Exception as e:  # noqa: BLE001 - 需保护既有密钥文件
            logger.error(
                "无法读取既有密钥文件 %s: %s。为保护已保存的凭据，已停止"
                "操作；如确认密钥已损坏，请先备份后手动删除该文件。",
                _KEY_FILE,
                e or type(e).__name__,
            )
            raise RuntimeError(
                "密钥文件无法读取，已取消操作以保护已保存的凭据"
            ) from e


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
        logger.error("加密凭据失败: %s", e)
        raise RuntimeError("无法安全加密凭据，已取消保存") from e


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
        # 不再回退返回密文：否则会把 "enc:..." 当成明文密码使用，
        # 既掩盖密钥损坏，又导致难以排查的认证失败
        logger.error(
            "解密凭据失败 (%s): %s；密钥可能不匹配或密钥文件不可读",
            type(e).__name__,
            e,
        )
        return ""


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
