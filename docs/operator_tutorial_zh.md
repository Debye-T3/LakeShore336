# Lake Shore 336 EPICS 温控面板使用教程

本教程说明如何通过 EPICS IOC 使用温控面板、调整 Loop 1 参数和保存温度日志。真实仪器的串口只由 IOC 打开；Python 网页程序通过 Channel Access 读写 IOC PV，并负责 CSV 归档。

## 1. 启动顺序

1. 在连接着 Lake Shore 336 串口的 Linux/WSL 主机上启动 IOC。
2. 确认 IOC 发布的 PV 前缀，例如 `LS336:`，并确认基本读回正常。
3. 在指定的一台 Windows、Linux 或 macOS 主机上启动 Python 网页程序；每台 IOC 只运行一个负责 CSV 的归档服务。
4. 在该主机的浏览器输入同一个 IOC 前缀，点击 `Connect`。

网页默认只绑定本机地址 `127.0.0.1`，使用 `http://127.0.0.1:8765` 打开。网页默认使用 `LS336:`。启动程序前也可以设置 `LS336_PREFIX`，或使用 `--prefix LS336_DEV:`。在网页输入 `DEMO` 可使用模拟器，无需连接 IOC。

其他获授权的 EPICS 控制系统可按 ACF 规则直接访问 IOC。网页远程访问时，浏览器请求会使用网页服务的 CA 身份；只有在现场另行配置 HTTP 身份认证和网络限制后，才开放远程网页访问。

