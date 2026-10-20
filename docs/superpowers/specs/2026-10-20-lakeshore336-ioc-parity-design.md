# Lake Shore 336 EPICS IOC 功能对齐设计

日期：2026-10-20  
状态：架构已认可；PV 细节与错误报告粒度随实施计划一并审阅  
范围：把已上机验证的 Python 控制与归档功能迁移到“IOC 为仪器接口、Python 为 EPICS 客户端”的运行方式。

## 目标

让 EPICS 客户端能够通过 IOC 完成当前 Python 控制程序支持的仪器操作，并保留现有操作界面和 CSV 归档能力。IOC 是连接 Lake Shore 336 串口的唯一进程；Python 仪表盘及其中的归档组件通过 EPICS Channel Access 访问 IOC。

这里的“功能对齐”指整套系统保留已验证的操作行为和归档结果，不要求把图形界面或 CSV 文件写入代码搬进 IOC。

## 已确认的设计选择

- 采用现有 C++ EPICS IOC、asyn 和 StreamDevice 继续扩展。
- 增加一个轻量 `aSub` 控制准备/完成处理器：在写串口前一次性验证并冻结 APPLY/PID 暂存值，命令本身和设备读回仍由 StreamDevice 完成。
- IOC 独占仪器串口；Python Web 仪表盘/归档组件和其他控制系统只连接 EPICS PV。
- 按 Python 现有控制顺序提供 IOC 侧整组 APPLY 操作。
- IOC 暴露日志控制和归档状态 PV；Python Web 仪表盘中的归档组件订阅仪器 PV 并写 CSV/元数据。
- 保留 Python 仪表盘作为 EPICS 客户端，继续承担界面、用户确认、显示通道映射和 CSV 下载。
- 初期通过现有 Channel Access PV 接入其他 EPICS 客户端；不把 PVA 纳入本次范围。

## 架构

```text
其他 EPICS 客户端 ─────────────┐
Python Web 仪表盘/归档组件 ────┼── Channel Access ── IOC PV 数据库
                              ┘                         │
                                    asyn / StreamDevice
                                             │
                                      串口（57600 7O1）
                                             │
                                      Lake Shore 336
```

Python Web 仪表盘保留原来的控制和趋势体验，现有 `LogArchive` 归档组件继续放在该 Python 应用中；所有真实设备操作改为读写 PV。归档组件不再打开串口；它订阅 IOC 的读数并根据日志控制 PV 开始、暂停、继续或切换 CSV 文件。直接串口模式只作为 IOC 停止时的维护/回退方式，不能与 IOC 同时连接仪器。

## 功能对齐范围

| 现有 Python 功能 | 对齐后的承载位置 | 对齐要求 |
|---|---|---|
| IDN、A-D 温度、设定值、斜率、量程、加热输出、PID 读数 | IOC 只读 PV | 保留现有名称与 `_RBV` 权威读回语义；读数异常能反映为 EPICS alarm/COMM 状态 |
| 选择控制输入 | IOC 控制 PV | 写入控制输入，并读回实际仪器状态；使用与 Python 相同的 `CSET` 行为 |
| Cold Head / Sample 显示通道选择 | Python 仪表盘配置 | 保留 A-D 可选映射；这只是显示映射，不改变仪器硬件配置 |
| 整组设定值、斜率和加热量程调整 | IOC APPLY 序列 | 按 `CSET → RANGE → RAMP → SETP` 顺序执行，命令间隔沿用当前约 150 ms；校验全部通过后才开始 |
| 单独改设定值及斜率 | IOC 命令 PV | 保留 Python 语义：斜率大于 0 时启用 ramp，斜率为 0 时关闭 ramp，然后写设定值 |
| PID 维护写入 | IOC 维护 PV + Python 维护界面 | 读旧值、写入、再读回；界面仍需维护登录和二次确认；元数据记录旧值、新值和操作时间 |
| 温度趋势、状态提示和模拟模式 | Python 仪表盘 | 保留现有界面体验；模拟模式不得连接或写入真实 IOC |
| CSV 记录及下载 | Python Web 仪表盘内的归档组件 | 保留 CSV 列、每日文件、手动新文件、暂停/继续、元数据和下载能力 |

## PV 接口提案

沿用可配置的 `LS336:` 前缀。以下新 PV 名称是设计提案，实施前可在不改变行为的前提下做一致性调整。

### 仪器控制 PV

保留 Phase 1 的 `Loop1:SETP`、`RAMP:*`、`RANGE`、各 `_RBV`、输入温度、加热输出和 PID 读数 PV。

新增以下控制面：

