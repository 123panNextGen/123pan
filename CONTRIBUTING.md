# 代码贡献

我们很欢迎您来为项目添砖加瓦，但是请遵守以下几点：

- 不要提交未测试的代码
- 不要提交无意义的内容
- 不要提交涉及隐私的内容

## 开发工作流

### 分支

```
fluent-dev  ← 合并目标
  feature/xxx  — 新功能
  fix/xxx      — 修复
  refactor/xxx — 重构
```
- fork项目时不要勾选仅复制main分支

### 提交规范

每条提交是一个**原子变更**，格式：

```
type: 简短描述

- 要点 1
- 要点 2
```

| type        | 含义                     |
| ----------- | ------------------------ |
| `feat:`     | 新功能                   |
| `fix:`      | 修复                     |
| `refactor:` | 重构（不改变行为）       |
| `test:`     | 测试                     |
| `docs:`     | 文档                     |
| `chore:`    | 基础设施（依赖、配置等） |

### 步骤规范

1. 新开分支 `refactor/xxx` 或 `feature/xxx`
2. 每做一小步提交一次
3. 每步提交后自行 review 潜在问题
4. 阶段完成后合并到 `fluent-dev`
5. 不确定时询问，不擅自行动

## 代码风格

- 按情况提交注释
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

## AI编写规范

按照顺序进行，新开 refactor/xxx 这样的分支，最后通过规范的 git commit 再进行合并到 fluent-dev 分支中
每做一小步就提交一次，并且自已review一下是否有潜在问题。
如果有任何不确定的问题 一定要询问意见，切忌擅自行动。

## 文档
关于文档，请在[WIKI](./doc/wiki.md)页面查看

## TODO
TODO列表请查看[这里](./doc/TODO.md)