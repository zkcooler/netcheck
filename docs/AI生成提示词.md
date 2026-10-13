# AI 生成提示词：netcheck 同款 Windows 网络工具箱

> 用法：把下面"【开始 AI 提示词】"和"【结束】"之间的全部文字，复制粘贴到任意大语言模型（豆包 / 通义千问 / Qwen / DeepSeek / GPT / Claude / 智谱 GLM 等）的对话框，AI 就会按这个规格独立把 netcheck 同款软件做出来。**不需要再附其他说明**。

---

【开始 AI 提示词】

你是一名经验丰富的 Python 桌面应用工程师。现在请你**从零开始**为一个完全没有编程经验的初学者用户（代号 "dad"，只会用 Windows，想学编程）开发一个 **Windows 网络工具箱**。这份提示词描述的是**完整规格**，你必须严格按规格做完，不能只做一半。

## 1. 项目目标
做一个单文件 Python 桌面程序，名叫 `netcheck`，有 8 个功能标签页（顶部的 Tab 切换）。所有功能都跑在本机，用 Windows 自带命令 + Python 标准库 + 少量第三方库。每个 tab 独立工作，互不依赖。最终用 PyInstaller 打成单个 exe，发给朋友的 Windows 电脑双击就能用。

## 2. 技术栈（必须严格遵守）
- **语言**：Python 3.13（兼容 3.10+）
- **GUI 库**：PySide6（Qt 6.8+），**不要**用 tkinter 或 PyQt5
- **进程间命令**：subprocess.run / subprocess.Popen 跑 Windows 自带命令
- **网络请求**：用 `http.client`（标准库）做测速，**不要**用 requests / aiohttp
- **DNS**：dnspython（pip 包名 `dnspython`）
- **网络接口信息**：psutil（pip 包名 `psutil`）
- **并发**：concurrent.futures.ThreadPoolExecutor + threading
- **打包**：PyInstaller（`pyinstaller --noconfirm --onefile --windowed`）

## 3. 文件结构
**单文件交付**：`netcheck.py` 一份。所有 class、function、常量都放这一个文件（最多 ~3500 行）。最终：
```
netcheck.py             # 主程序
netcheck.ico            # 图标
README.md               # 简要使用说明
```

## 4. 窗口整体结构
主窗口 `QMainWindow`，标题栏写 `netcheck v1.0  ·  Windows 网络工具箱`，大小 1000×700 起步可调。中间是一个 `QTabWidget` 装着 8 个标签页，底部状态栏显示一行文字。

8 个标签页（从左到右顺序固定）：
1. **探测** —— Ping / TCPing / 二合一，支持网段格子图
2. **IP 配置** —— 跑 ipconfig /all，查看/释放/续约 IP
3. **路由追踪** —— 跑 tracert，实时流式输出每一跳
4. **ARP 缓存** —— 跑 arp -a，可删除单条
5. **网络连接** —— 跑 netstat -ano，进程名 + 多重筛选 + 导出 CSV
6. **端口扫描** —— 一台主机的常见端口开放情况
7. **DNS 查询** —— A/AAAA/MX/NS/TXT/SOA/SRV/CAA/ALL
8. **宽带测速** —— 延迟+抖动+下载+上传+档位评价+本机外网信息

## 5. 各 Tab 详细规格

### 5.1 探测（DetectTab）
- 顶部一行：目标输入框、模式（Ping/TCPing/二合一）下拉、端口、ping 次数、连续 Ping 复选框、间隔、开始/停止按钮
- 下面：堆叠的两个页：`QPlainTextEdit`（单主机日志）+ `QGroupBox + QGridLayout`（网段扫描格子图，每个 IP 一格，绿/黄/红/灰）
- 支持目标格式：单 IP、域名、`192.168.1.1-254`（范围）、`192.168.1.0/24`（CIDR）、`192.168.1.*`（通配符）
- 后台用 `QThread` 子类 `HostWorker` / `SegmentWorker`，主线程用信号刷新 UI
- 关键函数：`ping_once(host, timeout_ms) -> (ok, rtt)` 调 `subprocess.run(["ping","-n","1","-w",str(t),host])`，正则提取 `时间=Nms` 或 `time=Nms`
- 关键函数：`tcp_ping(host, port, timeout_ms) -> (ok, rtt, msg)` 调 `socket.getaddrinfo` + `socket.connect`