| PV | 方向 | 行为 |
|---|---|---|
| `Loop1:INPUT` | 写 | 接受整数代码 `1=A`、`2=B`、`3=C`、`4=D`，校验后立即执行一次 `CSET`；对应 Python 的单独控制输入选择 |
| `Loop1:INPUT_RBV` | 读 | `OUTMODE? 1` 读回的实际 Loop 1 控制输入 |
| `Loop1:CTRL:INPUT` | 写入暂存值 | 整组 APPLY 使用的控制输入；原始数值必须为整数代码 `1=A`、`2=B`、`3=C`、`4=D` |
| `Loop1:CTRL:SETP` | 写入暂存值 | APPLY 的目标设定值输入 |
| `Loop1:CTRL:RAMP:RATE` | 写入暂存值 | APPLY 的 ramp 速率输入；0 表示关闭 ramp |
| `Loop1:CTRL:RANGE` | 写入暂存值 | APPLY 的加热量程；原始数值必须为整数 `0..3` |
| `Loop1:CTRL:APPLY` | 写 | 触发一次校验后的整组命令 |
| `Loop1:CTRL:BUSY` | 读 | 整组命令执行中状态 |
| `Loop1:CTRL:STATUS` | 读 | `Idle`、`Busy`、`Done`、`PartialFailure` 或 `Error` |
| `Loop1:CTRL:ERROR` | 读 | 最近一次整组协议错误摘要；结合输出记录 alarm/status 和读回 PV 判断实际状态 |
| `Loop1:PID:P` / `I` / `D` | 写入暂存值 | 受维护权限保护的 PID 参数 |
| `Loop1:PID:APPLY` | 写 | 一次性提交 P/I/D，并执行读旧值、写入、读回 |
| `Loop1:PID:P_OLD_RBV` / `I_OLD_RBV` / `D_OLD_RBV` | 读 | 最近一次 PID APPLY 写入前读取的旧值，供审计记录使用 |
| `Loop1:PID:STATUS` | 读 | 最近一次 PID 操作的 `Idle`、`Busy`、`Done` 或 `Error` 状态 |
| `Loop1:PID:ERROR` | 读 | 最近一次 PID 写入错误摘要 |

整组 APPLY 触发时，IOC 的同步 `aSub` 处理器读取全部暂存 PV，冻结到内部快照，并一次性验证控制输入、设定值、斜率和量程。成功开始后 IOC 串行执行 `CSET → RANGE → RAMP → SETP`，每条命令按现有 Python 程序节奏间隔发送；随后在同一 StreamDevice 协议内查询输入、量程、ramp 和设定值读回。所有硬件写入共用同一串行控制通道；APPLY 执行期间不得让另一条写入插入命令序列。输出记录完成只表示 IOC 接受/执行了请求，界面应以读回值判断仪器是否达到请求值。

PID 的 P/I/D 是暂存参数，`Loop1:PID:APPLY` 才发送一条 `PID 1,p,i,d` 命令。IOC 的 `aSub` 处理器捕获并验证三项参数；StreamDevice 先查询并保存到 `P_OLD_RBV`、`I_OLD_RBV`、`D_OLD_RBV`，再提交三项参数并查询新值；这样保留 Python 单次三参数写入的语义，也避免逐项写入时出现中间 PID 组合。

Model 336 串口命令没有多字段原子事务。若中途失败，不自动回滚已经发送的命令；IOC 必须报告整组操作失败并继续更新硬件读回。单个 StreamDevice 协议的错误状态可能只标明协议级错误，不能保证指出具体失败命令；界面应显示该错误并使用各 `_RBV` 判断哪些设定已生效。只有整组命令发完且读回满足预期时才报告 `Done`。

### 日志 PV

日志 PV 只控制/报告 Python Web 仪表盘内的归档组件状态，不表示 IOC 自己创建 CSV 文件。

| PV | 方向 | 行为 |
|---|---|---|
| `LOG:START` | 写命令 | 开始归档并开启一个会话；立即写首行 |
| `LOG:PAUSE` | 写命令 | 暂停追加记录，保留当前文件 |
| `LOG:RESUME` | 写命令 | 从当前文件继续记录 |
| `LOG:NEW_FILE` | 写命令 | 建立新文件并继续记录 |
| `LOG:STATE_RBV` | 读 | `Stopped`、`Recording`、`Paused` 或 `Error` |
| `LOG:FILE_RBV` | 读 | 当前 CSV 文件名 |
| `LOG:ROWS_RBV` | 读 | 已写数据行数 |
| `LOG:LAST_WRITE_RBV` | 读 | 最近一次写入时间（Asia/Shanghai） |
| `LOG:ERROR_RBV` | 读 | 最近一次归档错误；正常时为空 |
| `LOG:HEARTBEAT` | 写/读回 | Python 归档组件周期更新，用于识别归档服务失联 |

