"""
proxy_setup.py —— 自动设置/还原系统代理，然后启动 mitmproxy 拦截脚本

用法:
  python proxy_setup.py start   # 设置系统代理 + 启动 mitmproxy
  python proxy_setup.py stop    # 还原系统代理

支持 Windows / macOS
"""

import sys
import os
import platform
import subprocess
import time
import json

PORT = 8888
PROXY_HOST = "127.0.0.1"
BACKUP_FILE = ".proxy_backup.json"


# ---------------------------------------------------------------------------
# Windows proxy helpers (via winreg)
# ---------------------------------------------------------------------------

def _win_get_proxy():
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        0, winreg.KEY_READ,
    )
    def _get(name, default=None):
        try:
            v, _ = winreg.QueryValueEx(key, name)
            return v
        except FileNotFoundError:
            return default
    return {
        "ProxyEnable": _get("ProxyEnable", 0),
        "ProxyServer": _get("ProxyServer", ""),
        "ProxyOverride": _get("ProxyOverride", ""),
    }


def _win_set_proxy(enable: bool, server: str = ""):
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        0, winreg.KEY_WRITE,
    )
    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enable))
    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
    # Notify Windows of the change
    import ctypes
    INTERNET_OPTION_SETTINGS_CHANGED = 39
    INTERNET_OPTION_REFRESH = 37
    ctypes.windll.Wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
    ctypes.windll.Wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)


# ---------------------------------------------------------------------------
# macOS proxy helpers (via networksetup)
# ---------------------------------------------------------------------------

def _mac_get_active_service():
    """Return the active Wi-Fi or Ethernet service name."""
    try:
        out = subprocess.check_output(
            ["networksetup", "-listallnetworkservices"], text=True
        )
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("*") and line not in ("An asterisk", ""):
                if line.lower() in ("wi-fi", "wifi", "ethernet", "en0"):
                    return line
        # Return first non-comment line
        lines = [l.strip() for l in out.splitlines()
                 if l.strip() and not l.startswith("An asterisk") and not l.startswith("*")]
        return lines[0] if lines else "Wi-Fi"
    except Exception:
        return "Wi-Fi"


def _mac_get_proxy(service: str) -> dict:
    try:
        out = subprocess.check_output(
            ["networksetup", "-getwebproxy", service], text=True
        )
        enabled = "Yes" in out
        server = ""
        port = ""
        for line in out.splitlines():
            if line.startswith("Server:"):
                server = line.split(":", 1)[1].strip()
            if line.startswith("Port:"):
                port = line.split(":", 1)[1].strip()
        return {"enabled": enabled, "server": server, "port": port}
    except Exception:
        return {"enabled": False, "server": "", "port": ""}


def _mac_set_proxy(service: str, enable: bool,
                   host: str = "", port: int = 8888):
    if enable:
        subprocess.run(
            ["networksetup", "-setwebproxy", service, host, str(port)],
            check=True,
        )
        subprocess.run(
            ["networksetup", "-setsecurewebproxy", service, host, str(port)],
            check=True,
        )
        subprocess.run(
            ["networksetup", "-setwebproxystate", service, "on"], check=True
        )
        subprocess.run(
            ["networksetup", "-setsecurewebproxystate", service, "on"], check=True
        )
    else:
        subprocess.run(
            ["networksetup", "-setwebproxystate", service, "off"], check=True
        )
        subprocess.run(
            ["networksetup", "-setsecurewebproxystate", service, "off"], check=True
        )


# ---------------------------------------------------------------------------
# Cross-platform helpers
# ---------------------------------------------------------------------------

SYSTEM = platform.system()   # "Windows" | "Darwin" | "Linux"


def set_system_proxy(enable: bool):
    server = f"{PROXY_HOST}:{PORT}" if enable else ""
    if SYSTEM == "Windows":
        _win_set_proxy(enable, server)
    elif SYSTEM == "Darwin":
        svc = _mac_get_active_service()
        _mac_set_proxy(svc, enable, PROXY_HOST, PORT)
    else:
        print("Linux 请手动设置系统代理或设置环境变量:")
        if enable:
            print(f"  export http_proxy=http://{PROXY_HOST}:{PORT}")
            print(f"  export https_proxy=http://{PROXY_HOST}:{PORT}")
        else:
            print("  unset http_proxy https_proxy")


