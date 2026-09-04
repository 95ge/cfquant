# -*- coding: utf-8 -*-
"""Command-line entry points for the installed cfquant package."""

from __future__ import print_function

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .version import WEB_VERSION, __version__ as CORE_VERSION


QMT_SCRIPT_FILES = (
    "CFQUANT.py",
    "CFQUANT_CTYPE_ALL_LOWLAT.py",
    "CFQUANT_LITE.py",
    "CFQUANT_TRADE_LOWLAT.py",
    "同账号独立市场/CFQUANT_CTYPE_ALL_LOWLAT_SH.py",
    "同账号独立市场/CFQUANT_CTYPE_ALL_LOWLAT_SZ.py",
    "同账号独立市场/CFQUANT_LITE_SH.py",
    "同账号独立市场/CFQUANT_LITE_SZ.py",
    "同账号独立市场/CFQUANT_TRADE_LOWLAT_SH.py",
    "同账号独立市场/CFQUANT_TRADE_LOWLAT_SZ.py",
    "同账号独立市场/readme.md",
)


def _configure_console_encoding():
    """Keep Chinese CLI output readable on Windows and redirected consoles."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _package_version():
    project_file = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        for line in project_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version"):
                name, value = line.split("=", 1)
                if name.strip() == "version":
                    return value.strip().strip('"').strip("'")
    except Exception:
        pass

    try:
        from importlib import metadata

        dist = metadata.distribution("cfquant")
        return dist.version
    except Exception:
        pass
    return "unknown"


def _port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("port must be an integer")
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _path(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def _apply_web_environment(args):
    mappings = (
        ("home", "CFQUANT_HOME"),
        ("runtime_dir", "CFQUANT_RUNTIME_DIR"),
        ("log_dir", "CFQUANT_LOG_DIR"),
        ("config", "CFQUANT_WEB_CONFIG_FILE"),
        ("pipe_name", "CFQUANT_PIPE_NAME"),
        ("lttx_host", "CFQUANT_LTTX_HOST"),
        ("account_id", "CFQUANT_ACCOUNT_ID"),
    )
    for attribute, variable in mappings:
        value = getattr(args, attribute, None)
        if value:
            os.environ[variable] = _path(value) if variable.endswith(("_DIR", "_FILE", "_HOME")) else str(value)
    if getattr(args, "lttx_port", None):
        os.environ["CFQUANT_LTTX_PORT"] = str(args.lttx_port)


def _serve_parser(prog="cfquant"):
    help_command = "%s serve --help" % prog if prog == "cfquant" else "%s --help" % prog
    if prog == "cfquant":
        epilog = (
            "常用命令:\n"
            "  cfquant                                启动本地 Web 控制台。\n"
            "  cfquant qmt-scripts                    查看已安装的 QMT 入口脚本目录。\n"
            "  cfquant qmt-scripts --open             在资源管理器中打开 QMT 入口脚本目录。\n"
            "  cfquant qmt-scripts --output DIRECTORY 导出 QMT 入口脚本到指定目录。\n"
            "  cfquant pipe-hub [options]             只启动 named-pipe hub。\n"
            "  cfquant version                        显示安装版本和目录。\n"
            "使用 '%s' 查看 Web 启动参数。" % help_command
        )
    else:
        epilog = "使用 '%s' 查看 Web 启动参数。" % help_command
    parser = argparse.ArgumentParser(
        prog=prog,
        description="启动 cfquant 本地 Web 控制台。",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", help="Web 绑定地址。默认使用本机地址或已保存配置。")
    parser.add_argument("--port", type=_port, help="Web 监听端口。默认使用已保存配置或 8765。")
    parser.add_argument(
        "--home",
        "--state-dir",
        dest="home",
        help="cfquant 可写运行目录，用于保存配置、数据库、日志和状态文件。",
    )
    parser.add_argument("--runtime-dir", help="覆盖 runtime 子目录。")
    parser.add_argument("--log-dir", help="覆盖日志目录。")
    parser.add_argument("--config", help="Web 配置 JSON 文件路径。")
    parser.add_argument("--pipe-name", help=r"覆盖 QMT named pipe 名称，例如 \\.\pipe\cfquant_pipe_hub。")
    parser.add_argument("--lttx-host", help="LTtx 地址。默认 127.0.0.1。")
    parser.add_argument("--lttx-port", type=_port, help="LTtx 端口。默认 2049。")
    parser.add_argument("--account-id", help="Web 初始化完成前使用的默认资金账号。")
    parser.add_argument("--open-browser", action="store_true", help="服务就绪后自动打开浏览器。")
    parser.add_argument("--dry-run", action="store_true", help="只打印启动参数，不启动服务。")
    parser.add_argument("--version", action="version", version=_version_text())
    return parser


def _version_text():
    return "cfquant package %s\ncore %s\nweb %s" % (_package_version(), CORE_VERSION, WEB_VERSION)


def _browser_url(host, port):
    host = str(host or "").strip()
    if not host or host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "http://%s:%s/" % (host, port)


def _resolve_web_address(args):
    host = args.host or os.environ.get("CFQUANT_WEB_HOST")
    port = args.port
    if host and port is not None:
        return host, port

    try:
        from cfquant_web_server import WEB_CONFIG, normalize_web_port

        if not host:
            host = "0.0.0.0" if WEB_CONFIG.allow_remote() else "127.0.0.1"
        if port is None:
            port = normalize_web_port(
                os.environ.get("CFQUANT_WEB_PORT"),
                default=WEB_CONFIG.web_port(),
            )
    except Exception:
        if not host:
            host = "127.0.0.1"
        if port is None:
            port = 8765
    return host, port


def _print_startup_banner(args):
    host, port = _resolve_web_address(args)
    command = "cfquant"
    print("cfquant 本地服务启动中...")
    print("包版本: %s | 核心版本: %s | Web版本: %s" % (_package_version(), CORE_VERSION, WEB_VERSION))
    print("Web 控制台: %s" % _browser_url(host, port))
    print("QMT 入口脚本目录: %s" % _qmt_scripts_source_dir())
    print("查看脚本目录: %s qmt-scripts --show" % command)
    print(r"导出 QMT 入口脚本: %s qmt-scripts --output D:\QMT\cfquant" % command)


def _wait_and_open_browser(host, port):
    connect_host = str(host or "").strip()
    if not connect_host or connect_host in ("0.0.0.0", "::"):
        connect_host = "127.0.0.1"
    url = _browser_url(connect_host, port)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host.strip("[]"), int(port)), timeout=0.4):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.25)


def _serve(argv, prog="cfquant"):
    _configure_console_encoding()
    parser = _serve_parser(prog)
    args = parser.parse_args(argv)
    _apply_web_environment(args)
    if args.dry_run:
        print("cfquant 启动参数预览")
        print("cfquant package=%s core=%s web=%s" % (_package_version(), CORE_VERSION, WEB_VERSION))
        print("QMT 入口脚本目录=%s" % _qmt_scripts_source_dir())
        for key in (
            "CFQUANT_HOME",
            "CFQUANT_RUNTIME_DIR",
            "CFQUANT_LOG_DIR",
            "CFQUANT_WEB_CONFIG_FILE",
            "CFQUANT_PIPE_NAME",
            "CFQUANT_LTTX_HOST",
            "CFQUANT_LTTX_PORT",
            "CFQUANT_ACCOUNT_ID",
        ):
            if os.environ.get(key):
                print("%s=%s" % (key, os.environ[key]))
        return 0

    from cfquant_web_server import main as web_main

    server_args = []
    if args.host:
        server_args.extend(["--host", args.host])
    if args.port:
        server_args.extend(["--port", str(args.port)])
    _print_startup_banner(args)
    if args.open_browser:
        host, port = _resolve_web_address(args)
        thread = threading.Thread(target=_wait_and_open_browser, args=(host, port))
        thread.daemon = True
        thread.start()
    return web_main(server_args)


def _qmt_scripts_source_dir():
    import qmt_scripts

    return Path(qmt_scripts.__file__).resolve().parent


def _qmt_scripts_parser():
    parser = argparse.ArgumentParser(
        prog="cfquant qmt-scripts",
        description="查看、打开或导出当前 cfquant 安装包内置的 QMT 入口脚本。",
    )
    parser.add_argument("--show", action="store_true", help="显示当前安装包内置的 QMT 脚本目录。")
    parser.add_argument("--list", dest="list_files", action="store_true", help="列出内置 QMT 脚本文件。")
    parser.add_argument("--open", dest="open_dir", action="store_true", help="在系统文件管理器中打开 QMT 脚本目录。")
    parser.add_argument("--output", "-o", help="把 QMT 脚本导出到指定目录。")
    parser.add_argument("--force", action="store_true", help="导出时覆盖目标目录中的同名文件。")
    return parser


def _validate_qmt_scripts(source_dir):
    missing = [name for name in QMT_SCRIPT_FILES if not (source_dir / name).is_file()]
    if missing:
        raise RuntimeError("当前 cfquant 安装包缺少 QMT 脚本: %s" % ", ".join(missing))


def _print_qmt_scripts_info(source_dir, list_files=False):
    print("QMT 入口脚本目录: %s" % source_dir)
    print("查看目录: cfquant qmt-scripts --open")
    print(r"导出命令: cfquant qmt-scripts --output D:\QMT\cfquant")
    if list_files:
        print("内置脚本文件:")
        for relative_name in QMT_SCRIPT_FILES:
            print("  %s" % relative_name)


def _open_directory(path):
    if os.name == "nt" and hasattr(os, "startfile"):
        os.startfile(str(path))  # pylint: disable=no-member
        return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    if shutil.which(command) is None:
        raise RuntimeError("当前系统未找到可用的文件管理器打开命令: %s" % command)
    subprocess.Popen([command, str(path)])


def _export_qmt_scripts(argv):
    parser = _qmt_scripts_parser()
    args = parser.parse_args(argv)
    source_dir = _qmt_scripts_source_dir()
    _validate_qmt_scripts(source_dir)

    if not args.output and not args.show and not args.list_files and not args.open_dir:
        args.show = True
        args.list_files = True

    if args.show or args.list_files:
        _print_qmt_scripts_info(source_dir, list_files=args.list_files)
    if args.open_dir:
        _open_directory(source_dir)
        print("已打开 QMT 入口脚本目录: %s" % source_dir)
    if not args.output:
        return 0

    output_dir = Path(_path(args.output))
    if output_dir.exists() and not output_dir.is_dir():
        parser.error("输出路径不是目录: %s" % output_dir)
    existing = [name for name in QMT_SCRIPT_FILES if (output_dir / name).exists()]
    if existing and not args.force:
        parser.error("目标目录已存在同名文件；如需覆盖请加 --force: %s" % ", ".join(existing))

    output_dir.mkdir(parents=True, exist_ok=True)
    for relative_name in QMT_SCRIPT_FILES:
        source = source_dir / relative_name
        target = output_dir / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
    print("已导出 %s 个 QMT 入口脚本到: %s" % (len(QMT_SCRIPT_FILES), output_dir))
    return 0


def _print_version():
    package_root = Path(__file__).resolve().parent
    qmt_scripts_dir = _qmt_scripts_source_dir()
    print(_version_text())
    print("cfquant 包目录 %s" % package_root)
    print("QMT 入口脚本目录 %s" % qmt_scripts_dir)
    print("打开脚本目录 cfquant qmt-scripts --open")
    print(r"导出脚本目录 cfquant qmt-scripts --output D:\QMT\cfquant")
    return 0


def web_main(argv=None):
    """Backward-compatible entry point for the ``cfquant-web`` command."""
    return _serve(list(sys.argv[1:] if argv is None else argv), prog="cfquant-web")


def main(argv=None):
    _configure_console_encoding()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _serve([])
    command = argv[0]
    if command in ("serve", "web"):
        return _serve(argv[1:])
    if command == "pipe-hub":
        from cfquant_pipe_hub import main as pipe_hub_main

        return pipe_hub_main(argv[1:])
    if command in ("qmt-scripts", "qmt"):
        return _export_qmt_scripts(argv[1:])
    if command in ("version", "info"):
        return _print_version()
    if command in ("help", "-h", "--help"):
        return _serve(["--help"])
    return _serve(argv)


if __name__ == "__main__":
    raise SystemExit(main())
