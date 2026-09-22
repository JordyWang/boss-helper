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

设备页面、State、Recorder 是 ports 的基础设施实现。Recorder 同时负责运行
期间的数据采集落库。
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
- `boss/web.py` 提供本机浏览器操作台；页面请求仍通过同一套页面对象、运行
  归档和 `.run.lock` 执行，不另起一套设备控制逻辑。

`filter-check` 只加载配置并在本地评估职位；`health` 连接设备但不会强制
启动 App；`dry-run` 使用只读状态仓库，只扫描和过滤，不点击卡片、不发送消息、
也不会落盘修改投递状态；扫描到的职位快照仍会按统一规则写入 SQLite，便于
审计本次读取结果。

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

## 运行期间 SQLite 数据采集

`safety.records_db`（默认 `.state/records.db`）是统一的本地 SQLite 数据库。
设备/页面每次读到数据后立即调用 Recorder 并提交短事务，不等到整次运行
结束才落盘；因此中途断开设备时，前面已经获取的内容仍然可查。写入使用
稳定主键或去重键幂等更新，重复刷新不会复制同一条消息。

主要表：

- `runs`：运行 ID、来源、日志路径和结束状态；
- `jobs`：推荐卡片/详情职位快照；
- `conversations`：列表会话摘要（公司、职位、联系人和会话 ID）；
- `messages`：按“会话 ID + 消息 dedup_key”保存文本、发送方、类型和时间；
- `observations`：每次读取的追加式观测（包括设备健康和截图路径）；APK
  版本只在首次检测或版本变化时追加，保持安装基线日志的低噪声约束；
- `records`：兼容旧版本的投递动作记录。

会话消息的服务端 ID 优先作为去重依据；当前 APK 没有服务端 ID 时继续使用
已有的内容指纹规则。`records` 表的旧数据无需迁移，启动时会自动补充运行字段。

例如可直接查看最近会话和消息：

```bash
sqlite3 .state/records.db \
  'select conversation_id,recruiter,company,job_title,last_seen_at from conversations order by last_seen_at desc;'
sqlite3 .state/records.db \
  'select conversation_id,sender,kind,text,timestamp from messages order by first_seen_at;'
```

## 聊天消息归档与去重

`op messages` 会把结构化消息写入本次运行目录的 `*_messages.json`。当前
APK（14.160）提供给 UI hierarchy 的只有控件 `resource-id`、`index`、文本
和坐标，没有可直接使用的 `messageId`/`conversationId`；因此这些字段不会被
误当成唯一 ID。

每条归档消息包含 `dedup_key` 和 `dedup_source`：

- 接入 API/带有 `message_id` 时，使用“会话 + 服务端 ID”（`server_id`）；
- 当前 UI 方案使用“会话上下文 + sender + kind + 规范化文本 + 可选时间戳”
  的 SHA-256 内容指纹（`content`）。

聊天页中的“换电话、查看微信、发简历、同意、拒绝、复制微信号、已读”等
业务操作节点也会归档为 `sender=system`、`kind=action` 的消息，不会因为它们
是按钮而丢失；普通消息仍使用 `kind=text`，简历事件使用 `kind=resume`。

当前聊天页会把标题栏副标题（当前版本格式为“公司 · 职位”）和招聘者名称
组合为本地会话上下文，例如
`company=梦虎网络|job_title=ceo|recruiter=尚先生`。它不是 Boss 官方
`conversationId`；若能从接口取得服务端会话 ID，可通过 `--conversation-id`
覆盖。两个完全相同且没有时间戳的消息仍无法仅靠 UI 可靠区分。

## 会话管理

`conversations`（旧入口 `op conversations`）是只读会话管理入口。默认只进入
消息列表并记录当前可见会话的 ID，不会自动逐个打开聊天；也可以显式选择一个
ID，或明确指定数量：

```bash
# 只列出当前可见会话 ID（不打开聊天）
python3 main.py conversations
python3 main.py conversations --list-only

# 按列表 ID 精确匹配并只打开/保存一个会话
python3 main.py conversations \
  'company=三横科技|job_title=全栈工程师|recruiter=丘先生'
# 也可以写成 --id 或 --conversation-id
python3 main.py conversations --id 'company=三横科技|job_title=全栈工程师|recruiter=丘先生'

# 明确要求时才打开前 N 个会话
python3 main.py conversations -n 3
```

匹配会在当前屏和有限滚动范围内进行（可用 `--max-scrolls` 调整），找不到
目标时停止，不会无限遍历历史会话。归档 JSON 以消息列表生成的
`conversation_id` 为主键，并另外保存聊天页解析出的 `chat_conversation_id`，
这样聊天页副标题变化不会破坏后续按 ID 回查。当前 APK 没有暴露官方会话 ID，
所以这里的 ID 是本地组合标识；若后续 UI/API 提供服务端 ID，会使用
`server:<id>` 命名空间并优先匹配。

## 可视化操作台

不想使用命令行时可以启动本地浏览器界面：

```bash
python3 main.py ui
```

默认只监听 `127.0.0.1:8765`，启动后会自动打开浏览器。页面提供设备检查、
截图和 UI dump、批量沟通（按钮确认后才执行），以及会话列表、按 ID 保存和
按数量保存。每个设备动作都单独创建时间戳运行目录和日志，并经过全局运行锁；
服务本身不会长期占用 `.run.lock`。也可以用 `python3 main.py ui --no-browser`
手动打开显示的网址。

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
