# -*- coding: utf-8 -*-
"""
netcheck  ——  Windows 网络工具箱（图形界面）
================================================
作者：依依（为 dad 定制）
版本：见下方 VERSION 常量

八个功能页：
  1. 探测    Ping（ICMP）/ TCPing（TCP端口）/ 二合一，支持网段格子图
  2. IP配置  ipconfig —— 查看/管理 IP 配置（刷新、释放、续约、刷新DNS）
  3. 路由追踪 tracert —— 到目标的每一跳，实时输出
  4. ARP缓存  arp -a  —— ARP 表查看、删除单条
  5. 网络连接 netstat -ano —— 连接/监听查看，支持筛选、进程名、导出CSV
  6. 端口扫描 一台主机的常见端口开放情况
  7. DNS查询  A/AAAA/MX/NS/TXT/SOA/SRV/CAA/ALL
  8. 宽带测速 国内/国外分组测速 + 宽带档位评价 + 本机外网信息


──────────────────────────────────────────────────────────────────────────
★ 学习导读（写给初学者的阅读顺序）
──────────────────────────────────────────────────────────────────────────
本文件 ~3400 行，单文件组织。建议按下面的顺序读：

[STEP 1]  顶部导入（65~111 行）          → 看懂 PySide6 与 PyQt5 双绑定兼容的写法
[STEP 2]  retire_worker (112~159 行)    → Qt 线程生命周期坑的最关键补丁，v9.6 加的
[STEP 3]  install_excepthook (162~218 行) → 全局异常兜底，槽函数抛错不让程序自杀
[STEP 4]  常量与配色 (223~300 行)      → 几乎所有功能都引用这里的常量
[STEP 5]  工具函数 _decode/run_cmd/fill_table/parse_targets/local_subnet_cidr (303~)
        → 学会「拆 Windows 命令输出」与「自动获取本机网段」
[STEP 6]  icmp_ping/tcp_ping (488~)    → 探测页的核心，被 UI 反复调用
[STEP 7]  http_download_speed/http_upload_speed (641~/748~)
        → ★ 测速算法的两个核心，理解多连接+稳态测速
[STEP 8]  外网 IP 解析 _ipapi_lookup/query_public_ip (897~/961~)
        → IPv4 + IPv6 双栈取地址
[STEP 9]  evaluate_broadband (1093~)   → 「档位评价」那张表格是怎么生成的
[STEP 10] HostWorker / SegmentWorker / DetectTab (1186~1742)
        → 「探测」页完整实现：UI + 后台线程 + 信号槽
[STEP 11] IpConfigTab / TracertTab / ArpTab / NetstatTab / PortScanTab
        → 五个相对简单的「调用命令行」页面
[STEP 12] DnsWorker (2619)             → ★ DNS 修复后的关键代码（看 done 顺序）
[STEP 13] SpeedTestWorker + SpeedTestTab (2846~3475)
        → 测速页的大块头（国内/国外多节点编排 + CSV 导出 + 档位评价）
[STEP 14] MainWindow + main (3480~)    → 程序入口

★ 涉及的关键概念：
  · QThread 后台线程 + Signal/Slot 跨线程通信
  · http.client 分块发送 + 跳过慢启动（测速稳态法）
  · 工单（subprocess）Popen 流式输出 → 信号回 UI
  · 跨平台兼容（PySide6 + PyQt5 双绑定）
  · 线程安全的共享变量（threading.Lock）

★ 三个最容易踩坑的地方（已经修过）：
  ① worker 还没跑完就把引用清掉 → Qt abort → 程序自退
       修：retire_worker（详见 112 行）
  ② TCP/HTTPS 测速混进握手/慢启动 → 数字虚高
       修：http_download_speed (641 行) / http_upload_speed (748 行) 的「稳态窗口」
  ③ 槽函数里抛异常 → PySide6 默认 qFatal → 程序自退
       修：install_excepthook (162 行) 把异常写日志 + 弹窗

★ 阅读建议：先通读「STEP 1~STEP 7」建立直觉，再回去看每个 Tab 的 __init__
   就能跟得上节奏。完整的分步骤教程见 教程.md。
──────────────────────────────────────────────────────────────────────────
"""

import csv
import ipaddress
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- Qt 绑定兼容层：优先 PySide6（Py3.13 + Win10/11 官方版），
# ---- 找不到时自动切到 PyQt5（Py3.8 + Win7/8/8.1 也能跑，legacy 版）----
QT_BINDING = "PySide6"
try:
    from PySide6.QtCore import Qt, QThread, QTimer, Signal
    from PySide6.QtGui import QColor, QFont
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
        QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
        QWidget, QAbstractItemView,
    )
except ImportError:
    QT_BINDING = "PyQt5"
    from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal as Signal
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,
        QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
        QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
        QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
        QWidget, QAbstractItemView,
    )

def _qt_app_exec(app):
    """跨版本 app.exec：PySide6 6.x 与 PyQt5 5.15+ 都有 .exec()；更老的 PyQt5 退到 .exec_()"""
    try:
        return app.exec()
    except AttributeError:
        return app.exec_()


# ==========================================================================
# ★ 稳定性：worker 生命周期 与 全局异常兜底
# ==========================================================================
def retire_worker(owner, attr: str):
    """安全「退休」owner.<attr> 上持有的 QThread worker，然后清空该属性。

    ★ 为什么不能直接 `self.worker = None`：
      worker 的 done 信号是**跨线程队列投递**的 —— 主线程收到 done 时，子线程未必已经
      真正结束（例如 DNS worker 发完 done 还要再跑一次 nslookup）。这时把最后一个
      Python 引用丢掉，PySide6 / PyQt 就会去销毁这个 C++ QThread 对象；而 Qt **不允许
      销毁仍在运行的 QThread**，直接 abort()，整个程序一句话不说就退出了。
      别的电脑上 DNS 响应更慢、nslookup 更慢，踩中的概率就大得多。

    做法：把旧 worker 先放进 owner._retired_workers 名单里「托住引用」，
    只释放那些已经 isFinished()（并 wait 确认过）的，再清空属性。
    """
    w = getattr(owner, attr, None)
    if w is None:
        return
    lst = getattr(owner, "_retired_workers", None)
    if lst is None:
        lst = []
        try:
            owner._retired_workers = lst
        except Exception:
            return
    try:
        if w not in lst:
            lst.append(w)
    except Exception:
        pass
    keep = []
    for x in lst:
        try:
            if x is w:
                keep.append(x)          # 当前这个刚刚才用，先留着
                continue
            if x.isFinished():
                try:
                    x.wait(1)           # 再确认线程真的退出了
                except Exception:
                    pass
                continue                # 已结束 → 释放
            keep.append(x)              # 还在跑 → 继续托住
        except Exception:
            pass
    owner._retired_workers = keep
    try:
        setattr(owner, attr, None)
    except Exception:
        pass


def install_excepthook(app_name="netcheck"):
    """把 Python 未捕获异常写进日志并弹窗，而不是让 Qt 直接 abort 掉整个程序。

    PySide6/PyQt 默认会把「槽函数里未处理的 Python 异常」升级成 qFatal() → abort()，
    结果就是「点一下按钮，程序自己没了，连报错都看不到」。装了这个钩子以后：
      · 异常会写到 %LOCALAPPDATA%\\<app>\\error.log（同时尝试写 exe 同目录）
      · 屏幕上弹一个提示框，把异常类型和最后几行告诉你
    """
    import os
    import traceback
    import datetime as _dt

    def _log_paths():
        paths = []
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        paths.append(os.path.join(base, app_name, "error.log"))
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            paths.append(os.path.join(exe_dir, "netcheck_error.log"))
        except Exception:
            pass
        return paths

    def _hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        header = f"\n===== {_dt.datetime.now():%Y-%m-%d %H:%M:%S}  {app_name} 未捕获异常 =====\n"
        for p in _log_paths():
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(header + text + "\n")
            except Exception:
                pass
        # 尽量弹窗告知（弹窗本身不能再抛异常）
        try:
            from PySide6.QtWidgets import QApplication as _QA  # noqa
        except Exception:
            pass
        try:
            _qtmsg = QMessageBox
            _qtmsg.critical(None, f"{app_name} 出错了（已记录日志）",
                            f"{exc_type.__name__}: {exc}\n\n"
                            f"日志已写到：\n" + "\n".join(_log_paths()))
        except Exception:
            pass
        try:
            sys.stderr.write(header + text)
        except Exception:
            pass

    sys.excepthook = _hook
    try:
        import threading as _th
        _th.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback)
    except Exception:
        pass

try:
    import psutil
except Exception:
    psutil = None

# ---------------- 常量 ----------------
APP_NAME = "netcheck"
VERSION = "9.6"
BUILD_DATE = "2026-10-10"
MAX_HOSTS = 1024
CELL_W, CELL_H = 32, 26
CREATE_NO_WINDOW = 0x08000000

C_UNKNOWN = "#BDBDBD"
C_TESTING = "#FFD54F"
C_BOTH    = "#27AE60"
C_ICMP    = "#8BC34A"
C_TCP     = "#26C6DA"
C_NONE    = "#E74C3C"
TEXT_DARK = "#212121"
TEXT_LIGHT = "#FFFFFF"

MODE_PING, MODE_TCP, MODE_BOTH = 0, 1, 2
MODE_NAMES = ["Ping（ICMP 主机探测）", "TCPing（TCP 端口探测）", "二合一（Ping + TCPing 一起测）"]

# 端口 → 服务名（用于端口扫描页「服务」列展示）
PORT_SERVICES = {
    20: "FTP-数据", 21: "FTP-控制", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP-服务端", 68: "DHCP-客户端", 69: "TFTP", 80: "HTTP",
    110: "POP3", 119: "NNTP", 123: "NTP", 135: "RPC", 137: "NetBIOS-NS",
    138: "NetBIOS-DGM", 139: "NetBIOS-SSN", 143: "IMAP", 161: "SNMP", 162: "SNMP-TRAP",
    389: "LDAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS", 514: "syslog",
    587: "SMTP(提交)", 636: "LDAPS", 873: "rsync", 989: "FTPS-数据", 990: "FTPS-控制",
    993: "IMAPS", 995: "POP3S", 1080: "SOCKS", 1433: "MS SQL", 1521: "Oracle",
    1701: "L2TP", 1723: "PPTP", 1812: "RADIUS", 1883: "MQTT", 1900: "SSDP/UPnP",
    2049: "NFS", 2082: "cPanel", 2083: "cPanel-SSL", 2181: "ZooKeeper",
    2375: "Docker-API", 2376: "Docker-TLS", 3000: "Dev(3000)", 3128: "Squid",
    3306: "MySQL", 3389: "RDP", 3690: "SVN", 4000: "Dev(4000)", 4369: "Erlang",
    5000: "Dev(5000)", 5060: "SIP", 5222: "XMPP", 5353: "mDNS", 5432: "PostgreSQL",
    5601: "Kibana", 5672: "AMQP", 5900: "VNC", 5984: "CouchDB", 6379: "Redis",
    6443: "K8s-API", 7001: "WebLogic", 7474: "Neo4j", 8000: "HTTP-alt", 8008: "Dev",
    8080: "HTTP-Proxy", 8081: "Dev", 8443: "HTTPS-alt", 8500: "Consul", 8888: "Dev",
    9000: "Portainer", 9042: "Cassandra", 9090: "Prometheus", 9092: "Kafka",
    9200: "Elasticsearch", 9418: "Git", 10000: "Webmin", 11211: "Memcached",
    15672: "RabbitMQ-Mgmt", 25565: "Minecraft", 27017: "MongoDB", 27018: "MongoDB-S",
}

# 端口扫描预设（一组）
PORT_PRESETS = {
    "常用（约 80 个）": sorted({
        21, 22, 23, 25, 26, 53, 67, 69, 80, 110, 119, 123, 135, 137, 138, 139,
        143, 161, 162, 389, 443, 445, 465, 514, 515, 587, 631, 636, 873, 902,
        989, 990, 993, 995, 1080, 1194, 1433, 1521, 1701, 1723, 1883, 1900,
        2000, 2049, 2082, 2083, 2086, 2087, 2181, 2375, 2376, 3000, 3128, 3306,
        3389, 3690, 4000, 4369, 5000, 5060, 5222, 5353, 5432, 5601, 5672, 5900,
        5984, 6379, 6443, 7001, 7474, 8000, 8008, 8080, 8081, 8443, 8888, 9000,
        9042, 9090, 9092, 9200, 9418, 10000, 11211, 15672, 25565, 27017, 27018,
    }),
    "Web（HTTP/HTTPS/代理）": [80, 443, 8000, 8008, 8080, 8081, 8443, 8888, 3000, 5000, 9090, 7001, 7443, 9443],
    "数据库": [1433, 1521, 2181, 3306, 5432, 6379, 7474, 9042, 9092, 9200, 11211, 27017, 27018, 5984, 2375, 2376],
    "远程管理/服务": [22, 23, 53, 69, 123, 137, 138, 139, 161, 162, 514, 3389, 5060, 5900, 873, 2049, 445],
    "邮件": [25, 110, 143, 465, 587, 993, 995],
    "IoT/开发": [1883, 3000, 4000, 4369, 5000, 5601, 6379, 6443, 8500, 9000, 9090, 9418, 11211, 15672, 25565, 27017],
}

DNS_TYPES = [
    ("A",     "A（IPv4 地址）"),
    ("AAAA",  "AAAA（IPv6 地址）"),
    ("CNAME", "CNAME（别名）"),
    ("MX",    "MX（邮件交换）"),
    ("NS",    "NS（权威 DNS）"),
    ("TXT",   "TXT（文本记录）"),
    ("SOA",   "SOA（起始授权）"),
    ("SRV",   "SRV（服务定位）"),
    ("CAA",   "CAA（证书授权）"),
    ("ALL",   "ALL（A/AAAA/MX/NS/TXT/CNAME/SOA/SRV/CAA 一起查）"),
]

MONO = "Consolas"
DARK_QSS = "background:#111;color:#DDD;"


