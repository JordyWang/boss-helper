# 架构说明

项目按依赖方向分成四层：

```text
CLI / tools
    ↓
runtime（启动组装）
    ↓
application（ApplyService 业务编排）
    ↓
domain + ports（Job、Message、过滤策略和协议）

设备页面、State、Recorder 是 ports 的基础设施实现。
```

原子调试操作由 `operations` 注册表驱动：

```text
cli → OperationContext → OperationSpec(handler)
                       ├─ 设备/是否启动 App
                       ├─ 需要的页面对象
                       └─ 是否需要显式 --yes
```

- `boss/domain.py` 只保存职位、消息和运行结果，不依赖真机。
- `boss/application.py` 实现批量投递流程，依赖 `ports.py` 定义的页面/存储
  协议，因此可以用 fake 页面做测试。
- `boss/operations.py` 集中登记 `recommend`、`detail`、`send`、`dry-run`、
  `filter-check` 等原子操作及其依赖；CLI 不再维护一串 `if/elif`。
- `boss/engine.py` 是真实设备适配器，保留原来的 `ApplyEngine` 入口并组装
  `HomePage`、`JobDetailPage` 和 `ChatPage`。
- `boss/runtime.py` 负责连接设备、切到前台和创建状态仓库。
- `boss/cli.py` 只处理参数、输出和退出码，`main.py` 只是兼容启动脚本。

`filter-check` 只加载配置并在本地评估职位；`health` 连接设备但不会强制
启动 App；`dry-run` 使用只读状态仓库，只扫描和过滤，不点击卡片、不发送消息、
也不会落盘修改状态。

## 每次运行的文件归档

`RunArtifacts` 为每次命令创建 `logs/YYYYMMDD_HHMMSS/`（同秒重复时自动加
后缀）并生成 `run.log`。截图和 UI dump 共用递增序号，例如：

```text
logs/20260921_231500/
├── run.log
├── 001_dump.xml
└── 002_screenshot.png
```

`logs/.run.lock` 是运行锁。锁存在时新的命令会立即退出，从而保证设备操作
严格串行；正常结束或异常清理后锁会删除。

状态 JSON 使用临时文件写入后 `os.replace` 原子替换；运行锁使用
`O_CREAT|O_EXCL` 原子创建，避免两个进程同时取得设备控制权。

## 聊天消息归档与去重

`op messages` 会把结构化消息写入本次运行目录的 `*_messages.json`。当前
APK（14.160）提供给 UI hierarchy 的只有控件 `resource-id`、`index`、文本
和坐标，没有可直接使用的 `messageId`/`conversationId`；因此这些字段不会被
误当成唯一 ID。

每条归档消息包含 `dedup_key` 和 `dedup_source`：

- 接入 API/带有 `message_id` 时，使用“会话 + 服务端 ID”（`server_id`）；
- 当前 UI 方案使用“会话上下文 + sender + kind + 规范化文本 + 可选时间戳”
  的 SHA-256 内容指纹（`content`）。

内容指纹是本地 best-effort 标识，不是 Boss 官方 ID。两个完全相同且没有
时间戳的消息无法仅靠 UI 可靠区分；需要严格去重时，应从接口或 App 的业务
数据层取得服务端消息 ID，并通过 `--conversation-id` 提供会话上下文。

## 当前真机与 APK 基线

最近一次从已连接设备读取（2026-09-22）：

- 包名：`com.hpbr.bosszhipin`
- `versionName`：`14.160`
- `versionCode`：`1416010`
- 设备：Redmi K30i 5G，Android 12，1080×2400
- 安装/更新时间：2026-09-21 22:39:43

选择器校准和 UI dump 结果应注明对应 APK 版本；升级 App 后先重新执行
`python3 main.py dump` 并复核 `boss/selectors.py`。
运行时会把首次检测到的版本保存到 `.state/app_version.json`；同版本后续运行
不会重复写入或刷 `run.log`，只有检测到版本变化时才更新基线。

## 无真机测试

核心编排使用端口协议，可以直接运行：

```bash
python3 -m unittest discover -v
```

这组测试不连接设备，覆盖配置解析、状态去重、运行锁/工件命名、页面等待
语义、批处理编排和原子操作安全边界。