归档器以 2 秒间隔采样，和当前仪表盘自动刷新周期保持一致；点击连接/开始后立即采一行。CSV 继续使用当前字段顺序：`timestamp_local`、`cold_head_K`、`sample_K`、`input_a_K`、`input_b_K`、`input_c_K`、`input_d_K`、`setpoint_K`、`ramp_enable`、`ramp_rate_K_per_min`、`heater_range`、`heater_percent`、`pid_p`、`pid_i`、`pid_d`、`comm`、`stable_state`。时间使用 Asia/Shanghai；稳定判定继续使用 Sample 与设定值相差不超过 0.2 K 的规则。

每日文件名、手动新文件后缀、元数据 JSON、会话记录、暂停/继续/新文件操作记录、PID 旧值/新值审计和下载行为继续保留。元数据中的设备连接信息改为 IOC PV 前缀/连接模式，不再声称 Python 直接打开串口。

归档器不能把断连时保留的旧 PV 值伪装成新数据。采样行应根据 IOC 的 `COMM:STATUS`、各 PV alarm 和读数时间判断有效性；无效读数按现有 CSV 格式写空值或通信状态，并在归档状态中报告问题。归档进程断开时，心跳应停止更新，仪表盘显示归档器不可用。

## 校验、维护和权限

- 保留现有控制范围：设定值 0–350 K、斜率 0–10 K/min、量程 Off/Low/Medium/High、输入 A-D。
- 无效写入必须在发送串口命令前拒绝。
- PID 写入按 Model 336 `PID` 命令范围限制：P 0.1–1000、I 0.1–1000、D 0–200；不沿用 Python 当前 `0..10000` 的过宽界限。维护界面仍保留登录、二次确认、读前/写后读回和旧/新值审计。
- 正常控制、PID 维护、日志命令和归档状态写回分别使用 `CONTROL`、`MAINT`、`LOG_CONTROL`、`ARCHIVER` 四个 EPICS Access Security 组。将 ACF 加入 IOC 启动配置；未配置权限规则时不能开放控制写入。
- Python 维护登录不能代替 CA 网络访问控制。部署时由实验室 EPICS 网络/网关和 ACF 明确哪些客户端可操作；其他控制系统需要通过批准的控制组访问可写 PV。
- IOC 启动仍只发查询，不恢复或写入保存的控制值。

PID 范围依据：[Lake Shore Model 336 用户手册](https://www.lakeshore.com/docs/default-source/product-downloads/336manual.pdf)，命令摘要中的 P/I/D 范围分别为 0.1–1000、0.1–1000 和 0–200。

## 通信和跨系统连接

此版本以 Channel Access 为公共接口，与当前 IOC 依赖和既有 PV 保持一致。同网段客户端按 EPICS CA 自动发现连接；跨网段时由部署方配置 `EPICS_CA_ADDR_LIST` 或 EPICS Gateway。PVA、额外软 IOC、Windows/Linux 生产部署形态以及以太网仪器传输不在本次功能对齐范围内。

## 验收条件

1. IOC 启动只查询，不写入设定值、ramp、量程、输入或 PID。
2. Python 仪表盘在 EPICS 模式下可读所有现有状态 PV，并完成输入、设定值、斜率、量程、整组 APPLY 和维护 PID 操作；真实硬件串口只由 IOC 打开。
3. APPLY 顺序及节奏与已验证 Python 控制程序一致；非法请求不会发送任何一条控制命令；失败时显示协议错误和部分执行状态，并能查看各项实际读回。
4. 每个写入都能通过独立 `_RBV` 验证；写入请求值和实际读回不符时界面提示差异。
5. Python 归档器按 2 秒周期从 IOC PV 写 CSV，保持既有列名/顺序、Asia/Shanghai 时间、稳定状态算法、每日文件和元数据行为。
6. 日志启动、暂停、继续、新文件命令经 PV 生效，状态、当前文件、行数、最后写入时间、错误和心跳可见；归档器退出后能识别为失联。
7. PID 维护写入受保护，并记录操作时间、旧值、新值；普通控制组不能写 PID 维护 PV。
8. EPICS Access Security 在真实控制写入启用前配置并确认；跨网段客户端按实际网络/网关配置连接。
9. 在实验批准的安全条件下，通过实机确认 `CSET` 写入及 `OUTMODE? 1` 读回一致，确认整组 APPLY 的硬件结果与原 Python 操作一致。

## 尚待实施阶段落实的细节

- 新 PV 的 record 类型及命令确认/复位语义。
- `aSub` 负责验证和快照；StreamDevice 在同一 asyn 串口事务中执行命令并将查询结果写入权威读回 PV。
- ACF 的操作组、维护组、日志控制组、归档服务组及部署主机名单。
- 归档 PV 的时间戳表示和 CA 客户端对读数 alarm/stale 状态的判定阈值。
- 按现场仪器手册版本复核 PID 范围 P 0.1–1000、I 0.1–1000、D 0–200。

以上细节不改变已选架构和 Python 功能对齐目标，但应在实施计划中给出明确决定。