def backup_proxy():
    if SYSTEM == "Windows":
        data = _win_get_proxy()
    elif SYSTEM == "Darwin":
        svc = _mac_get_active_service()
        data = {"service": svc, **_mac_get_proxy(svc)}
    else:
        data = {}
    with open(BACKUP_FILE, "w") as f:
        json.dump(data, f)
    return data


def restore_proxy():
    if not os.path.exists(BACKUP_FILE):
        print("无备份文件，直接关闭代理")
        set_system_proxy(False)
        return
    with open(BACKUP_FILE) as f:
        data = json.load(f)
    if SYSTEM == "Windows":
        _win_set_proxy(bool(data.get("ProxyEnable")), data.get("ProxyServer", ""))
    elif SYSTEM == "Darwin":
        svc = data.get("service", _mac_get_active_service())
        if data.get("enabled"):
            _mac_set_proxy(svc, True, data["server"], int(data["port"] or 8888))
        else:
            _mac_set_proxy(svc, False)
    os.remove(BACKUP_FILE)
    print("系统代理已还原")


# ---------------------------------------------------------------------------
# Certificate installation helper
# ---------------------------------------------------------------------------

def install_cert_hint():
    cert_path = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")
    print("\n" + "=" * 60)
    print("【首次使用需要安装 mitmproxy CA 证书】")
    if SYSTEM == "Windows":
        print(f"证书路径: %USERPROFILE%\\.mitmproxy\\mitmproxy-ca-cert.p12")
        print("操作: 双击证书 → 本地计算机 → 将所有证书放入「受信任的根证书颁发机构」")
        # Try to auto-install on Windows
        p12 = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.p12")
        if os.path.exists(p12):
            print("\n正在尝试自动安装...")
            subprocess.run(
                ["certutil", "-addstore", "Root", p12],
                capture_output=True,
            )
            print("证书安装完成（如失败请手动双击安装）")
    elif SYSTEM == "Darwin":
        if os.path.exists(cert_path):
            print(f"证书路径: {cert_path}")
            print("正在尝试自动安装到系统钥匙串...")
            subprocess.run([
                "security", "add-trusted-cert", "-d",
                "-r", "trustRoot",
                "-k", "/Library/Keychains/System.keychain",
                cert_path,
            ])
            print("证书安装完成")
        else:
            print("请先运行一次 mitmproxy 生成证书，再重新运行本脚本")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cmd_start():
    print(f"[1/4] 备份当前系统代理设置...")
    backup_proxy()

    print(f"[2/4] 设置系统代理 → {PROXY_HOST}:{PORT}")
    set_system_proxy(True)

    # Generate certs by running mitmproxy briefly if not yet generated
    cert_path = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")
    if not os.path.exists(cert_path):
        print("[3/4] 首次运行，生成 mitmproxy 证书...")
        proc = subprocess.Popen(
            ["mitmdump", "--listen-port", str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        proc.terminate()

    print("[4/4] 安装 CA 证书...")
    install_cert_hint()

    print("正在启动 mitmproxy 拦截脚本（Ctrl+C 结束）...")
    print("─" * 60)
    print("请在微信PC版中依次打开以下景点的评论页并向下滚动:")
    print("  1. 凤凰古城")
    print("  2. 矮寨奇观旅游区-矮寨大桥")
    print("  3. 德夯峡谷景区")
    print("  4. 芙蓉镇")
    print("─" * 60)

    try:
        subprocess.run(
            ["mitmdump", "-s", "intercept.py", "--listen-port", str(PORT)],
        )
    except KeyboardInterrupt:
        pass
    finally:
        print("\n正在还原系统代理...")
        restore_proxy()
        print("完成！运行 python scraper.py 开始抓取评论")


def cmd_stop():
    restore_proxy()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("start", "stop"):
        print("用法: python proxy_setup.py start|stop")
        sys.exit(1)

    if sys.argv[1] == "start":
        cmd_start()
    else:
        cmd_stop()
