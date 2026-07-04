# AGENTS.md — 123pan 项目规范

## 项目概览

123pan 是一款基于 PyQt6 的 123 云盘第三方客户端，通过模拟安卓协议绕过官方 PC 端的下载流量限制。

- Python ≥3.12，PyQt6 + qfluentwidgets
- 构建/依赖管理：[uv](https://github.com/astral-sh/uv)
- 分支策略：功能开发 → `feature/xxx` → 合并到 `fluent-dev`

## 架构

```
src/
  app/
    __init__.py
    api/
      session.py        # NetSession — HTTP 会话层
      model.py           # 数据模型（dataclass + from_dict/to_json）
    common/
      api.py             # Pan123 — 门面类，转发到各 Service
      config.py          # ConfigManager — 配置读写
      credential.py      # AES-256-GCM 加密
      speed_limiter.py   # 令牌桶速度限制器
      log.py             # 日志
      const.py           # 常量
    service/
      auth_service.py    # 认证
      file_service.py    # 文件操作
      download_service.py # 下载
      upload_service.py   # 上传
    tasks/
      file_tasks.py      # QRunnable 后台任务
      signals.py          # Qt 信号类
    view/
      file_interface.py  # 文件浏览界面
      transfer_interface.py # 传输管理界面
      setting_interface.py  # 设置界面
      login_window.py    # 登录窗口
      main_window.py     # 主窗口
      cloud_interface.py # 云盘界面
      dialogs.py         # 通用输入对话框
tests/
  unit/                  # 纯逻辑测试
  integration/           # mock HTTP 集成测试
```

### 分层职责

| 层 | 目录 | 职责 |
|---|---|---|
| **API** | `api/` | HTTP 请求、数据模型。无业务逻辑 |
| **Service** | `service/` | 业务逻辑编排。无 UI 依赖 |
| **Facade** | `common/api.py:Pan123` | 向后兼容门面，转发到 Service |
| **Tasks** | `tasks/` | QRunnable 后台任务 + Qt 信号 |
| **View** | `view/` | PyQt6 界面。不直接访问 `NetSession` |

### 关键约束

- View 层**禁止**直接访问 `NetSession`（`pan._session`），必须通过 `Pan123` 门面或 Service 层
- Service 类**禁止** import Qt 模块
- `Pan123` **禁止**包含业务逻辑，仅做转发

## 开发工作流

### 分支

```
fluent-dev  ← 合并目标
  feature/xxx  — 新功能
  fix/xxx      — 修复
  refactor/xxx — 重构
```

### 提交规范

每条提交是一个**原子变更**，格式：

```
type: 简短描述

- 要点 1
- 要点 2
```

| type | 含义 |
|---|---|
| `feat:` | 新功能 |
| `fix:` | 修复 |
| `refactor:` | 重构（不改变行为） |
| `test:` | 测试 |
| `docs:` | 文档 |
| `chore:` | 基础设施（依赖、配置等） |

### 步骤规范

1. 新开分支 `refactor/xxx` 或 `feature/xxx`
2. 每做一小步提交一次
3. 每步提交后自行 review 潜在问题
4. 阶段完成后合并到 `fluent-dev`
5. 不确定时询问，不擅自行动

## 代码风格

- 无注释（除非必须，如 pylint disable）
- 无类型注解（项目风格，不使用 type hints）
- 文件名：蛇形命名（`file_interface.py`）
- 类名：帕斯卡命名（`FileInterface`）
- 私有方法双下划线（`__loadCurrentList`）
- UI 方法名以 `__` 开头表示私有
- 信号类以 `_` 开头（`_LoadListSignals`）

## 测试

```shell
uv run pytest                    # 全部测试
uv run pytest -v                 # 详细
uv run pytest --cov              # 覆盖率
uv run pytest tests/unit/        # 单元测试
uv run pytest -k "test_login"    # 按名称
```

### 测试策略

- **Unit**: 纯函数测试，mock 时间/文件系统
- **Integration**: `responses` 库 mock HTTP，不发起真实请求
- **Fixture**: `tmp_path` 隔离文件操作，模块级变量需手动覆盖

## 依赖分组

```shell
uv sync                             # 运行时依赖
uv sync --group test                # + 测试
uv sync --group lint                # + 代码检查
uv sync --group build               # + nuitka 打包
```