### 5.2 IP 配置（IpConfigTab）
- 一个"刷新"按钮 + 一个"刷新 DNS"按钮 + 两个"释放 IP" / "续约 IP"按钮（管理员）
- 一个 `QPlainTextEdit` 显示 `ipconfig /all` 输出
- 后台 `CmdWorker`（QThread 子类）跑命令，把 stdout 一行一行 `Signal` 出来
- 关键函数：`run_cmd(cmd, timeout)` 用 `subprocess.run(..., capture_output=True, timeout=...)`，GBK 解码
- "释放/续约"提示"需要管理员权限"

### 5.3 路由追踪（TracertTab）
- 目标输入 + 最大跳数下拉（8/15/30/64 默认 30） + 开始/停止
- 实时输出 tracert 每一跳
- 关键：`subprocess.Popen(["tracert","-d","-h",str(30),target], stdout=PIPE)`，逐行 `readline()` 用 `Signal(str)` 发主线程追加到 `QPlainTextEdit`
- 下面用一个 `QTableWidget` 同步每一跳：跳号 / RTT1 / RTT2 / RTT3 / 节点

### 5.4 ARP 缓存（ArpTab）
- 刷新按钮 + 表格显示 `IP / MAC / 类型 / 操作`
- 用正则 `re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+([\da-f-]{17})\s+(\w+)", text)` 解析 `arp -a` 输出
- "删除"按钮调 `arp -d 192.168.x.x`

### 5.5 网络连接（NetstatTab）
- 跑 `netstat -ano` 解析每行
- 列：协议 / 本地地址 / 远程地址 / 状态 / PID / 进程名
- 用 psutil 把 PID 翻译成进程名
- 顶部筛选行：协议下拉（全部/TCP/UDP）、状态下拉（全部/LISTENING/ESTABLISHED/...）、进程名搜索框、PID 搜索框
- 导出 CSV 按钮

### 5.6 端口扫描（PortScanTab）
- 目标主机输入 + 端口预设下拉（常用 80 个 / Web / 数据库 / 远程管理 / 邮件 / IoT）+ 自定义端口（`-`分隔，如 22,80,443 或 8000-8100）
- 并发数下拉 + 超时下拉
- 表格：端口 / 服务名 / 状态（开放/关闭/超时）/ 延迟 / 备注
- 后台 `PortScanWorker`：用 `ThreadPoolExecutor(max_workers=conc)` 并行，每条线程用 `socket.create_connection((host, port), timeout)` 试连

### 5.7 DNS 查询（DnsLookupTab）
- 目标输入 + 服务器输入（可空）+ 类型下拉（A/AAAA/MX/NS/TXT/SOA/SRV/CAA/CNAME/ALL）+ 开始
- 表格：类型 / 名称 / TTL / 值
- 上半用 dnspython 解析（程序化）
- 下半显示 `nslookup` 原始输出（参考）
- 后台 `DnsWorker`（QThread）：先 dnspython，再 nslookup，**最后才发 `done` 信号**（关键！）

### 5.8 宽带测速（SpeedTestTab）—— 最重要
- 上方一排参数：延迟包数（3/5/10/20）、下载时长（5/6/8/12 秒）、上传数据量（4/8/16/32 MB）
- ② 测速结果：两个并排卡片（国内蓝色 / 国外红色），每张卡片四个大数字（下载 / 上传 / 延迟 / 抖动）
- 进度条 + 阶段文字（"国内 延迟 1/3 QQ"） + 实时计时"已用 X.X s"
- 详细表格：区域 / 类型 / 节点 / 结果
- ③ 宽带评价：两个并排"档位"卡片（国内/国外）固定同高，显示"≡ 500M~千兆宽带" + 描述 + 适用场景
- ④ 本机外网信息：五栏（外网 IPv4 / 外网 IPv6 / 所在地 / 运营商 / ASN），启动测速时自动查
- 综合评语一行："你的网速相当于 500M~千兆宽带，典型用途：4K HDR / 10+ 设备..."
- 后台 `SpeedTestWorker`（QThread 子类）：

```python
SPEED_TEST_NODES = {
    "latency": {
        "国内": [("百度","www.baidu.com"), ("QQ","www.qq.com"),
                 ("淘宝","www.taobao.com"), ("阿里 DNS","223.5.5.5")],
        "国外": [("Cloudflare","one.one.one.one"), ("Google DNS","dns.google")],
    },
    "download": {
        "国内": [("清华镜像","https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/24.04.4/ubuntu-24.04.4-desktop-amd64.iso"),
                 ("北大镜像","https://mirrors.pku.edu.cn/ubuntu-releases/24.04.4/ubuntu-24.04.4-desktop-amd64.iso"),
                 ("哈工大镜像","https://mirrors.hit.edu.cn/ubuntu-releases/24.04.4/ubuntu-24.04.4-desktop-amd64.iso")],
        "国外": [("Cloudflare","https://speed.cloudflare.com/__down?bytes=52428800"),
                 ("OVH","https://proof.ovh.net/files/100Mb.dat")],
    },
    "upload": {
        "国内": [("华为云镜像","https://mirrors.huaweicloud.com/")],
        "国外": [("Cloudflare","https://speed.cloudflare.com/__up")],
    },
}
```

