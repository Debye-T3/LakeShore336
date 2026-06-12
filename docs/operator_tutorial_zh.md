# Lake Shore 336 ARPES 温控面板使用教程

这份教程给实验室使用者看。目标是：能打开面板、看温度、连接真实 Lake Shore 336、设置安全升温，并知道哪些功能只是演示，哪些会真的控制仪器。

## 1. 先分清两种页面

### Vercel 公开网站

Vercel 网站适合给别人预览界面、测试按钮、看中文/英文切换和 Demo 数据。

重要：Vercel 不能直接连接实验室仪器，也不能控制真实温控器。浏览器网页没有权限直接访问办公室电脑上的 COM 口。

### 本地控制页面

真实控制 Lake Shore 336 时，必须在连接着仪器的那台电脑上运行本地服务，然后打开：

```text
http://127.0.0.1:8765
```

只有这个本地页面可以连接串口并读写仪器。

## 2. Windows 电脑怎么启动

办公室电脑如果只能用 Windows，不需要 Linux，也不需要 WSL。

最友好的方式是双击项目文件夹里的：

```text
START_WINDOWS_DASHBOARD.bat
```

它会自动检查 Python、安装需要的串口库、启动本地网页面板，并打开：

```text
http://127.0.0.1:8765
```

使用面板时，不要关闭弹出来的黑色命令窗口。实验结束后，可以在那个窗口里按 `Ctrl+C` 停止服务。

如果想手动运行，也可以先安装 Python 3，然后打开 PowerShell，进入项目目录：

```powershell
cd LakeShore336
```

第一次使用需要安装串口库：

```powershell
python -m pip install -r requirements.txt
```

启动网页面板：

```powershell
python scripts\ls336_web_dashboard.py
```

PowerShell 里会显示一个地址。通常是：

```text
http://127.0.0.1:8765
```

用浏览器打开这个地址。

## 3. Mac 电脑怎么启动

在 Terminal 里进入项目目录：

```bash
cd /Users/cocoyou/LakeShore336
```

安装串口库：

```bash
python3 -m pip install pyserial
```

启动面板：

```bash
python3 scripts/ls336_web_dashboard.py
```

然后打开：

```text
http://127.0.0.1:8765
```

## 4. Demo 测试

如果只是想确认界面能跑，不要连接真实仪器。

1. 右上角端口选择 `DEMO`。
2. 点击 `CONNECT`。
3. 左边应该显示 `CONNECTED`。
4. Cold Head Temp 和 Sample Stage Temp 会出现虚拟温度。
5. 曲线图会开始画出冷头和样品温度趋势。

Demo 模式不会控制任何真实设备，可以放心测试。

## 5. 连接真实 Lake Shore 336

先把 Lake Shore 336 用 USB/串口线接到电脑。

刷新页面后，右上角端口列表里应该出现真实串口。

Windows 常见端口名：

```text
COM3
COM4
COM5
```

Mac 常见端口名：

```text
/dev/cu.usbserial-xxxx
/dev/cu.usbmodem-xxxx
```

不要选明显像蓝牙的端口，例如：

```text
/dev/cu.BLTH
```

连接步骤：

1. 选择真实端口。
2. 点击 `CONNECT`。
3. 如果成功，状态会变成 `CONNECTED`。
4. Cold Head Temp 和 Sample Stage Temp 会显示真实温度。

连接后，面板会自动刷新温度，不需要一直点 `READ`。

## 6. 面板上的主要参数是什么意思

### Cold Head Temp

冷头温度。通常对应 Lake Shore 的 A 通道。

### Sample Stage Temp

样品台温度。通常对应 Lake Shore 的 B 通道。ARPES 实验中更应该关注这个读数。

### Setpoint

目标温度，单位 K。

第一次测试真实仪器时，不要一下设很远。建议只比当前温度高 `2 K` 到 `5 K`。

### Ramp

升温速率，单位 K/min。

建议第一次用：

```text
0.2 或 0.5 K/min
```

### Heater Range

加热档位，用来控制加热能力：

| 档位 | 含义 | 建议 |
| --- | --- | --- |
| Off | 关闭加热 | 停止加热或安全状态 |
| Low | 低档 | 第一次真实测试推荐 |
| Medium | 中档 | 确认系统稳定后再用 |
| High | 高档 | 只在实验负责人确认后使用 |

### PID

PID 是 Lake Shore 的控温逻辑参数：

| 参数 | 作用 |
| --- | --- |
| P | 对温差的直接响应强度 |
| I | 长时间误差修正 |
| D | 抑制过快变化或过冲 |

如果实验室已有推荐 PID，使用实验室参数。没有确认前，不建议随意大幅修改 PID。

## 7. 第一次真实升温建议流程

先只读温度，不要马上控制。

确认读数正常后：

1. 看当前 Sample Stage Temp，比如 `60 K`。
2. Setpoint 设成 `62 K` 或 `65 K`。
3. Ramp 设成 `0.2` 或 `0.5`。
4. Heater Range 选 `Low`。
5. PID 先保持默认值或实验室推荐值。
6. 点击 `APPLY`。
7. 观察温度曲线是否平稳上升。

如果温度上升太快、过冲明显、或者 heater 输出长期接近 100%，先点 `OFF`，再检查参数。

## 8. 节奏升温怎么用

节奏升温适合一点一点升，例如每次升 `5 K` 或 `10 K`。

参数：

- `Step K`: 每一步增加多少 K。
- `Rhythm min`: 每隔几分钟自动前进一步。
- `Stable ±K`: 判断接近目标温度的容差。

手动一步：

1. `Step K` 填 `5`。
2. 点击 `STEP`。
3. Setpoint 会增加 `5 K`。

自动节奏：

1. `Step K` 填 `5`。
2. `Rhythm min` 填 `5` 或更长。
3. 点击 `START RHYTHM`。
4. 需要停止时再点一次。

真实仪器第一次测试时，不要把 `Rhythm min` 设得太短。

## 9. CSV 记录

点击 `LOG` 后，面板会记录读数。

点击 `CSV` 可以下载数据文件：

```text
ls336_arpes_log.csv
```

CSV 里包含：

- 时间
- Cold Head 温度
- Sample 温度
- Setpoint
- Ramp
- Heater Range
- Heater 输出
- PID

## 10. 常见问题

### 页面里只有 DEMO，没有 COM 口

检查：

- Lake Shore 是否真的插在这台电脑上。
- USB 线是不是数据线。
- Windows 设备管理器里有没有 `Ports (COM & LPT)`。
- 是否需要 USB-serial 驱动。

### 点 CONNECT 后失败

常见原因：

- 选错端口。
- 端口被别的软件占用。
- 串口设置和仪器不匹配。
- 仪器没有回复。

把页面底部 log 里的错误信息发给维护者。

### 温度一直是 `-- K`

说明还没有成功读到仪器。

先用 `DEMO` 确认页面正常，再换真实 COM 口。

### Vercel 页面能不能控制仪器

不能。Vercel 页面只能演示。

真实控制必须在插着 Lake Shore 的电脑上运行本地服务。

## 11. 安全提醒

- 第一次真实测试用 `Low` heater range。
- 第一次 setpoint 只比当前温度高几 K。
- Ramp 不要太大，建议从 `0.2` 或 `0.5 K/min` 开始。
- PID 不要随便大幅改。
- 如果不确定，先点 `OFF`。
- 不要把真实控制页面暴露到公网。
