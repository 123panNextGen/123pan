"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import random
import uuid

from ..api.model import DeviceModel, UserInfoModel
from ..common.config import ConfigManager
from ..common.const import all_device_type, all_os_versions
from ..common.log import get_logger

logger = get_logger(__name__)


class AuthService:
    """认证与凭证管理服务。

    负责登录、登出、账户信息持久化、设备指纹生成。
    """

    def __init__(self, session):
        self._session = session

        self.devicetype = random.choice(all_device_type)
        self.osversion = random.choice(all_os_versions)
        self.loginuuid = uuid.uuid4().hex

        self.user_name = ""
        self.password = ""
        self.authorization = ""
        # 保持登录：为 True 时持久化凭证（密码/token），下次启动自动登录
        self.stay_logged_in = True

    def sync_to_session(self):
        """将当前设备/用户信息同步到内部 NetSession。"""
        device = DeviceModel(os=self.osversion, type=self.devicetype)
        user_info = UserInfoModel(
            user_name=self.user_name,
            password=self.password,
            uuid=self.loginuuid,
            authorization=self.authorization,
            device=device,
        )
        self._session.set_user_info(user_info)

    def login(self):
        """登录123云盘账户并获取授权令牌。"""
        logger.info("AuthService.login: user=%s", self.user_name)
        result = self._session.login(self.user_name, self.password)
        if result.code not in (200, 0):
            logger.error("登录失败: code=%s, msg=%s", result.code, result.msg)
            return result.code
        token_data = result.data
        self.authorization = token_data["authorization"]
        logger.info("登录成功: user=%s, token已获取", self.user_name)
        self.save_file()
        return 200

    def save_file(self):
        """将账户信息保存到配置文件。

        未勾选「保持登录」时不持久化密码与 token，下次启动需重新登录。
        """
        try:
            account_info = {
                "userName": self.user_name,
                "passWord": self.password if self.stay_logged_in else "",
                "authorization": self.authorization if self.stay_logged_in else "",
                "deviceType": self.devicetype,
                "osVersion": self.osversion,
                "loginuuid": self.loginuuid,
            }
            ConfigManager.save_account(self.user_name, account_info)
            logger.info(
                "账号已保存 (stay_logged_in=%s)", self.stay_logged_in
            )
        except Exception as e:
            logger.error("保存账号失败: %s", e)

    def read_ini(self, user_name="", password="", input_pwd=False, authorization=""):
        """从配置文件读取账号信息。"""
        try:
            account = ConfigManager.get_account(user_name) if user_name else {}
            if not account:
                account = ConfigManager.get_account(None)

            if account:
                if not user_name:
                    user_name = account.get("userName", user_name)
                if not password:
                    password = account.get("passWord", password)
                if not authorization:
                    authorization = account.get("authorization", authorization)

                device_type = account.get("deviceType", "")
                os_version = account.get("osVersion", "")
                loginuuid = account.get("loginuuid", "")
                if device_type:
                    self.devicetype = device_type
                if os_version:
                    self.osversion = os_version
                if loginuuid:
                    self.loginuuid = loginuuid
            else:
                config = ConfigManager.load_config()
                device_type = config.get("deviceType", "")
                os_version = config.get("osVersion", "")
                loginuuid = config.get("loginuuid", "")
                if device_type:
                    self.devicetype = device_type
                if os_version:
                    self.osversion = os_version
                if loginuuid:
                    self.loginuuid = loginuuid
                user_name = config.get("userName", user_name)
                if not password:
                    password = config.get("passWord", password)
                if not authorization:
                    authorization = config.get("authorization", authorization)
        except Exception as e:
            logger.error("获取配置失败: %s", e)
            if not user_name or not password:
                raise Exception("无法从配置获取账号信息") from e

        self.user_name = user_name
        self.password = password
        self.authorization = authorization

    def get_user_info(self):
        """获取当前用户的云盘信息（UID、空间、VIP等）。"""
        return self._session.get_user_info()

    def get_device_list(self):
        """获取当前账户的登录设备列表。"""
        return self._session.get_device_list()

    # ---- 二维码登录 ----

    def qr_generate(self):
        """获取二维码登录会话（uniID + url）。"""
        logger.info("AuthService.qr_generate")
        result = self._session.qr_generate(self.loginuuid)
        if result.code != 0:
            logger.error("获取二维码失败: code=%s, msg=%s", result.code, result.msg)
            raise RuntimeError(f"获取二维码失败: {result.msg or result.code}")
        return result.data

    def qr_poll(self, uni_id):
        """轮询二维码扫码状态。

        Returns:
            dict: {loginStatus, scanPlatform, token?}
        """
        result = self._session.qr_poll(uni_id, self.loginuuid)
        if result.code != 0:
            logger.error("轮询扫码状态失败: code=%s, msg=%s", result.code, result.msg)
            raise RuntimeError(f"轮询扫码状态失败: {result.msg or result.code}")
        return result.data

    def qr_wx_code(self, uni_id):
        """获取微信扫码登录凭证（wxCode）。"""
        result = self._session.qr_wx_code(uni_id, self.loginuuid)
        if result.code != 0:
            logger.error("获取 wxCode 失败: code=%s, msg=%s", result.code, result.msg)
            raise RuntimeError(f"获取 wxCode 失败: {result.msg or result.code}")
        return result.data.get("wxCode", "")

    def load_saved_device(self):
        """从已保存账户配置恢复设备指纹（扫码登录验证用）。"""
        try:
            account = ConfigManager.get_account(None)
            if not account:
                return
            if account.get("deviceType"):
                self.devicetype = account["deviceType"]
            if account.get("osVersion"):
                self.osversion = account["osVersion"]
            if account.get("loginuuid"):
                self.loginuuid = account["loginuuid"]
            logger.debug("已恢复设备指纹: os=%s, type=%s", self.osversion, self.devicetype)
        except Exception as e:
            logger.error("恢复设备指纹失败: %s", e)
