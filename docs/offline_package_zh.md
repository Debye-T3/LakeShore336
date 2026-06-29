# Lake Shore 336 离线控制软件使用说明

## 运行条件

- 64 位 Windows 10 或 Windows 11。
- 目标电脑不需要联网，不需要安装 Python，也不需要 WSL。
- Windows 必须能够把 Lake Shore 336 识别为 `COM` 串口。若设备管理器没有出现串口，需要先安装仪器对应的 USB 串口驱动。

## 启动

1. 将 `LakeShore336_portable.zip` 复制到目标电脑。
2. 完整解压 ZIP，不要直接在压缩包中运行。
3. 双击 `START.bat`。
4. 浏览器会打开 `http://127.0.0.1:8765`。
5. 首次检查先选择 `DEMO`，点击 `CONNECT`，确认温度、设温和日志状态能够更新。

软件运行期间不要关闭黑色命令窗口。需要退出时，在该窗口按 `Ctrl+C`。

## 第二次联机测试

1. 确认 Lake Shore 336 面板处于安全状态，heater range 建议先保持 `Off`。
2. 用 USB/串口线连接仪器，在 Windows 设备管理器中记下端口号，例如 `COM4`。
3. 关闭 Lake Shore 官方软件及其他可能占用串口的程序。
4. 启动本软件，在端口列表选择对应的 `COM` 端口，点击 `CONNECT`。
5. 核对仪器型号、A/B/C/D 温度、当前 setpoint、ramp、heater range 和 heater output。
6. 根据实际接线选择 cold-head、sample 和 control input，点击通道设置。
7. 首次控制测试使用现场负责人确认的安全目标值。建议先将 heater range 保持 `Off`，设置较小 ramp，然后点击 `APPLY SETTINGS`。
8. 核对网页回读值与仪器面板一致后，才由线站负责人决定是否打开 `Low` heater range 进行真实升温。
9. 测试结束时将 heater range 设为 `Off`，并再次确认仪器面板。

软件限制 setpoint 为 `0..350 K`，ramp rate 为 `0..10 K/min`。软件限制不能替代线站的硬件联锁和实验安全流程。

## 温度日志

连接成功后会自动记录，不需要实验用户点击开始按钮。日志位于软件目录内的 `logs\`：

- `ls336_temperature_YYYYMMDD.csv`
- `ls336_temperature_YYYYMMDD.meta.json`

日期和 `timestamp_local` 使用北京时间 `Asia/Shanghai`，带 `+08:00` 时区偏移；`timestamp_iso` 保留 UTC，便于跨系统交换。

## 维护页面

维护页面地址为 `http://127.0.0.1:8765/maintenance`。生产使用前应在启动软件前设置环境变量 `LS336_MAINT_PASSWORD`。如果没有设置，默认密码为 `ls336-maint`。

维护页面可暂停/恢复日志并写入 PID。PID 写入属于高风险维护操作，必须由线站维护人员执行。

## 常见问题

- 找不到 `COM` 端口：检查 USB 驱动、线缆和设备管理器。
- 连接失败：关闭 Lake Shore 官方软件，避免串口被其他程序占用。
- 页面打不开：确认黑色命令窗口仍在运行，并检查 8765 端口是否被其他程序占用。
- CSV 没有增加：查看页面中的 Recording 状态和错误提示，确认软件目录可写。