# ==========================================================================
# 通用工具
# ==========================================================================
def _decode(data: bytes) -> str:
    for enc in ("gbk", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return ""


def run_cmd(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
        return _decode(p.stdout) or _decode(p.stderr)
    except Exception as e:
        return f"[执行失败] {e}"


class CmdWorker(QThread):
    """跑一条命令，把输出整段发回来"""
    output = Signal(str)

    def __init__(self, cmd, timeout=30):
        super().__init__()
        self.cmd, self.timeout = cmd, timeout

    def run(self):
        self.output.emit(run_cmd(self.cmd, self.timeout))


class StreamWorker(QThread):
    """持续跑一条命令，逐行发回（用于 tracert）"""
    line = Signal(str)
    done = Signal()

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self._stop = False
        self.p = None

    def stop(self):
        self._stop = True
        try:
            if self.p:
                self.p.kill()
        except Exception:
            pass

    def run(self):
        try:
            self.p = subprocess.Popen(self.cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT,
                                      creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.line.emit(f"[执行失败] {e}")
            self.done.emit()
            return
        while True:
            if self._stop:
                break
            raw = self.p.stdout.readline()
            if not raw:
                break
            self.line.emit(_decode(raw).rstrip("\r\n"))
        try:
            self.p.kill()
        except Exception:
            pass
        self.done.emit()


def fill_table(table: QTableWidget, headers, rows):
    table.setSortingEnabled(False)
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(val)))
    table.setSortingEnabled(True)
    table.resizeColumnsToContents()


def table_to_csv(table: QTableWidget, path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        w.writerow(headers)
        for r in range(table.rowCount()):
            row = []
            for c in range(table.columnCount()):
                it = table.item(r, c)
                row.append(it.text() if it else "")
            w.writerow(row)


# ==========================================================================
# 探测逻辑（Ping / TCPing）
# ==========================================================================
def parse_targets(text: str):
    t = (text or "").strip().replace(" ", "")
    if not t:
        return [], "请输入主机地址或 IP 段"
    try:
        if "/" in t:
            net = ipaddress.ip_network(t, strict=False)
            hosts = [str(h) for h in net.hosts()] or [str(h) for h in net]
            return hosts, None
        if "*" in t:
            base = t.replace(".*", ".0") if t.endswith(".*") else t
            net = ipaddress.ip_network(base + "/24", strict=False)
            return [str(h) for h in net.hosts()], None
        if "-" in t:
            left, right = [x.strip() for x in t.split("-", 1)]
            if "." not in right:
                if not (0 <= int(right) <= 255):
                    return [], "范围结尾应在 0~255 之间"
                prefix = left.rsplit(".", 1)[0]
                start = ipaddress.ip_address(f"{prefix}.{int(left.rsplit('.', 1)[1])}")
                end = ipaddress.ip_address(f"{prefix}.{int(right)}")
            else:
                start, end = ipaddress.ip_address(left), ipaddress.ip_address(right)
            a, b = int(start), int(end)
            if b < a:
                a, b = b, a
            return [str(ipaddress.ip_address(i)) for i in range(a, b + 1)], None
        return [str(ipaddress.ip_address(t))], None
    except ValueError as e:
        return [], f"格式看不懂：{e}\n示例：192.168.1.22 或 192.168.1.1-254 或 192.168.1.0/24"


def is_range(text: str) -> bool:
    return any(c in (text or "") for c in "-*/")


def local_subnet_cidr() -> str:
    """探测本机首选物理网卡（up、非虚拟、IPv4、/16 以上）所属的网段，返回 CIDR 串。
    用于「探测」页默认目标。找不到时返回 None。
    """
    if psutil is None:
        return None
    try:
        infos = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        SKIP = ("vmware", "virtualbox", "hyper-v", "veth", "wsl",
                "loopback", "npcap", "docker", "hamachi", "zerotier")
        # 第一遍：up + 非虚拟 + IPv4 + /16 以上
        for iface, addrs in infos.items():
            st = stats.get(iface)
            is_up = (st.isup if st is not None else True)
            il = iface.lower()
            if not is_up or any(k in il for k in SKIP):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    try:
                        net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
                    except Exception:
                        continue
                    if net.prefixlen >= 16:
                        return f"{net.network_address}/{net.prefixlen}"
        # 兜底：随便找一个非回环 IPv4
        for iface, addrs in infos.items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    try:
                        net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
                        return f"{net.network_address}/{net.prefixlen}"
                    except Exception:
                        continue
    except Exception:
        pass
    return None


def last_two(ip: str) -> str:
    try:
        return f"{int(ip.rsplit('.', 1)[1]):02d}"
    except Exception:
        return ip[-2:]


def icmp_ping(host: str, count: int, timeout_ms: int):
    """ICMP ping：返回 (是否通, 平均延迟ms, 丢包率%)"""
    cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    try:
        p = subprocess.run(cmd, capture_output=True,
                           timeout=count * (timeout_ms / 1000.0) + 6,
                           creationflags=CREATE_NO_WINDOW)
    except Exception:
        return False, None, 100.0
    out = _decode(p.stdout)
    replies, times = 0, []
    neg = r"(无法访问|不可达|unreachable|一般性故障|General failure|超时|timed out)"
    for line in out.splitlines():
        # IPv6 回复行没有 TTL → 按"来自/Reply from"判断；并排除失败回包
        if re.search(r"(来自|Reply from|TTL\s*[=:])", line, re.I) and not re.search(neg, line, re.I):
            replies += 1
            m = re.search(r"[=<>]\s*(\d+)\s*ms", line, re.I)
            if m:
                times.append(int(m.group(1)))
    ok = replies > 0
    avg = (sum(times) / len(times)) if times else None
    loss = ((count - replies) / count * 100.0) if count else 0.0
    return ok, avg, max(0.0, min(100.0, loss))


WSA_MSG = {10061: "端口关闭(拒绝)", 10060: "超时无响应", 10065: "主机不可达",
           10064: "主机宕机", 11001: "域名解析失败"}


def tcp_ping(host: str, port: int, timeout_ms: int):
    timeout = max(0.05, timeout_ms / 1000.0)
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        ip = infos[0][4][0]
    except socket.gaierror:
        return False, None, "域名解析失败", host

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.perf_counter()
    ok, msg = False, "连接失败"
    try:
        s.connect((ip, port))
        ok, msg = True, "端口开放"
    except (socket.timeout, TimeoutError):
        msg = "超时无响应"
    except ConnectionRefusedError:
        msg = "端口关闭(拒绝)"
    except OSError as e:
        code = getattr(e, "winerror", None) or getattr(e, "errno", None)
        msg = WSA_MSG.get(code, f"连接失败({e.__class__.__name__}"
                                f"{'' if code is None else ' ' + str(code)})")
    dt = (time.perf_counter() - t0) * 1000.0 if ok else None
    try:
        s.close()
    except Exception:
        pass
    return ok, dt, msg, ip


# ==========================================================================
# 测速辅助（延迟/下载/上传）
# ==========================================================================
def icmp_ping_times(host: str, count: int, timeout_ms: int):
    """发 count 个包，返回每个回包的延迟（ms）列表；空表示全失败"""
    cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    try:
        p = subprocess.run(cmd, capture_output=True,
                           timeout=count * (timeout_ms / 1000.0) + 6,
                           creationflags=CREATE_NO_WINDOW)
    except Exception:
        return []
    out = _decode(p.stdout)
    neg = r"(无法访问|不可达|unreachable|一般性故障|General failure|超时|timed out)"
    times = []
    for line in out.splitlines():
        if re.search(r"(来自|Reply from|TTL\s*[=:])", line, re.I) and not re.search(neg, line, re.I):
            m = re.search(r"[=<>]\s*(\d+)\s*ms", line, re.I)
            if m:
                times.append(int(m.group(1)))
    return times


def http_size_speed(url: str, max_time: float = 6.0, warmup_sec: float = 2.5,
                    max_bytes: int = 160 * 1024 * 1024):
    """单连接下载（兜底用）。从 URL 拉数据，最多 max_time 秒，返回（平均速率 字节/秒，读到字节数）。

    · warmup_sec：**连接 + 首字节**阶段最长等待；不可达节点在这段时间内就会失败，
      不再傻等 max_time —— 这是修复"点开始很久没结果"的关键。
    · 速率只统计「首字节到达之后」的纯传输时间，排除 TCP 握手和 TTFB 的干扰。
    · max_bytes：单节点最多读这么多字节就停，避免跑 1G 专线时测一次吃掉好几 GB。
    """
    import http.client
    import urllib.parse
    pu = urllib.parse.urlsplit(url)
    host = pu.hostname
    if not host:
        return 0.0, 0
    port = pu.port or (443 if pu.scheme == "https" else 80)
    path = pu.path or "/"
    if pu.query:
        path += "?" + pu.query
    conn_cls = http.client.HTTPSConnection if pu.scheme == "https" else http.client.HTTPConnection

    conn = None
    bytes_read = 0
    t_data = None
    try:
        # ① 连接 + 首字节：最多等 warmup_sec（不可达立即失败）
        conn = conn_cls(host, port, timeout=warmup_sec)
        conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0 netcheck",
                                           "Accept": "*/*"})
        resp = conn.getresponse()
        if not (200 <= resp.status < 300):
            return 0.0, 0
        # 已连上 → 放宽读取超时，避免慢节点被误杀
        try:
            conn.sock.settimeout(max(2.0, min(max_time, 6.0)))
        except Exception:
            pass
        # ② 纯传输阶段
        t_data = time.perf_counter()
        while True:
            el = time.perf_counter() - t_data
            if el >= max_time:
                break
            if bytes_read >= max_bytes:
                break
            if bytes_read == 0 and el >= warmup_sec:
                break
            try:
                chunk = resp.read(64 * 1024)
            except Exception:
                break
            if not chunk:
                break
            bytes_read += len(chunk)
    except Exception:
        pass
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    if t_data is None or bytes_read == 0:
        return 0.0, 0
    el = time.perf_counter() - t_data
    if el < 0.05:
        return 0.0, 0
    return bytes_read / el, bytes_read


def http_download_speed(url: str, max_time: float = 8.0, streams: int = 4,
                        skip_sec: float = 2.0, warmup_sec: float = 3.0,
                        max_bytes: int = 400 * 1024 * 1024):
    """★ 下载测速（多连接 + 稳态法）★ —— 比单连接准得多的算法

    为什么这么设计（"国内测速差别大"的三个根因）：
      1. **多连接并发**（默认 4 条）：单个 TCP 连接常被 CDN 限速，或受带宽时延积限制
         跑不满线路。4 条并发才能把 100M/150M/千兆的家宽"喂饱"。
      2. **跳过慢启动**（skip_sec=2s）：TCP 刚建立处于慢启动阶段（速率从很小爬升），
         且国内运营商普遍给前几秒"突发加速"（高于套餐带宽）。把前 2 秒算进去会让
         结果忽高忽低。只统计之后的稳态窗口，才贴近真实带宽。
      3. **时长足够**：稳态窗口默认 ~6s，避免只测到突发。

    返回 (稳态速率 字节/秒, 总字节数, 成功连接数)。总耗时约 max_time 秒。
    """
    import http.client
    import urllib.parse
    pu = urllib.parse.urlsplit(url)
    host = pu.hostname
    if not host:
        return 0.0, 0, 0
    port = pu.port or (443 if pu.scheme == "https" else 80)
    path = pu.path or "/"
    if pu.query:
        path += "?" + pu.query
    conn_cls = http.client.HTTPSConnection if pu.scheme == "https" else http.client.HTTPConnection

    lock = threading.Lock()
    st = {"bytes": 0, "connected": 0, "stop": False}

    def _one_stream():
        conn = None
        try:
            conn = conn_cls(host, port, timeout=warmup_sec)
            conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0 netcheck",
                                               "Accept": "*/*"})
            resp = conn.getresponse()
            if not (200 <= resp.status < 300):
                return
            with lock:
                st["connected"] += 1
            try:
                conn.sock.settimeout(max(3.0, min(max_time, 8.0)))
            except Exception:
                pass
            while not st["stop"]:
                try:
                    chunk = resp.read(64 * 1024)
                except Exception:
                    break
                if not chunk:
                    break
                with lock:
                    st["bytes"] += len(chunk)
                    if st["bytes"] >= max_bytes:
                        st["stop"] = True
                        break
        except Exception:
            pass
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    threads = [threading.Thread(target=_one_stream, daemon=True)
               for _ in range(max(1, streams))]
    for t in threads:
        t.start()

    t_wait = time.perf_counter()
    n_conn = 0
    while True:
        with lock:
            n_conn = st["connected"]
        if n_conn > 0:
            break
        if time.perf_counter() - t_wait >= warmup_sec:
            break
        time.sleep(0.05)
    if n_conn == 0:
        st["stop"] = True
        for t in threads:
            t.join(timeout=1.0)
        return 0.0, 0, 0

    time.sleep(skip_sec)
    with lock:
        b1 = st["bytes"]
    t1 = time.perf_counter()

    time.sleep(max(1.0, max_time - skip_sec))
    with lock:
        b2 = st["bytes"]
    t2 = time.perf_counter()

    st["stop"] = True
    for t in threads:
        t.join(timeout=2.0)

    dt = t2 - t1
    if dt < 0.2 or b2 <= b1:
        return (0.0, b2, n_conn) if b2 > 0 else (0.0, 0, n_conn)
    return (b2 - b1) / dt, b2, n_conn


def http_upload_speed(url: str, size_mb: int = 8, max_time: float = 25.0,
                      warmup_sec: float = 3.0):
    """★ 上传测速（稳态法）★

    为什么不能直接「总字节 ÷ 总耗时」：
      1) 连接/握手阶段（TCP + TLS）本身要花掉几百毫秒，混进去会严重偏低；
      2) TCP 慢启动：开头一小段速率从 0 爬升；
      3) 服务端要收完全部 body 才可能回响应，这里以「收到响应」为结束点。

    做法：分块发送 body，跳过开头 warm_bytes（0.5~2MB）后再开始计时，
    得到的就是「稳态上行速率」。只有服务端返回 2xx 才算数。

    返回 字节/秒（失败返回 0.0）。
    """
    import http.client
    import urllib.parse
    pu = urllib.parse.urlsplit(url)
    host = pu.hostname
    if not host:
        return 0.0
    port = pu.port or (443 if pu.scheme == "https" else 80)
    path = pu.path or "/"
    if pu.query:
        path += "?" + pu.query
    total = max(1, int(size_mb)) * 1024 * 1024
    chunk = b"\0" * (256 * 1024)
    warm_bytes = min(max(total // 4, 1024 * 1024), 4 * 1024 * 1024)
    conn_cls = http.client.HTTPSConnection if pu.scheme == "https" else http.client.HTTPConnection

    conn = None
    sent = 0
    t_warm = None
    t_body0 = None
    t_end = None
    ok = False
    try:
        conn = conn_cls(host, port, timeout=warmup_sec)
        conn.connect()                       # 连接阶段：最多 warmup_sec
        try:
            conn.sock.settimeout(max_time)   # 上传阶段放宽
        except Exception:
            pass
        conn.putrequest("POST", path, skip_accept_encoding=True)
        conn.putheader("User-Agent", "Mozilla/5.0 netcheck")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(total))
        conn.endheaders()
        t_body0 = time.perf_counter()
        left = total
        while left > 0:
            n = min(len(chunk), left)
            conn.sock.sendall(chunk[:n])
            sent += n
            left -= n
            if t_warm is None and sent >= warm_bytes:
                t_warm = time.perf_counter()
        resp = conn.getresponse()
        ok = 200 <= resp.status < 300
        try:
            resp.read(2048)
        except Exception:
            pass
        t_end = time.perf_counter()
    except Exception:
        ok = False
        t_end = time.perf_counter()
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    if not ok or sent <= 0 or t_end is None:
        return 0.0
    if t_warm is not None and t_body0 is not None and (t_end - t_warm) > 0.15 and sent > warm_bytes:
        return (sent - warm_bytes) / (t_end - t_warm)
    if (t_end - (t_body0 or t_end)) > 0.05:
        return sent / (t_end - t_body0)
    return 0.0


# ==========================================================================
# 外网 IP / 归属地 / 运营商（IPv4 + IPv6 双栈）
# ==========================================================================
# IPv4：ip-api.com 免费版只走 IPv4，且 lang=zh-CN 直接给中文地名/运营商（首选）；
#       再兜底两个纯 IPv4 的取 IP 接口。
IPV4_SOURCES = [
    ("ip-api.com",    "http://ip-api.com/json/?lang=zh-CN"),
    ("api-ipv4.ip.sb", "https://api-ipv4.ip.sb/ip"),
    ("ipv4.icanhazip", "https://ipv4.icanhazip.com"),
]
# IPv6：只取地址（能取到就说明本机有 IPv6 出口）
IPV6_SOURCES = [
    ("api-ipv6.ip.sb", "https://api-ipv6.ip.sb/ip"),
    ("ipv6.icanhazip", "https://ipv6.icanhazip.com"),
]
# 归属地兜底（当 IPv4 首选源失败时用）
GEO_SOURCES = [
    ("api.ip.sb", "https://api.ip.sb/geoip"),
    ("ipip.net",  "https://myip.ipip.net"),
]

_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
_IPV6_RE = re.compile(r"^[0-9a-fA-F:]{2,45}$")


def _http_get_text(url: str, timeout: float = 3.5, max_bytes: int = 65536):
    """GET 一个 URL，返回正文文本（最多 64KB），失败返回 None"""
    import http.client
    import urllib.parse
    pu = urllib.parse.urlsplit(url)
    host = pu.hostname
    if not host:
        return None
    port = pu.port or (443 if pu.scheme == "https" else 80)
    path = pu.path or "/"
    if pu.query:
        path += "?" + pu.query
    conn_cls = http.client.HTTPSConnection if pu.scheme == "https" else http.client.HTTPConnection
    conn = None
    try:
        conn = conn_cls(host, port, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0 netcheck",
                                           "Accept": "*/*"})
        resp = conn.getresponse()
        if not (200 <= resp.status < 300):
            return None
        return resp.read(max_bytes).decode("utf-8", errors="ignore")
    except Exception:
        return None
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _dedup_join(parts):
    seen, uniq = set(), []
    for p in parts:
        p = (p or "").strip()
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return " ".join(uniq)


