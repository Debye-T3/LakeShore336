# Lake Shore 336 IOC 网页控制软件部署说明

## 运行条件

- 64 位 Windows 10 或 Windows 11。
- 目标电脑无需安装 Python，也无需访问互联网。
- 目标电脑必须通过实验室网络访问一个正在运行的 EPICS IOC。
- IOC 主机独占 Lake Shore 336 串口；Windows 网页程序通过 Channel Access 连接 IOC。
- 每台 IOC 只运行一个负责 CSV 归档的 Python 服务，避免多个服务同时写同一组归档状态 PV。
- 现场 EPICS 管理员已按最小权限配置 CA 用户/主机规则。IOC 自带的 `access.acf` 默认只读；部署时在对应 `ASG` 添加受 `UAG` 和 `HAG` 限制的写规则，语法见 [EPICS ACF 文档](https://docs.epics-controls.org/projects/base/en/latest/ACF-Language.html)。

“离线”表示目标 Windows 电脑不需要互联网；它仍需要到 IOC 的网络通路。默认同一子网使用 CA 搜索，跨子网需要站点配置 CA 地址列表或 Gateway。

## 启动

1. 在 IOC 主机上先启动 IOC，并确认 PV 前缀及读回正常。
2. 将 `LakeShore336_portable.zip` 复制到 Windows 电脑并完整解压。
3. 如 IOC 前缀不是 `LS336:`，在启动前设置 `LS336_PREFIX`；也可以在网页顶部直接修改前缀。
4. 双击 `START.bat`。
5. 在这台电脑打开 `http://127.0.0.1:8765`，输入 IOC 前缀并点 `Connect`。
6. 核对 IDN、A/B/C/D 温度、控制输入和各项 `_RBV`。

首次检查可以将前缀输入为 `DEMO`，测试模拟数据与界面。DEMO 不连接真实 IOC，也不控制仪器。

在命令提示符中设置非默认前缀的例子：

```bat
set LS336_PREFIX=LS336_DEV:
START.bat
```

## 控制与权限

- IOC 必须先启动；网页程序不打开 COM 口。
- 整组 `APPLY SETTINGS` 由 IOC 按 CSET、RANGE、RAMP、SETP 的顺序执行，随后网页核对实际读回。
- PID 写入只在维护页面执行，要求网页维护登录、二次确认和 EPICS `MAINT` 写权限。
- 日志命令通过 `LOG:*` PV 发送；Python 服务必须具有 `LOG_CONTROL` 和 `ARCHIVER` 写权限。
- 常规控制使用 `CONTROL` 权限。不要用宽泛规则向所有 CA 客户端开放写权限。
- 如果能读不能写，请联系 EPICS 管理员确认所用 CA 用户/主机在正确权限组中。
- 网页默认只允许本机浏览器连接。远程浏览器访问需另行配置 HTTP 身份认证和网络限制；远程控制系统也可以按 ACF 规则直接连接 IOC PV。

第一次真实操作遵守现场安全流程，使用现场确认的目标、低 Heater Range 和低 Ramp；检查读回及仪器面板后再继续。软件范围限制不能替代硬件联锁。

## 温度日志

连接 IOC 后，Python 服务立即开始一个 session 并写入首行，此后每 2 秒写入 CSV。浏览器关闭不会停止归档；关闭 Python 服务才会停止心跳。

日志保存在解压目录下的 `logs\`：

- `ls336_temperature_YYYYMMDD.csv`
- `ls336_temperature_YYYYMMDD.meta.json`

时间使用北京时间 `Asia/Shanghai`。CSV 字段顺序与网页版本一致；超过有效时间或带 EPICS alarm 的读数留空。页面显示当前文件、行数、最近写入时间和心跳状态。

IOC 归档 PV 包含 `LOG:START`、`PAUSE`、`RESUME`、`NEW_FILE` 命令，以及 `STATE_RBV`、`FILE_RBV`、`ROWS_RBV`、`LAST_WRITE_RBV`、`ERROR_RBV`、`HEARTBEAT` 状态。日志命令执行后由 Python 服务清零；命令 PV 回到 `0` 后再发下一次脉冲。

## 维护页面

维护页面地址为 `http://127.0.0.1:8765/maintenance`。正式使用前在 Windows 中配置 `LS336_MAINT_PASSWORD`。未设置时默认密码为 `ls336-maint`。

维护页可暂停/恢复归档、创建手动新文件、下载 CSV 和提交 PID。PID 范围为 P `0.1..1000`、I `0.1..1000`、D `0..200`；写入前需确认，旧值/新值会写入 metadata。

## 直接串口备用程序

便携包只包含 IOC-backed 网页客户端。仓库中的 `scripts/ls336_direct_dashboard.py` 是独立串口备用程序，只能在 IOC 停止时运行；同一台仪器不能同时由 IOC 和直接串口程序控制。

## 常见问题

- **连接超时：**确认 IOC 已运行、PV 前缀正确，并检查 CA 搜索/地址列表/Gateway 网络配置。
- **读得到但写不了：**默认 ACF 只读，联系 EPICS 管理员配置正确的最小写权限。
- **归档心跳停止：**确认 `START.bat` 启动的 Python 服务仍运行，检查页面错误、`LOG:ERROR_RBV` 和目录可写性。
- **日志字段为空：**对应 PV 可能 stale 或处于 alarm；检查 IOC communication 状态和该 PV 的时间戳/alarm。
- **需要独立直连：**先停止 IOC，再使用仓库中的 direct-serial 备用程序，不要同时打开同一仪器串口。
