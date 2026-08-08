<div align="center">

# 🚀 [123pan](https://www.123panng.top)

  <p>突破限制 · 高效下载 · 简单易用</p>

  <div>
    <a href="https://github.com/123pannextgen/123pan/stargazers"><img src="https://img.shields.io/github/stars/123pannextgen/123pan" alt="Stars"></a>
    <a href="https://github.com/123pannextgen/123pan/issues"><img src="https://img.shields.io/github/issues/123pannextgen/123pan" alt="Issues"></a>
    <a href="https://github.com/123pannextgen/123pan/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL%203-green" alt="License"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python Version"></a>
    <a href="https://github.com/123pannextgen/123pan/releases"><img src="https://img.shields.io/github/v/tag/123pannextgen/123pan?label=release" alt="latest_release"></a>
    <a href="https://github.com/123pannextgen/123pan/releases"><img src="https://img.shields.io/github/downloads/123pannextgen/123pan/total" alt="Downloads"></a>
  </div>
  <br>
  <img src="./doc/image.png" width="600" alt="Screenshot">

</div>

## 介绍

123pan是一款第三方123云盘客户端，解决了123云盘官方客户端的若干问题，并使用多种方式解除流量限制，使用Python3和PySide6等由123pan Next Gen团队制作。本项目永久开源并托管在Github.

## 使用

>[!WARNING]
> **免责声明**
>
> 本项目为**个人学习与技术研究目的开发，与 123 云盘官方无任何关联。**使用本软件即表示您已**知晓并同意**以下内容：
>
> - **本软件按「现状」提供，不提供任何明示或暗示的保证**
> - **开发者不对因使用本软件导致的任何直接或间接损失承担责任，包括但不限于数据丢失、账号封禁、服务中断等**
> - **使用者应自行承担使用本软件的全部风险，并遵守 123 云盘用户协议及相关法律法规**
> - **请勿将本软件用于商业用途**

### 使用打包后的文件运行

如果你的电脑是Windows系统或者Linux发行版，可以直接下载并解压，然后运行其中的`123pan.exe`或`123pan`。  
下载地址：

- Github: https://github.com/123panNextGen/123pan/releases/
- Website(CloudFlare CDN, 更新可能不及时): https://download.123panng.top/

>[!TIP]
>Windows下如果无法运行，可以尝试打开兼容模式。杀毒软件有可能报毒，请放行。

>[!IMPORTANT]
>请**不要**把文件放在**中文路径**下！

>[!IMPORTANT]
>请不要从未知渠道下载！

其他系统以及开发者请参考下方的源码运行。

### 使用源码运行

首先准备好 [Python3](https://www.python.org/downloads/) 与 [uv](https://github.com/astral-sh/uv) 环境，并克隆存储库。

```shell
git clone https://github.com/123panNextGen/123pan.git
cd 123pan/
```

准备Python虚拟环境。

```shell
uv sync
uv sync --group build --group lint # 构建环境
```

然后运行`src`下的`123pan.py`即可。

```shell
uv run src/123pan.py
```
>[!TIP]
>键盘快捷键
>
>F5: 刷新文件列表
>
>Ctrl+N: 新建文件夹
>
>Ctrl+U: 上传文件
>
>Ctrl+D: 下载选中文件
>
>Delete: 删除选中文件
>
>F2: 重命名文件
>
>Backspace: 返回上级目录
>
>Ctrl+F: 聚焦搜索框
>
>Ctrl+A: 全选文件
>
>Enter: 进入文件夹/预览文件

## 问题反馈&社区讨论

你可以通过多种途径反馈&讨论问题。

- Github Issues: https://github.com/123panNextGen/123pan/issues
- Github Discussions：https://github.com/123panNextGen/123pan/discussions
- QQ群: 996241397

我们将在第一时间解决问题。

## 使用协议

本程序使用[GPLv3](./LICENSE)协议。  

---

本程序由[123panNextGen](https://github.com/123panNextGen)开发团队用♥️制作～  
我们由衷感谢为本程序贡献代码的人们。 [贡献人员名单](https://github.com/123panNextGen/123pan/graphs/contributors)

<!--
 ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⡀⠀⠀⣀⡀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⠀⣼⣿⣿⣦⡀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⠀⠀⠀⠀⢸⣿⣿⡟⢰⣿⣿⣿⠟⠁⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢰⣿⠿⢿⣦⣀⠀⠘⠛⠛⠃⠸⠿⠟⣫⣴⣶⣾⡆⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⡀⠀⠉⢿⣦⡀⠀⠀⠀⠀⠀⠀⠛⠿⠿⣿⠃⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣦⠀⠀⠹⣿⣶⡾⠛⠛⢷⣦⣄⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣧⠀⠀⠈⠉⣀⡀⠀⠀⠙⢿⡇⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⢀⣠⣴⡿⠟⠋⠀⠀⢠⣾⠟⠃⠀⠀⠀⢸⣿⡆⠀⠀⠀⠀⠀
⠀⠀⠀⠀⢀⣠⣶⡿⠛⠉⠀⠀⠀⠀⠀⣾⡇⠀⠀⠀⠀⠀⢸⣿⠇⠀⠀⠀⠀⠀
⠀⢀⣠⣾⠿⠛⠁⠀⠀⠀⠀⠀⠀⠀⢀⣼⣧⣀⠀⠀⠀⢀⣼⠇⠀⠀⠀⠀⠀⠀
⠀⠈⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⡿⠋⠙⠛⠛⠛⠛⠛⠁⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣾⡿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢾⠿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
-->
