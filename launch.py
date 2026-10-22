"""Launch the local app. --desktop opens an optional native pywebview window."""
import argparse
import multiprocessing
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from backend.runtime import FROZEN, VERSION, bundled_browser


def prepare_logs():
    if sys.stdout is None or sys.stderr is None:
        from backend.storage import DATA
        DATA.mkdir(parents=True, exist_ok=True)
        stream = (DATA / 'StrokeScape.log').open('a', encoding='utf-8', buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream


def show_window(url, desktop):
    from backend.storage import DATA
    if desktop:
        try:
            import webview
            webview.create_window("绘序成境 · StrokeScape", url, width=1480, height=960,
                                  min_size=(960, 680), background_color="#101214")
            webview.start(gui='edgechromium' if sys.platform == 'win32' else None,
                          private_mode=False, storage_path=str(DATA / 'WebView'))
            return
        except Exception as exc:
            print(f"桌面 WebView 不可用，尝试内置浏览器：{exc}")
    browser = bundled_browser()
    if browser:
        profile = DATA / 'BrowserProfile'
        profile.mkdir(parents=True, exist_ok=True)
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        process = subprocess.Popen([
            str(browser), '--app=' + url, '--user-data-dir=' + str(profile),
            '--no-first-run', '--no-default-browser-check', '--disable-default-apps',
            '--disable-background-networking', '--disable-component-update', '--disable-sync',
            '--window-size=1480,960',
        ], **flags)
        process.wait()
        return
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="绘序成境 · 离线数字笔触工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--browser", action="store_true", help="使用浏览器窗口")
    parser.add_argument("--version", action="version", version=f"StrokeScape {VERSION}")
    args = parser.parse_args()
    desktop = (args.desktop or FROZEN) and not args.browser
    import uvicorn
    from backend.storage import ROOT
    if not (ROOT / "web-dist" / "index.html").exists():
        raise SystemExit("尚未构建界面。请先运行 npm install 和 npm run build。")
    url = f"http://127.0.0.1:{args.port}"
    with socket.socket() as check:
        if check.connect_ex(("127.0.0.1", args.port)) == 0:
            import json
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=2) as response:
                    existing = json.load(response)
            except Exception:
                existing = {}
            if existing.get("name") == "绘序成境":
                if not args.no_browser:
                    show_window(url, desktop)
                return
            raise SystemExit(f"端口 {args.port} 已被占用，请使用 --port 指定其他端口。")
    config = uvicorn.Config("backend.api:app", host="127.0.0.1", port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    ready = False
    for _ in range(100):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=0.3) as response:
                ready = response.status == 200
            if ready:
                break
        except Exception:
            time.sleep(0.15)
    if not ready:
        raise SystemExit("本地服务未能启动，请检查控制台错误。")
    print(f"绘序成境已启动：{url}\n图片与作品保存在本机。按 Ctrl+C 退出。")
    if desktop or (FROZEN and args.browser and not args.no_browser):
        if args.no_browser:
            desktop = False
        else:
            show_window(url, desktop)
            server.should_exit = True
            thread.join(timeout=10)
            return
    elif not args.no_browser:
        webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(timeout=1)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    prepare_logs()
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        if FROZEN and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动失败：{exc}\n\n请将整个文件夹解压到可写目录，并查看 UserData/StrokeScape.log。", 'StrokeScape', 0x10)
        raise
