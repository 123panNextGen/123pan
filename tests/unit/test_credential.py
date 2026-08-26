"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

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
        """非加密字符串（无 enc: 前缀）原样返回。"""
        cred_mod._KEY_FILE = tmp_path / ".keyfile"
        assert cred_mod.decrypt_credential("") == ""
        assert cred_mod.decrypt_credential("hello") == "hello"
        assert cred_mod.decrypt_credential("enc:") == "enc:"
        assert cred_mod.decrypt_credential("enc:invalid") == "enc:invalid"

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