测速函数（必须按这个算法）：
```python
def http_download_speed(url, max_time=8.0, streams=4, skip_sec=2.0,
                        warmup_sec=3.0, max_bytes=400*1024*1024):
    """★ 多连接 + 稳态法 ★
    1) 多条线程同时 GET（默认 4 条），把单 TCP 限速绕开
    2) 跳过开头 2 秒（TCP 慢启动 + ISP 突发加速）
    3) 测之后 ~6 秒的稳态窗口
    4) 字节数最多 400MB 就停
    返回 (字节/秒, 总字节, 成功连接数)"""

def http_upload_speed(url, size_mb=8, max_time=25.0, warmup_sec=3.0):
    """★ 上传稳态法 ★
    分块 POST；跳过开头 warm_bytes（最多 4MB）后再计时；只有 2xx 才算
    """
```

## 6. 关键设计原则（必须遵守，违反会崩）

### 6.1 工人线程模式
所有耗时操作（跑命令、ping 整段、下载/上传、查 IP）都放 QThread 子类。**子线程里绝对不能直接动 UI**，只能 `Signal.emit()` 让主线程去动。

### 6.2 工人释放
每个 tab 类都有 `self.worker = None`。**绝对不能**在 `on_done` 回调里直接 `self.worker = None`，这会让 Qt 销毁正在运行的 QThread → 进程无声退出（这在别的电脑上随机发生）。必须用一个辅助函数 `retire_worker(self, "worker")` 把旧 worker 放进 `self._retired_workers = []` 托住引用，只释放已经 `isFinished()` 的。

### 6.3 全局异常兜底
在 `main()` 里调用 `install_excepthook("netcheck")`，把未捕获异常写日志并弹窗，避免进程无声退出。

### 6.4 子进程超时
- 单主机 Ping：超时 1.5s
- 下载/上传：连接阶段 ≤ 2.5s，否则快速失败
- 用 `http.client` 的两阶段超时：先 `HTTPSConnection(host, port, timeout=2.5).connect()`，连上后 `sock.settimeout(max_time)`。**不要用** `urlopen(timeout=10)`，会卡满 10 秒。

### 6.5 测速窗口
- 延迟用 `ThreadPoolExecutor` 并行（5 个节点同时 ping，从 ~20s 压到 ~5s）
- 节点间取**中位数**作为主结果（避免个别抽风节点拉偏）
- 上传默认 8MB，选 4/8/16/32
- 结果字符串要带括号标注测量过程，例如 `"52.5 MB/s = 441 Mbps（4连接稳态 / 共取 258 MB / 3.2s）"`

### 6.6 编码
- Windows cmd 输出是 **GBK**，用 `out.decode("gbk", "ignore")`
- 测速文件 GET 头加 `User-Agent: Mozilla/5.0 netcheck` 防止被 403
- nslookup 单独再跑一次拿原始输出（避免 dnspython 的中英文差异），**最后**才发 done 信号

### 6.7 IPv4 + IPv6 双栈
- 外网 IP 走两条独立线路：
  - IPv4：先 `ip-api.com/json/?lang=zh-CN`（自带中文 + ipv4-only），再备 `api-ipv4.ip.sb/ip` / `ipv4.icanhazip.com`
  - IPv6：`api-ipv6.ip.sb/ip` / `ipv6.icanhazip.com`
  - 地理/运营商：api.ip.sb/geoip（英文）+ ip-api.com 中文增强 + myip.ipip.net 兜底
- 第四栏（"本机外网信息"）固定显示 5 列：外网 IPv4 / 外网 IPv6 / 所在地 / 运营商 / ASN

### 6.8 不要用什么
- ❌ 不要用 `tkinter`（Python 3.13 自带不带 tkinter，重新装很容易出岔）
- ❌ 不要用 `requests`（要走 `http.client` 才好控制超时与多连接）
- ❌ 不要用 `pyqtSignal`（用 PySide6 的 `Signal`）
- ❌ 不要在子线程里调任何 Qt 控件（只 emit 信号）
- ❌ 不要写 1.1.1.1 当国外延迟节点（国内 ISP 会"就近应答"导致 0ms 是假数据，用 `one.one.one.one`）