def _ipapi_lookup(timeout=3.0):
    """ip-api.com ：返回 IPv4 + 中文归属地/运营商/ASN"""
    import json
    txt = _http_get_text("http://ip-api.com/json/?lang=zh-CN", timeout=timeout)
    if not txt:
        return None
    try:
        d = json.loads(txt.strip())
    except Exception:
        return None
    if d.get("status") != "success":
        return None
    ip = (d.get("query") or "").strip()
    if not _IPV4_RE.match(ip):
        return None
    return {
        "ip": ip,
        "location": _dedup_join([d.get("country"), d.get("regionName"), d.get("city")]) or "—",
        "isp": d.get("isp") or d.get("org") or "—",
        "asn": (d.get("as") or "").split()[0] if d.get("as") else "",
    }


def _plain_ip(url, timeout=3.0, want="v4"):
    """从纯 IP 接口取地址；want='v4'|'v6' 用来校验格式"""
    txt = _http_get_text(url, timeout=timeout)
    if not txt:
        return None
    ip = txt.strip().split()[0] if txt.strip() else ""
    if want == "v4" and _IPV4_RE.match(ip):
        return ip
    if want == "v6" and _IPV6_RE.match(ip) and ":" in ip:
        return ip
    return None


def _geo_lookup(timeout=3.0):
    """归属地兜底：api.ip.sb/geoip → myip.ipip.net"""
    import json
    txt = _http_get_text("https://api.ip.sb/geoip", timeout=timeout)
    if txt:
        try:
            d = json.loads(txt.strip())
            return {
                "location": _dedup_join([d.get("country"), d.get("region"), d.get("city")]) or "—",
                "isp": d.get("isp") or d.get("organization") or d.get("asn_organization") or "—",
                "asn": f"AS{d['asn']}" if d.get("asn") else "",
                "source": "api.ip.sb",
            }
        except Exception:
            pass
    txt = _http_get_text("https://myip.ipip.net", timeout=timeout)
    if txt:
        seg = ""
        m = re.search(r"来自于[：:]\s*(.+)", txt)
        if m:
            seg = m.group(1).strip()
        parts = [p for p in re.split(r"\s+", seg) if p]
        if parts:
            return {"location": " ".join(parts[:-1]) or seg, "isp": parts[-1],
                    "asn": "", "source": "ipip.net"}
    return None


def query_public_ip(total_budget: float = 8.0):
    """查询本机外网 IPv4 / IPv6 / 所在地 / 运营商 / ASN。

    · IPv4：ip-api.com（首选，含中文归属地）→ api-ipv4.ip.sb/ip → ipv4.icanhazip.com
    · IPv6：api-ipv6.ip.sb/ip → ipv6.icanhazip.com（取不到就说明没有 IPv6 出口）
    · 归属地/运营商：优先用 ip-api.com 的中文结果；它失败再用 geo 兜底源
    返回 dict：{ok, ipv4, ipv6, location, isp, asn, location_zh, isp_zh, source, note}
    """
    t0 = time.perf_counter()

    def _left(lo=1.0, hi=3.0):
        return max(lo, min(hi, total_budget - (time.perf_counter() - t0)))

    ipv4 = None
    ipv6 = None
    geo = None
    src_bits = []

    # ---- IPv4 ----
    r = _ipapi_lookup(timeout=_left())
    if r:
        ipv4 = r["ip"]
        geo = {"location": r["location"], "isp": r["isp"], "asn": r["asn"],
               "location_zh": r["location"], "isp_zh": r["isp"], "source": "ip-api.com"}
        src_bits.append("ip-api.com(中文)")
    else:
        for nm, url in IPV4_SOURCES[1:]:
            if time.perf_counter() - t0 >= total_budget:
                break
            ipv4 = _plain_ip(url, timeout=_left(), want="v4")
            if ipv4:
                src_bits.append(nm)
                break

    # ---- IPv6 ----
    for nm, url in IPV6_SOURCES:
        if time.perf_counter() - t0 >= total_budget:
            break
        ipv6 = _plain_ip(url, timeout=_left(), want="v6")
        if ipv6:
            src_bits.append(nm)
            break

    # ---- 归属地兜底 ----
    if geo is None and time.perf_counter() - t0 < total_budget:
        g = _geo_lookup(timeout=_left())
        if g:
            geo = {"location": g["location"], "isp": g["isp"], "asn": g["asn"],
                   "location_zh": "", "isp_zh": "", "source": g["source"]}
            src_bits.append(g["source"])

    ok = bool(ipv4 or ipv6)
    out = {
        "ok": ok,
        "ipv4": ipv4 or "",
        "ipv6": ipv6 or "",
        "location": (geo or {}).get("location", "—"),
        "isp": (geo or {}).get("isp", "—"),
        "asn": (geo or {}).get("asn", ""),
        "location_zh": (geo or {}).get("location_zh", ""),
        "isp_zh": (geo or {}).get("isp_zh", ""),
        "source": " + ".join(src_bits) if src_bits else "—",
        "note": "" if ok else "所有查询源均失败（可能被网络策略拦截）",
    }
    return out


# 测速节点（按「国内 / 国外」分开）
# 国内节点在你这台武汉电信机器上测速最贴近实际带宽；
# 国外节点反映国际出口真实体验（Wuhan 出口通常 ≤ 50 Mbps）。
SPEED_TEST_NODES = {
    "latency": {
        "国内": [
            ("百度",         "www.baidu.com"),
            ("QQ",           "www.qq.com"),
            ("淘宝",         "www.taobao.com"),
            ("阿里 DNS",     "223.5.5.5"),
        ],
        "国外": [
            # 注意：不要用 1.1.1.1 —— 国内不少宽带会被本地设备「就近应答」，测出来 0~1ms 是假的
            ("Cloudflare", "one.one.one.one"),
            ("Google DNS", "dns.google"),
        ],
    },
    "download": {
        "国内": [
            ("清华镜像",   "https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/24.04.4/ubuntu-24.04.4-desktop-amd64.iso"),
            ("北大镜像",   "https://mirrors.pku.edu.cn/ubuntu-releases/24.04.4/ubuntu-24.04.4-desktop-amd64.iso"),
            ("哈工大镜像", "https://mirrors.hit.edu.cn/ubuntu-releases/24.04.4/ubuntu-24.04.4-desktop-amd64.iso"),
        ],
        "国外": [
            # Cloudflare __down 单次 100MB 会被 403，50MB 稳定 → 用 50MB
            ("Cloudflare", "https://speed.cloudflare.com/__down?bytes=52428800"),
            ("OVH 法国",   "https://proof.ovh.net/files/100Mb.dat"),
        ],
    },
    "upload": {
        "国内": [
            # 国内极少有公开「收上传」的测速点；华为云镜像站会完整读取 body 并回 200，稳
            ("华为云镜像", "https://mirrors.huaweicloud.com/"),
        ],
        "国外": [
            ("Cloudflare", "https://speed.cloudflare.com/__up"),
        ],
    },
}

# 国内常见家庭/企业宽带档位（下行速率，单位 Mbps）
# 顺序：从高到低，第一个满足条件的为该宽带档位
BROADBAND_TIERS = [
    (3000, "万兆级专线 (≥3 Gbps)",    "运营商顶级政企专线",  ["数据中心互联", "8K 直播推流", "大型 NAS 多机同步", "千人级 Wi-Fi"]),
    (1000, "千兆宽带 (≥1000 Mbps)",   "运营商顶配套餐",     ["8K 视频点播", "千兆 NAS 传输", "多设备同时 4K", "云游戏 4K HDR"]),
    (500,  "500M~千兆宽带",          "运营商高端套餐",     ["流畅 4K HDR", "10+ 设备同时上网", "大文件秒下", "云游戏 60fps"]),
    (300,  "300M~500M 宽带",         "运营商主流中高端",   ["4K 视频", "家庭多设备同时上网", "云游戏", "高清直播"]),
    (200,  "200M~300M 宽带",         "运营商主流套餐",     ["1080P 高清", "5~10 设备同时上网", "一般网游无延迟"]),
    (100,  "100M~200M 宽带",         "运营商标准套餐",     ["1080P 视频", "3~5 设备同时上网", "普通网游"]),
    (50,   "50M~100M 宽带",          "运营商基础套餐",     ["720P 视频", "2~3 设备上网", "日常浏览/购物"]),
    (20,   "20M~50M 宽带",           "运营商入门套餐",     ["480P 视频", "1~2 设备上网", "聊天看新闻"]),
    (0,    "20M 以下",               "低速网络",            ["基础浏览", "不推荐视频/游戏"]),
]

# 延迟档位（国内/国外通用描述）
LATENCY_TIERS = [
    (10,  "极佳 (≤10 ms)",   "游戏级延迟，操作几乎无感"),
    (30,  "优秀 (≤30 ms)",   "主流网游、4K 直播毫无问题"),
    (60,  "良好 (≤60 ms)",   "一般网游、视频聊天正常"),
    (100, "一般 (≤100 ms)",  "网页/视频够用，FPS 游戏能感到延迟"),
    (200, "欠佳 (≤200 ms)",  "看视频可能卡顿，竞技类游戏明显延迟"),
    (99999, "较差 (>200 ms)", "建议排查网络 / Wi-Fi / 路由器问题"),
]


def evaluate_broadband(down_mbps, up_mbps, lat_ms, scope="国内"):
    """根据下行/上行/延迟返回 (档位标签, 档位名, 典型用途列表, 延迟档位标签, 总体评语)
    scope 仅为评语修饰用，不影响判定阈值
    """
    # 下行档位
    down_tier = None
    for min_d, label, desc, uses in BROADBAND_TIERS:
        if down_mbps >= min_d:
            down_tier = (label, desc, uses)
            break
    if down_tier is None:
        down_tier = ("未测出", "未能测出有效下行速率", ["请检查网络连接"])

    # 上行档位（如果有上行数据，作为补充信息）
    up_note = ""
    if up_mbps and up_mbps > 0:
        if up_mbps >= 100:
            up_note = "，上行达到「对称千兆 / 专线」水准"
        elif up_mbps >= 50:
            up_note = "，上行可达 4K 直播推流"
        elif up_mbps >= 20:
            up_note = "，上行可满足高清直播 / 视频通话"
        elif up_mbps >= 5:
            up_note = "，上行满足日常视频通话"
        else:
            up_note = "，上行偏弱，大文件上传会较慢"

    # 延迟档位
    lat_label = "未测出"
    for lat_limit, lat_l, lat_desc in LATENCY_TIERS:
        if lat_ms is None:
            break
        if lat_ms <= lat_limit:
            lat_label = f"{lat_l}　{lat_desc}"
            break

    # 总体评语（举例："你的网速相当于 500M~千兆宽带，可流畅 4K HDR / 10+ 设备同时上网 / 云游戏 60fps"）
    if lat_ms is not None:
        summary = (f"你的网速相当于 {down_tier[0]}{up_note}，"
                   f"典型用途：{' / '.join(down_tier[2])}；延迟 {lat_ms} ms（{lat_label}）。")
    else:
        summary = (f"你的网速相当于 {down_tier[0]}{up_note}，"
                   f"典型用途：{' / '.join(down_tier[2])}；延迟数据缺失。")

    return {
        "scope": scope,
        "down_mbps": down_mbps,
        "up_mbps": up_mbps,
        "lat_ms": lat_ms,
        "tier_label": down_tier[0],
        "tier_desc": down_tier[1],
        "uses": down_tier[2],
        "lat_label": lat_label,
        "summary": summary,
    }


def check_host(host, port, mode, ping_count, timeout_ms):
    r = {"icmp": None, "tcp": None, "ip": host}
    if mode in (MODE_PING, MODE_BOTH):
        r["icmp"] = icmp_ping(host, ping_count, timeout_ms)
    if mode in (MODE_TCP, MODE_BOTH):
        ok, rtt, msg, ip = tcp_ping(host, port, timeout_ms)
        r["tcp"] = (ok, rtt, msg)
        r["ip"] = ip
    return r


def resolve_host(host):
    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


def cell_state_from(r, mode):
    if r is None:
        return "unknown"
    if mode == MODE_PING:
        return "both" if r["icmp"] and r["icmp"][0] else "none"
    if mode == MODE_TCP:
        return "both" if r["tcp"] and r["tcp"][0] else "none"
    i_ok = bool(r["icmp"] and r["icmp"][0])
    t_ok = bool(r["tcp"] and r["tcp"][0])
    if i_ok and t_ok:
        return "both"
    if i_ok:
        return "icmp"
    if t_ok:
        return "tcp"
    return "none"


class HostWorker(QThread):
    sample = Signal(int, object)
    done = Signal(dict)

    def __init__(self, host, port, mode, count, ping_count, timeout_ms, interval, continuous):
        super().__init__()
        self.host, self.port, self.mode = host, port, mode
        self.count, self.ping_count = count, ping_count
        self.timeout_ms, self.interval = timeout_ms, interval
        self.continuous = continuous
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        stat = {"n": 0, "icmp_ok": 0, "tcp_ok": 0, "icmp_rtt": [], "tcp_rtt": []}
        i = 0
        while not self._stop and (self.continuous or i < self.count):
            i += 1
            r = check_host(self.host, self.port, self.mode, self.ping_count, self.timeout_ms)
            stat["n"] += 1
            if r["icmp"] and r["icmp"][0]:
                stat["icmp_ok"] += 1
                if r["icmp"][1] is not None:
                    stat["icmp_rtt"].append(r["icmp"][1])
            if r["tcp"] and r["tcp"][0]:
                stat["tcp_ok"] += 1
                if r["tcp"][1] is not None:
                    stat["tcp_rtt"].append(r["tcp"][1])
            self.sample.emit(i, r)
            if self._stop:
                break
            if not self.continuous and i >= self.count:
                break
            waited, step = 0.0, 0.05
            while waited < self.interval and not self._stop:
                time.sleep(min(step, self.interval - waited))
                waited += step
        self.done.emit(stat)


class SegmentWorker(QThread):
    result = Signal(str, object)
    progress = Signal(int, int)
    done = Signal(int, int, int)

    def __init__(self, hosts, port, mode, ping_count, timeout_ms, concurrency):
        super().__init__()
        self.hosts, self.port, self.mode = hosts, port, mode
        self.ping_count, self.timeout_ms = ping_count, timeout_ms
        self.concurrency = max(1, min(concurrency, 256))
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.hosts)
        good = part = bad = done_n = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futs = {ex.submit(check_host, h, self.port, self.mode, self.ping_count,
                              self.timeout_ms): h for h in self.hosts}
            for fut in as_completed(futs):
                if self._stop:
                    for f in futs:
                        f.cancel()
                    break
                host = futs[fut]
                try:
                    r = fut.result()
                except Exception:
                    r = {"icmp": None, "tcp": None, "ip": host}
                done_n += 1
                st = cell_state_from(r, self.mode)
                if st == "both":
                    good += 1
                elif st in ("icmp", "tcp"):
                    part += 1
                else:
                    bad += 1
                self.result.emit(host, r)
                self.progress.emit(done_n, total)
        self.done.emit(good, part, bad)