默认 `access.acf` 只允许读取。现场 EPICS 管理员应在 ACF 中定义站点自己的 `UAG` 用户组和 `HAG` 主机组，并仅在对应 `ASG` 中增加带有这两个限制的 `RULE(1,WRITE)`；保留 `RULE(1,READ)` 供监视。归档服务用户需要同时属于 `LOG_CONTROL` 和 `ARCHIVER` 授权范围。跨子网访问需要配置 CA 地址列表或 EPICS Gateway；不要在通用配置中开放所有主机写权限。语法请参考 [EPICS ACF 文档](https://docs.epics-controls.org/projects/base/en/latest/ACF-Language.html)。

规则结构示例（部署时必须换成站点批准的用户名和主机名/IP，并分别配置所需 ASG）：

```text
UAG(LS336_CONTROL_USERS) {replace_with_site_ca_user}
HAG(LS336_CONTROL_HOSTS) {replace_with_approved_host}
ASG(CONTROL) {
    RULE(1, READ)
    RULE(1, WRITE) {
        UAG(LS336_CONTROL_USERS)
        HAG(LS336_CONTROL_HOSTS)
    }
}
```

## 2. Windows 启动

在项目文件夹双击：

```text
START_WINDOWS_DASHBOARD.bat
```

或手动运行：

```powershell
python -m pip install -r requirements.txt
python scripts\ls336_web_dashboard.py --prefix LS336:
```

网页默认地址为 `http://127.0.0.1:8765`。如果 IOC 使用其他前缀，请在命令中替换，或在启动前设置：

```powershell
$env:LS336_PREFIX="LS336_DEV:"
python scripts\ls336_web_dashboard.py
```

## 3. 读取和输入通道

连接后确认仪器型号、A/B/C/D 温度、Loop 1 输入、设定值、Ramp、Heater Range 和 Heater Output 均显示合理数值。通信状态应为 `Connected`。

- `Cold Input Channel` 和 `Sample Input Channel` 仅决定网页的冷头/样品显示与 CSV 字段映射。
- `Control Input Channel` 会修改仪器 Loop 1 控制输入，并与 `LS336:Loop1:INPUT_RBV` 的 `OUTMODE? 1` 读回对应。
- 直接 IOC 命令 `Loop1:INPUT` 与整组 APPLY 暂存 PV `Loop1:CTRL:INPUT` 都使用整数代码 `1=A`、`2=B`、`3=C`、`4=D`；小数或超范围代码会在串口命令前被拒绝。
- `_RBV` 是实际读回值的权威来源。收到 PV 写入成功并不代表仪器已经达到目标值。

## 4. 设置温度

整组 `Apply Settings` 会先把输入通道、设定值、Ramp 速率和 Heater Range 暂存到 IOC，再触发一次校验后的 `Loop1:CTRL:APPLY`。IOC 按 `CSET → RANGE → RAMP → SETP` 顺序执行，并在命令后查询读回。

IOC 的 `Loop1:CTRL:INPUT` 暂存值使用整数代码 `1=A`、`2=B`、`3=C`、`4=D`；`Loop1:CTRL:RANGE` 使用 `0=Off`、`1=Low`、`2=Medium`、`3=High`。小数或超范围代码会在串口命令前被拒绝。

IOC 提供下列状态：

- `LS336:Loop1:CTRL:BUSY`：操作是否进行中。
- `LS336:Loop1:CTRL:STATUS`：`Idle`、`Busy`、`Done`、`PartialFailure` 或 `Error`。
- `LS336:Loop1:CTRL:ERROR`：协议失败或读回不一致的摘要。

若出现 `PartialFailure` 或 `Error`，先查看实际 `_RBV`，不要假设参数已回滚。单独调整设定值和 Ramp 时，网页会通过 `Loop1:RAMP:ENABLE`、`Loop1:RAMP:RATE`、`Loop1:SETP` 命令 PV 操作，并检查对应读回。

第一次真实控制时按现场负责人要求设置安全值；通常先选 `Off` 或 `Low`，设小幅目标变化和较低 Ramp，观察实际读回与温度曲线后再继续。

## 5. PID 维护

普通控制页面可读取 PID。维护页面地址为 `http://127.0.0.1:8765/maintenance`，使用前设置 `LS336_MAINT_PASSWORD`；默认密码为 `ls336-maint`。

PID 写入需要登录和网页二次确认。IOC 将 P/I/D 暂存后通过一次 `Loop1:PID:APPLY` 提交，范围为 P `0.1..1000`、I `0.1..1000`、D `0..200`。IOC 提供 `PID:STATUS`、`PID:ERROR` 和最近一次写入前的 `PID:P_OLD_RBV`、`I_OLD_RBV`、`D_OLD_RBV`。Python 维护页把旧值、新值和时间写入 metadata 审计记录。

维护登录是网页层保护；还必须由 EPICS Access Security 授予该用户 `MAINT` 写权限。

## 6. CSV 日志

成功连接 IOC 后，Python 归档线程立即创建/续写当天文件并写首行，此后每 2 秒写一行，不依赖浏览器刷新。日志保存在项目目录的 `logs/`：

```text
ls336_temperature_YYYYMMDD.csv
ls336_temperature_YYYYMMDD.meta.json
```

日期和 `timestamp_local` 使用北京时间 `Asia/Shanghai`。CSV 字段顺序保留原有格式，包括冷头、样品、A/B/C/D 温度、设定值、Ramp、Heater Range、Heater 输出、PID、通信状态和稳定状态。稳定状态仍按样品温度与设定值相差不超过 `0.2 K` 判断。

归档器按 CA 时间戳和 EPICS alarm 判断字段有效性。温度及常规读回超过 6 秒、PID 超过 22 秒或有 alarm 时，相应 CSV 字段留空，不把旧读数伪装成新测量。PID 的较长有效期对应 IOC 的 10 秒 PID 扫描周期。

网页显示文件名、行数、最近写入时间和归档状态。`HEARTBEAT LOST` 表示 IOC 上的 `LOG:HEARTBEAT` 停止变化；应确认 Python 服务仍在运行并检查 `LOG:ERROR_RBV`。点击 `DOWNLOAD CSV` 可下载当前文件。

其他获授权的 EPICS 客户端也能操作归档：

- `LS336:LOG:START`：开始新 session 并立即写一行。
- `LS336:LOG:PAUSE`、`LS336:LOG:RESUME`：暂停或恢复追加。
- `LS336:LOG:NEW_FILE`：创建当天带手动后缀的新文件并继续记录。
- `LS336:LOG:STATE_RBV`、`FILE_RBV`、`ROWS_RBV`、`LAST_WRITE_RBV`、`ERROR_RBV`：归档状态。
- `LS336:LOG:HEARTBEAT`：由 Python 服务周期更新。

归档器会在处理完命令后把命令 PV 复位到 `0`；该 PV 回到 `0` 前不要重复脉冲。日志文件操作保留 session 和操作记录，PID 维护写入会保留旧值/新值审计。

归档器的 EPICS 用户需要 `ARCHIVER` 写权限，并需要 `LOG_CONTROL` 权限来确认日志命令。日常硬件控制使用 `CONTROL`，PID 维护使用 `MAINT`。

## 7. 直接串口备用程序

`scripts/ls336_direct_dashboard.py` 是单独的串口程序，只能在 IOC 已停止、确认串口未被其他进程占用时运行。不要让备用程序和 IOC 同时控制同一台仪器。

## 8. 常见问题

### 页面无法连接 IOC

- 确认 IOC 已启动，并核对网页前缀与 IOC 前缀完全一致。
- 确认 IOC 所在主机和网页主机之间可进行 CA 搜索；跨子网请联系 EPICS 管理员配置地址列表或 Gateway。
- 检查 IOC 的 PV 是否存在、`COMM:STATUS` 是否为 `Connected`，以及 IOC 串口是否可访问。

### 能读数但不能控制

默认 ACF 只开放读取。请让 EPICS 管理员为相应 CA 用户/主机配置 `CONTROL`、`MAINT`、`LOG_CONTROL` 和 `ARCHIVER` 的最小必要写权限。网页 PID 密码不能替代 EPICS 权限。

### 日志没有增加

检查 `LOG:STATE_RBV`、`LOG:ERROR_RBV` 和 `LOG:HEARTBEAT`。确认 Python 网页服务仍在运行、`logs/` 可写，并且归档器用户有 `ARCHIVER` 写权限。若某个读数超过有效期或有 alarm，该 CSV 单元格会留空。

### 需要公开演示

静态 `web/index.html` 可以模拟温度和控制界面，但不会连接真实仪器或本地 IOC。公开页面只用于 Demo。

## 9. 安全提醒

- 首次真实操作遵守线站的控制值和联锁流程，核对 `_RBV` 后再继续。
- 不要把 IOC 写权限、真实控制页面或串口暴露到公网。
- 直接串口备用程序启动前先停止 IOC。