## 7. 图标
- `netcheck.ico` 是一个圆角深蓝底 + 绿色雷达信号 + 白色端口插槽
- 用 Pillow 都能现场画：
  ```python
  from PIL import Image, ImageDraw
  img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
  d = ImageDraw.Draw(img)
  d.rounded_rectangle((8, 8, 248, 248), radius=32, fill=(13, 71, 161))
  d.ellipse((64, 64, 192, 192), fill=(76, 175, 80))
  img.save("netcheck.ico", sizes=[(16,16),(32,32),(48,48),(64,64),(256,256)])
  ```
  （实际项目里手工用图像软件画一张更专业。）

## 8. 打包命令（必须能跑通）
```bash
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    PySide6 psutil dnspython pyinstaller

pyinstaller --noconfirm --onefile --windowed --name netcheck_v1.0 \
    --icon netcheck.ico --collect-all dnspython --hidden-import psutil \
    netcheck.py
```
产物 `dist/netcheck_v1.0.exe` 约 37MB。

## 9. 验收清单（自检，按这个列表逐条验证）

- [ ] `python netcheck.py` 在 cmd 里跑能弹出窗口不报错
- [ ] 8 个 Tab 都在，名称正确
- [ ] 探测页输入 `www.baidu.com` 点开始，2~3 秒后显示通+延迟
- [ ] 探测页输入 `192.168.1.0/24`（或本机实际网段）开始，能扫出 254 个 IP 的格子图
- [ ] IP 配置页点刷新，能看到 ipconfig 输出
- [ ] 路由追踪页输入 `8.8.8.8` 开始，能实时看到每一跳
- [ ] ARP 页能看到本地 arp 表
- [ ] 网络连接页能看到 netstat 列表，能按状态筛选
- [ ] 端口扫描页扫 `127.0.0.1` 预设常用 80 个，能列出开放/关闭
- [ ] DNS 查询 `www.baidu.com` 类型 A，能解析到 110.242.68.66 之类
- [ ] 宽带测速点开始：能给出国内下行、上行、延迟、抖动四组数字；档位卡片显示"500M~千兆宽带"之类；外网信息五栏都填上了
- [ ] **关键**：连续点 3 次 DNS 查询（不间隔）程序不会自己退出
- [ ] 打包后 `netcheck_v1.0.exe` 双击能直接跑，不弹黑窗
- [ ] 把 exe 拷到另一台 Windows 电脑（没装 Python 也能用）能正常打开
- [ ] 程序任何位置出意外错误，弹窗显示错误并写日志到 `%LOCALAPPDATA%\netcheck\error.log`

## 10. 交付物
请按以下顺序输出：
1. **完整源代码**（一份 `netcheck.py`，分段贴出来，最后给完整版）
2. **`netcheck.ico` 图标生成脚本**（Python + Pillow）
3. **`README.md`**（用中文写，包含：功能简介、运行方式、打包命令、常见问题）
4. **分阶段说明**：你打算怎么开发（5~10 个阶段，每个阶段做哪些事、产出什么可运行的代码）
5. **每阶段的完整代码**（阶段之间可以独立运行看效果）
6. **测试用例**（关键功能的 3~5 个手动测试步骤）

## 11. 给初学者的风格
- **每段代码必须有大量中文注释**。变量名尽量自解释。复杂逻辑分多步写，每步一行注释。
- 在每个新概念第一次出现时，用一段"★ 重点解释 ★"的方块讲清楚。
- 假设用户完全没写过程序。
- 鼓励用户亲手抄而不是复制粘贴（抄代码练手感）。

## 12. 关键提示词（让 AI 自己也好理解）
- 用户叫 "dad"，是中国武汉人，正在从零学编程，主要学习方向是英语、AI、计算机软硬件、网络、虚拟货币、股票
- 用户的网络环境是中国电信宽带，国内速度快（约 780Mbps 实测），国外出口慢且部分被墙
- 用户的 Python 在 `C:\Users\zk\.workbuddy\binaries\python\versions\3.13.12\python.exe`，没有 tkinter
- 用户的 cmd 是 GBK 编码
- 用户的旧版兼容（Win7/8）通过 PyQt5 + Python 3.8 实现，但**本次主版本用 PySide6 + Python 3.13 即可**

---

好，现在请按上面的规格开始**分阶段开发**，先讲你的开发计划（5~10 阶段），再逐阶段写代码并解释。

【结束】
