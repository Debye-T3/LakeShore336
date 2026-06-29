# Lake Shore 336 ARPES 温控面板使用教程

这份教程给实验室使用者看。目标是：能打开本地面板、读取温度、连接真实 Lake Shore 336、设置安全升温，并把温度记录保存成可归档的 CSV 文件。

## 1. 页面类型

### 本地控制页面

真实控制 Lake Shore 336 时，必须在连接着仪器的电脑上运行本地服务，然后打开：

```text
http://127.0.0.1:8765
```

只有本地页面可以访问电脑上的 COM 口并读写仪器。

### 公开 Demo 页面

Vercel 或静态网页只适合预览界面和测试 Demo 数据。它不能连接实验室仪器，也不能控制真实温控器。静态页面里的 CSV 下载只是浏览器临时数据，不会生成可归档的本地日志文件。

## 2. Windows 启动

最简单的方式是在项目文件夹中双击：

```text
START_WINDOWS_DASHBOARD.bat
```

它会检查 Python、安装串口依赖、启动本地网页服务，并打开：

```text
http://127.0.0.1:8765
```

手动运行时，可以在 PowerShell 中执行：

```powershell
python -m pip install -r requirements.txt
python scripts\ls336_web_dashboard.py
```

## 3. 连接真实 Lake Shore 336

1. 用 USB/串口线把 Lake Shore 336 接到电脑。
2. 刷新本地页面，端口列表里应出现真实串口，例如 `COM3`、`COM4`。
3. 选择真实端口，不要选择 `DEMO`。
4. 点击 `CONNECT`。
5. 确认 Cold Head Temp 和 Sample Stage Temp 出现真实读数。

如果只是测试界面，请选择 `DEMO`。Demo 模式不会控制任何真实设备。

## 4. 主要参数

- Cold Head Temp：冷头温度，通常对应 Lake Shore 的 A 通道。
- Sample Stage Temp：样品台温度，通常对应 B 通道，实验中更应该关注这个读数。
- Setpoint：Loop 1 目标温度，单位 K。
- Ramp：升温速率，单位 K/min。
- Heater Range：加热档位，首次真实测试建议从 `Low` 开始。
- PID：普通实验页面只读取仪器当前 PID；PID 写入只在维护页面中开放。

## 5. 安全升温建议

第一次真实测试时，不要一次设置很远的目标温度。

推荐流程：

1. 先只连接并读取温度。
2. 确认读数正常后，把 Setpoint 设为比当前样品温度高 `2 K` 到 `5 K`。
3. Ramp 设为 `0.2` 或 `0.5 K/min`。
4. Heater Range 选 `Low`。
5. 点击 `APPLY`。
6. 观察温度曲线是否平稳上升。

如果温度上升过快、明显过冲，或 heater 输出长期接近 100%，先点击 `OFF`，再检查参数。

## 6. 温度日志归档

本地网页服务支持自动归档温度记录。连接成功后会自动开始记录，实验用户不需要点击开始，也不能在普通页面停止记录。

使用方式：

1. 连接 `DEMO` 或真实仪器。
2. 确认记录状态显示为 `ON`。
3. 保持本地 Python 服务运行，面板会随自动刷新持续写入数据。
4. 点击 `DOWNLOAD CSV` 下载当前 CSV。

归档文件默认保存在项目目录下：

```text
logs/
```

默认按北京时间每天创建两个文件：

```text
ls336_temperature_YYYYMMDD.csv
ls336_temperature_YYYYMMDD.meta.json
```

CSV 包含：

- UTC ISO 时间
- 本地时间
- 冷头温度
- 样品温度
- A/B/C/D 通道温度
- Setpoint
- Ramp 开关和 ramp rate
- Heater range
- Heater 输出
- PID 读回值
- 通信状态
- 稳定状态

`.meta.json` 记录连接 session、端口、模式、CSV 字段、项目路径和维护操作，方便后续归档。

CSV 里的 `timestamp_local` 和 metadata 里的本地时间都使用北京时间 `Asia/Shanghai`。

## 7. 维护页面

维护页面地址：

```text
http://127.0.0.1:8765/maintenance
```

维护页面需要密码。正式使用前建议在启动本地服务前设置：

```powershell
$env:LS336_MAINT_PASSWORD="your-password"
python scripts\ls336_web_dashboard.py
```

如果没有设置环境变量，默认维护密码是：

```text
ls336-maint
```

维护页面可以执行：

- 暂停/恢复记录
- 强制新建当前日期的日志文件
- 下载当前 CSV
- 读取 PID
- 受控写入 PID

PID 写入属于高风险维护操作。写入前页面会要求确认，写入后旧值和新值会记录到 `.meta.json` 的审计记录中。

## 8. 常见问题

### 页面里只有 DEMO，没有 COM 口

检查：

- Lake Shore 是否接在这台电脑上。
- USB 线是否是数据线。
- Windows 设备管理器里是否有 `Ports (COM & LPT)`。
- 串口是否被其他软件占用。

### 点击 CONNECT 后失败

常见原因：

- 选错端口。
- 端口被别的软件占用。
- 串口设置和仪器不匹配。
- 仪器没有回复。

### CSV 没有写入

真实归档只在本地 Python 服务页面中可用。Vercel 或直接打开 `web/index.html` 的静态页面只能下载浏览器临时 CSV，不能写入 `logs/`。

如果本地页面显示记录错误，通常是 `logs/` 目录不可写或磁盘空间不足。请把页面中的错误信息发给维护人员。

## 9. 安全提醒

- 第一次真实测试用 `Low` heater range。
- 第一次 setpoint 只比当前样品温度高几 K。
- Ramp 建议从 `0.2` 或 `0.5 K/min` 开始。
- PID 只能由维护人员在维护页面或仪器本机按实验室流程调整。
- 不要把真实控制页面暴露到公网。
