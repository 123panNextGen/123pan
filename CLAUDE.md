# 123pan-open 项目规范

## 设置页面原则

所有 `database.py` `_init_defaults` 中的用户可调配置项，都必须在设置页面（`setting_interface.py`）提供对应的 UI 控件。新增配置项时同步添加设置界面入口。

当前需要在设置页面暴露的配置项：

| 配置 key | 说明 | 类型 | 范围 |
|----------|------|------|------|
| defaultDownloadPath | 默认下载路径 | 路径选择 | - |
| askDownloadLocation | 每次询问下载位置 | 开关 | bool |
| rememberPassword | 记住密码 | 开关 | bool |
| stayLoggedIn | 保持登录 | 开关 | bool |
| maxDownloadThreads | 单任务下载并发数 | SpinBox | 1-16 |
| maxUploadThreads | 单任务上传并发数 | SpinBox | 1-16 |
| maxConcurrentDownloads | 同时下载任务数 | SpinBox | 1-5 |
| maxConcurrentUploads | 同时上传任务数 | SpinBox | 1-5 |
| retryMaxAttempts | 最大重试次数 | SpinBox | 1-10 |
| uploadPartSizeMB | 上传分片大小 | SpinBox | 5-16 MB |
| downloadPartSizeMB | 下载分片大小 | SpinBox | 4-32 MB |
