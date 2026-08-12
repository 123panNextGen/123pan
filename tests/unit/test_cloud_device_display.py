"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.api.model import DeviceItemModel, DeviceListResponse
from src.app.view.cloud_interface import CloudInterface

_app = QApplication.instance() or QApplication([])


def _make_device(name="PC", cur=False):
    """构造一个设备条目。"""
    return DeviceItemModel(
        device_name=name,
        plat_form="Windows",
        ip="1.2.3.4",
        last_login_time="2026-08-08 06:00",
        device_type="PC",
        key=f"k-{name}",
        cur_device=cur,
        login_type="password",
        img="",
        login_uuid=f"u-{name}",
    )


def _make_interface():
    """构造并显示云盘界面（动态添加卡片的场景需要界面已显示）。"""
    ci = CloudInterface()
    ci.resize(800, 600)
    ci.show()
    _app.processEvents()
    return ci


class TestDeviceDisplay:
    """设备列表动态卡片显示（回归：卡片未显式 show 时会被裁剪不可见）。"""

    def test_cards_visible_and_group_expands(self):
        ci = _make_interface()
        devices = [_make_device("PC"), _make_device("Android"), _make_device("Web")]
        ci._update_device_display(DeviceListResponse(device_list=devices))
        _app.processEvents()

        assert len(ci._device_cards) == 3
        assert all(c.isVisible() for c in ci._device_cards), "卡片应全部可见"
        # 卡片组高度应被撑开（标题 ~46px + 3 张 70px 卡片 + 间距 > 200）
        assert ci.deviceGroup.height() > 200, "卡片组应随卡片数量伸展"

    def test_master_device_card_added(self):
        ci = _make_interface()
        devices = [_make_device("PC", cur=True)]
        resp = DeviceListResponse(device_list=devices, master_device=devices[0])
        ci._update_device_display(resp)
        _app.processEvents()

        # 1 个设备 + 1 个主设备卡片
        assert len(ci._device_cards) == 2
        assert all(c.isVisible() for c in ci._device_cards)

    def test_empty_shows_placeholder(self):
        ci = _make_interface()
        ci._update_device_display(DeviceListResponse(device_list=[]))
        _app.processEvents()

        assert len(ci._device_cards) == 1
        assert ci._device_cards[0].isVisible()

    def test_refresh_replaces_cards(self):
        """重复加载时应替换旧卡片而不是叠加。"""
        ci = _make_interface()
        ci._update_device_display(
            DeviceListResponse(device_list=[_make_device("PC")])
        )
        _app.processEvents()
        ci._update_device_display(
            DeviceListResponse(device_list=[_make_device("PC"), _make_device("Web")])
        )
        _app.processEvents()

        assert len(ci._device_cards) == 2
        assert all(c.isVisible() for c in ci._device_cards)
