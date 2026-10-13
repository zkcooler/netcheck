# netcheck · Windows 网络工具箱

> 一个用 Python + PySide6 写的 Windows 图形化网络工具箱：Ping / TCPing、IP 配置、路由追踪、ARP、网络连接、端口扫描、DNS 查询、宽带测速，八合一。

[![Python](https://img.shields.io/badge/Python-3.8%20~%203.13-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%20%7C%20PyQt5-green.svg)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/Platform-Windows%207%20~%2011-lightgrey.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ 功能一览

| # | 功能页 | 说明 |
|---|--------|------|
| 1 | **探测** | Ping（ICMP）/ TCPing（TCP 端口）/ 二合一；支持**网段扫描格子图**，默认自动填入本机网段 |
| 2 | **IP 配置** | `ipconfig` 图形化：查看、刷新、释放 / 续约、刷新 DNS |
| 3 | **路由追踪** | `tracert` 到目标的每一跳，**实时**流式输出 |
| 4 | **ARP 缓存** | `arp -a` 表格化查看、删除单条 |
| 5 | **网络连接** | `netstat -ano` 连接 / 监听查看，支持筛选、PID→进程名、导出 CSV |
| 6 | **端口扫描** | 一台主机常见端口的开放情况 |
| 7 | **DNS 查询** | A / AAAA / MX / NS / TXT / SOA / SRV / CAA / ALL，可指定 DNS 服务器 |
| 8 | **宽带测速** | 国内 / 国外分组测速（下载 / 上传 / 延迟）+ 宽带档位评价 + 本机外网 IP（IPv4 + IPv6 双栈） |

## 🖼 界面预览

<p align="center">
  <img src="assets/icon_preview.png" width="128" alt="netcheck 图标">
</p>

## 🚀 快速开始

### 方式一：直接用现成的 exe（推荐给普通用户）

到 [Releases](../../releases) 页面下载 `netcheck_v9.6.exe`，双击即可运行，**无需安装 Python**。

- Win10 / Win11 → 用 `netcheck_v9.6.exe`
- Win7 SP1 / Win8 / Win8.1 → 用 `netcheck_v9.6_legacy.exe`

### 方式二：从源码运行（需要 Python）

```bash
# 1. 克隆仓库
git clone https://github.com/zkcooler/netcheck.git
cd netcheck

# 2. 安装依赖（国内建议用阿里云镜像，速度快）
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 3. 运行
python netcheck.py
```

## 📦 依赖

| 包 | 用途 | 必需 |
|----|------|:----:|
| PySide6 | 图形界面（Win10/11） | ✅ |
| PyQt5 | 图形界面（Win7/8 老系统回退） | 可选 |
| dnspython | DNS 查询 | ✅ |
| psutil | 网卡检测 / 自动识别本机网段 | ✅ |
| pyinstaller | 打包成 exe | 可选 |

代码内置了 **PySide6 → PyQt5 自动回退**的兼容层，缺哪个用另一个。

## 🔨 自己打包成 exe

```bash
pip install pyinstaller PySide6-Essentials -i https://mirrors.aliyun.com/pypi/simple/

python -m PyInstaller --noconfirm --onefile --windowed ^
  --name netcheck --icon assets/netcheck.ico ^
  --distpath dist --workpath build --specpath build netcheck.py
```

> Win7/8 老系统：需 Python 3.8 + PyQt5 + **PyInstaller 5.13.2**（6.x 已放弃 Win7）。

## 📁 项目结构

```
netcheck/
├── netcheck.py            # 主程序（单文件，约 3500 行，含详细注释与学习导读）
├── make_icon.py           # 图标生成脚本
├── requirements.txt       # 依赖清单
├── assets/
│   ├── netcheck.ico       # 应用图标
│   └── icon_preview.png
├── docs/
│   ├── 教程.md            # ★ 初学者分步骤教程（从环境搭建到打包）
│   ├── AI生成提示词.md     # ★ 给 AI 的提示词，让小白也能生成同类软件
│   └── 使用说明.txt
├── LICENSE
└── README.md
```

## 🎓 想学着自己做？

仓库自带一套完整的**初学者教程**：

1. [`docs/教程.md`](docs/教程.md) —— 从装 Python、装 VS Code 开始，15 个步骤带你从零写出 netcheck，每步都有可运行代码。
2. [`docs/AI生成提示词.md`](docs/AI生成提示词.md) —— 把里面的提示词复制给任意 AI，就能让 AI 引导你生成同类软件。
3. `netcheck.py` 顶部有 **★ 学习导读**，告诉你按什么顺序读这 3500 行代码。

## ⚠️ 已知说明

- 上传测速的国内节点只有华为云镜像真正接收 body，其余镜像大多拒收。
- 国外测速节点在国内网络下可能不稳定，属正常现象。
- Win7 需要 SP1 及以上；**不支持 Windows XP**。

## 🤝 贡献

欢迎提 Issue 和 Pull Request！提 PR 前请：

1. Fork 本仓库并新建分支：`git checkout -b feature/你的功能`
2. 提交改动：`git commit -m "feat: 添加了 xxx"`
3. 推送分支：`git push origin feature/你的功能`
4. 在 GitHub 上发起 Pull Request

提交信息建议遵循 [Conventional Commits](https://www.conventionalcommits.org/)。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。

## 🙏 致谢

- GUI 框架：[PySide6](https://pypi.org/project/PySide6/) / [PyQt5](https://pypi.org/project/PyQt5/)
- DNS 库：[dnspython](https://www.dnspython.org/)
- 系统信息：[psutil](https://github.com/giampaolo/psutil)
