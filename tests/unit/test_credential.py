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

import src.app.common.credential as cred_mod
import pytest


class TestCredential:
    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        """加密后能解密还原原始字符串。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        original = "MySecretPassword123!"
        encrypted = cred_mod.encrypt_credential(original)
        assert encrypted.startswith("enc:")
        decrypted = cred_mod.decrypt_credential(encrypted)
        assert decrypted == original

    def test_decrypt_plaintext(self, tmp_path):
        """非加密字符串（无 enc: 前缀）原样返回；解密失败不再回退密文。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        assert cred_mod.decrypt_credential("") == ""
        assert cred_mod.decrypt_credential("hello") == "hello"
        assert cred_mod.decrypt_credential("enc:") == ""
        assert cred_mod.decrypt_credential("enc:invalid") == ""

    def test_decrypt_failure_does_not_rotate_key(self, tmp_path):
        """解密失败不得覆盖密钥文件（否则已存凭据会永久失效）。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        secret = "MySecretPassword123!"
        encrypted = cred_mod.encrypt_credential(secret)
        key_before = cred_mod._KEY_FILE.read_bytes()

        # 用错误密钥加密的密文：非法长度/内容都会导致解密失败
        bad = "enc:" + base64.b64encode(b"\x00" * 40).decode()
        assert cred_mod.decrypt_credential(bad) == ""

        # 原密钥文件必须原封不动，且原密文仍可解
        assert cred_mod._KEY_FILE.read_bytes() == key_before
        assert cred_mod.decrypt_credential(encrypted) == secret

    def test_keyfile_read_failure_does_not_overwrite(
        self, tmp_path, monkeypatch
    ):
        """读取既有密钥文件失败时必须报错，绝不能重新生成覆盖。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        secret = "KeepThisPassword"
        encrypted = cred_mod.encrypt_credential(secret)
        key_before = cred_mod._KEY_FILE.read_bytes()

        real_open = open

        def flaky_open(path, mode="r", *args, **kwargs):
            if str(path) == str(cred_mod._KEY_FILE) and "r" in mode and "+" not in mode:
                raise PermissionError(13, "simulated transient read error")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", flaky_open)
        with pytest.raises(RuntimeError):
            cred_mod.encrypt_credential("another")

        # 文件未被覆盖，且原凭据仍可用
        assert cred_mod._KEY_FILE.read_bytes() == key_before
        monkeypatch.undo()
        assert cred_mod.decrypt_credential(encrypted) == secret

    def test_create_key_file_cleans_up_on_write_failure(
        self, tmp_path, monkeypatch
    ):
        """写入失败时必须删除残留的不完整密钥文件。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        monkeypatch.setattr(
            cred_mod.os,
            "write",
            lambda fd, data: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(RuntimeError):
            cred_mod.encrypt_credential("secret")
        assert not cred_mod._KEY_FILE.exists()

    def test_partial_writes_are_completed(self, tmp_path, monkeypatch):
        """os.write 只写入部分字节时仍需写出完整密钥并可用。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        real_write = os.write

        def one_byte(fd, data):
            return real_write(fd, bytes(data[:1]))

        monkeypatch.setattr(cred_mod.os, "write", one_byte)
        secret = "partial-write-ok"
        encrypted = cred_mod.encrypt_credential(secret)
        monkeypatch.undo()
        assert cred_mod.decrypt_credential(encrypted) == secret

    def test_encrypt_empty_string(self, tmp_path):
        """空字符串加密返回空字符串。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        assert cred_mod.encrypt_credential("") == ""
        assert cred_mod.encrypt_credential(None) == ""

    def test_encrypt_failure_does_not_return_plaintext(self, monkeypatch):
        """密钥不可用时必须失败，不能回退返回明文。"""
        monkeypatch.setattr(
            cred_mod,
            "_load_or_create_key",
            lambda: (_ for _ in ()).throw(OSError("key unavailable")),
        )
        with pytest.raises(RuntimeError, match="无法安全加密凭据"):
            cred_mod.encrypt_credential("secret")

    def test_encrypt_multiple_calls_different_results(self, tmp_path):
        """相同明文每次加密产生不同密文（GCM nonce 随机性）。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        plain = "same password"
        e1 = cred_mod.encrypt_credential(plain)
        e2 = cred_mod.encrypt_credential(plain)
        assert e1 != e2
        assert cred_mod.decrypt_credential(e1) == plain
        assert cred_mod.decrypt_credential(e2) == plain

    def test_account_passwords_roundtrip(self, tmp_path):
        """账户密码字典的加密/解密回环。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        info = {"userName": "test", "passWord": "p@ss123"}
        encrypted = cred_mod.encrypt_account_passwords(info)
        assert encrypted["passWord"].startswith("enc:")
        assert encrypted["userName"] == "test"
        decrypted = cred_mod.decrypt_account_passwords(encrypted)
        assert decrypted["passWord"] == "p@ss123"

    def test_account_passwords_skip_non_encrypted(self):
        """非 enc: 前缀的密码在解密时原样保留。"""
        info = {"userName": "test", "passWord": "plain_pwd"}
        result = cred_mod.decrypt_account_passwords(info)
        assert result["passWord"] == "plain_pwd"

    def test_account_passwords_empty(self):
        """空字典或空密码不报错。"""
        assert cred_mod.encrypt_account_passwords({}) == {}
        assert cred_mod.decrypt_account_passwords({}) == {}
        assert cred_mod.encrypt_account_passwords(None) is None
        assert cred_mod.decrypt_account_passwords(None) is None