# ==========================================================================
# 页1：探测
# ==========================================================================
# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 1/8  探测页（Ping / TCPing / 二合一）                                  ║
# ║                                                                         ║
# ║  这是整个工具里最复杂的一页：单个目标 + 网段格子图都要支持。                    ║
# ║  关键依赖：local_subnet_cidr()、icmp_ping()、tcp_ping()、check_host()         ║
# ║  线程：HostWorker（单目标）、SegmentWorker（网段并发扫）                      ║
# ║  看懂这一页，其它 Tab 都不怕。                                                  ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class DetectTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.cells = {}
        self.hosts = []
        self.results = {}
        self.worker = None
        self.seg_worker = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 目标（单个主机 / 域名 / IP 段）")
        h1 = QHBoxLayout(gb)
        self.ed_target = QLineEdit()
        self.ed_target.setPlaceholderText("自动填入本机网段；也可手填 www.baidu.com / 192.168.1.1 / 192.168.1.1-254 / 192.168.1.0/24")
        self.ed_target.setText(local_subnet_cidr() or "www.baidu.com")
        self.ed_target.setMinimumHeight(30)
        h1.addWidget(self.ed_target, 1)
        h1.addWidget(QLabel("端口："))
        self.cb_port = QComboBox()
        self.cb_port.setEditable(True)
        self.cb_port.addItems(["80", "443", "22", "3389", "8080", "3306", "21", "25", "53", "8000"])
        self.cb_port.setCurrentText("443")
        self.cb_port.setFixedWidth(86)
        h1.addWidget(self.cb_port)
        for text, slot, w in (("开始", self.start, 76), ("停止", self.stop_all, 66),
                              ("清空", self.clear_all, 66), ("导出CSV", self.export_csv, 88)):
            b = QPushButton(text)
            b.setFixedWidth(w)
            b.setMinimumHeight(30)
            b.clicked.connect(slot)
            h1.addWidget(b)
            if text == "开始":
                self.btn_scan = b
            elif text == "停止":
                self.btn_stop = b
                b.setEnabled(False)
        root.addWidget(gb)

        gb2 = QGroupBox("② 检测模式与参数（点选即可）")
        h2 = QHBoxLayout(gb2)
        h2.addWidget(QLabel("模式："))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(MODE_NAMES)
        self.cb_mode.setCurrentIndex(MODE_BOTH)
        self.cb_mode.setMinimumWidth(228)
        h2.addWidget(self.cb_mode)
        h2.addWidget(QLabel("超时 -w："))
        self.cb_timeout = QComboBox()
        self.cb_timeout.addItems(["300", "500", "1000", "2000", "4000"])
        self.cb_timeout.setCurrentText("1000")
        h2.addWidget(self.cb_timeout)
        h2.addWidget(QLabel("ms"))
        h2.addWidget(QLabel("Ping包数 -n："))
        self.cb_pingn = QComboBox()
        self.cb_pingn.addItems(["1", "2", "3", "4", "6", "8", "10"])
        self.cb_pingn.setCurrentText("4")
        h2.addWidget(self.cb_pingn)
        h2.addWidget(QLabel("TCP次数："))
        self.cb_tcpn = QComboBox()
        self.cb_tcpn.addItems(["1", "2", "4", "6", "8", "10"])
        self.cb_tcpn.setCurrentText("4")
        h2.addWidget(self.cb_tcpn)
        h2.addWidget(QLabel("间隔："))
        self.cb_interval = QComboBox()
        self.cb_interval.addItems(["0.2", "0.5", "1", "2", "5"])
        self.cb_interval.setCurrentText("1")
        h2.addWidget(self.cb_interval)
        h2.addWidget(QLabel("秒"))
        self.chk_t = QCheckBox("持续 -t")
        h2.addWidget(self.chk_t)
        h2.addSpacing(8)
        h2.addWidget(QLabel("每行格子数："))
        self.sp_cols = QSpinBox()
        self.sp_cols.setRange(4, 64)
        self.sp_cols.setValue(51)
        h2.addWidget(self.sp_cols)
        h2.addWidget(QLabel("并发："))
        self.sp_conc = QSpinBox()
        self.sp_conc.setRange(1, 256)
        self.sp_conc.setValue(64)
        h2.addWidget(self.sp_conc)
        h2.addStretch(1)
        root.addWidget(gb2)

        gb3 = QGroupBox("③ 结果")
        v = QVBoxLayout(gb3)
        self.lb_legend = QLabel()
        self.lb_legend.setTextFormat(Qt.RichText)
        v.addWidget(self.lb_legend)
        self.stack = QStackedWidget()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont(MONO, 10))
        self.log.setStyleSheet(DARK_QSS)
        self.log.setMaximumBlockCount(5000)
        self.stack.addWidget(self.log)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(3)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.scroll.setWidget(self.grid_host)
        self.stack.addWidget(self.scroll)
        v.addWidget(self.stack, 1)
        root.addWidget(gb3, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.lb_detail = QLabel("")
        self.lb_detail.setStyleSheet("color:#555;")
        bottom.addWidget(self.lb_detail)
        bottom.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(250)
        bottom.addWidget(self.progress)
        root.addLayout(bottom)

        self.cb_mode.currentIndexChanged.connect(self._update_legend)
        self._update_legend()

    def _update_legend(self):
        mode = self.cb_mode.currentIndex()
        if mode == MODE_PING:
            txt = ('图例：<span style="color:#BDBDBD">■</span> 未测　'
                   '<span style="color:#FFD54F">■</span> 测试中　'
                   '<span style="color:#27AE60">■</span> Ping 通　'
                   '<span style="color:#E74C3C">■</span> Ping 不通')
        elif mode == MODE_TCP:
            txt = ('图例：<span style="color:#BDBDBD">■</span> 未测　'
                   '<span style="color:#FFD54F">■</span> 测试中　'
                   '<span style="color:#27AE60">■</span> 端口开放　'
                   '<span style="color:#E74C3C">■</span> 端口不通')
        else:
            txt = ('图例：<span style="color:#BDBDBD">■</span> 未测　'
                   '<span style="color:#FFD54F">■</span> 测试中　'
                   '<span style="color:#27AE60">■</span> 两项都通　'
                   '<span style="color:#8BC34A">■</span> 仅 Ping 通　'
                   '<span style="color:#26C6DA">■</span> 仅端口通　'
                   '<span style="color:#E74C3C">■</span> 都不通')
        self.lb_legend.setText(txt)

    def _make_cell(self, ip):
        lb = QLabel(last_two(ip))
        lb.setFixedSize(CELL_W, CELL_H)
        lb.setAlignment(Qt.AlignCenter)
        f = QFont()
        f.setPointSize(8)
        lb.setFont(f)
        lb._ip = ip
        lb.mousePressEvent = lambda e, i=ip: self._show_detail(i)
        self._paint(lb, C_UNKNOWN, TEXT_DARK)
        lb.setToolTip(ip)
        return lb

    @staticmethod
    def _paint(lb, bg, fg):
        border = QColor(bg).darker(130).name()
        lb.setStyleSheet(f"QLabel{{background:{bg};color:{fg};"
                         f"border:1px solid {border};border-radius:4px;}}")

    def _apply_state(self, ip, state, r=None):
        lb = self.cells.get(ip)
        if not lb:
            return
        color = {"both": C_BOTH, "icmp": C_ICMP, "tcp": C_TCP, "none": C_NONE,
                 "testing": C_TESTING, "unknown": C_UNKNOWN}[state]
        fg = TEXT_DARK if state in ("unknown", "testing", "icmp", "tcp") else TEXT_LIGHT
        self._paint(lb, color, fg)
        words = {"both": "通", "icmp": "仅 Ping 通", "tcp": "仅端口通",
                 "none": "不通", "testing": "测试中", "unknown": "未测"}
        tip = f"{ip}\n{words[state]}"
        if r:
            if r.get("icmp"):
                ok, avg, loss = r["icmp"]
                tip += "\nICMP：" + (f"通 {avg:.0f} ms" if ok and avg is not None else ("通" if ok else "不通"))
            if r.get("tcp"):
                ok, rtt, msg = r["tcp"]
                tip += "\nTCP：" + (f"开放 {rtt:.1f} ms" if ok and rtt is not None else msg)
        lb.setToolTip(tip)

    def _build_grid(self, hosts):
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.cells.clear()
        cols = self.sp_cols.value()
        for idx, ip in enumerate(hosts):
            lb = self._make_cell(ip)
            self.cells[ip] = lb
            self.grid.addWidget(lb, idx // cols, idx % cols)
        self.grid.setRowStretch(self.grid.rowCount(), 1)
        self.grid.setColumnStretch(cols, 1)

    def _port(self):
        try:
            return int(self.cb_port.currentText().strip())
        except Exception:
            return 443

    def start(self):
        self.stop_all(silent=True)
        target = self.ed_target.text().strip()
        mode = self.cb_mode.currentIndex()
        port = self._port()
        if mode in (MODE_TCP, MODE_BOTH) and not (1 <= port <= 65535):
            QMessageBox.warning(self, "端口有误", "端口范围应在 1~65535")
            return
        if is_range(target):
            self._start_segment(target, port, mode)
        else:
            self._start_single(target, port, mode)

    def _start_single(self, host, port, mode):
        self.stack.setCurrentIndex(0)
        self.log.clear()
        self.results.clear()
        self.hosts = [host]
        ip = resolve_host(host)
        self.log.appendPlainText(f"** netcheck  {host}  模式：{MODE_NAMES[mode]} **")
        self.log.appendPlainText(f"** 解析IP：{ip or '未解析'}   端口：{port if mode != MODE_PING else '-'}"
                                 f"   超时 {self.cb_timeout.currentText()}ms **\n")
        count = int(self.cb_tcpn.currentText()) if mode == MODE_TCP else int(self.cb_pingn.currentText())
        if mode == MODE_BOTH:
            count = max(int(self.cb_pingn.currentText()), int(self.cb_tcpn.currentText()))
        self.progress.setRange(0, 0 if self.chk_t.isChecked() else count)
        self.progress.setValue(0)
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        retire_worker(self, "worker")          # 先安置上一个（可能还在收尾）
        self.worker = HostWorker(host, port, mode, count, int(self.cb_pingn.currentText()),
                                 int(self.cb_timeout.currentText()),
                                 float(self.cb_interval.currentText()), self.chk_t.isChecked())
        self.worker.sample.connect(self.on_sample)
        self.worker.done.connect(self.on_single_done)
        self.worker.start()

    def on_sample(self, idx, r):
        ip = r.get("ip") or self.ed_target.text().strip()
        self.results[ip] = r
        parts = []
        if r["icmp"]:
            ok, avg, loss = r["icmp"]
            parts.append("ICMP " + (f"通 {avg:.1f}ms" if ok and avg is not None else ("通" if ok else "不通"))
                         + (f"(丢包{loss:.0f}%)" if ok and loss > 0 else ""))
        if r["tcp"]:
            ok, rtt, msg = r["tcp"]
            parts.append(f"TCP:{self._port()} " + (f"开放 {rtt:.1f}ms" if ok and rtt is not None
                                                   else ("开放" if ok else msg)))
        self.log.appendPlainText(f"[{idx:>3}] {ip:<16} " + "  |  ".join(parts))
        if not self.chk_t.isChecked():
            self.progress.setValue(idx)
        self.lb_detail.setText(f"{ip}  第{idx}次  " + "  |  ".join(parts))

    def on_single_done(self, stat):
        n = stat["n"]
        self.log.appendPlainText("")
        if stat["icmp_rtt"] or stat["icmp_ok"]:
            loss = (n - stat["icmp_ok"]) / n * 100 if n else 0
            self.log.appendPlainText(f"** ICMP ：发送 {n}  成功 {stat['icmp_ok']}  失败 {n - stat['icmp_ok']}"
                                     f"  丢包率 {loss:.1f}% **")
            if stat["icmp_rtt"]:
                rt = stat["icmp_rtt"]
                self.log.appendPlainText(f"** ICMP 延迟：最小 {min(rt):.1f}ms  平均 {sum(rt)/len(rt):.1f}ms"
                                         f"  最大 {max(rt):.1f}ms **")
        if self.cb_mode.currentIndex() in (MODE_TCP, MODE_BOTH):
            loss = (n - stat["tcp_ok"]) / n * 100 if n else 0
            self.log.appendPlainText(f"** TCP  ：发送 {n}  成功 {stat['tcp_ok']}  失败 {n - stat['tcp_ok']}"
                                     f"  丢包率 {loss:.1f}% **")
            if stat["tcp_rtt"]:
                rt = stat["tcp_rtt"]
                self.log.appendPlainText(f"** TCP  延迟：最小 {min(rt):.1f}ms  平均 {sum(rt)/len(rt):.1f}ms"
                                         f"  最大 {max(rt):.1f}ms **")
        bits = []
        if self.cb_mode.currentIndex() in (MODE_PING, MODE_BOTH):
            bits.append(f"ICMP 成功 {stat['icmp_ok']}/{n}")
        if self.cb_mode.currentIndex() in (MODE_TCP, MODE_BOTH):
            bits.append(f"TCP 成功 {stat['tcp_ok']}/{n}")
        self.lb_stats.setText(f"{self.ed_target.text().strip()} · " + " · ".join(bits))
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        retire_worker(self, "worker")
        self.status_cb("测试完成")

    def _start_segment(self, target, port, mode):
        hosts, err = parse_targets(target)
        if err:
            QMessageBox.warning(self, "输入有误", err)
            return
        if len(hosts) > MAX_HOSTS:
            if QMessageBox.question(self, "范围较大",
                                    f"本次要检测 {len(hosts)} 台主机，确定继续？") != QMessageBox.Yes:
                return
        self.stack.setCurrentIndex(1)
        self.hosts = hosts
        self.results.clear()
        self._build_grid(hosts)
        self.progress.setRange(0, len(hosts))
        self.progress.setValue(0)
        self._update_seg_stats()
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_cb(f"正在检测 {len(hosts)} 台主机，并发 {self.sp_conc.value()}")
        retire_worker(self, "seg_worker")
        self.seg_worker = SegmentWorker(hosts, port, mode, int(self.cb_pingn.currentText()),
                                        int(self.cb_timeout.currentText()), self.sp_conc.value())
        self.seg_worker.result.connect(self.on_seg_result)
        self.seg_worker.progress.connect(self.on_seg_progress)
        self.seg_worker.done.connect(self.on_seg_done)
        self.seg_worker.start()

    def on_seg_result(self, host, r):
        self.results[host] = r
        self._apply_state(host, cell_state_from(r, self.cb_mode.currentIndex()), r)

    def on_seg_progress(self, done, total):
        self.progress.setValue(done)
        self._update_seg_stats()

    def on_seg_done(self, good, part, bad):
        self._update_seg_stats()
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        retire_worker(self, "seg_worker")
        self.status_cb(f"完成：全通 {good} · 部分通 {part} · 不通 {bad}")

    def _update_seg_stats(self):
        mode = self.cb_mode.currentIndex()
        total = len(self.hosts)
        cnt = {"both": 0, "icmp": 0, "tcp": 0, "none": 0}
        for r in self.results.values():
            cnt[cell_state_from(r, mode)] += 1
        done = len(self.results)
        if mode == MODE_PING:
            txt = f"共 {total} 台 · Ping 通 {cnt['both']} · 不通 {cnt['none']} · 未测 {total - done}"
        elif mode == MODE_TCP:
            txt = f"共 {total} 台 · 端口开放 {cnt['both']} · 不通 {cnt['none']} · 未测 {total - done}"
        else:
            txt = (f"共 {total} 台 · 全通 {cnt['both']} · 仅Ping {cnt['icmp']} · "
                   f"仅端口 {cnt['tcp']} · 都不通 {cnt['none']} · 未测 {total - done}")
        self.lb_stats.setText(txt)

    def _show_detail(self, ip):
        r = self.results.get(ip)
        if not r:
            self.lb_detail.setText(f"{ip}  未测")
            return
        parts = []
        if r["icmp"]:
            ok, avg, loss = r["icmp"]
            parts.append("ICMP " + (f"通 {avg:.0f}ms" if ok and avg is not None else ("通" if ok else "不通")))
        if r["tcp"]:
            ok, rtt, msg = r["tcp"]
            parts.append(f"TCP:{self._port()} " + (f"开放 {rtt:.1f}ms" if ok and rtt is not None
                                                   else ("开放" if ok else msg)))
        self.lb_detail.setText(f"{ip}  " + "  |  ".join(parts))

    def stop_all(self, silent=False):
        for w in (self.worker, self.seg_worker):
            if w:
                try:
                    w.stop()
                    w.wait(1500)
                except Exception:
                    pass
        retire_worker(self, "worker")
        retire_worker(self, "seg_worker")
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if not silent:
            self.status_cb("已停止")

    def clear_all(self):
        self.stop_all(silent=True)
        self.results.clear()
        self.hosts = []
        self.log.clear()
        self._build_grid([])
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.lb_stats.setText("就绪")
        self.lb_detail.setText("")
        self.status_cb("已清空")

    def export_csv(self):
        if not self.results:
            QMessageBox.information(self, "没有数据", "先跑一次再导出吧")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出结果", "netcheck_result.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        mode = self.cb_mode.currentIndex()
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["目标", "端口", "Ping状态", "Ping延迟(ms)", "Ping丢包(%)",
                            "TCP状态", "TCP延迟(ms)", "TCP说明"])
                for host, r in self.results.items():
                    if isinstance(r, dict):
                        ic, tc = r.get("icmp"), r.get("tcp")
                        w.writerow([host, self._port() if mode != MODE_PING else "",
                                    ("通" if ic[0] else "不通") if ic else "",
                                    f"{ic[1]:.1f}" if ic and ic[1] is not None else "",
                                    f"{ic[2]:.0f}" if ic else "",
                                    ("开放" if tc[0] else "不通") if tc else "",
                                    f"{tc[1]:.1f}" if tc and tc[1] is not None else "",
                                    tc[2] if tc else ""])
                    else:
                        w.writerow([host, "", "", "", "", "", "", str(r)])
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 页2：IP 配置（ipconfig）
# ==========================================================================
def parse_ipconfig(text):
    rows = []
    cur = "系统信息"
    last = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if not raw.startswith((" ", "\t")) and raw.rstrip().rstrip(":").strip():
            # 适配器标题行（无缩进）
            if ":" in raw or "适配器" in raw or "adapter" in raw.lower():
                cur = raw.rstrip().rstrip(":").strip()
                last = None
                continue
        if " : " in raw:
            key, val = raw.split(" : ", 1)
            key = key.strip().rstrip(".").strip()
            val = val.strip()
            if key:
                rows.append([cur, key, val])
                last = [cur, key, val]
                continue
        # 续行（网关/DNS 多值）
        if last is not None and raw.strip():
            if last[2]:
                last[2] += " / " + raw.strip()
            else:
                last[2] = raw.strip()
            rows[-1] = last
    return rows


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 2/8  IP 配置（ipconfig 子集）                                            ║
# ║  关键依赖：parse_ipconfig()、run_cmd("ipconfig /all")、release/renew 接口        ║
# ║  设计：所有改动类的操作都走「子进程 + 提权」自动进管理员模式                       ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class IpConfigTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.raw_text = ""
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 操作（ipconfig）")
        h = QHBoxLayout(gb)
        for text, cmd, w in (("刷新配置", ["ipconfig", "/all"], 96),
                             ("刷新DNS缓存", ["ipconfig", "/flushdns"], 110),
                             ("释放IP", ["ipconfig", "/release"], 88),
                             ("重新获取IP", ["ipconfig", "/renew"], 104),
                             ("查看DNS缓存", ["ipconfig", "/displaydns"], 116)):
            b = QPushButton(text)
            b.setMinimumHeight(30)
            b.setFixedWidth(w)
            b.clicked.connect(lambda _, c=cmd, t=text: self.run(c, t))
            h.addWidget(b)
        self.chk_raw = QCheckBox("显示原始输出")
        self.chk_raw.stateChanged.connect(self._toggle_raw)
        h.addWidget(self.chk_raw)
        h.addStretch(1)
        root.addWidget(gb)

        self.lb_hint = QLabel("提示：释放/重新获取 IP 需要管理员权限；「刷新配置」显示全部适配器详情")
        self.lb_hint.setStyleSheet("color:#666;")
        root.addWidget(self.lb_hint)

        gb2 = QGroupBox("② IP 配置明细")
        v = QVBoxLayout(gb2)
        self.stack = QStackedWidget()
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.stack.addWidget(self.table)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setFont(QFont(MONO, 9))
        self.raw.setStyleSheet(DARK_QSS)
        self.stack.addWidget(self.raw)
        v.addWidget(self.stack, 1)
        root.addWidget(gb2, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.btn_csv = QPushButton("导出CSV")
        self.btn_csv.setFixedWidth(88)
        self.btn_csv.clicked.connect(self.export_csv)
        bottom.addWidget(self.btn_csv)
        root.addLayout(bottom)

        self.run(["ipconfig", "/all"], "刷新配置")

    def run(self, cmd, title):
        self.status_cb(f"正在执行：{' '.join(cmd)}")
        self.lb_stats.setText(f"{title} …")
        retire_worker(self, "worker")
        self.worker = CmdWorker(cmd, timeout=30)
        self.worker.output.connect(lambda t: self._show(cmd, title, t))
        self.worker.start()

    def _show(self, cmd, title, text):
        self.raw_text = text
        self.raw.setPlainText(text)
        if cmd[:1] == ["ipconfig"] and len(cmd) > 1 and cmd[1] == "/all":
            rows = parse_ipconfig(text)
            fill_table(self.table, ["适配器", "项目", "值"], rows)
            self.lb_stats.setText(f"{title} 完成 · 共 {len(rows)} 项")
        else:
            self.stack.setCurrentWidget(self.raw)
            self.lb_stats.setText(f"{title} 完成")
        self.status_cb(f"{title} 完成")

    def _toggle_raw(self):
        self.stack.setCurrentWidget(self.raw if self.chk_raw.isChecked() else self.table)

    def export_csv(self):
        if not self.raw_text:
            QMessageBox.information(self, "没有数据", "先刷新一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 IP 配置", "ipconfig.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            rows = parse_ipconfig(self.raw_text)
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["适配器", "项目", "值"])
                w.writerows(rows)
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 页3：路由追踪（tracert）
# ==========================================================================
# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 3/8  路由追踪 tracert                                                       ║
# ║  关键依赖：Popen 流式抓 tracert 的实时输出（subprocess）                          ║
# ║  设计：把进程绑在 CmdWorker 上，每来一行就 emit 出去                                  ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class TracertTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.hops = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 目标与参数（tracert）")
        h = QHBoxLayout(gb)
        self.ed_target = QLineEdit()
        self.ed_target.setPlaceholderText("要追踪的目标，例如 www.baidu.com 或 8.8.8.8")
        self.ed_target.setText("www.baidu.com")
        self.ed_target.setMinimumHeight(30)
        h.addWidget(self.ed_target, 1)
        self.chk_d = QCheckBox("不解析主机名 -d")
        self.chk_d.setChecked(True)
        h.addWidget(self.chk_d)
        h.addWidget(QLabel("最大跳数 -h："))
        self.cb_hops = QComboBox()
        self.cb_hops.addItems(["8", "15", "30", "64"])
        self.cb_hops.setCurrentText("30")
        h.addWidget(self.cb_hops)
        h.addWidget(QLabel("超时 -w："))
        self.cb_to = QComboBox()
        self.cb_to.addItems(["1000", "2000", "4000"])
        self.cb_to.setCurrentText("1000")
        h.addWidget(self.cb_to)
        h.addWidget(QLabel("ms"))
        self.btn_start = QPushButton("开始追踪")
        self.btn_start.setFixedWidth(96)
        self.btn_start.setMinimumHeight(30)
        self.btn_start.clicked.connect(self.start)
        h.addWidget(self.btn_start)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedWidth(66)
        self.btn_stop.setMinimumHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        h.addWidget(self.btn_stop)
        root.addWidget(gb)

        gb2 = QGroupBox("② 跳点明细")
        v = QVBoxLayout(gb2)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(230)
        v.addWidget(self.table)
        v.addWidget(QLabel("原始输出："))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont(MONO, 9))
        self.log.setStyleSheet(DARK_QSS)
        v.addWidget(self.log, 1)
        root.addWidget(gb2, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.btn_csv = QPushButton("导出CSV")
        self.btn_csv.setFixedWidth(88)
        self.btn_csv.clicked.connect(self.export_csv)
        bottom.addWidget(self.btn_csv)
        root.addLayout(bottom)

    def start(self):
        target = self.ed_target.text().strip()
        if not target:
            QMessageBox.warning(self, "缺少目标", "请输入要追踪的目标")
            return
        cmd = ["tracert", "-h", self.cb_hops.currentText(), "-w", self.cb_to.currentText()]
        if self.chk_d.isChecked():
            cmd.append("-d")
        cmd.append(target)
        self.log.clear()
        self.hops = []
        fill_table(self.table, ["跳", "RTT1", "RTT2", "RTT3", "节点"], [])
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lb_stats.setText(f"追踪 {target} …")
        self.status_cb(f"执行：{' '.join(cmd)}")
        retire_worker(self, "worker")
        self.worker = StreamWorker(cmd)
        self.worker.line.connect(self.on_line)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_line(self, line):
        self.log.appendPlainText(line)
        m = re.match(r"^\s*(\d+)\s+(.*)$", line)
        if m:
            hop = m.group(1)
            rest = m.group(2)
            rtts = re.findall(r"([<\d]+\s*ms|\*)", rest)
            node = rest
            for t in rtts:
                node = node.replace(t, " ", 1)
            node = node.strip()
            rtts = (rtts + ["", "", ""])[:3]
            self.hops.append([hop, rtts[0], rtts[1], rtts[2], node])
            fill_table(self.table, ["跳", "RTT1", "RTT2", "RTT3", "节点"], self.hops)
            self.lb_stats.setText(f"已追踪 {len(self.hops)} 跳")

    def on_done(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        retire_worker(self, "worker")
        self.status_cb(f"追踪完成，共 {len(self.hops)} 跳")

    def stop(self):
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(1500)
            except Exception:
                pass
        retire_worker(self, "worker")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_cb("已停止追踪")

    def export_csv(self):
        if not self.hops:
            QMessageBox.information(self, "没有数据", "先追踪一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出路由追踪", "tracert.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            table_to_csv(self.table, path)
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 页4：ARP 缓存
# ==========================================================================
def parse_arp(text):
    rows = []
    iface = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^接口[:：]\s*(\S+)\s*---\s*(\S+)$", s)
        if m:
            iface = f"{m.group(1)} ({m.group(2)})"
            continue
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-]{11,17})\s+(\S+)$", s)
        if m:
            rows.append([iface, m.group(1), m.group(2), m.group(3)])
    return rows


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 4/8  ARP 缓存                                                                  ║
# ║  关键依赖：parse_arp() 把 arp -a 的输出解析成表格                                  ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class ArpTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.rows = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 操作（arp）")
        h = QHBoxLayout(gb)
        b1 = QPushButton("刷新 ARP 缓存")
        b1.setMinimumHeight(30)
        b1.setFixedWidth(120)
        b1.clicked.connect(lambda: self.run(["arp", "-a"], "刷新 ARP"))
        h.addWidget(b1)
        self.btn_del = QPushButton("删除选中项")
        self.btn_del.setMinimumHeight(30)
        self.btn_del.setFixedWidth(104)
        self.btn_del.clicked.connect(self.delete_selected)
        h.addWidget(self.btn_del)
        self.btn_clear = QPushButton("清空缓存(需管理员)")
        self.btn_clear.setMinimumHeight(30)
        self.btn_clear.setFixedWidth(150)
        self.btn_clear.clicked.connect(lambda: self.run(
            ["netsh", "interface", "ip", "delete", "arpcache"], "清空 ARP 缓存"))
        h.addWidget(self.btn_clear)
        h.addStretch(1)
        root.addWidget(gb)

        self.lb_hint = QLabel("提示：ARP 缓存记录「IP ↔ MAC」的对应关系；删除单条后若还需通信会自动重新学习")
        self.lb_hint.setStyleSheet("color:#666;")
        root.addWidget(self.lb_hint)

        gb2 = QGroupBox("② ARP 表")
        v = QVBoxLayout(gb2)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        v.addWidget(self.table, 1)
        root.addWidget(gb2, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.btn_csv = QPushButton("导出CSV")
        self.btn_csv.setFixedWidth(88)
        self.btn_csv.clicked.connect(self.export_csv)
        bottom.addWidget(self.btn_csv)
        root.addLayout(bottom)

        self.run(["arp", "-a"], "刷新 ARP")

    def run(self, cmd, title):
        self.status_cb(f"正在执行：{' '.join(cmd)}")
        retire_worker(self, "worker")
        self.worker = CmdWorker(cmd, timeout=20)
        self.worker.output.connect(lambda t, c=cmd, ti=title: self._show(t, c, ti))
        self.worker.start()

    def _show(self, text, cmd, title):
        if cmd[:2] == ["arp", "-a"]:
            self.rows = parse_arp(text)
            fill_table(self.table, ["接口", "IP 地址", "物理地址(MAC)", "类型"], self.rows)
            self.lb_stats.setText(f"共 {len(self.rows)} 条 ARP 记录")
        else:
            self.lb_stats.setText(f"{title} 结果：{text.strip()[:60]}")
        self.status_cb(f"{title} 完成")

    def delete_selected(self):
        it = self.table.currentItem()
        if not it:
            QMessageBox.information(self, "未选中", "请先在表格里选一行")
            return
        row = it.row()
        ip_item = self.table.item(row, 1)
        if not ip_item:
            return
        ip = ip_item.text()
        if QMessageBox.question(self, "确认", f"删除 ARP 记录：{ip} ？") != QMessageBox.Yes:
            return
        self.run(["arp", "-d", ip], f"删除 {ip}")

    def export_csv(self):
        if not self.rows:
            QMessageBox.information(self, "没有数据", "先刷新一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 ARP 表", "arp.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            table_to_csv(self.table, path)
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 页5：网络连接（netstat）
# ==========================================================================
def parse_netstat(text):
    rows = []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(TCP|UDP)\s+(\S+)\s+(\S+)\s+(\S+)?\s*(\d+)$", s)
        if m:
            proto, local, foreign, state, pid = m.groups()
            rows.append([proto, local, foreign, state or "", pid])
            continue
        m = re.match(r"^(TCP|UDP)\s+(\S+)\s+(\S+)\s+(\d+)$", s)
        if m:
            proto, local, foreign, pid = m.groups()
            rows.append([proto, local, foreign, "", pid])
    return rows


def pid_name_map():
    mapping = {}
    if psutil is None:
        return mapping
    for p in psutil.process_iter(["pid", "name"]):
        try:
            mapping[str(p.info["pid"])] = p.info["name"] or ""
        except Exception:
            continue
    return mapping


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 5/8  网络连接 netstat -ano                                                     ║
# ║  关键依赖：parse_netstat()、pid_name_map() 通过 PID 反查进程名（tasklist）        ║
# ║  特色：支持筛选 + 导出 CSV                                                               ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class NetstatTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.raw_rows = []
        self.pnames = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 操作（netstat -ano）")
        h = QHBoxLayout(gb)
        b1 = QPushButton("刷新连接")
        b1.setMinimumHeight(30)
        b1.setFixedWidth(96)
        b1.clicked.connect(lambda: self.run(["netstat", "-ano"]))
        h.addWidget(b1)
        b2 = QPushButton("刷新+解析端口名")
        b2.setMinimumHeight(30)
        b2.setFixedWidth(140)
        b2.setToolTip("-ano 的基础上加 -b 之外的端口名解析较慢，这里用进程名代替")
        b2.clicked.connect(lambda: self.run(["netstat", "-ano"]))
        h.addWidget(b2)
        h.addStretch(1)
        root.addWidget(gb)

        gb2 = QGroupBox("② 筛选")
        h2 = QHBoxLayout(gb2)
        h2.addWidget(QLabel("协议："))
        self.cb_proto = QComboBox()
        self.cb_proto.addItems(["全部", "TCP", "UDP"])
        h2.addWidget(self.cb_proto)
        h2.addWidget(QLabel("状态："))
        self.cb_state = QComboBox()
        self.cb_state.addItems(["全部", "LISTENING", "ESTABLISHED", "TIME_WAIT", "CLOSE_WAIT",
                                "SYN_SENT", "UDP"])
        h2.addWidget(self.cb_state)
        h2.addWidget(QLabel("搜索："))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("按 IP / 端口 / PID / 进程名过滤")
        self.ed_search.setMinimumHeight(28)
        h2.addWidget(self.ed_search, 1)
        b3 = QPushButton("应用")
        b3.setFixedWidth(70)
        b3.setMinimumHeight(28)
        b3.clicked.connect(self.apply_filter)
        h2.addWidget(b3)
        b4 = QPushButton("重置")
        b4.setFixedWidth(70)
        b4.setMinimumHeight(28)
        b4.clicked.connect(self.reset_filter)
        h2.addWidget(b4)
        root.addWidget(gb2)

        for w in (self.cb_proto, self.cb_state):
            w.currentIndexChanged.connect(self.apply_filter)
        self.ed_search.textChanged.connect(self.apply_filter)

        gb3 = QGroupBox("③ 连接列表")
        v = QVBoxLayout(gb3)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        v.addWidget(self.table, 1)
        root.addWidget(gb3, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.btn_csv = QPushButton("导出CSV")
        self.btn_csv.setFixedWidth(88)
        self.btn_csv.clicked.connect(self.export_csv)
        bottom.addWidget(self.btn_csv)
        root.addLayout(bottom)

        self.run(["netstat", "-ano"])

    def run(self, cmd):
        self.status_cb(f"正在执行：{' '.join(cmd)}")
        self.lb_stats.setText("读取中 …")
        retire_worker(self, "worker")
        self.worker = CmdWorker(cmd, timeout=60)
        self.worker.output.connect(self._show)
        self.worker.start()

    def _show(self, text):
        self.pnames = pid_name_map()
        self.raw_rows = parse_netstat(text)
        self.apply_filter()
        self.status_cb(f"共读取 {len(self.raw_rows)} 条连接")

    def apply_filter(self):
        proto = self.cb_proto.currentText()
        state = self.cb_state.currentText()
        key = self.ed_search.text().strip().lower()
        out = []
        for proto_, local, foreign, st, pid in self.raw_rows:
            if proto != "全部" and proto_ != proto:
                continue
            if state != "全部":
                if state == "UDP":
                    if proto_ != "UDP":
                        continue
                elif st != state:
                    continue
            name = self.pnames.get(pid, "")
            if key and not (key in local.lower() or key in foreign.lower()
                            or key in pid or key in name.lower()):
                continue
            out.append([proto_, local, foreign, st, pid, name])
        fill_table(self.table, ["协议", "本地地址", "外部地址", "状态", "PID", "进程名"], out)
        self.lb_stats.setText(f"显示 {len(out)} / {len(self.raw_rows)} 条")

    def reset_filter(self):
        self.cb_proto.setCurrentText("全部")
        self.cb_state.setCurrentText("全部")
        self.ed_search.clear()
        self.apply_filter()

    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "没有数据", "先刷新一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出连接列表", "netstat.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            table_to_csv(self.table, path)
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 页6：端口扫描
# ==========================================================================
def parse_port_text(text):
    """解析自定义端口字符串，支持 80,443,22 / 10000-10005，返回有序去重列表。
    非法的数字/范围自动跳过（不报错）。"""
    out = []
    seen = set()
    for part in re.split(r"[,\s]+", (text or "").strip()):
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                a, b = int(a), int(b)
                if not (1 <= a <= 65535 and 1 <= b <= 65535):
                    continue
                if b < a:
                    a, b = b, a
                for p in range(a, b + 1):
                    if p not in seen:
                        seen.add(p)
                        out.append(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
            except ValueError:
                continue
            if not (1 <= p <= 65535):
                continue
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


class PortScanWorker(QThread):
    progress = Signal(int, int)
    result = Signal(int, bool, object, str)        # port, ok, rtt, msg
    done = Signal(int, int, float)                # open[count], closed[count], elapsed

    def __init__(self, host, ports, timeout_ms, concurrency):
        super().__init__()
        self.host, self.ports = host, list(ports)
        self.timeout_ms = timeout_ms
        self.concurrency = max(1, min(concurrency, 256))
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        t0 = time.perf_counter()
        done_n = open_n = closed_n = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            futs = {ex.submit(tcp_ping, self.host, p, self.timeout_ms): p for p in self.ports}
            for fut in as_completed(futs):
                if self._stop:
                    for f in futs:
                        f.cancel()
                    break
                port = futs[fut]
                try:
                    ok, rtt, msg, ip = fut.result()
                except Exception:
                    ok, rtt, msg, ip = False, None, "异常", ""
                done_n += 1
                if ok:
                    open_n += 1
                else:
                    closed_n += 1
                self.result.emit(port, ok, rtt, msg)
                self.progress.emit(done_n, len(self.ports))
        self.done.emit(open_n, closed_n, time.perf_counter() - t0)


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 6/8  端口扫描                                                                     ║
# ║  关键依赖：PortScanWorker（并发连接 + 判 2xx/timeout）                              ║
# ║  并发：ThreadPoolExecutor 把 PORT_SERVICES 列表里的端口批量试                   ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class PortScanTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.rows = []                    # [port, service, state, rtt, msg]
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 目标与端口列表")
        v = QVBoxLayout(gb)

        # 目标 + 预设
        h = QHBoxLayout()
        h.addWidget(QLabel("目标主机/IP："))
        self.ed_target = QLineEdit()
        self.ed_target.setPlaceholderText("例如 www.baidu.com 或 192.168.1.1")
        self.ed_target.setText("127.0.0.1")
        self.ed_target.setMinimumHeight(30)
        h.addWidget(self.ed_target, 1)
        h.addWidget(QLabel("预设："))
        self.cb_preset = QComboBox()
        self.cb_preset.addItems(list(PORT_PRESETS.keys()))
        h.addWidget(self.cb_preset)
        v.addLayout(h)

        # 自定义端口
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("自定义额外端口："))
        self.ed_extra = QLineEdit()
        self.ed_extra.setPlaceholderText("可选，逗号或空格分隔，支持范围：10000-10005  例如 8080,9200,5000-5010")
        self.ed_extra.setMinimumHeight(28)
        h2.addWidget(self.ed_extra, 1)
        self.lb_count = QLabel("（将扫描 0 个端口）")
        self.lb_count.setStyleSheet("color:#666;")
        h2.addWidget(self.lb_count)
        v.addLayout(h2)

        # 参数 + 按钮
        h4 = QHBoxLayout()
        h4.addWidget(QLabel("超时 -w："))
        self.cb_timeout = QComboBox()
        self.cb_timeout.addItems(["300", "500", "1000", "2000", "4000"])
        self.cb_timeout.setCurrentText("1000")
        h4.addWidget(self.cb_timeout)
        h4.addWidget(QLabel("ms"))
        h4.addWidget(QLabel("并发："))
        self.sp_conc = QSpinBox()
        self.sp_conc.setRange(1, 256)
        self.sp_conc.setValue(64)
        h4.addWidget(self.sp_conc)
        h4.addSpacing(12)
        for text, slot, w in (("开始扫描", self.start, 96), ("停止", self.stop, 66),
                              ("清空", self.clear_all, 66), ("导出CSV", self.export_csv, 88)):
            b = QPushButton(text)
            b.setFixedWidth(w)
            b.setMinimumHeight(30)
            b.clicked.connect(slot)
            h4.addWidget(b)
            if text == "开始扫描":
                self.btn_start = b
            elif text == "停止":
                self.btn_stop = b
                b.setEnabled(False)
        h4.addStretch(1)
        v.addLayout(h4)

        self.cb_preset.currentIndexChanged.connect(self._refresh_count)
        self.ed_extra.textChanged.connect(self._refresh_count)
        root.addWidget(gb)

        gb2 = QGroupBox("② 扫描结果")
        v2 = QVBoxLayout(gb2)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        v2.addWidget(self.table, 1)
        root.addWidget(gb2, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        bottom.addWidget(self.progress)
        root.addLayout(bottom)

        self._refresh_count()

    def _ports_to_scan(self):
        ports = list(PORT_PRESETS.get(self.cb_preset.currentText(), []))
        extras = parse_port_text(self.ed_extra.text())
        for p in extras:
            if p not in ports:
                ports.append(p)
        return sorted(set(ports))

    def _refresh_count(self):
        n = len(self._ports_to_scan())
        self.lb_count.setText(f"（将扫描 {n} 个端口）")

    def start(self):
        host = self.ed_target.text().strip()
        if not host:
            QMessageBox.warning(self, "缺少目标", "请输入目标主机或 IP")
            return
        ports = self._ports_to_scan()
        if not ports:
            QMessageBox.information(self, "没有端口", "预设+自定义加起来没有有效端口")
            return
        self.rows = []
        fill_table(self.table, ["端口", "服务", "状态", "延迟(ms)", "备注"], [])
        self.progress.setRange(0, len(ports))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lb_stats.setText(f"开始扫描 {host} 的 {len(ports)} 个端口 …")
        self.status_cb(f"端口扫描：{host} × {len(ports)} 端口")
        retire_worker(self, "worker")
        self.worker = PortScanWorker(host, ports, int(self.cb_timeout.currentText()),
                                      self.sp_conc.value())
        self.worker.progress.connect(self.on_progress)
        self.worker.result.connect(self.on_result)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_progress(self, done, total):
        self.progress.setValue(done)

    def on_result(self, port, ok, rtt, msg):
        service = PORT_SERVICES.get(port, "")
        state = "开放" if ok else "关闭"
        rtt_s = f"{rtt:.1f}" if rtt is not None else "-"
        row = [port, service, state, rtt_s, "" if ok else msg]
        self.rows.append(row)

        # 用颜色标识：开放=绿底白字；关闭=粉底深字
        bg = "#27AE60" if ok else "#F8D7DA"
        fg = "#FFFFFF" if ok else "#212121"
        r_idx = self.table.rowCount()
        self.table.insertRow(r_idx)
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            if c == 2 or c == 3:
                it.setData(Qt.UserRole, str(val))
            it.setBackground(QColor(bg))
            it.setForeground(QColor(fg))
            if c == 0 or c == 3:
                it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r_idx, c, it)
        # 按端口排序展示前，保持原顺序即可
        self.lb_stats.setText(f"已完成 {len(self.rows)} / {len(self._ports_to_scan())}（开放 1, 关闭 0）".replace(
            f" 1, 关闭 0", f" {sum(1 for r in self.rows if r[2]=='开放')}, 关闭 {sum(1 for r in self.rows if r[2]=='关闭')}"))

    def on_done(self, open_n, closed_n, elapsed):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        retire_worker(self, "worker")
        self.rows.sort(key=lambda r: r[0])
        fill_table(self.table, ["端口", "服务", "状态", "延迟(ms)", "备注"], self.rows)
        for row_idx, row in enumerate(self.rows):
            bg = "#27AE60" if row[2] == "开放" else "#F8D7DA"
            fg = "#FFFFFF" if row[2] == "开放" else "#212121"
            for c in range(self.table.columnCount()):
                it = self.table.item(row_idx, c)
                if it:
                    it.setBackground(QColor(bg))
                    it.setForeground(QColor(fg))
                    if c in (0, 3):
                        it.setTextAlignment(Qt.AlignCenter)
        self.lb_stats.setText(f"完成：{open_n} 个开放 / {closed_n} 个关闭 · 耗时 {elapsed:.2f}s")
        self.status_cb(f"端口扫描完成：{open_n} 开放 / {closed_n} 关闭")

    def stop(self):
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(1500)
            except Exception:
                pass
        retire_worker(self, "worker")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_cb("已停止扫描")

    def clear_all(self):
        self.stop_all(silent=True)
        self.rows = []
        fill_table(self.table, ["端口", "服务", "状态", "延迟(ms)", "备注"], [])
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.lb_stats.setText("就绪")
        self.status_cb("已清空")

    def export_csv(self):
        if not self.rows:
            QMessageBox.information(self, "没有数据", "先扫一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出端口扫描", "portscan.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            table_to_csv(self.table, path)
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def stop_all(self, silent=False):
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(1500)
            except Exception:
                pass
        retire_worker(self, "worker")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if not silent:
            self.status_cb("已停止")


# ==========================================================================
# 页7：DNS 查询
# ==========================================================================
class DnsWorker(QThread):
    rows = Signal(list)
    raw = Signal(str)
    done = Signal(dict)

    def __init__(self, target, rtype, server):
        super().__init__()
        self.target, self.rtype, self.server = target, rtype, server

    def run(self):
        import dns.resolver
        import dns.rdatatype
        import dns.reversename
        info = {"ok": False, "error": "", "elapsed": 0.0, "ip": ""}

        try:
            info["ip"] = socket.gethostbyname(self.target)
        except Exception:
            pass

        # 构造 resolver
        rs = dns.resolver.Resolver()
        rs.timeout = 3
        rs.lifetime = 5
        if self.server.strip():
            try:
                rs.nameservers = [s.strip() for s in self.server.split(",") if s.strip()]
            except Exception:
                pass

        types_to_query = []
        if self.rtype == "ALL":
            types_to_query = ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "SRV", "CAA"]
        else:
            types_to_query = [self.rtype]

        out = []
        for t in types_to_query:
            try:
                start = time.perf_counter()
                ans = rs.resolve(self.target, t)
                elapsed = (time.perf_counter() - start) * 1000
                ttl = ans.rrset.ttl if ans.rrset else 0
                for r in ans:
                    val = self._format_value(t, r)
                    out.append([t, self.target, str(ttl), val])
            except dns.resolver.NoAnswer:
                pass
            except Exception as e:
                out.append([t, self.target, "—", f"查询失败：{e.__class__.__name__}"])

        self.rows.emit(out)

        # 顺便跑一下 nslookup，拿到原始输出（避免中文/英文差异，直接看就好）
        try:
            cmd = ["nslookup", "-type=" + self.rtype, self.target]
            if self.server.strip():
                cmd.append(self.server.strip())
            out_text = run_cmd(cmd, timeout=10)
            self.raw.emit(out_text)
        except Exception as e:
            try:
                self.raw.emit(f"nslookup 执行失败：{e.__class__.__name__}: {e}")
            except Exception:
                pass

        # ★ done 必须放在最后发！UI 一收到 done 就会释放这个 worker；
        #   如果先发 done 再跑 nslookup，主线程可能在子线程还在运行时销毁 QThread
        #   → Qt 直接 abort，程序「自己退出」（在别的电脑上尤其容易触发）。
        info["ok"] = True
        self.done.emit(info)

    @staticmethod
    def _format_value(t, r):
        if t == "A":
            return f"{r.address}（A）"
        if t == "AAAA":
            return f"{r.address}（AAAA）"
        if t == "CNAME":
            return f"{r.target.to_text()}（CNAME）"
        if t == "MX":
            return f"优先级 {r.preference} → {r.exchange.to_text()}"
        if t == "NS":
            return f"{r.target.to_text()}（NS）"
        if t == "TXT":
            txt = r.to_text()
            return ("TXT: " + txt[:120] + ("…" if len(txt) > 120 else "")) if txt else "(空)"
        if t == "SOA":
            return (f"主DNS {r.mname.to_text()} / 联系人 {r.rname.to_text()} "
                    f"/ 序列号 {r.serial} / 刷新 {r.refresh}s / 重试 {r.retry}s")
        if t == "SRV":
            return f"{r.target.to_text()} {r.port}（优先级 {r.priority}, 权重 {r.weight}）"
        if t == "CAA":
            return f"{r.flags} {r.tag} \"{r.value}\""
        return r.to_text()


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 7/8  DNS 查询                                                                   ║
# ║  关键依赖：DnsWorker（dnspython）+ run_cmd("nslookup ...")                         ║
# ║  ★ v9.6 关键修复：DnsWorker.run() 必须把 done 信号放最后发（详见 2541 行附近）         ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class DnsLookupTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.rows = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 目标与查询参数")
        h = QHBoxLayout(gb)
        h.addWidget(QLabel("域名 / IP："))
        self.ed_target = QLineEdit()
        self.ed_target.setPlaceholderText("例如 www.baidu.com 或 8.8.8.8（IP 自动尝试反向解析）")
        self.ed_target.setText("www.baidu.com")
        self.ed_target.setMinimumHeight(30)
        h.addWidget(self.ed_target, 1)
        h.addWidget(QLabel("类型："))
        self.cb_type = QComboBox()
        self.cb_type.addItems([label + "：" + desc for label, desc in DNS_TYPES])
        self.cb_type.setCurrentIndex(0)
        h.addWidget(self.cb_type)
        h.addWidget(QLabel("DNS 服务器（可选）："))
        self.ed_server = QLineEdit()
        self.ed_server.setPlaceholderText("留空用系统默认，如 8.8.8.8 或 114.114.114.114")
        self.ed_server.setMinimumHeight(30)
        h.addWidget(self.ed_server, 1)
        for text, slot, w in (("查询", self.start, 70), ("清空", self.clear_all, 66),
                              ("导出CSV", self.export_csv, 88)):
            b = QPushButton(text)
            b.setFixedWidth(w)
            b.setMinimumHeight(30)
            b.clicked.connect(slot)
            h.addWidget(b)
            if text == "查询":
                self.btn_query = b
        root.addWidget(gb)

        gb2 = QGroupBox("② 查询结果")
        v = QVBoxLayout(gb2)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        v.addWidget(self.table, 1)

        v.addWidget(QLabel("nslookup 原始输出（参考）："))
        self.raw_out = QPlainTextEdit()
        self.raw_out.setReadOnly(True)
        self.raw_out.setFont(QFont(MONO, 9))
        self.raw_out.setStyleSheet(DARK_QSS)
        self.raw_out.setMaximumHeight(160)
        v.addWidget(self.raw_out)
        root.addWidget(gb2, 1)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        root.addLayout(bottom)

    def start(self):
        target = self.ed_target.text().strip()
        if not target:
            QMessageBox.warning(self, "缺少目标", "请输入域名或 IP")
            return
        rtype = DNS_TYPES[self.cb_type.currentIndex()][0]
        self.rows = []
        fill_table(self.table, ["类型", "名称", "TTL", "值"], [])
        self.raw_out.clear()
        self.lb_stats.setText(f"查询 {target} 的 {rtype} 记录 …")
        self.status_cb(f"DNS 查询：{target} / {rtype}")
        retire_worker(self, "worker")
        self.worker = DnsWorker(target, rtype, self.ed_server.text())
        self.worker.rows.connect(self.on_rows)
        self.worker.raw.connect(self.on_raw)
        self.worker.done.connect(self.on_done)
        self.btn_query.setEnabled(False)
        self.worker.start()

    def on_rows(self, rows):
        self.rows.extend(rows)
        fill_table(self.table, ["类型", "名称", "TTL", "值"], self.rows)

    def on_raw(self, text):
        self.raw_out.setPlainText(text)

    def on_done(self, info):
        self.btn_query.setEnabled(True)
        retire_worker(self, "worker")
        ip = info.get("ip", "")
        bits = [f"共 {len(self.rows)} 条结果"]
        if ip:
            bits.append(f"该域名解析 IP：{ip}")
        self.lb_stats.setText(" · ".join(bits))
        self.status_cb("DNS 查询完成")

    def clear_all(self):
        self.rows = []
        fill_table(self.table, ["类型", "名称", "TTL", "值"], [])
        self.raw_out.clear()
        self.lb_stats.setText("就绪")
        self.status_cb("已清空")

    def export_csv(self):
        if not self.rows:
            QMessageBox.information(self, "没有数据", "先查一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 DNS 查询", "dns.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            table_to_csv(self.table, path)
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 页8：宽带测速
# ==========================================================================
class SpeedTestWorker(QThread):
    progress = Signal(str, int, int)        # phase, done, total
    result_row = Signal(str, str, str, str)  # 区域, 类型, 节点, 结果文本
    summary = Signal(str, dict)             # 区域, 汇总 dict
    net_info = Signal(dict)                 # 本机外网信息（IP/所在地/运营商）
    done = Signal()

    def __init__(self, latency_count, download_sec, upload_size_mb, upload_sec):
        super().__init__()
        self.latency_count = latency_count
        self.download_sec = download_sec
        self.upload_size_mb = upload_size_mb
        self.upload_sec = upload_sec
        self._stop = False
        # 全局进度：每个区域跑 latency + download + upload 共 N 个测点
        self._global_done = 0
        self._global_total = sum(
            len(SPEED_TEST_NODES["latency"].get(s, []))
            + len(SPEED_TEST_NODES["download"].get(s, []))
            + len(SPEED_TEST_NODES["upload"].get(s, []))
            for s in ("国内", "国外")
        )

    def stop(self):
        self._stop = True

    def _emit_phase(self, msg, in_step_done=None, in_step_total=None):
        """统一发出 phase 信号；可选给出本步骤内 i/total，但仍叠加全局进度"""
        self.progress.emit(msg, self._global_done, self._global_total)

    def _bump(self):
        self._global_done += 1

    def _run_region(self, scope):
        """对一个区域（国内/国外）跑延迟 + 下载 + 上传，返回该区域汇总"""
        lat_results = []
        dl_results = []
        up_results = []

        # 1) 延迟：并行发（Windows ping 包间隔固定 ~1s，串行 5 个节点要 20s，
        #    并行后总时长≈最慢的那个节点）
        nodes_lat = SPEED_TEST_NODES["latency"].get(scope, [])
        if nodes_lat:
            self._emit_phase(f"[{scope}] 延迟测试（{len(nodes_lat)} 节点并行）")
            workers = max(1, min(8, len(nodes_lat)))

            def _ping_one(item):
                nm, hs = item
                t = time.perf_counter()
                ts = icmp_ping_times(hs, self.latency_count, 1000)
                return nm, hs, ts, time.perf_counter() - t

            try:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = [ex.submit(_ping_one, it) for it in nodes_lat]
                    pinged = [f.result() for f in futs]
            except Exception:
                pinged = [_ping_one(it) for it in nodes_lat]
            for name, host, times, dt in pinged:
                if self._stop:
                    break
                if times:
                    mn, mx, avg = min(times), max(times), sum(times) / len(times)
                    mdev = statistics.pstdev(times) if len(times) > 1 else 0.0
                    loss = (self.latency_count - len(times)) / self.latency_count * 100
                    s = f"{mn}ms（{mn}~{mx}ms，均 {avg:.1f}，抖动 ±{mdev:.1f}，丢包 {loss:.0f}%）[{dt:.1f}s]"
                    lat_results.append({"name": name, "host": host, "min": mn, "avg": avg,
                                        "mdev": mdev, "loss": loss, "ok": True})
                else:
                    s = f"全部超时 [{dt:.1f}s]"
                    lat_results.append({"name": name, "host": host, "ok": False})
                self.result_row.emit(scope, "延迟", f"{name} ({host})", s)
                self._bump()
                self._emit_phase(f"[{scope}] 延迟 {name}")
                self.msleep(10)

        # 2) 下载（多连接 + 稳态法；单节点串行，避免互相抢带宽）
        nodes_dl = SPEED_TEST_NODES["download"].get(scope, [])
        for i, (name, url) in enumerate(nodes_dl):
            if self._stop:
                break
            self._emit_phase(f"[{scope}] 下载 {i+1}/{len(nodes_dl)} {name}（4 连接稳态法）")
            t0 = time.perf_counter()
            sp, n, nconn = http_download_speed(url, max_time=self.download_sec,
                                               streams=4, skip_sec=2.0)
            dt = time.perf_counter() - t0
            if sp > 0:
                mb_s = sp / (1024 * 1024)
                mbps = sp * 8 / 1_000_000
                s = f"{mb_s:.1f} MB/s = {mbps:.0f} Mbps（{nconn}连接稳态 / 共取 {n/1024/1024:.0f} MB / {dt:.1f}s）"
                dl_results.append({"name": name, "speed": sp, "mbps": mbps,
                                   "streams": nconn, "bytes": n})
            else:
                if n > 0:
                    s = f"连接不稳（仅取到 {n/1024/1024:.1f} MB / {dt:.1f}s）"
                elif dt >= 2.9:
                    s = f"不可达（{dt:.1f}s 内 0 字节，提前放弃）"
                else:
                    s = f"失败 [{dt:.1f}s]"
            self.result_row.emit(scope, "下载", name, s)
            self._bump()
            self._emit_phase(f"[{scope}] 下载 {i+1}/{len(nodes_dl)} {name}")
            self.msleep(10)

        # 3) 上传
        nodes_up = SPEED_TEST_NODES["upload"].get(scope, [])
        for i, (name, url) in enumerate(nodes_up):
            if self._stop:
                break
            self._emit_phase(f"[{scope}] 上传 {i+1}/{len(nodes_up)} {name}")
            t0 = time.perf_counter()
            sp = http_upload_speed(url, size_mb=self.upload_size_mb,
                                   max_time=self.upload_sec, warmup_sec=3.0)
            dt = time.perf_counter() - t0
            if sp > 0:
                mb_s = sp / (1024 * 1024)
                mbps = sp * 8 / 1_000_000
                s = f"{mb_s:.1f} MB/s = {mbps:.0f} Mbps（POST {self.upload_size_mb} MB 稳态 / {dt:.1f}s）"
                up_results.append({"name": name, "speed": sp, "mbps": mbps})
            else:
                s = f"暂不可用 [{dt:.1f}s]"
            self.result_row.emit(scope, "上传", name, s)
            self._bump()
            self._emit_phase(f"[{scope}] 上传 {i+1}/{len(nodes_up)} {name}")
            self.msleep(20)

        # 取最佳延迟 / 下载 / 上传
        best_lat = next((r for r in lat_results if r.get("ok")), None)
        best_dl = max(dl_results, key=lambda x: x["speed"]) if dl_results else None
        best_up = max(up_results, key=lambda x: x["speed"]) if up_results else None

        # 下载速率：多节点时同时给「最大」和「中位数」——中位数抗单个节点抽风
        dl_speeds = sorted(r["speed"] for r in dl_results) if dl_results else []
        if dl_speeds:
            if len(dl_speeds) >= 3:
                dl_med = dl_speeds[len(dl_speeds) // 2]
            else:
                dl_med = sum(dl_speeds) / len(dl_speeds)
        else:
            dl_med = 0.0

        down_mbps = best_dl["mbps"] if best_dl else 0.0
        down_med_mbps = dl_med * 8 / 1_000_000 if dl_med else 0.0
        up_mbps = best_up["mbps"] if best_up else 0.0
        lat_min = best_lat["min"] if best_lat else None

        evaluation = evaluate_broadband(down_mbps, up_mbps, lat_min, scope=scope)

        return {
            "scope": scope,
            "download_bps": best_dl["speed"] if best_dl else 0.0,
            "download_med_bps": dl_med,
            "download_med_mbps": down_med_mbps,
            "dl_node_count": len(dl_results),
            "upload_bps": best_up["speed"] if best_up else 0.0,
            "download_mbps": down_mbps,
            "upload_mbps": up_mbps,
            "latency_min": lat_min,
            "latency_mdev": best_lat["mdev"] if best_lat else None,
            "latency_loss": best_lat["loss"] if best_lat else None,
            "best_node": best_lat["name"] if best_lat else "—",
            "best_dl_node": best_dl["name"] if best_dl else "—",
            "best_up_node": best_up["name"] if best_up else "—",
            "dl_all": dl_results,
            "up_all": up_results,
            "lat_all": lat_results,
            "evaluation": evaluation,
        }

    def run(self):
        try:
            # 0) 先查本机外网信息（此时网络空闲，最准；失败也不影响后续测速）
            self._emit_phase("查询本机外网信息…")
            try:
                self.net_info.emit(query_public_ip())
            except Exception:
                self.net_info.emit({"ok": False, "source": "—", "ip": "—",
                                    "location": "—", "isp": "—", "asn": "",
                                    "note": "查询异常"})
            for scope in ("国内", "国外"):
                if self._stop:
                    break
                self._emit_phase(f"开始测「{scope}」节点")
                summary = self._run_region(scope)
                self.summary.emit(scope, summary)
        except Exception as e:
            import traceback
            self._emit_phase(f"测速异常：{e.__class__.__name__} {e}")
            try:
                print(traceback.format_exc())
            except Exception:
                pass
        self._emit_phase("测速完成")
        self.done.emit()


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ TAB 8/8  宽带测速（最大块）                                                          ║
# ║  关键依赖：SPEED_TEST_NODES（节点字典）、http_download_speed()、                          ║
# ║             http_upload_speed()、query_public_ip()、evaluate_broadband()               ║
# ║  流程：节点编排 → 并发测速（每个节点一个 SpeedTestWorker）→ 汇总 → 显示档位评价            ║
# ║  ★ 想理解「为什么国内数字差异大」看 595 行 http_download_speed 的 docstring               ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class SpeedTestTab(QWidget):
    def __init__(self, status_cb=None):
        super().__init__()
        self.status_cb = status_cb or (lambda m: None)
        self.worker = None
        self.rows = []
        self.summaries = {}        # scope -> summary dict
        self.eval_widgets = {}    # scope -> 评价面板内的 QLabel 字典
        self.info_labels = {}     # 外网信息标签
        self.net_info = None      # 最近一次外网信息
        self._t_start = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    def _tick(self):
        if self._t_start:
            el = time.perf_counter() - self._t_start
            self.lbl_elapsed.setText(f"已用 {el:.1f}s")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        gb = QGroupBox("① 配置")
        h = QHBoxLayout(gb)
        h.addWidget(QLabel("延迟包数："))
        self.cb_count = QComboBox()
        self.cb_count.addItems(["3", "5", "10", "20"])
        self.cb_count.setCurrentText("3")
        h.addWidget(self.cb_count)
        h.addSpacing(10)
        h.addWidget(QLabel("下载测试时长："))
        self.cb_dl = QComboBox()
        self.cb_dl.addItems(["5", "6", "8", "12"])
        self.cb_dl.setCurrentText("6")
        h.addWidget(self.cb_dl)
        h.addWidget(QLabel("秒"))
        h.addSpacing(10)
        h.addWidget(QLabel("上传数据量："))
        self.cb_up = QComboBox()
        self.cb_up.addItems(["4", "8", "16", "32"])
        self.cb_up.setCurrentText("8")
        h.addWidget(self.cb_up)
        h.addWidget(QLabel("MB"))
        h.addSpacing(16)
        for text, slot, w in (("开始测速", self.start, 96), ("停止", self.stop, 66)):
            b = QPushButton(text)
            b.setFixedWidth(w)
            b.setMinimumHeight(30)
            b.clicked.connect(slot)
            h.addWidget(b)
            if text == "开始测速":
                self.btn_start = b
            elif text == "停止":
                self.btn_stop = b
                b.setEnabled(False)
        h.addStretch(1)
        root.addWidget(gb)

        gb2 = QGroupBox("② 测速结果（按区域分组）")
        v2 = QVBoxLayout(gb2)

        # 四大核心数字（两区域并行）
        big_wrap = QHBoxLayout()
        big_wrap.setSpacing(14)
        for scope, color in (("国内", "#0D47A1"), ("国外", "#B71C1C")):
            box = QGroupBox(f"● {scope} 节点")
            box.setStyleSheet(f"QGroupBox {{ font-weight:bold; color:{color}; border:1px solid {color}; "
                              f"border-radius:6px; margin-top:8px; padding-top:10px; }}")
            grid = QGridLayout(box)
            grid.setSpacing(10)
            f = QFont(); f.setPointSize(20); f.setBold(True)
            self.eval_widgets[scope] = {}
            for col, (label, key) in enumerate([
                ("下载", "down"),
                ("上传", "up"),
                ("延迟", "lat"),
                ("抖动", "jit"),
            ]):
                lab = QLabel(label)
                lab.setStyleSheet("color:#666;")
                lab.setAlignment(Qt.AlignCenter)
                grid.addWidget(lab, 0, col)
                v = QLabel("—")
                v.setFont(f)
                v.setAlignment(Qt.AlignCenter)
                v.setStyleSheet(f"color:{color};")
                # 预留两行高度：数字从「—」变成「52.5 MB/s\n(441 Mbps)」时，卡片高度不跳动
                v.setMinimumHeight(64)
                grid.addWidget(v, 1, col)
                self.eval_widgets[scope][key] = v
            big_wrap.addWidget(box, 1)
        v2.addLayout(big_wrap)

        # 进度
        h_phase = QHBoxLayout()
        self.lbl_phase = QLabel("就绪")
        self.lbl_phase.setStyleSheet("font-weight:bold;")
        h_phase.addWidget(self.lbl_phase)
        h_phase.addStretch(1)
        self.lbl_elapsed = QLabel("")
        self.lbl_elapsed.setStyleSheet("color:#888;")
        h_phase.addWidget(self.lbl_elapsed)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        self.progress.setRange(0, 0)
        h_phase.addWidget(self.progress)
        v2.addLayout(h_phase)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["区域", "类型", "节点", "结果"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        v2.addWidget(self.table, 1)
        root.addWidget(gb2, 1)

        # ③ 宽带评价（按区域显示）
        gb3 = QGroupBox("③ 宽带评价")
        v3 = QVBoxLayout(gb3)
        h_eval = QHBoxLayout()
        h_eval.setSpacing(10)
        for scope, color in (("国内", "#0D47A1"), ("国外", "#B71C1C")):
            box = QGroupBox(f"{scope} 宽带档位")
            box.setStyleSheet(f"QGroupBox {{ font-weight:bold; color:{color}; border:1px solid {color}; "
                              f"border-radius:6px; margin-top:6px; padding:6px 4px 4px 4px; }}")
            # 两个档位卡片固定同高；内容行数不同时，多余空间留给底部空白（不再把文字撑开、上下浮动）
            box.setMinimumHeight(126)
            box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            v = QVBoxLayout(box)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(3)
            lab_tier = QLabel("未测速")
            f_tier = QFont(); f_tier.setPointSize(14); f_tier.setBold(True)
            lab_tier.setFont(f_tier)
            lab_tier.setStyleSheet(f"color:{color};")
            lab_tier.setWordWrap(True)
            lab_tier.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            lab_desc = QLabel("")
            lab_desc.setWordWrap(True)
            lab_desc.setStyleSheet("color:#444;")
            lab_desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            lab_uses = QLabel("")
            lab_uses.setWordWrap(True)
            lab_uses.setStyleSheet("color:#666;")
            lab_uses.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            v.addWidget(lab_tier)
            v.addWidget(lab_desc)
            v.addWidget(lab_uses)
            v.addStretch(1)          # ★ 关键：多余高度沉到底部，文字始终贴着顶部排列
            h_eval.addWidget(box, 1)
            self.eval_widgets[scope]["tier"] = lab_tier
            self.eval_widgets[scope]["desc"] = lab_desc
            self.eval_widgets[scope]["uses"] = lab_uses
        v3.addLayout(h_eval)

        self.lb_summary = QLabel("综合：尚未测速")
        self.lb_summary.setWordWrap(True)
        self.lb_summary.setStyleSheet("padding:8px 4px 2px 4px; font-weight:bold; color:#222;")
        v3.addWidget(self.lb_summary)
        root.addWidget(gb3)

        # ④ 本机外网信息（IP / 所在地 / 运营商）
        gb4 = QGroupBox("④ 本机外网信息")
        h4 = QHBoxLayout(gb4)
        h4.setSpacing(14)
        self.info_labels = {}
        for key, title, color, pt in (
            ("ipv4",     "外网 IPv4",  "#0D47A1", 13),
            ("ipv6",     "外网 IPv6",  "#1565C0", 10),
            ("location", "所在地",     "#00695C", 12),
            ("isp",      "运营商",     "#6A1B9A", 12),
            ("asn",      "ASN",       "#8D6E63", 12),
        ):
            col = QVBoxLayout()
            col.setSpacing(2)
            cap = QLabel(title)
            cap.setStyleSheet("color:#888;")
            cap.setAlignment(Qt.AlignCenter)
            val = QLabel("—")
            fv = QFont(); fv.setPointSize(pt); fv.setBold(True)
            val.setFont(fv)
            val.setStyleSheet(f"color:{color};")
            val.setAlignment(Qt.AlignCenter)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col.addWidget(cap)
            col.addWidget(val)
            wrap = QWidget()
            wrap.setLayout(col)
            h4.addWidget(wrap, 2 if key == "ipv6" else 1)
            self.info_labels[key] = val
        self.lb_ip_src = QLabel("点击「开始测速」后自动查询\nIPv4：ip-api.com → api-ipv4.ip.sb → ipv4.icanhazip.com\n"
                                "IPv6：api-ipv6.ip.sb → ipv6.icanhazip.com")
        self.lb_ip_src.setStyleSheet("color:#999;")
        h4.addWidget(self.lb_ip_src, 2)
        root.addWidget(gb4)

        bottom = QHBoxLayout()
        self.lb_stats = QLabel("就绪")
        self.lb_stats.setStyleSheet("font-weight:bold;")
        bottom.addWidget(self.lb_stats)
        bottom.addStretch(1)
        self.btn_csv = QPushButton("导出CSV")
        self.btn_csv.setFixedWidth(88)
        self.btn_csv.clicked.connect(self.export_csv)
        bottom.addWidget(self.btn_csv)
        root.addLayout(bottom)

    def start(self):
        self.rows = []
        self.table.setRowCount(0)
        self.summaries = {}
        for scope, wmap in self.eval_widgets.items():
            for k in ("down", "up", "lat", "jit"):
                wmap[k].setText("…")
            wmap["tier"].setText("测速中…")
            wmap["desc"].setText("")
            wmap["uses"].setText("")
        self.lb_summary.setText("综合：测速进行中…")
        for k in self.info_labels:
            self.info_labels[k].setText("…")
        self.lb_ip_src.setText("查询外网信息中…")
        self.progress.setRange(0, 0)
        self.lbl_phase.setText("开始测速…")
        self.lbl_elapsed.setText("")
        self._t_start = time.perf_counter()
        self._timer.start()
        self.lb_stats.setText("测速进行中…")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_cb("开始宽带测速…")
        retire_worker(self, "worker")
        self.worker = SpeedTestWorker(
            latency_count=int(self.cb_count.currentText()),
            download_sec=int(self.cb_dl.currentText()),
            upload_size_mb=int(self.cb_up.currentText()),
            upload_sec=8,
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.result_row.connect(self.on_row)
        self.worker.summary.connect(self.on_summary)
        self.worker.net_info.connect(self.on_net_info)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_net_info(self, info):
        self.net_info = info
        loc_zh = info.get("location_zh") or ""
        isp_zh = info.get("isp_zh") or ""
        loc = info.get("location") or "—"
        isp = info.get("isp") or "—"
        # 有中文就用中文，英文原值放在括号里对照
        if loc_zh and loc_zh not in loc:
            loc_txt = f"{loc_zh}\n({loc})" if loc != "—" else loc_zh
        else:
            loc_txt = loc
        if isp_zh and isp_zh not in isp:
            isp_txt = f"{isp_zh}\n({isp})" if isp != "—" else isp_zh
        else:
            isp_txt = isp
        self.info_labels["ipv4"].setText(info.get("ipv4") or "未获取")
        self.info_labels["ipv6"].setText(info.get("ipv6") or "无 / 未启用")
        self.info_labels["location"].setText(loc_txt)
        self.info_labels["isp"].setText(isp_txt)
        self.info_labels["asn"].setText(info.get("asn") or "—")
        if info.get("ok"):
            self.lb_ip_src.setText("来源：" + (info.get("source") or "—"))
        else:
            self.lb_ip_src.setText(info.get("note") or "查询失败")

    def on_progress(self, phase, done, total):
        # done / total 是全 15 个节点的全局进度
        if total > 0:
            self.lbl_phase.setText(f"{phase}　·　{done}/{total}")
        else:
            self.lbl_phase.setText(phase)
        if total == 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def on_row(self, scope, kind, target, text):
        self.rows.append([scope, kind, target, text])
        r = self.table.rowCount()
        self.table.insertRow(r)
        bg = {"延迟": "#FFF3E0", "下载": "#E3F2FD", "上传": "#E8F5E9"}.get(kind)
        for c, v in enumerate([scope, kind, target, text]):
            it = QTableWidgetItem(str(v))
            if c == 0:
                # 区域着色
                color = {"国内": "#E3F2FD", "国外": "#FFEBEE"}.get(scope)
                if color:
                    it.setBackground(QColor(color))
                    f = QFont(); f.setBold(True); it.setFont(f)
            elif c == 1 and bg:
                it.setBackground(QColor(bg))
                f = QFont(); f.setBold(True); it.setFont(f)
            self.table.setItem(r, c, it)

    def _fmt_speed(self, bps):
        if bps <= 0:
            return "—"
        mb_s = bps / (1024 * 1024)
        mbps = bps * 8 / 1_000_000
        return f"{mb_s:.1f} MB/s\n({mbps:.0f} Mbps)"

    def on_summary(self, scope, s):
        self.summaries[scope] = s
        wmap = self.eval_widgets.get(scope, {})
        wmap["down"].setText(self._fmt_speed(s["download_bps"]))
        wmap["up"].setText(self._fmt_speed(s["upload_bps"]))
        if s["latency_min"] is not None:
            wmap["lat"].setText(f"{s['latency_min']} ms")
            wmap["jit"].setText(f"±{s['latency_mdev']:.1f} ms")
        else:
            wmap["lat"].setText("—")
            wmap["jit"].setText("—")

        ev = s["evaluation"]
        wmap["tier"].setText(f"≡ {ev['tier_label']}")
        # 描述里补一句多节点稳定性信息
        n = s.get("dl_node_count", 0)
        med = s.get("download_med_mbps", 0.0)
        mx = s.get("download_mbps", 0.0)
        extra = ""
        if n >= 2 and med > 0 and mx > 0:
            spread = (mx - med) / mx * 100 if mx else 0
            extra = (f"（{n} 个节点稳态：最快 {mx:.0f} / 中位 {med:.0f} Mbps，"
                     f"离散 {spread:.0f}%）")
        wmap["desc"].setText(ev["tier_desc"] + (("\n" + extra) if extra else ""))
        wmap["uses"].setText("适用场景：" + " / ".join(ev["uses"]))

        # 更新底部 stats 与综合评语
        bits = []
        for sc, sm in self.summaries.items():
            if sm["download_bps"] > 0:
                line = f"{sc}下载 {sm['download_mbps']:.0f} Mbps"
                if sm.get("dl_node_count", 0) >= 2 and sm.get("download_med_mbps", 0) > 0:
                    line += f"（中位 {sm['download_med_mbps']:.0f}）"
                bits.append(line)
            if sm["upload_bps"] > 0:
                bits.append(f"{sc}上传 {sm['upload_mbps']:.0f} Mbps")
            if sm["latency_min"] is not None:
                bits.append(f"{sc}延迟 {sm['latency_min']} ms")
        if bits:
            self.lb_stats.setText("　·　".join(bits))

        # 综合评语：优先用国内评价作为主体
        if "国内" in self.summaries:
            dom = self.summaries["国内"]["evaluation"]
            extra = ""
            if "国外" in self.summaries:
                intl = self.summaries["国外"]["evaluation"]
                extra = f"\n· 国外体验：{intl['tier_label']}；{intl['uses'][0]}"
            self.lb_summary.setText("≡ " + dom["summary"] + extra)

    def on_done(self):
        self._timer.stop()
        if self._t_start:
            self.lbl_elapsed.setText(f"总用时 {time.perf_counter() - self._t_start:.1f}s")
            self._t_start = 0.0
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        retire_worker(self, "worker")
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.status_cb("宽带测速完成")

    def stop(self):
        self._timer.stop()
        self._t_start = 0.0
        if self.worker:
            try:
                self.worker.stop()
                self.worker.wait(1500)
            except Exception:
                pass
        retire_worker(self, "worker")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_phase.setText("已停止")
        self.lbl_elapsed.setText("")
        self.lb_stats.setText("已停止")
        self.status_cb("已停止测速")

    def export_csv(self):
        if not self.rows:
            QMessageBox.information(self, "没有数据", "先测一次再导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出测速结果", f"netcheck_v{VERSION}_speedtest.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            table_to_csv(self.table, path)
            # 追加本机外网信息
            try:
                with open(path, "a", encoding="utf-8-sig", newline="") as f:
                    if self.net_info:
                        info = self.net_info
                        f.write("\n本机外网信息\n")
                        f.write(f"外网IPv4,{info.get('ipv4') or '未获取'}\n")
                        f.write(f"外网IPv6,{info.get('ipv6') or '无/未启用'}\n")
                        loc = info.get("location_zh") or info.get("location") or "—"
                        isp = info.get("isp_zh") or info.get("isp") or "—"
                        f.write(f"所在地,{loc}\n")
                        f.write(f"运营商,{isp}\n")
                        f.write(f"ASN,{info.get('asn', '—')}\n")
                        f.write(f"数据来源,{info.get('source', '—')}\n")
                    f.write(f"\n版本,{APP_NAME} v{VERSION} ({BUILD_DATE})\n")
            except Exception:
                pass
            self.status_cb(f"已导出：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ==========================================================================
# 主窗口
# ==========================================================================
# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ★ MAIN 主窗口 + 入口                                                                  ║
# ║  MainWindow 只负责「把 8 个 Tab 装上 QTabWidget + 给状态栏传回调」                       ║
# ║  closeEvent 在退出时主动停掉所有子线程（双保险）。                                       ║
# ╚═════════════════════════════════════════════════════════════════════════╝
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}  ·  Windows 网络工具箱")
        self.resize(1180, 860)
        cb = self.statusBar().showMessage
        tabs = QTabWidget()
        self.detect = DetectTab(cb)
        tabs.addTab(self.detect, "探测（Ping / TCPing）")
        tabs.addTab(IpConfigTab(cb), "IP 配置")
        tabs.addTab(TracertTab(cb), "路由追踪")
        tabs.addTab(ArpTab(cb), "ARP 缓存")
        tabs.addTab(NetstatTab(cb), "网络连接")
        tabs.addTab(PortScanTab(cb), "端口扫描")
        tabs.addTab(DnsLookupTab(cb), "DNS 查询")
        tabs.addTab(SpeedTestTab(cb), "宽带测速")
        self.setCentralWidget(tabs)
        self.setWindowTitle(f"{APP_NAME} v{VERSION}  ·  Windows 网络工具箱")
        cb(f"{APP_NAME} v{VERSION}（{BUILD_DATE}）　·　探测 / IP 配置 / 路由追踪 / ARP / 连接 / 端口 / DNS / 测速")

    def closeEvent(self, e):
        for w in self.findChildren(QThread):
            try:
                if hasattr(w, "stop"):
                    w.stop()
                w.wait(800)
            except Exception:
                pass
        e.accept()


def main():
    install_excepthook(APP_NAME)
    app = QApplication(sys.argv)
    app.setApplicationName("netcheck")
    w = MainWindow()
    w.show()
    sys.exit(_qt_app_exec(app))


if __name__ == "__main__":
    main()
