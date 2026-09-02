#coding:gbk
#! /usr/bin/python
# CFQUANT_LITE.py
# Self-contained ctypes named-pipe entry for QMT whitelist environments.
# This file intentionally avoids importing the cfquant package.

import base64
import datetime as dt
import io
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import time
import traceback
import uuid
import ctypes
from ctypes import wintypes

CORE_VERSION = "core_20260902_03"
LITE_ENTRY_VERSION = "lite_20260828_01"

_CANCELABLE_ORDER_STATUS_VALUES = set([48, 49, 50, 55])
_ORDER_STATUS_FIELD_NAMES = (
    "order_status",
    "m_nOrderStatus",
    "m_nOrderState",
    "m_strOrderStatus",
    "m_strStatus",
)


def _truthy_param(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _normalize_order_status(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        number = float(text)
        if number.is_integer():
            return int(number)
    except Exception:
        pass
    return {
        "ORDER_UNREPORTED": 48,
        "ORDER_WAIT_REPORTING": 49,
        "ORDER_REPORTED": 50,
        "ORDER_PART_SUCC": 55,
    }.get(text.upper())


def _row_value(row, name):
    if hasattr(row, name):
        return getattr(row, name)
    if hasattr(row, "get"):
        return row.get(name)
    return None


def _is_cancelable_order(row):
    for name in _ORDER_STATUS_FIELD_NAMES:
        value = _row_value(row, name)
        if value is not None and value != "":
            return _normalize_order_status(value) in _CANCELABLE_ORDER_STATUS_VALUES
    return False


def _filter_cancelable_orders(rows):
    if rows is None:
        return None
    if isinstance(rows, list):
        return [row for row in rows if _is_cancelable_order(row)]
    return rows if _is_cancelable_order(rows) else None

_LANG_LOCK = threading.RLock()
_LOG_LANGUAGE = ""
_LOG_ENABLED = None


_TRANSLATIONS = [
    ('^\\[trade\\]start trading mode$', '[交易] 交易模式已启动'),
    ('^cfquant lite extreme bridge module loaded$', 'cfquant 极致模式桥接模块已加载'),
    ('^cfquant lite extreme entry version:(?P<version>.+)$', 'cfquant 极致模式入口版本：{version}'),
    ('^cfquant lite bridge id:(?P<bridge_id>[^ ]+) pipe:(?P<pipe>[^ ]+) normal_channel:(?P<normal>[^ ]+) trade_channel:(?P<trade>[^ ]+) callback_channel:(?P<callback>.+)$', 'cfquant 极致模式 桥接ID={bridge_id} pipe={pipe} 普通通道={normal} 交易通道={trade} 回调通道={callback}'),
    ('^cfquant lite trade loop in thread:(?P<thread>[^ ]+) sleep_seconds:(?P<sleep>.+)$', 'cfquant 极致模式 交易循环后台线程={thread} 轮询间隔={sleep}秒'),
    ('^cfquant lite extreme trade loop started in worker thread$', 'cfquant 极致模式交易循环已在后台线程启动'),
    ('^cfquant lite extreme trade loop entering current QMT thread$', 'cfquant 极致模式交易循环进入当前 QMT 线程'),
    ('^cfquant lite extreme trade loop error:(?P<error>.+)$', 'cfquant 极致模式交易循环异常：{error}'),
    ('^cfquant lite extreme trade dispatch error source=(?P<source>[^ ]+) error=(?P<error>.+)$', 'cfquant 极致模式交易请求派发异常 来源={source} 错误={error}'),
    ('^cfquant lite extreme trade timer scheduled key:(?P<key>[^ ]+) interval_ms:(?P<interval>.+)$', 'cfquant 极致模式交易定时器已注册 key={key} 间隔={interval}ms'),
    ('^cfquant lite extreme trade timer schedule failed:(?P<error>.+)$', 'cfquant 极致模式交易定时器注册失败：{error}'),
    ('^cfquant lite normal context ready version:(?P<version>.+)$', 'cfquant 极致模式普通桥 ContextInfo 已就绪 入口版本={version}'),
    ('^cfquant lite extreme trade context ready version:(?P<version>.+)$', 'cfquant 极致模式交易桥 ContextInfo 已就绪 入口版本={version}'),
    ('^cfquant lite extreme trade timer cancel failed:(?P<error>.+)$', 'cfquant 极致模式交易定时器取消失败：{error}'),
    ('^cfquant lite extreme trade bridge stopped$', 'cfquant 极致模式交易桥已停止'),
    ('^cfquant lite normal bridge stopped$', 'cfquant 极致模式普通桥已停止'),
    ('^cfquant lite extreme callback publish failed event=(?P<event>[^ ]+) error=(?P<error>.+)$', 'cfquant 极致模式回调事件发布失败 event={event} 错误={error}'),
    ('^cfquant lite runtime version report sent reason=(?P<reason>[^ ]+) version=(?P<version>[^ ]+) entry_version=(?P<entry>.+)$', 'cfquant 极致模式运行版本已上报 reason={reason} core={version} entry={entry}'),
    ('^cfquant lite runtime version report pending reason=(?P<reason>.+)$', 'cfquant 极致模式运行版本等待管道连接后上报 reason={reason}'),
    ('^cfquant lite runtime version report failed:(?P<error>.+)$', 'cfquant 极致模式运行版本上报失败：{error}'),
    ('^cfquant lite runtime config not found$', 'cfquant 极致模式运行配置未找到，将使用默认配置'),
    ('^cfquant lite runtime config loaded path=(?P<path>[^ ]+) bridge_id=(?P<bridge_id>[^ ]+) pipe=(?P<pipe>.+)$', 'cfquant 极致模式运行配置已加载 path={path} bridge_id={bridge_id} pipe={pipe}'),
    ('^cfquant lite runtime config read failed path=(?P<path>[^ ]+) error=(?P<error>.+)$', 'cfquant 极致模式运行配置读取失败 path={path} 错误={error}'),
    ('^cfquant lite entry executing from (?P<entry>.+) cwd (?P<cwd>.+)$', 'cfquant 极致模式入口执行路径={entry} 当前目录={cwd}'),
    ('^pipe connected pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>[^ ]+) bridge_id=(?P<bridge_id>.+)$', '命名管道已连接 pipe={pipe} 请求通道={channel} 桥接ID={bridge_id}'),
    ('^pipe connect/read failed: (?P<error>.+)$', '命名管道连接或读取中断：{error}'),
    ('^pipe push failed: (?P<error>.+)$', '命名管道推送失败：{error}'),
    (r"^tx trade bridge reload failed:(?P<error>.+)$", "交易桥模块重载失败：{error}"),
    (r"^normal bridge reload failed:(?P<error>.+)$", "普通桥模块重载失败：{error}"),
    (r"^QMT log output enabled=(?P<enabled>.+)$", "QMT 日志输出已切换 enabled={enabled}"),
    (r"^pipe transport reload failed:(?P<error>.+)$", "Pipe 传输模块重载失败：{error}"),
    (r"^pipe bridge reload failed:(?P<error>.+)$", "Pipe 桥接模块重载失败：{error}"),
    (r"^cfquant normal bridge module loaded$", "cfquant 普通桥模块已加载"),
    (r"^cfquant entry version:(?P<version>.+)$", "cfquant 入口版本：{version}"),
    (
        r"^cfquant bridge id:(?P<bridge_id>[^ ]+) normal_channel:(?P<normal>[^ ]+) callback_channel:(?P<callback>.+)$",
        "cfquant 桥接ID={bridge_id} 普通通道={normal} 回调通道={callback}",
    ),
    (
        r"^cfquant normal bridge pump max_count:(?P<count>[^ ]+) max_ms:(?P<ms>.+)$",
        "cfquant 普通桥泵处理上限 条数={count} 耗时={ms}ms",
    ),
    (
        r"^cfquant normal bridge timer scheduled key:(?P<key>[^ ]+) interval_ms:(?P<interval>.+)$",
        "cfquant 普通桥定时器已注册 key={key} 间隔={interval}ms",
    ),
    (
        r"^cfquant normal bridge timer schedule failed:(?P<error>.+)$",
        "cfquant 普通桥定时器注册失败：{error}",
    ),
    (
        r"^cfquant normal bridge context ready version:(?P<version>.+)$",
        "cfquant 普通桥 ContextInfo 已就绪 版本={version}",
    ),
    (
        r"^cfquant normal bridge timer cancel failed:(?P<error>.+)$",
        "cfquant 普通桥定时器取消失败：{error}",
    ),
    (r"^cfquant normal bridge stopped$", "cfquant 普通桥已停止"),
    (
        r"^cfquant callback publish failed event=(?P<event>[^ ]+) error=(?P<error>.+)$",
        "cfquant 回调事件发布失败 event={event} 错误={error}",
    ),
    (r"^cfquant lowlat trade bridge module loaded$", "cfquant 极速交易桥模块已加载"),
    (r"^cfquant lowlat entry version:(?P<version>.+)$", "cfquant 极速交易入口版本：{version}"),
    (
        r"^cfquant bridge id:(?P<bridge_id>[^ ]+) trade_channel:(?P<trade>.+)$",
        "cfquant 桥接ID={bridge_id} 交易通道={trade}",
    ),
    (
        r"^cfquant lowlat trade context ready version:(?P<version>.+)$",
        "cfquant 极速交易桥 ContextInfo 已就绪 版本={version}",
    ),
    (r"^cfquant lowlat trade bridge stopped$", "cfquant 极速交易桥已停止"),
    (r"^cfquant ctypes all-in-one lowlat bridge module loaded$", "cfquant ctypes 单文件低延迟桥模块已加载"),
    (r"^cfquant ctypes all-in-one lowlat entry version:(?P<version>.+)$", "cfquant ctypes 单文件低延迟入口版本：{version}"),
    (
        r"^cfquant ctypes bridge id:(?P<bridge_id>[^ ]+) pipe:(?P<pipe>[^ ]+) normal_channel:(?P<normal>[^ ]+) trade_channel:(?P<trade>[^ ]+) callback_channel:(?P<callback>.+)$",
        "cfquant ctypes 桥接ID={bridge_id} pipe={pipe} 普通通道={normal} 交易通道={trade} 回调通道={callback}",
    ),
    (
        r"^cfquant ctypes trade loop in thread:(?P<thread>[^ ]+) sleep_seconds:(?P<sleep>.+)$",
        "cfquant ctypes 交易循环后台线程={thread} 轮询间隔={sleep}秒",
    ),
    (
        r"^cfquant ctypes lowlat trade loop error:(?P<error>.+)$",
        "cfquant ctypes 低延迟交易循环异常：{error}",
    ),
    (r"^cfquant ctypes lowlat trade loop started in worker thread$", "cfquant ctypes 低延迟交易循环已在后台线程启动"),
    (r"^cfquant ctypes lowlat trade loop entering current QMT thread$", "cfquant ctypes 低延迟交易循环进入当前 QMT 线程"),
    (
        r"^cfquant ctypes lowlat trade dispatch error source=(?P<source>[^ ]+) error=(?P<error>.+)$",
        "cfquant ctypes 低延迟交易请求派发异常 来源={source} 错误={error}",
    ),
    (
        r"^cfquant ctypes lowlat trade timer scheduled key:(?P<key>[^ ]+) interval_ms:(?P<interval>.+)$",
        "cfquant ctypes 低延迟交易定时器已注册 key={key} 间隔={interval}ms",
    ),
    (
        r"^cfquant ctypes lowlat trade timer schedule failed:(?P<error>.+)$",
        "cfquant ctypes 低延迟交易定时器注册失败：{error}",
    ),
    (
        r"^cfquant ctypes lowlat trade timer cancel failed:(?P<error>.+)$",
        "cfquant ctypes 低延迟交易定时器取消失败：{error}",
    ),
    (
        r"^cfquant ctypes normal context ready version:(?P<version>.+)$",
        "cfquant ctypes 普通桥 ContextInfo 已就绪 版本={version}",
    ),
    (
        r"^cfquant ctypes lowlat trade context ready version:(?P<version>.+)$",
        "cfquant ctypes 低延迟交易桥 ContextInfo 已就绪 版本={version}",
    ),
    (r"^cfquant ctypes lowlat trade bridge stopped$", "cfquant ctypes 低延迟交易桥已停止"),
    (r"^cfquant ctypes normal bridge stopped$", "cfquant ctypes 普通桥已停止"),
    (
        r"^cfquant ctypes lowlat callback publish failed event=(?P<event>[^ ]+) error=(?P<error>.+)$",
        "cfquant ctypes 回调事件发布失败 event={event} 错误={error}",
    ),
    (
        r"^stage=request_dequeued raw=(?P<raw>.+)$",
        "阶段=请求出队 raw={raw}",
    ),
    (
        r"^stage=parse_invalid parse_ms=(?P<parse_ms>[^ ]+) raw=(?P<raw>.+)$",
        "阶段=解析失败 解析耗时={parse_ms}ms raw={raw}",
    ),
    (
        r"^stage=request_enqueued_qmt_thread action=(?P<action>[^ ]+) id=(?P<id>.+)$",
        "阶段=请求转入QMT线程 action={action} id={id}",
    ),
    (
        r"^stage=request_received action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) parse_ms=(?P<parse_ms>[^ ]+) params=(?P<params>.+)$",
        "阶段=收到请求 action={action} id={id} 解析耗时={parse_ms}ms 参数={params}",
    ),
    (
        r"^stage=response_ready action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) dispatch_ms=(?P<dispatch_ms>[^ ]+) result=(?P<result>.+)$",
        "阶段=响应已生成 action={action} id={id} 处理耗时={dispatch_ms}ms 结果={result}",
    ),
    (
        r"^stage=response_sent action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) client_id=(?P<client_id>[^ ]+) total_ms=(?P<ms>.+)$",
        "阶段=响应已发送 action={action} id={id} 客户端={client_id} 总耗时={ms}ms",
    ),
    (r"^tx trade bridge context ready$", "交易桥 ContextInfo 已就绪"),
    (r"^tx trade bridge stopped$", "交易桥已停止"),
    (
        r"^tx trade bridge started LTtx=(?P<endpoint>[^ ]+) request_channel=(?P<channel>.+)$",
        "交易桥已启动 LTtx={endpoint} 请求通道={channel}",
    ),
    (
        r"^tx trade response_ready action=(?P<action>[^ ]+) id=(?P<id>.+)$",
        "交易请求已生成响应 action={action} id={id}",
    ),
    (
        r"^tx trade request_error action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) error=(?P<error>.+)$",
        "交易请求处理失败 action={action} id={id} 错误={error}",
    ),
    (
        r"^tx trade response_sent action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) client_id=(?P<client_id>[^ ]+) total_ms=(?P<ms>.+)$",
        "交易响应已发送 action={action} id={id} 客户端={client_id} 总耗时={ms}ms",
    ),
    (
        r"^query_trade_detail start account=(?P<account>[^ ]+) account_type=(?P<account_type>[^ ]+) detail_type=(?P<detail_type>.+)$",
        "交易明细查询开始 账号={account} 账号类型={account_type} 明细类型={detail_type}",
    ),
    (
        r"^query_trade_detail call failed account=(?P<account>[^ ]+) detail_type=(?P<detail_type>[^ ]+) error=(?P<error>.+)$",
        "交易明细查询调用失败 账号={account} 明细类型={detail_type} 错误={error}",
    ),
    (
        r"^query_trade_detail format failed detail_type=(?P<detail_type>[^ ]+) index=(?P<index>[^ ]+) type=(?P<type>[^ ]+) error=(?P<error>.+)$",
        "交易明细格式化失败 明细类型={detail_type} 序号={index} 数据类型={type} 错误={error}",
    ),
    (
        r"^query_trade_detail done detail_type=(?P<detail_type>[^ ]+) count=(?P<count>.+)$",
        "交易明细查询完成 明细类型={detail_type} 数量={count}",
    ),
    (
        r"^trade detail getattr failed type=(?P<type>[^ ]+) field=(?P<field>[^ ]+) error=(?P<error>.+)$",
        "交易明细读取属性失败 数据类型={type} 字段={field} 错误={error}",
    ),
    (
        r"^trade detail get failed type=(?P<type>[^ ]+) field=(?P<field>[^ ]+) error=(?P<error>.+)$",
        "交易明细 get 读取失败 数据类型={type} 字段={field} 错误={error}",
    ),
    (
        r"^qmt userdata log cleanup log_dir=(?P<dir>.+) retention_days=(?P<days>[^ ]+) deleted=(?P<deleted>[^ ]+) failed=(?P<failed>[^ ]+) dry_run=(?P<dry_run>.+)$",
        "QMT userdata 日志清理完成 目录={dir} 保留天数={days} 删除={deleted} 失败={failed} dry_run={dry_run}",
    ),
    (
        r"^account subscribed account=(?P<account>[^ ]+) client_id=(?P<client_id>.+)$",
        "账号回调已订阅 账号={account} 客户端={client_id}",
    ),
    (
        r"^account unsubscribed account=(?P<account>[^ ]+) client_id=(?P<client_id>.+)$",
        "账号回调已取消订阅 账号={account} 客户端={client_id}",
    ),
    (
        r"^normal bridge started LTtx=(?P<endpoint>[^ ]+) request_channel=(?P<channel>.+)$",
        "普通桥已启动 LTtx={endpoint} 请求通道={channel}",
    ),
    (r"^normal bridge worker is released by quote/timer/handlebar callbacks$", "普通桥 worker 由行情/定时器/handlebar 回调唤醒"),
    (r"^normal bridge context ready$", "普通桥 ContextInfo 已就绪"),
    (r"^normal bridge worker thread started in init context$", "普通桥 worker 线程已在 init context 中启动"),
    (
        r"^normal bridge recv error: (?P<error>.+)$",
        "普通桥接收请求异常：{error}",
    ),
    (
        r"^normal bridge request queued action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) queue_size=(?P<size>[^ ]+) coalesced=(?P<coalesced>.+)$",
        "普通桥请求已入队 action={action} id={id} 队列长度={size} 合并查询={coalesced}",
    ),
    (
        r"^normal bridge request queued action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) queue_size=(?P<size>.+)$",
        "普通桥请求已入队 action={action} id={id} 队列长度={size}",
    ),
    (
        r"^normal bridge request coalesced action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) waiters=(?P<waiters>.+)$",
        "普通桥请求已合并 action={action} id={id} 等待方={waiters}",
    ),
    (
        r"^normal bridge quote subscribed id=(?P<id>[^ ]+) kind=(?P<kind>.+)$",
        "行情订阅已建立 id={id} 类型={kind}",
    ),
    (
        r"^normal bridge whole quote publish enabled id=(?P<id>[^ ]+) internal_id=(?P<internal>.+)$",
        "全推行情发布已开启 id={id} 内部订阅={internal}",
    ),
    (
        r"^normal bridge quote unsubscribed id=(?P<id>.+)$",
        "行情订阅已取消 id={id}",
    ),
    (
        r"^normal bridge worker error source=(?P<source>[^ ]+) error=(?P<error>.+)$",
        "普通桥 worker 异常 来源={source} 错误={error}",
    ),
    (
        r"^normal bridge worker response source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) total_ms=(?P<ms>.+)$",
        "普通桥响应完成 来源={source} action={action} id={id} 总耗时={ms}ms",
    ),
    (
        r"^normal bridge worker coalesced_response source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) waiters=(?P<waiters>[^ ]+) total_ms=(?P<ms>.+)$",
        "普通桥合并响应完成 来源={source} action={action} id={id} 等待方={waiters} 总耗时={ms}ms",
    ),
    (
        r"^normal bridge worker coalesced_error source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) waiters=(?P<waiters>[^ ]+) error=(?P<error>.+)$",
        "普通桥合并请求处理失败 来源={source} action={action} id={id} 等待方={waiters} 错误={error}",
    ),
    (
        r"^normal bridge worker request_error source=(?P<source>[^ ]+) action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) error=(?P<error>.+)$",
        "普通桥请求处理失败 来源={source} action={action} id={id} 错误={error}",
    ),
    (
        r"^normal bridge internal whole quote subscribed id=(?P<id>.+)$",
        "普通桥内部全推行情订阅成功 id={id}",
    ),
    (
        r"^normal bridge internal whole quote subscribe failed: (?P<error>.+)$",
        "普通桥内部全推行情订阅失败：{error}",
    ),
    (
        r"^normal bridge timer scheduled key=(?P<key>.+)$",
        "普通桥定时器已注册 key={key}",
    ),
    (
        r"^normal bridge timer schedule failed: (?P<error>.+)$",
        "普通桥定时器注册失败：{error}",
    ),
    (
        r"^normal bridge send_error action=(?P<action>[^ ]+) id=(?P<id>[^ ]+) client_id=(?P<client_id>[^ ]+) error=(?P<error>.+)$",
        "普通桥错误响应已发送 action={action} id={id} 客户端={client_id} 错误={error}",
    ),
    (
        r"^normal bridge callback event sent event=(?P<event>[^ ]+) account=(?P<account>.+)$",
        "普通桥交易回调事件已发送 event={event} 账号={account}",
    ),
    (
        r"^pipe normal bridge started pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>.+)$",
        "Pipe 普通桥已启动 pipe={pipe} 请求通道={channel}",
    ),
    (r"^pipe normal bridge stopped$", "Pipe 普通桥已停止"),
    (
        r"^pipe trade bridge started pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>.+)$",
        "Pipe 交易桥已启动 pipe={pipe} 请求通道={channel}",
    ),
    (r"^pipe trade bridge stopped$", "Pipe 交易桥已停止"),
    (
        r"^pipe connected pipe=(?P<pipe>[^ ]+) request_channel=(?P<channel>[^ ]+) bridge_id=(?P<bridge_id>.+)$",
        "Pipe 已连接 pipe={pipe} 请求通道={channel} 桥接ID={bridge_id}",
    ),
    (
        r"^pipe connect/read failed: (?P<error>.+)$",
        "Pipe 连接或读取失败：{error}",
    ),
    (
        r"^pipe push failed: (?P<error>.+)$",
        "Pipe 推送失败：{error}",
    ),
]


def normalize_log_language(value=None):
    value = str(value or "").strip().lower()
    if value in ("en", "english"):
        return "en"
    return "zh"


def normalize_log_enabled(value=None):
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off", "disable", "disabled", "closed", "close"):
        return False
    return True


def get_log_language():
    with _LANG_LOCK:
        if _LOG_LANGUAGE:
            return _LOG_LANGUAGE
    return normalize_log_language(os.environ.get("CFQUANT_QMT_LOG_LANGUAGE") or os.environ.get("CFQUANT_LOG_LANGUAGE") or os.environ.get("CFQUANT_LOG_LANG") or "zh")


def set_log_language(value):
    global _LOG_LANGUAGE
    lang = normalize_log_language(value)
    with _LANG_LOCK:
        _LOG_LANGUAGE = lang
    return lang


def get_log_enabled():
    with _LANG_LOCK:
        if _LOG_ENABLED is not None:
            return bool(_LOG_ENABLED)
    return normalize_log_enabled(os.environ.get("CFQUANT_QMT_LOG_ENABLED") or os.environ.get("CFQUANT_LOG_ENABLED") or "1")


def set_log_enabled(value):
    global _LOG_ENABLED
    enabled = normalize_log_enabled(value)
    with _LANG_LOCK:
        _LOG_ENABLED = enabled
    return enabled


def translate_log(message, language=None):
    text = str(message)
    if normalize_log_language(language or get_log_language()) == "en":
        return text
    for pattern, template in _TRANSLATIONS:
        match = re.match(pattern, text)
        if not match:
            continue
        try:
            return template.format(**match.groupdict())
        except Exception:
            return text
    return text


PROTOCOL_VERSION = 1
MESSAGE_PREFIX = "cfquant:"
_pd = None
_pd_loaded = False


def now_ms():
    return int(time.time() * 1000)


def new_id(prefix="req"):
    return "%s_%s_%s" % (prefix, now_ms(), uuid.uuid4().hex[:12])


def dumps_message(payload):
    data = dict(payload)
    data.setdefault("protocol", "cfquant")
    data.setdefault("version", PROTOCOL_VERSION)
    data.setdefault("ts", now_ms())
    return MESSAGE_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def loads_message(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    if "|" in raw:
        _, raw = raw.split("|", 1)
    if not raw.startswith(MESSAGE_PREFIX):
        return None
    try:
        data = json.loads(raw[len(MESSAGE_PREFIX):])
    except Exception:
        return None
    if data.get("protocol") != "cfquant":
        return None
    return data


def pack_request(action, params=None, reply_channel=None, client_id=None, request_id=None):
    return dumps_message({
        "type": "request",
        "id": request_id or new_id("req"),
        "action": action,
        "params": params or {},
        "reply_channel": reply_channel,
        "client_id": client_id,
    })


def pack_response(request_id, ok=True, result=None, error=None, meta=None):
    return dumps_message({
        "type": "response",
        "id": request_id,
        "ok": bool(ok),
        "result": encode_value(result),
        "error": encode_error(error),
        "meta": meta or {},
    })


def pack_event(event, data=None, client_id=None, subscription_id=None, meta=None):
    return dumps_message({
        "type": "event",
        "event": event,
        "client_id": client_id,
        "subscription_id": subscription_id,
        "data": encode_value(data),
        "meta": meta or {},
    })


def encode_error(error):
    if error is None:
        return None
    if isinstance(error, dict):
        return error
    return {
        "type": type(error).__name__,
        "message": str(error),
    }


def encode_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, bytes):
        return {
            "__cf_type__": "bytes",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, dict):
        return {str(k): encode_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [encode_value(v) for v in value]
    if _looks_like_dataframe(value):
        return _encode_dataframe(value)
    if _looks_like_series(value):
        return _encode_series(value)
    pd = _get_pandas()
    if pd is not None and isinstance(value, pd.DataFrame):
        return _encode_dataframe(value)
    if pd is not None and isinstance(value, pd.Series):
        return _encode_series(value)
    if hasattr(value, "__dict__"):
        return {
            "__cf_type__": "object",
            "class": type(value).__name__,
            "attrs": encode_value(vars(value)),
        }
    return str(value)


def _get_pandas():
    return None

def _looks_like_dataframe(value):
    return (
        hasattr(value, "columns")
        and hasattr(value, "index")
        and hasattr(value, "values")
        and hasattr(value, "to_dict")
    )


def _looks_like_series(value):
    return (
        hasattr(value, "index")
        and hasattr(value, "values")
        and hasattr(value, "name")
        and not hasattr(value, "columns")
    )


def _clean_cell(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return encode_value(value)


def _encode_dataframe(value):
    try:
        raw_rows = value.values.tolist()
    except Exception:
        raw_rows = []
    rows = []
    for row in raw_rows:
        rows.append([_clean_cell(v) for v in row])
    index_name = getattr(getattr(value, "index", None), "name", None)
    return {
        "__cf_type__": "dataframe",
        "columns": [str(c) for c in getattr(value, "columns", [])],
        "index": [str(i) for i in getattr(value, "index", [])],
        "data": rows,
        "index_name": str(index_name) if index_name is not None else None,
    }


def _encode_series(value):
    try:
        raw_values = value.values.tolist()
    except Exception:
        raw_values = []
    return {
        "__cf_type__": "series",
        "index": [str(i) for i in getattr(value, "index", [])],
        "data": [_clean_cell(v) for v in raw_values],
        "name": str(value.name) if getattr(value, "name", None) is not None else None,
    }


def decode_value(value):
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    if not isinstance(value, dict):
        return value

    value_type = value.get("__cf_type__")
    if value_type == "bytes":
        return base64.b64decode(value.get("data", ""))
    if value_type in ("dataframe", "series"):
        return value

    if value_type == "object":
        return SimpleObject(**decode_value(value.get("attrs", {})))
    return {k: decode_value(v) for k, v in value.items()}


class SimpleObject(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join("%s=%r" % item for item in sorted(self.__dict__.items())),
        )

LEGACY_NORMAL_REQUEST_CHANNEL = "cfquant.normal.request"
LEGACY_TRADE_REQUEST_CHANNEL = "cfquant.trade.request"
LEGACY_CALLBACK_EVENT_CHANNEL = "cfquant.callback.event"


def normalize_bridge_id(value=None):
    value = str(value or "").strip()
    if not value:
        return "default"
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", value)
    return value or "default"


def bridge_id_from_env(default="default"):
    return normalize_bridge_id(os.environ.get("CFQUANT_BRIDGE_ID") or default)


def bridge_env_prefix(bridge_id):
    safe = re.sub(r"[^0-9A-Za-z]+", "_", normalize_bridge_id(bridge_id)).upper()
    return "CFQUANT_BRIDGE_%s_" % safe


def channels_for_bridge(bridge_id=None):
    bridge_id = normalize_bridge_id(bridge_id or bridge_id_from_env())
    prefix = bridge_env_prefix(bridge_id)
    if bridge_id == "default":
        default_normal = os.environ.get("CFQUANT_NORMAL_REQUEST_CHANNEL", LEGACY_NORMAL_REQUEST_CHANNEL)
        default_trade = os.environ.get("CFQUANT_TRADE_REQUEST_CHANNEL", LEGACY_TRADE_REQUEST_CHANNEL)
        default_callback = os.environ.get("CFQUANT_CALLBACK_EVENT_CHANNEL", LEGACY_CALLBACK_EVENT_CHANNEL)
    else:
        default_normal = "cfquant.%s.normal.request" % bridge_id
        default_trade = "cfquant.%s.trade.request" % bridge_id
        default_callback = "cfquant.%s.callback.event" % bridge_id
    return {
        "normal": os.environ.get(prefix + "NORMAL_REQUEST_CHANNEL", default_normal),
        "trade": os.environ.get(prefix + "TRADE_REQUEST_CHANNEL", default_trade),
        "callback": os.environ.get(prefix + "CALLBACK_EVENT_CHANNEL", default_callback),
    }


def bridge_name(bridge_id):
    bridge_id = normalize_bridge_id(bridge_id)
    prefix = bridge_env_prefix(bridge_id)
    return os.environ.get(prefix + "NAME", bridge_id)


def configured_bridge_ids():
    raw = os.environ.get("CFQUANT_BRIDGE_IDS")
    if raw:
        ids = [normalize_bridge_id(item) for item in raw.split(",") if item.strip()]
    else:
        ids = [bridge_id_from_env()]
    seen = set()
    result = []
    for bridge_id in ids:
        if bridge_id in seen:
            continue
        seen.add(bridge_id)
        result.append(bridge_id)
    return result or ["default"]


def configured_bridges():
    result = {}
    for bridge_id in configured_bridge_ids():
        result[bridge_id] = {
            "id": bridge_id,
            "name": bridge_name(bridge_id),
            "channels": channels_for_bridge(bridge_id),
        }
    return result

_ACCOUNT_ROUTE_LOCK = threading.RLock()
_ACCOUNT_ROUTE_SUBSCRIBERS = {}
_ACCOUNT_ROUTE_CLIENT_ACCOUNTS = {}


def _account_route_type(account):
    if account is None:
        return ""
    return str(getattr(account, "m_nAccountType", "") or getattr(account, "account_type", "") or "")


def _account_route_id(account):
    if account is None:
        return ""
    return str(getattr(account, "m_strAccountID", "") or getattr(account, "account_id", "") or account or "")


def _account_route_key(account):
    return (_account_route_type(account), _account_route_id(account))


def account_route_subscribe(account, client_id, *, strategy=None, sync_account_status=None):
    if account is None or not client_id:
        return
    key = _account_route_key(account)
    with _ACCOUNT_ROUTE_LOCK:
        subscribers = _ACCOUNT_ROUTE_SUBSCRIBERS.setdefault(key, set())
        subscribers.add(str(client_id))
        account_text = "{}:{}".format(key[0], key[1])
        _ACCOUNT_ROUTE_CLIENT_ACCOUNTS.setdefault(str(client_id), set()).add(account_text)


def account_route_unsubscribe(account, client_id, *, strategy=None):
    if not client_id:
        return
    client_id = str(client_id)
    keys = []
    if account is not None:
        keys.append(_account_route_key(account))
    with _ACCOUNT_ROUTE_LOCK:
        if not keys:
            keys = list(_ACCOUNT_ROUTE_SUBSCRIBERS.keys())
        for key in keys:
            subscribers = _ACCOUNT_ROUTE_SUBSCRIBERS.get(key)
            if subscribers:
                subscribers.discard(client_id)
                if not subscribers:
                    _ACCOUNT_ROUTE_SUBSCRIBERS.pop(key, None)
        for accounts in _ACCOUNT_ROUTE_CLIENT_ACCOUNTS.values():
            accounts.discard(client_id)
        empty_clients = [cid for cid, accounts in _ACCOUNT_ROUTE_CLIENT_ACCOUNTS.items() if not accounts]
        for cid in empty_clients:
            _ACCOUNT_ROUTE_CLIENT_ACCOUNTS.pop(cid, None)


def account_route_client_ids(account):
    key = _account_route_key(account)
    with _ACCOUNT_ROUTE_LOCK:
        return list(_ACCOUNT_ROUTE_SUBSCRIBERS.get(key, set()))


def account_route_status():
    with _ACCOUNT_ROUTE_LOCK:
        return {
            "accounts": {"{}:{}".format(key[0], key[1]): sorted(values) for key, values in _ACCOUNT_ROUTE_SUBSCRIBERS.items()},
            "clients": {client_id: sorted(accounts) for client_id, accounts in _ACCOUNT_ROUTE_CLIENT_ACCOUNTS.items()},
        }

XTTRADER_COMPAT_CANDIDATES = {
    "query_account_info": ("query_account_info", "get_account_info"),
    "query_account_infos": ("query_account_infos", "get_account_infos", "query_account_info", "get_account_info"),
    "query_account_status": ("query_account_status", "get_account_status"),
    "query_position_statistics": ("query_position_statistics", "get_position_statistics"),
    "query_secu_account": ("query_secu_account", "get_secu_account"),
    "query_credit_detail": ("query_credit_detail", "get_credit_detail"),
    "query_credit_subjects": ("query_credit_subjects", "get_credit_subjects"),
    "query_credit_slo_code": ("query_credit_slo_code", "get_credit_slo_code"),
    "query_credit_assure": ("query_credit_assure", "get_credit_assure"),
    "query_stk_compacts": ("query_stk_compacts", "get_stk_compacts"),
    "query_ipo_data": ("query_ipo_data", "get_ipo_data"),
    "query_new_purchase_limit": ("query_new_purchase_limit", "get_new_purchase_limit"),
    "query_bank_info": ("query_bank_info", "get_bank_info"),
    "query_bank_amount": ("query_bank_amount", "get_bank_amount"),
    "query_bank_transfer_stream": ("query_bank_transfer_stream", "get_bank_transfer_stream"),
    "bank_transfer_in": ("bank_transfer_in", "transfer_bank_to_security"),
    "bank_transfer_out": ("bank_transfer_out", "transfer_security_to_bank"),
    "fund_transfer": ("fund_transfer",),
    "secu_transfer": ("secu_transfer",),
    "ctp_transfer_future_to_option": ("ctp_transfer_future_to_option",),
    "ctp_transfer_option_to_future": ("ctp_transfer_option_to_future",),
    "query_data": ("query_data",),
    "export_data": ("export_data",),
    "sync_transaction_from_external": ("sync_transaction_from_external",),
    "smt_query_compact": ("smt_query_compact",),
    "smt_query_order": ("smt_query_order",),
    "smt_query_quoter": ("smt_query_quoter",),
    "smt_appointment_order": ("smt_appointment_order",),
    "smt_appointment_cancel": ("smt_appointment_cancel",),
    "smt_negotiate_order": ("smt_negotiate_order",),
    "smt_compact_return": ("smt_compact_return",),
    "smt_compact_renewal": ("smt_compact_renewal",),
}


XTDATA_COMPAT_CANDIDATES = {
    "get_trading_calendar": ("get_trading_calendar",),
    "get_trading_period": ("get_trading_period",),
    "get_kline_trading_period": ("get_kline_trading_period",),
    "get_all_trading_periods": ("get_all_trading_periods",),
    "get_period_list": ("get_period_list",),
    "create_sector": ("create_sector",),
    "add_sector": ("add_sector",),
    "remove_sector": ("remove_sector",),
    "reset_sector": ("reset_sector",),
    "remove_stock_from_sector": ("remove_stock_from_sector",),
    "create_formula": ("create_formula",),
    "call_formula": ("call_formula",),
    "subscribe_formula": ("subscribe_formula",),
    "unsubscribe_formula": ("unsubscribe_formula",),
    "get_formula_result": ("get_formula_result",),
    "get_l2_quote": ("get_l2_quote",),
    "get_l2_order": ("get_l2_order",),
    "get_l2_transaction": ("get_l2_transaction",),
    "subscribe_l2thousand": ("subscribe_l2thousand",),
    "get_l2thousand_queue": ("get_l2thousand_queue",),
    "get_tabular_data": ("get_tabular_data",),
    "download_tabular_data": ("download_tabular_data", "down_tabular_data"),
    "push_custom_data": ("push_custom_data",),
    "download_sector_data": ("download_sector_data", "down_sector_data"),
    "download_index_weight": ("download_index_weight", "down_index_weight"),
    "download_history_contracts": ("download_history_contracts", "down_history_contracts"),
    "download_holiday_data": ("download_holiday_data", "down_holiday_data"),
    "download_etf_info": ("download_etf_info", "down_etf_info"),
    "download_cb_data": ("download_cb_data", "down_cb_data"),
    "download_his_st_data": ("download_his_st_data", "down_his_st_data"),
    "download_metatable_data": ("download_metatable_data", "down_metatable_data"),
}

XTDATA_MAINCHAIN_UNSUPPORTED = {
    "connect",
    "disconnect",
    "reconnect",
    "get_quote_server_status",
    "watch_quote_server_status",
    "get_quote_server_config",
    "get_data_dir",
    "set_data_dir",
    "read_feather",
    "write_feather",
}


class TxTradeBridge(object):
    def __init__(
        self,
        context,
        ip="127.0.0.1",
        port=2049,
        token="LTtx",
        request_channel="cfquant.request",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
    ):
        self.context = context
        self.ip = ip
        self.port = int(port)
        self.token = token
        self.request_channel = request_channel
        self.bridge_id = bridge_id or "default"
        self.account_id = account_id
        self.show = show
        self.globals_dict = globals_dict or {}
        self.running = False
        self.tx = None
        self.log_file = self._default_log_file()
        self.account_subscribers = {}
        self.client_accounts = {}
        self.subscriber_lock = threading.RLock()
        self.started_at = 0.0
        self.account_type = ""
        self.auto_trade_callback_enabled = False

    def set_context(self, context):
        self.context = context
        if self.account_id:
            self._set_context_account(self.account_id, self.account_type)
        self._enable_auto_trade_callback()
        self._log("tx trade bridge context ready")
        self._publish_runtime_report("context_ready")

    def start(self):
        if self.running:
            return self
        self.running = True
        if not self.started_at:
            self.started_at = time.time()
        txl = self._load_txl()
        self.tx = txl(self.ip, self.port, self.token)
        self.tx.start_tx()
        self.tx.start_txg(self.request_channel)
        self._log(
            "tx trade bridge started LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def close(self):
        self.running = False
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass
        self._log("tx trade bridge stopped")

    def run_forever(self, sleep_seconds=0.05):
        self.start()
        while self.running:
            self.poll(max_messages=100, timeout=sleep_seconds)

    def poll(self, max_messages=100, timeout=0):
        self.start()
        count = 0
        while self.running and count < max_messages:
            try:
                raw = self.tx.Q.get(timeout=timeout if count == 0 else 0)
            except Exception:
                break
            if raw is None:
                break
            self._handle_raw(raw)
            count += 1
        return count

    def _handle_raw(self, raw):
        received_at = time.time()
        msg = loads_message(raw)
        if not msg or msg.get("type") != "request":
            return
        request_id = msg.get("id")
        action = msg.get("action")
        client_id = msg.get("client_id") or msg.get("reply_channel")
        try:
            result = self._dispatch(action, msg.get("params") or {}, msg)
            response = pack_response(request_id, ok=True, result=result)
            self._log("tx trade response_ready action=%s id=%s" % (action, request_id))
        except Exception as e:
            response = pack_response(request_id, ok=False, error=e)
            self._log("tx trade request_error action=%s id=%s error=%s" % (action, request_id, e))
        if client_id:
            self.tx.push("response", response, client_id)
            self._log(
                "tx trade response_sent action=%s id=%s client_id=%s total_ms=%.2f"
                % (action, request_id, client_id, (time.time() - received_at) * 1000)
            )

    def _dispatch(self, action, params, msg):
        if action == "cfquant.ping":
            return {
                "pong": True,
                "ts": time.time(),
                "request_channel": self.request_channel,
                "bridge_id": self.bridge_id,
            }
        if action == "cfquant.status":
            return self._status()
        if action == "cfquant.set_log_language":
            return self._set_log_language(params)
        if action == "cfquant.get_log_language":
            return {"language": get_log_language()}
        if action == "cfquant.set_log_enabled":
            return self._set_log_enabled(params)
        if action == "cfquant.get_log_enabled":
            return {"enabled": get_log_enabled()}
        if action == "cfquant.cleanup_qmt_logs":
            return self._cleanup_qmt_userdata_logs(params)
        if action == "cfquant.query_info":
            return self._query_info(params)
        if action == "xttrader.subscribe":
            return self._subscribe_account(params, msg)
        if action == "xttrader.unsubscribe":
            return self._unsubscribe_account(params, msg)
        if action == "xttrader.query_stock_positions":
            return self._query_trade_detail(params, "position")
        if action == "xttrader.query_stock_orders":
            return self._query_trade_detail(params, "order")
        if action == "xttrader.query_stock_trades":
            return self._query_trade_detail(params, "deal")
        if action == "xttrader.query_stock_asset":
            return self._query_trade_detail(params, "account")
        if action == "xttrader.order_stock":
            return self._order_stock(params, msg)
        if action == "xttrader.order_stock_batch":
            return self._order_stock_batch(params, msg)
        if action == "xttrader.order_stock_async":
            return self._order_stock_async(params, msg)
        if action == "xttrader.cancel_order_stock":
            return self._cancel_order_stock(params)
        if action == "xttrader.cancel_order_stock_async":
            return self._cancel_order_stock_async(params, msg)
        if action == "xttrader.cancel_order_stock_sysid":
            return self._cancel_order_stock_sysid(params)
        if action == "xttrader.cancel_order_stock_sysid_async":
            return self._cancel_order_stock_sysid_async(params, msg)
        if action == "xtdata.get_market_data":
            return self._get_market_data(params)
        if action == "xtdata.get_market_data_ex":
            return self._get_market_data_ex(params)
        if action == "xtdata.get_full_tick":
            return self.context.get_full_tick(params.get("code_list", []))
        if action == "xtdata.get_local_data":
            return self._get_local_data(params)
        if action == "xtdata.download_history_data":
            return self._download_history_data(params, msg)
        if action == "xtdata.download_history_data2":
            return self._download_history_data2(params, msg)
        if action == "xtdata.get_financial_data":
            return self._get_financial_data(params)
        if action == "xtdata.get_raw_financial_data":
            return self._get_raw_financial_data(params)
        if action == "xtdata.download_financial_data":
            return self._download_financial_data(params, msg)
        if action == "xtdata.download_financial_data2":
            return self._download_financial_data(params, msg)
        if action == "xtdata.get_instrument_detail":
            return self._get_instrument_detail(params)
        if action == "xtdata.get_stock_list_in_sector":
            return self.context.get_stock_list_in_sector(params.get("sector_name", ""))
        if action.startswith("xtdata."):
            return self._dispatch_xtdata_compat(action, params, msg)
        if action.startswith("xttrader."):
            return self._dispatch_xttrader_compat(action, params, msg)
        raise ValueError("unsupported action: %s" % action)

    def _status(self):
        runtime = self._runtime_info()
        status = {
            "bridge": type(self).__name__,
            "bridge_id": self.bridge_id,
            "running": self.running,
            "request_channel": self.request_channel,
            "account_id": self.account_id,
            "version": CORE_VERSION,
            "core_version": CORE_VERSION,
            "runtime_core_version": CORE_VERSION,
            "qmt_runtime_core_version": CORE_VERSION,
            "entry_version": LITE_ENTRY_VERSION,
            "runtime_entry_version": LITE_ENTRY_VERSION,
            "qmt_runtime_entry_version": LITE_ENTRY_VERSION,
            "qmt_runtime_entry_script": "CFQUANT_LITE.py",
            "qmt_runtime_mode": "lite_extreme_pipe",
            "qmt_runtime_label": "极致模式",
            "transport": "lite",
            "transport_mode": "lite",
            "runtime": runtime,
            "account_subscribers": self._account_subscriber_status(),
            "log_language": get_log_language(),
            "log_enabled": get_log_enabled(),
            "context_ready": self.context is not None,
            "tx_ready": self.tx is not None,
            "ts": time.time(),
        }
        try:
            extra = self._status_extra()
            if extra:
                status.update(extra)
        except Exception as e:
            status["status_extra_error"] = str(e)
        return status

    def _runtime_info(self):
        now = time.time()
        entry_file = ""
        try:
            entry_file = str((self.globals_dict or {}).get("__file__") or "")
        except Exception:
            entry_file = ""
        try:
            entry_file = entry_file or str(globals().get("__file__") or "")
        except Exception:
            entry_file = entry_file or ""
        try:
            entry_file_func = globals().get("_entry_file_path")
            if not entry_file and callable(entry_file_func):
                entry_file = str(entry_file_func() or "")
        except Exception:
            pass
        try:
            base_dir_func = globals().get("_entry_base_dir")
            core_dir = str(base_dir_func() or "") if callable(base_dir_func) else ""
        except Exception:
            core_dir = ""
        if not core_dir:
            core_dir = os.path.dirname(os.path.abspath(entry_file)) if entry_file else os.getcwd()
        return {
            "schema": "cfquant.qmt.runtime",
            "version": CORE_VERSION,
            "core_version": CORE_VERSION,
            "entry_version": LITE_ENTRY_VERSION,
            "runtime_entry_version": LITE_ENTRY_VERSION,
            "qmt_runtime_entry_version": LITE_ENTRY_VERSION,
            "entry_script": "CFQUANT_LITE.py",
            "runtime_mode": "lite_extreme_pipe",
            "qmt_runtime_mode": "lite_extreme_pipe",
            "runtime_label": "极致模式",
            "transport": "lite",
            "transport_mode": "lite",
            "bridge": type(self).__name__,
            "bridge_id": self.bridge_id,
            "account_id": self.account_id,
            "request_channel": self.request_channel,
            "pid": os.getpid(),
            "python": sys.executable,
            "core_dir": core_dir,
            "version_file": os.path.join(core_dir, "version.py"),
            "entry_file": entry_file,
            "started_at": self.started_at,
            "started_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)) if self.started_at else "",
            "reported_at": now,
            "reported_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        }

    def _publish_runtime_report(self, reason):
        tx = self.tx
        if tx is None or not hasattr(tx, "put"):
            return
        try:
            channel_key = "normal" if "normal" in str(self.request_channel or "").lower() else "trade"
            data = self._runtime_info()
            data.update({
                "reason": reason,
                "transport": data.get("transport") or ("lite" if not self.port else "lttx"),
                "transport_mode": data.get("transport_mode") or ("lite" if not self.port else "lttx"),
                "runtime_mode": data.get("runtime_mode") or ("lite_extreme_pipe" if not self.port else "lttx"),
                "channel_key": channel_key,
            })
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            key = "cfquant.qmt.runtime.%s" % self.bridge_id
            tx.put(key, payload)
            tx.put("%s.%s" % (key, channel_key), payload)
            tx.put("%s.version" % key, CORE_VERSION)
            self._log("tx trade runtime report published version=%s reason=%s" % (CORE_VERSION, reason))
        except Exception as e:
            self._log("tx trade runtime report failed:%s" % e)

    def _status_extra(self):
        return {}

    def _set_log_language(self, params):
        params = params or {}
        lang = set_log_language(params.get("language") or params.get("lang"))
        self._log("QMT日志语言已切换为:%s" % ("中文" if lang == "zh" else "English"))
        return {"language": lang}

    def _set_log_enabled(self, params):
        params = params or {}
        if "enabled" in params:
            value = params.get("enabled")
        else:
            value = params.get("show")
        enabled = set_log_enabled(value)
        self.show = True
        self._log("QMT log output enabled=%s" % ("1" if enabled else "0"), force=True)
        return {"enabled": enabled}

    def _cleanup_qmt_userdata_logs(self, params):
        params = params or {}
        retention_days = self._retention_days(params.get("retention_days"), default=5)
        dry_run = str(params.get("dry_run") or "").strip().lower() in ("1", "true", "yes", "on")
        log_dir, candidate_dirs, python_dir, entry_file = self._qmt_userdata_log_dir()
        result = {
            "bridge_id": self.bridge_id,
            "request_channel": self.request_channel,
            "retention_days": retention_days,
            "dry_run": dry_run,
            "entry_file": entry_file,
            "python_dir": python_dir,
            "log_dir": log_dir,
            "candidate_dirs": candidate_dirs,
            "exists": bool(log_dir and os.path.isdir(log_dir)),
            "scanned_files": 0,
            "kept_files": 0,
            "deleted_files": 0,
            "would_delete_files": 0,
            "failed_files": 0,
            "deleted_bytes": 0,
            "errors": [],
            "ts": time.time(),
        }
        if not result["exists"]:
            return result

        cutoff = time.time() - retention_days * 86400
        for current_root, dirs, files in os.walk(log_dir):
            for name in files:
                path = os.path.join(current_root, name)
                result["scanned_files"] += 1
                try:
                    stat_result = os.stat(path)
                    if stat_result.st_mtime >= cutoff:
                        result["kept_files"] += 1
                        continue
                    if dry_run:
                        result["would_delete_files"] += 1
                        result["deleted_bytes"] += stat_result.st_size
                    else:
                        os.remove(path)
                        result["deleted_files"] += 1
                        result["deleted_bytes"] += stat_result.st_size
                except Exception as e:
                    result["failed_files"] += 1
                    result["errors"].append("%s: %s" % (path, e))
        self._log(
            "qmt userdata log cleanup log_dir=%s retention_days=%s deleted=%s failed=%s dry_run=%s"
            % (log_dir, retention_days, result["deleted_files"], result["failed_files"], dry_run)
        )
        return result

    def _qmt_userdata_log_dir(self):
        entry_file = self.globals_dict.get("__file__") or ""
        if entry_file:
            entry_file = os.path.abspath(entry_file)
            python_dir = os.path.dirname(entry_file)
        else:
            python_dir = os.path.abspath(os.getcwd())
        candidate_dirs = []
        if os.path.basename(python_dir).lower() == "python":
            candidate_dirs.append(os.path.join(os.path.dirname(python_dir), "userdata", "log"))
        candidate_dirs.append(os.path.join(python_dir, "userdata", "log"))

        normalized = []
        seen = set()
        for path in candidate_dirs:
            path = os.path.abspath(path)
            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(path)
        for path in normalized:
            if os.path.isdir(path):
                return path, normalized, python_dir, entry_file
        return normalized[0] if normalized else "", normalized, python_dir, entry_file

    def _retention_days(self, value, default=5):
        try:
            days = int(value)
        except Exception:
            days = int(default)
        if days < 1:
            days = 1
        if days > 3650:
            days = 3650
        return days

    def _query_info(self, params):
        return {
            "orders": self._query_trade_detail(params, "order"),
            "deals": self._query_trade_detail(params, "deal"),
            "positions": self._query_trade_detail(params, "position"),
            "accounts": self._query_trade_detail(params, "account"),
        }

    def _query_trade_detail(self, params, detail_type):
        func = self._get_callable("get_trade_detail_data")
        if not func:
            raise NotImplementedError("get_trade_detail_data not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        if not account_id:
            raise ValueError("account_id is required")
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        self._log(
            "query_trade_detail start account=%s account_type=%s detail_type=%s"
            % (account_id, account_type.lower(), detail_type.lower())
        )
        try:
            rows = func(account_id, account_type.lower(), detail_type.lower()) or []
        except Exception as e:
            self._log(
                "query_trade_detail call failed account=%s detail_type=%s error=%s"
                % (account_id, detail_type, e)
            )
            raise

        result = []
        for index, row in enumerate(rows):
            try:
                result.append(self._format_trade_detail(row, detail_type))
            except Exception as e:
                self._log(
                    "query_trade_detail format failed detail_type=%s index=%s type=%s error=%s"
                    % (detail_type, index, type(row).__name__, e)
                )
                result.append({
                    "format_error": str(e),
                    "raw_type": type(row).__name__,
                })
        if detail_type.lower() == "order" and _truthy_param(params.get("cancelable_only")):
            result = _filter_cancelable_orders(result)
        self._log(
            "query_trade_detail done detail_type=%s count=%s"
            % (detail_type, len(result))
        )
        return result

    def _order_stock(self, params, msg):
        passorder = self._get_callable("passorder")
        if not passorder:
            raise NotImplementedError("passorder not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        order_type = params.get("optype", params.get("order_type"))
        if not account_id:
            raise ValueError("account_id is required")
        if isinstance(order_type, str):
            order_type = 23 if order_type.lower() == "buy" else 24
        price_type = params.get("price_type", 11)
        order_remark = self._first_param(
            params,
            ("order_remark", "remark", "strategy_name"),
            msg.get("id", "tx_order"),
        )
        result = passorder(
            order_type,
            params.get("qmt_order_type", 1101),
            account_id,
            params.get("stock_code", params.get("code", "")),
            price_type,
            params.get("price", 0),
            params.get("order_volume", params.get("num", 0)),
            params.get("strategy_name", "1"),
            params.get("quick_trade", 2),
            order_remark,
            self.context,
        )
        return {"request_result": result, "order_id": result, "order_remark": order_remark}

    def _order_stock_async(self, params, msg):
        result = self._order_stock(params, msg)
        data = {
            "seq": params.get("seq"),
            "account_id": (params.get("account") or {}).get("account_id", params.get("account_id", "")),
            "account_type": self._account_type_name((params.get("account") or {}).get("account_type") or params.get("account_type")).upper(),
            "order_id": result.get("order_id", -1) if isinstance(result, dict) else result,
            "order_remark": result.get("order_remark", params.get("order_remark", "")) if isinstance(result, dict) else params.get("order_remark", ""),
        }
        self._send_trader_event(msg.get("client_id"), "on_order_stock_async_response", data)
        return result

    def _order_stock_batch(self, params, msg):
        orders = params.get("orders") or []
        if not isinstance(orders, list) or not orders:
            raise ValueError("orders must be a non-empty list")
        common_account = params.get("account") or {}
        stop_on_error = bool(params.get("stop_on_error"))
        results = []
        for index, order in enumerate(orders):
            row = dict(params)
            row.pop("orders", None)
            row.update(order or {})
            if common_account and not row.get("account"):
                row["account"] = common_account
            if self._first_param(row, ("order_remark", "remark", "strategy_name")) is None:
                row["order_remark"] = "%s_%s" % (params.get("order_remark") or msg.get("id", "batch_order"), index + 1)
            try:
                result = self._order_stock(row, msg)
                results.append({
                    "index": index,
                    "ok": True,
                    "stock_code": row.get("stock_code", row.get("code", "")),
                    "result": result,
                })
            except Exception as e:
                results.append({
                    "index": index,
                    "ok": False,
                    "stock_code": row.get("stock_code", row.get("code", "")),
                    "error": str(e),
                })
                if stop_on_error:
                    break
        return {
            "total": len(orders),
            "submitted": len([item for item in results if item.get("ok")]),
            "failed": len([item for item in results if not item.get("ok")]),
            "results": results,
        }

    def _cancel_order_stock(self, params):
        cancel_func = self._get_callable("cancel")
        if not cancel_func:
            raise NotImplementedError("cancel not found")
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        order_id = str(params.get("order_id", ""))
        if not account_id:
            raise ValueError("account_id is required")
        if not order_id:
            raise ValueError("order_id is required")
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        result = cancel_func(order_id, account_id, account_type, self.context)
        return {"cancel_result": 0 if result else -1, "request_result": result, "order_id": order_id}

    def _cancel_order_stock_async(self, params, msg):
        result = self._cancel_order_stock(params)
        data = {
            "seq": params.get("seq"),
            "account_id": (params.get("account") or {}).get("account_id", params.get("account_id", "")),
            "account_type": self._account_type_name((params.get("account") or {}).get("account_type") or params.get("account_type")).upper(),
            "order_id": params.get("order_id"),
            "cancel_result": result.get("cancel_result", -1) if isinstance(result, dict) else result,
        }
        self._send_trader_event(msg.get("client_id"), "on_cancel_order_stock_async_response", data)
        return result

    def _cancel_order_stock_sysid(self, params):
        row = dict(params)
        row["order_id"] = params.get("sysid", params.get("order_id", ""))
        result = self._cancel_order_stock(row)
        result["market"] = params.get("market")
        result["sysid"] = params.get("sysid")
        return result

    def _cancel_order_stock_sysid_async(self, params, msg):
        result = self._cancel_order_stock_sysid(params)
        data = {
            "seq": params.get("seq"),
            "account_id": (params.get("account") or {}).get("account_id", params.get("account_id", "")),
            "order_id": params.get("sysid", params.get("order_id")),
            "cancel_result": result.get("cancel_result", -1) if isinstance(result, dict) else result,
        }
        self._send_trader_event(msg.get("client_id"), "on_cancel_order_stock_async_response", data)
        return result

    def _dispatch_xttrader_compat(self, action, params, msg):
        method = action.split(".", 1)[1]
        if method == "query_com_fund":
            rows = self._query_trade_detail(params, "account")
            return rows[0] if rows else {}
        if method == "query_com_position":
            return self._query_trade_detail(params, "position")
        if method == "query_stock_asset_async":
            return self._query_trade_detail(params, "account")
        if method == "query_stock_orders_async":
            return self._query_trade_detail(params, "order")
        if method == "query_stock_trades_async":
            return self._query_trade_detail(params, "deal")
        if method == "query_stock_positions_async":
            return self._query_trade_detail(params, "position")
        return self._generic_xttrader_call(method, params)

    def _dispatch_xtdata_compat(self, action, params, msg):
        method = action.split(".", 1)[1]
        if method == "get_trading_dates":
            return self._get_trading_dates(params)
        if method in (
            "is_stock",
            "is_fund",
            "is_future",
            "get_stock_type",
            "get_stock_name",
            "get_open_date",
            "get_contract_expire_date",
            "get_contract_multiplier",
        ):
            return self._call_stock_callable(method, params)
        if method == "get_weight_in_index":
            return self._get_weight_in_index(params)
        if method == "get_turnover_rate":
            return self._get_turnover_rate(params)
        if method in ("get_ETF_list", "get_etf_list"):
            return self._get_etf_list(params)
        if method == "get_option_detail_data":
            return self._get_option_detail_data(params)
        if method == "get_option_list":
            return self._get_option_list(params)
        if method == "get_option_undl":
            return self._get_option_undl(params)
        if method == "get_option_undl_data":
            return self._get_option_undl_data(params)
        if method == "get_his_st_data":
            return self._get_his_st_data(params)
        if method == "get_his_index_data":
            return self._get_his_index_data(params)
        if method == "get_factor_data":
            return self._get_factor_data(params)
        if method in ("get_financial_data_ori", "get_financial_data_raw"):
            return self._get_raw_financial_data(params)
        if method in XTDATA_MAINCHAIN_UNSUPPORTED:
            raise NotImplementedError(
                "xtdata.%s belongs to MiniQMT client/local data-dir management and is not implemented in cfquant QMT bridge"
                % method
            )
        if method in XTDATA_COMPAT_CANDIDATES:
            return self._generic_xtdata_call(method, params, msg)
        raise NotImplementedError("xtdata.%s is not implemented by cfquant QMT bridge" % method)

    def _generic_xtdata_call(self, method, params, msg=None):
        candidates = XTDATA_COMPAT_CANDIDATES.get(method, (method,))
        func = self._get_callable(*candidates)
        if not func:
            raise NotImplementedError(
                "xtdata.%s requires QMT callable: %s"
                % (method, ", ".join(candidates))
            )
        args = list(params.get("args") or [])
        kwargs = dict(params.get("kwargs") or {})
        callback_event = params.get("callback_event")
        callback_positions = []
        for item in params.get("callback_positions") or []:
            try:
                callback_positions.append(int(item))
            except Exception:
                pass
        client_id = msg.get("client_id") if msg else None

        variants = []
        if callback_event and client_id:
            def callback(data):
                self._send_event(
                    client_id,
                    callback_event,
                    data,
                    meta=self._generic_xtdata_event_meta(params, method, "callback"),
                )

            callback_args = list(args)
            for index in callback_positions:
                if 0 <= index < len(callback_args):
                    callback_args[index] = callback
            if callback_positions:
                variants.append((tuple(callback_args), dict(kwargs)))
            callback_kwargs = dict(kwargs)
            callback_kwargs.setdefault(params.get("callback_name") or "callback", callback)
            variants.append((tuple(args), callback_kwargs))
            variants.append((tuple(args) + (callback,), dict(kwargs)))
        variants.extend([
            (tuple(args), dict(kwargs)),
            ((params,), {}),
            ((), {}),
        ])
        return self._call_variants(func, variants)

    def _generic_xtdata_event_meta(self, params, method, stage):
        meta = {
            "xtdata_generic": True,
            "method": method,
            "stage": stage,
            "bridge_id": self.bridge_id,
        }
        for key in ("job_id", "download_job_id", "stock_code", "stockcode", "period", "start_time", "end_time"):
            value = params.get(key)
            if value not in (None, ""):
                meta[key] = value
        return meta

    def _generic_xttrader_call(self, method, params):
        candidates = XTTRADER_COMPAT_CANDIDATES.get(method, (method,))
        func = self._get_callable(*candidates)
        if not func:
            raise NotImplementedError(
                "xttrader.%s requires QMT callable: %s"
                % (method, ", ".join(candidates))
            )
        args = list(params.get("args") or [])
        kwargs = dict(params.get("kwargs") or {})
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        account_type_value = account.get("account_type") or params.get("account_type")
        account_type = self._account_type_name(account_type_value)
        variants = []
        if account:
            variants.extend([
                ((account,) + tuple(args), kwargs),
                ((account_id,) + tuple(args), kwargs),
                ((account_id, account_type.lower()) + tuple(args), kwargs),
                ((account_id, account_type) + tuple(args), kwargs),
                ((account_id, account_type_value) + tuple(args), kwargs),
            ])
        variants.extend([
            (tuple(args), kwargs),
            ((params,), {}),
        ])
        return self._call_variants(func, variants)

    def _get_market_data(self, params):
        func = self._get_callable("get_market_data")
        if not func:
            return self._get_market_data_ex(params)
        return func(
            params.get("field_list", []),
            params.get("stock_list", []),
            params.get("start_time", ""),
            params.get("end_time", ""),
            params.get("skip_paused", params.get("fill_data", True)),
            params.get("period", "1d"),
            params.get("dividend_type", "none"),
            params.get("count", -1),
        )

    def _get_market_data_ex(self, params):
        func = self._get_callable("get_market_data_ex")
        if not func:
            raise NotImplementedError("get_market_data_ex not found")
        return func(
            params.get("field_list", []),
            params.get("stock_list", []),
            params.get("period", "1d"),
            params.get("start_time", ""),
            params.get("end_time", ""),
            params.get("count", -1),
            params.get("dividend_type", "none"),
            params.get("fill_data", True),
        )

    def _get_local_data(self, params):
        func = self._get_callable("get_local_data")
        if not func:
            return self._get_market_data_ex(params)
        stock_code = self._first_param(params, ("stock_code", "stockcode", "stock", "code"), "")
        stock_list = self._list_param(params.get("stock_list", params.get("code_list", [])))
        if not stock_code and stock_list:
            return dict((code, self._call_local_data(func, code, params)) for code in stock_list)
        return self._call_local_data(func, stock_code, params)

    def _call_local_data(self, func, stock_code, params):
        return self._call_variants(func, [
            ((
                stock_code,
                params.get("start_time", params.get("start_date", "19700101")),
                params.get("end_time", params.get("end_date", "22010101")),
                params.get("period", "follow"),
                params.get("divid_type", params.get("dividend_type", "none")),
                params.get("count", -1),
            ), {}),
            ((
                stock_code,
                params.get("start_time", params.get("start_date", "19700101")),
                params.get("end_time", params.get("end_date", "22010101")),
                params.get("period", "follow"),
                params.get("divid_type", params.get("dividend_type", "none")),
            ), {}),
            ((
                stock_code,
                params.get("start_time", params.get("start_date", "19700101")),
                params.get("end_time", params.get("end_date", "22010101")),
            ), {}),
            ((stock_code,), {}),
        ])

    def _download_event_meta(self, params, kind, stage):
        meta = {
            "download": True,
            "download_kind": kind,
            "stage": stage,
            "bridge_id": self.bridge_id,
        }
        job_id = params.get("download_job_id") or params.get("job_id")
        if job_id:
            meta["job_id"] = str(job_id)
        for name in ("stock_code", "period", "start_time", "end_time"):
            value = params.get(name)
            if value not in (None, ""):
                meta[name] = value
        for name in ("stock_list", "code_list", "table_list"):
            value = params.get(name)
            if value:
                meta[name] = value
        return meta

    def _send_download_event(self, client_id, params, kind, stage, data=None):
        callback_event = params.get("callback_event")
        if not callback_event or not client_id:
            return
        self._send_event(
            client_id,
            callback_event,
            data if data is not None else {},
            meta=self._download_event_meta(params, kind, stage),
        )

    def _download_history_data(self, params, msg=None):
        client_id = msg.get("client_id") if msg else None
        emit_lifecycle = bool(params.get("download_emit_lifecycle"))
        func = self._get_callable("download_history_data", "down_history_data")
        if not func:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": "download_history_data not found",
                })
            raise NotImplementedError("download_history_data not found")
        variants = []
        incrementally = params.get("incrementally")
        if incrementally is not None:
            variants.append((
                (
                    params.get("stock_code", ""),
                    params.get("period", "1d"),
                    params.get("start_time", ""),
                    params.get("end_time", ""),
                    incrementally,
                ),
                {},
            ))
        variants.append((
            (
                params.get("stock_code", ""),
                params.get("period", "1d"),
                params.get("start_time", ""),
                params.get("end_time", ""),
            ),
            {},
        ))
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "submitted", {
                "stage": "submitted",
                "message": "history download request submitted",
            })
        try:
            result = self._call_variants(func, variants)
        except Exception as e:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": str(e),
                })
            raise
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "request_done", {
                "stage": "request_done",
                "result": result,
            })
        return result

    def _download_history_data2(self, params, msg):
        client_id = msg.get("client_id")
        callback_event = params.get("callback_event")
        emit_lifecycle = bool(params.get("download_emit_lifecycle"))
        func = self._get_callable("download_history_data2", "down_history_data2")
        if not func:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": "download_history_data2 not found",
                })
            raise NotImplementedError("download_history_data2 not found")

        def callback(data):
            if callback_event and client_id:
                self._send_event(
                    client_id,
                    callback_event,
                    data,
                    meta=self._download_event_meta(params, "history", "progress"),
                )

        callback_func = callback if callback_event else None
        variants = []
        incrementally = params.get("incrementally")
        if incrementally is not None:
            variants.append((
                (
                    params.get("stock_list", params.get("code_list", [])),
                    params.get("period", "1d"),
                    params.get("start_time", ""),
                    params.get("end_time", ""),
                    callback_func,
                    incrementally,
                ),
                {},
            ))
        variants.append((
            (
                params.get("stock_list", params.get("code_list", [])),
                params.get("period", "1d"),
                params.get("start_time", ""),
                params.get("end_time", ""),
                callback_func,
            ),
            {},
        ))
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "submitted", {
                "stage": "submitted",
                "message": "history download request submitted",
            })
        try:
            result = self._call_variants(func, variants)
        except Exception as e:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "history", "error", {
                    "stage": "error",
                    "error": str(e),
                })
            raise
        if emit_lifecycle:
            self._send_download_event(client_id, params, "history", "request_done", {
                "stage": "request_done",
                "result": result,
            })
        return result

    def _get_instrument_detail(self, params):
        func = self._get_callable("get_instrument_detail")
        if not func:
            raise NotImplementedError("get_instrument_detail not found")
        return func(params.get("stock_code", ""))

    def _get_financial_data(self, params):
        func = self._get_callable("get_financial_data")
        if not func:
            raise NotImplementedError("get_financial_data not found")
        fields = params.get("field_list") or []
        stock_list = params.get("stock_list", params.get("code_list", []))
        table_list = params.get("table_list") or []
        start_time = params.get("start_time", params.get("start_date", ""))
        end_time = params.get("end_time", params.get("end_date", ""))
        report_type = params.get("report_type") or ("announce_time" if fields else "report_time")
        variants = []
        if fields:
            variants.append(((fields, stock_list, start_time, end_time, report_type), {}))
            variants.append(((fields, stock_list, start_time, end_time), {}))
        if not variants:
            raise ValueError("field_list is required")
        return self._call_variants(func, variants)

    def _get_raw_financial_data(self, params):
        func = self._get_callable("get_raw_financial_data")
        if not func:
            raise NotImplementedError("get_raw_financial_data not found")
        fields = params.get("field_list") or []
        stock_list = params.get("stock_list", params.get("code_list", []))
        if not fields:
            raise ValueError("field_list is required for get_raw_financial_data")
        return self._call_variants(func, [
            ((
                fields,
                stock_list,
                params.get("start_time", params.get("start_date", "")),
                params.get("end_time", params.get("end_date", "")),
                params.get("report_type") or "announce_time",
            ), {}),
            ((
                fields,
                stock_list,
                params.get("start_time", params.get("start_date", "")),
                params.get("end_time", params.get("end_date", "")),
            ), {}),
        ])

    def _default_financial_field(self, table):
        table = str(table or "").strip().upper()
        defaults = {
            "ASHAREBALANCESHEET": "fix_assets",
            "ASHAREINCOME": "net_profit_excl_min_int_inc",
            "ASHARECASHFLOW": "net_cash_flows_oper_act",
            "CAPITALSTRUCTURE": "capital",
            "PERSHAREINDEX": "eps",
        }
        return defaults.get(table, "fix_assets")

    def _financial_probe_fields(self, params):
        fields = self._list_param(params.get("field_list") or params.get("fields"))
        tables = self._list_param(params.get("table_list") or params.get("tables") or params.get("table"))
        if not tables:
            tables = ["ASHAREBALANCESHEET"]
        if not fields:
            fields = [self._default_financial_field(tables[0])]
        if len(tables) == 1:
            table = tables[0]
            fields = [
                field if "." in str(field) or "。" in str(field) else "%s.%s" % (table, field)
                for field in fields
            ]
        return fields

    def _summarize_data_result(self, value):
        if value is None:
            return {"type": "None", "empty": True}
        type_name = value.__class__.__name__
        if type_name == "DataFrame":
            shape = list(getattr(value, "shape", []) or [])
            columns = [str(item) for item in list(getattr(value, "columns", []) or [])[:20]]
            return {
                "type": "DataFrame",
                "shape": shape,
                "columns": columns,
                "empty": bool(getattr(value, "empty", False)),
            }
        if type_name == "Series":
            size = int(getattr(value, "size", 0) or 0)
            return {"type": "Series", "count": size, "empty": size <= 0}
        if isinstance(value, dict):
            return {
                "type": "dict",
                "count": len(value),
                "keys": [str(item) for item in list(value.keys())[:20]],
                "empty": len(value) <= 0,
            }
        if isinstance(value, (list, tuple, set)):
            return {"type": type_name, "count": len(value), "empty": len(value) <= 0}
        return {"type": type_name, "preview": str(value)[:200], "empty": False}

    def _check_local_financial_data(self, params):
        fields = self._financial_probe_fields(params)
        stock_list = params.get("stock_list", params.get("code_list", []))
        start_time = params.get("start_time", params.get("start_date", ""))
        end_time = params.get("end_time", params.get("end_date", ""))
        report_type = params.get("report_type") or "report_time"
        func = self._get_callable("get_raw_financial_data")
        action = "get_raw_financial_data"
        if not func:
            func = self._get_callable("get_financial_data")
            action = "get_financial_data"
        if not func:
            raise NotImplementedError("get_raw_financial_data/get_financial_data not found")
        result = self._call_variants(func, [
            ((fields, stock_list, start_time, end_time, report_type), {}),
            ((fields, stock_list, start_time, end_time), {}),
        ])
        return {
            "download_supported": False,
            "manual_download_required": True,
            "manual_download_hint": "QMT官方脚本侧未提供财务数据下载函数；请先在QMT客户端 数据管理 - 财务数据下载 中下载，再读取本地财务数据。",
            "query_action": action,
            "field_list": fields,
            "stock_list": stock_list,
            "query_summary": self._summarize_data_result(result),
            "result": True,
        }

    def _download_financial_data(self, params, msg=None):
        stock_list = params.get("stock_list", params.get("code_list", []))
        table_list = params.get("table_list") or []
        start_time = params.get("start_time", params.get("start_date", ""))
        end_time = params.get("end_time", params.get("end_date", ""))
        callback_event = params.get("callback_event")
        client_id = msg.get("client_id") if msg else None
        emit_lifecycle = bool(params.get("download_emit_lifecycle"))
        func = self._get_callable("download_financial_data2", "down_financial_data2")
        if func:
            def callback(data):
                if callback_event and client_id:
                    self._send_event(
                        client_id,
                        callback_event,
                        data,
                        meta=self._download_event_meta(params, "financial", "progress"),
                    )

            callback_func = callback if callback_event else None
            variants = [
                ((stock_list, table_list, start_time, end_time, callback_func), {}),
                ((stock_list, table_list, start_time, end_time), {}),
            ]
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial", "submitted", {
                    "stage": "submitted",
                    "message": "financial download request submitted",
                })
            try:
                result = self._call_variants(func, variants)
            except Exception as e:
                if emit_lifecycle:
                    self._send_download_event(client_id, params, "financial", "error", {
                        "stage": "error",
                        "error": str(e),
                    })
                raise
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial", "request_done", {
                    "stage": "request_done",
                    "result": result,
                })
            return result
        func = self._get_callable("download_financial_data", "down_financial_data")
        if not func:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial_check", "submitted", {
                    "stage": "submitted",
                    "message": "开始校验本地财务数据，QMT官方脚本侧未提供财务下载函数。",
                })
            try:
                result = self._check_local_financial_data(params)
            except Exception as e:
                if emit_lifecycle:
                    self._send_download_event(client_id, params, "financial_check", "error", {
                        "stage": "error",
                        "error": str(e),
                    })
                raise
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial_check", "request_done", {
                    "stage": "request_done",
                    "message": "本地财务数据校验已返回。",
                    "summary": result.get("query_summary"),
                    "available": not bool((result.get("query_summary") or {}).get("empty")),
                })
            return result
        if emit_lifecycle:
            self._send_download_event(client_id, params, "financial", "submitted", {
                "stage": "submitted",
                "message": "financial download request submitted",
            })
        try:
            result = self._call_variants(func, [
                ((stock_list, table_list), {}),
                ((stock_list,), {}),
            ])
        except Exception as e:
            if emit_lifecycle:
                self._send_download_event(client_id, params, "financial", "error", {
                    "stage": "error",
                    "error": str(e),
                })
            raise
        if emit_lifecycle:
            self._send_download_event(client_id, params, "financial", "request_done", {
                "stage": "request_done",
                "result": result,
            })
        return result

    def _get_trading_dates(self, params):
        func = self._get_callable("get_trading_dates")
        if not func:
            raise NotImplementedError("get_trading_dates not found")
        return func(
            self._first_param(params, ("stockcode", "stock_code", "stock", "code"), ""),
            params.get("start_date", params.get("start_time", "")),
            params.get("end_date", params.get("end_time", "")),
            params.get("count", -1),
            params.get("period", "1d"),
        )

    def _call_stock_callable(self, method, params):
        func = self._get_callable(method)
        if not func:
            raise NotImplementedError("%s not found" % method)
        return func(self._first_param(params, ("stock_code", "stockcode", "stock", "code"), ""))

    def _get_weight_in_index(self, params):
        func = self._get_callable("get_weight_in_index")
        if not func:
            raise NotImplementedError("get_weight_in_index not found")
        return func(
            self._first_param(params, ("mtkindexcode", "index_code", "index", "index_code_ref"), ""),
            self._first_param(params, ("stockcode", "stock_code", "stock", "code"), ""),
        )

    def _get_turnover_rate(self, params):
        func = self._get_callable("get_turnover_rate")
        if not func:
            raise NotImplementedError("get_turnover_rate not found")
        return func(
            self._first_param(params, ("stock_code", "stockcode", "stock", "code"), ""),
            params.get("start_time", params.get("start_date", "")),
            params.get("end_time", params.get("end_date", "")),
        )

    def _get_etf_list(self, params):
        func = self._get_callable("get_ETF_list", "get_etf_list")
        if not func:
            raise NotImplementedError("get_ETF_list not found")
        return func(
            params.get("market", ""),
            self._first_param(params, ("stockcode", "stock_code", "stock", "code"), ""),
            self._list_param(params.get("typeList", params.get("type_list", []))),
        )

    def _get_option_detail_data(self, params):
        func = self._get_callable("get_option_detail_data")
        if not func:
            raise NotImplementedError("get_option_detail_data not found")
        return func(self._first_param(params, ("stockcode", "stock_code", "opt_code", "code"), ""))

    def _get_option_list(self, params):
        func = self._get_callable("get_option_list")
        if not func:
            raise NotImplementedError("get_option_list not found")
        return func(
            self._first_param(params, ("object", "underlying_code", "undl_code", "stock_code", "code"), ""),
            params.get("dedate", params.get("expire_date", "")),
            params.get("opttype", params.get("option_type", "")),
            params.get("isavailavle", params.get("is_available", params.get("available", False))),
        )

    def _get_option_undl(self, params):
        func = self._get_callable("get_option_undl")
        if not func:
            raise NotImplementedError("get_option_undl not found")
        return func(self._first_param(params, ("opt_code", "stock_code", "stockcode", "code"), ""))

    def _get_option_undl_data(self, params):
        func = self._get_callable("get_option_undl_data")
        if not func:
            raise NotImplementedError("get_option_undl_data not found")
        return self._call_variants(func, [
            ((self._first_param(params, ("undl_code_ref", "undl_code", "underlying_code", "stock_code", "code"), ""),), {}),
            ((), {}),
        ])

    def _get_his_st_data(self, params):
        func = self._get_callable("get_his_st_data")
        if not func:
            raise NotImplementedError("get_his_st_data not found")
        return func(self._first_param(params, ("stockCode", "stock_code", "stockcode", "code"), ""))

    def _get_his_index_data(self, params):
        func = self._get_callable("get_his_index_data")
        if not func:
            raise NotImplementedError("get_his_index_data not found")
        return func(self._first_param(params, ("stockCode", "stock_code", "stockcode", "code"), ""))

    def _get_factor_data(self, params):
        func = self._get_callable("get_factor_data")
        if not func:
            raise NotImplementedError("get_factor_data not found")
        return func(
            params.get("field_list", params.get("fields", [])),
            params.get("stock_list", params.get("code_list", [])),
            params.get("start_date", params.get("start_time", "")),
            params.get("end_date", params.get("end_time", "")),
        )

    def _subscribe_account(self, params, msg=None):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id") or self.account_id
        if not account_id:
            raise ValueError("account_id is required")
        account_id = str(account_id).strip()
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        self.account_id = account_id
        self.account_type = account_type
        subscriber_key = (account_type.upper(), account_id)
        client_id = ""
        if msg:
            client_id = msg.get("client_id") or msg.get("reply_channel") or ""
        if client_id:
            with self.subscriber_lock:
                self.account_subscribers.setdefault(subscriber_key, set()).add(client_id)
                self.client_accounts.setdefault(client_id, set()).add(subscriber_key)
            account_route_subscribe(self.bridge_id, account_id, client_id, account_type=account_type)
        self._set_context_account(account_id, account_type)
        self._enable_auto_trade_callback()
        self._log("account subscribed account=%s client_id=%s" % (account_id, client_id or "-"))
        return 0

    def _unsubscribe_account(self, params, msg=None):
        account = params.get("account") or {}
        account_id = account.get("account_id") or params.get("account_id")
        account_type = self._account_type_name(account.get("account_type") or params.get("account_type"))
        subscriber_key = None
        client_id = ""
        if msg:
            client_id = msg.get("client_id") or msg.get("reply_channel") or ""
        if account_id:
            account_id = str(account_id).strip()
            subscriber_key = (account_type.upper(), account_id)
        with self.subscriber_lock:
            if account_id and client_id:
                subscribers = self.account_subscribers.get(subscriber_key)
                if subscribers:
                    subscribers.discard(client_id)
                    if not subscribers:
                        self.account_subscribers.pop(subscriber_key, None)
                accounts = self.client_accounts.get(client_id)
                if accounts:
                    accounts.discard(subscriber_key)
                    accounts.discard(account_id)
                    if not accounts:
                        self.client_accounts.pop(client_id, None)
            elif client_id:
                accounts = self.client_accounts.pop(client_id, set())
                for item in accounts:
                    subscribers = self.account_subscribers.get(item)
                    if subscribers:
                        subscribers.discard(client_id)
                        if not subscribers:
                            self.account_subscribers.pop(item, None)
        account_route_unsubscribe(self.bridge_id, account_id=account_id, client_id=client_id, account_type=account_type if account_id else None)
        if account_id and account_id == self.account_id:
            self.account_id = ""
            self.account_type = ""
        self._log("account unsubscribed account=%s client_id=%s" % (account_id or "-", client_id or "-"))
        return 0

    def _format_trade_detail(self, obj, detail_type):
        detail_type = str(detail_type).lower()
        if detail_type == "order":
            return {
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "order_source": self._order_source(obj),
                "order_time": self._first_value(obj, (
                    "order_time",
                    "entrust_time",
                    "insert_time",
                    "m_strOrderTime",
                    "m_strEntrustTime",
                    "m_strInsertTime",
                    "m_nOrderTime",
                    "m_nEntrustTime",
                    "m_nInsertTime",
                )),
                "order_date": self._first_value(obj, (
                    "order_date",
                    "entrust_date",
                    "m_strOrderDate",
                    "m_strEntrustDate",
                    "m_strTradingDay",
                    "m_nOrderDate",
                    "m_nEntrustDate",
                )),
                "offset_flag": self._get_value(obj, "m_nOffsetFlag"),
                "order_volume": self._get_value(obj, "m_nVolumeTotalOriginal"),
                "traded_price": self._get_value(obj, "m_dTradedPrice"),
                "traded_volume": self._get_value(obj, "m_nVolumeTraded"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "order_status": self._get_value(obj, "m_nOrderStatus"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nOffsetFlag": self._get_value(obj, "m_nOffsetFlag"),
                "m_nVolumeTotalOriginal": self._get_value(obj, "m_nVolumeTotalOriginal"),
                "m_dTradedPrice": self._get_value(obj, "m_dTradedPrice"),
                "m_nVolumeTraded": self._get_value(obj, "m_nVolumeTraded"),
                "m_dTradeAmount": self._get_value(obj, "m_dTradeAmount"),
                "m_strRemark": self._get_value(obj, "m_strRemark"),
                "m_strStrategyName": self._get_value(obj, "m_strStrategyName"),
                "m_strOrderSysID": self._get_value(obj, "m_strOrderSysID"),
                "m_nOrderID": self._get_value(obj, "m_nOrderID"),
                "m_strOrderID": self._get_value(obj, "m_strOrderID"),
                "m_nOrderStatus": self._get_value(obj, "m_nOrderStatus"),
                "m_strOrderStatus": self._get_value(obj, "m_strOrderStatus"),
                "m_nOrderState": self._get_value(obj, "m_nOrderState"),
                "m_strStatus": self._get_value(obj, "m_strStatus"),
                "m_strOrderTime": self._get_value(obj, "m_strOrderTime"),
                "m_strEntrustTime": self._get_value(obj, "m_strEntrustTime"),
                "m_strInsertTime": self._get_value(obj, "m_strInsertTime"),
                "m_nOrderTime": self._get_value(obj, "m_nOrderTime"),
                "m_nEntrustTime": self._get_value(obj, "m_nEntrustTime"),
                "m_nInsertTime": self._get_value(obj, "m_nInsertTime"),
                "m_strOrderDate": self._get_value(obj, "m_strOrderDate"),
                "m_strEntrustDate": self._get_value(obj, "m_strEntrustDate"),
                "m_strTradingDay": self._get_value(obj, "m_strTradingDay"),
            }
        if detail_type == "deal":
            return {
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "trade_time": self._first_value(obj, (
                    "trade_time",
                    "deal_time",
                    "m_strTradeTime",
                    "m_strDealTime",
                    "m_nTradeTime",
                    "m_nDealTime",
                )),
                "trade_date": self._first_value(obj, (
                    "trade_date",
                    "deal_date",
                    "m_strTradeDate",
                    "m_strDealDate",
                    "m_strTradingDay",
                    "m_nTradeDate",
                    "m_nDealDate",
                )),
                "offset_flag": self._get_value(obj, "m_nOffsetFlag"),
                "price": self._get_value(obj, "m_dPrice"),
                "volume": self._get_value(obj, "m_nVolume"),
                "trade_amount": self._get_value(obj, "m_dTradeAmount"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nOffsetFlag": self._get_value(obj, "m_nOffsetFlag"),
                "m_dPrice": self._get_value(obj, "m_dPrice"),
                "m_nVolume": self._get_value(obj, "m_nVolume"),
                "m_dTradeAmount": self._get_value(obj, "m_dTradeAmount"),
                "m_strTradeTime": self._get_value(obj, "m_strTradeTime"),
                "m_strDealTime": self._get_value(obj, "m_strDealTime"),
                "m_nTradeTime": self._get_value(obj, "m_nTradeTime"),
                "m_nDealTime": self._get_value(obj, "m_nDealTime"),
                "m_strTradeDate": self._get_value(obj, "m_strTradeDate"),
                "m_strDealDate": self._get_value(obj, "m_strDealDate"),
                "m_strTradingDay": self._get_value(obj, "m_strTradingDay"),
            }
        if detail_type == "position":
            return {
                "stock_code": self._stock_code(obj),
                "market": self._get_value(obj, "m_strExchangeID"),
                "instrument_name": self._get_value(obj, "m_strInstrumentName"),
                "volume": self._get_value(obj, "m_nVolume"),
                "can_use_volume": self._get_value(obj, "m_nCanUseVolume"),
                "open_price": self._get_value(obj, "m_dOpenPrice"),
                "market_value": self._get_value(obj, "m_dInstrumentValue"),
                "position_cost": self._get_value(obj, "m_dPositionCost"),
                "position_profit": self._get_value(obj, "m_dPositionProfit"),
                "m_strInstrumentID": self._get_value(obj, "m_strInstrumentID"),
                "m_strExchangeID": self._get_value(obj, "m_strExchangeID"),
                "m_strInstrumentName": self._get_value(obj, "m_strInstrumentName"),
                "m_nVolume": self._get_value(obj, "m_nVolume"),
                "m_nCanUseVolume": self._get_value(obj, "m_nCanUseVolume"),
                "m_dOpenPrice": self._get_value(obj, "m_dOpenPrice"),
                "m_dInstrumentValue": self._get_value(obj, "m_dInstrumentValue"),
                "m_dPositionCost": self._get_value(obj, "m_dPositionCost"),
                "m_dPositionProfit": self._get_value(obj, "m_dPositionProfit"),
            }
        if detail_type == "account":
            return {
                "balance": self._get_value(obj, "m_dBalance"),
                "assure_asset": self._get_value(obj, "m_dAssureAsset"),
                "market_value": self._get_value(obj, "m_dInstrumentValue"),
                "total_debit": self._get_value(obj, "m_dTotalDebit"),
                "available": self._get_value(obj, "m_dAvailable"),
                "position_profit": self._get_value(obj, "m_dPositionProfit"),
                "m_dBalance": self._get_value(obj, "m_dBalance"),
                "m_dAssureAsset": self._get_value(obj, "m_dAssureAsset"),
                "m_dInstrumentValue": self._get_value(obj, "m_dInstrumentValue"),
                "m_dTotalDebit": self._get_value(obj, "m_dTotalDebit"),
                "m_dAvailable": self._get_value(obj, "m_dAvailable"),
                "m_dPositionProfit": self._get_value(obj, "m_dPositionProfit"),
            }
        return {"value": str(obj)}

    def _first_value(self, obj, names):
        for name in names:
            value = self._get_value(obj, name)
            if value is not None and value != "":
                return value
        return None

    def _stock_code(self, obj):
        instrument_id = self._get_value(obj, "m_strInstrumentID")
        exchange_id = self._get_value(obj, "m_strExchangeID")
        if instrument_id and exchange_id:
            return "%s.%s" % (instrument_id, exchange_id)
        return instrument_id

    def _order_source(self, obj):
        values = [
            self._get_value(obj, name)
            for name in (
                "order_source",
                "source",
                "order_remark",
                "strategy_name",
                "m_strRemark",
                "m_strOrderRemark",
                "m_strStrategyName",
            )
        ]
        text = " ".join(str(value or "") for value in values).strip().lower()
        return "cfquant" if "cfquant" in text else "other"

    def _get_value(self, obj, name):
        if obj is None:
            return None
        try:
            return self._plain_value(getattr(obj, name))
        except AttributeError:
            pass
        except Exception as e:
            self._log(
                "trade detail getattr failed type=%s field=%s error=%s"
                % (type(obj).__name__, name, e)
            )
        try:
            getter = getattr(obj, "get", None)
            if callable(getter):
                return self._plain_value(getter(name))
        except AttributeError:
            pass
        except Exception as e:
            self._log(
                "trade detail get failed type=%s field=%s error=%s"
                % (type(obj).__name__, name, e)
            )
        return None

    def _plain_value(self, value):
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return str(value)
        try:
            item = getattr(value, "item", None)
            if callable(item):
                return item()
        except Exception:
            pass
        if isinstance(value, (list, tuple)):
            return [self._plain_value(item) for item in value]
        if isinstance(value, dict):
            return dict((str(k), self._plain_value(v)) for k, v in value.items())
        return str(value)

    def _first_param(self, params, names, default=None):
        for name in names:
            value = params.get(name)
            if value is not None and value != "":
                return value
        return default

    def _list_param(self, value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value]

    def _account_type_name(self, account_type):
        mapping = {
            1: "future",
            2: "stock",
            3: "credit",
            5: "future_option",
            6: "stock_option",
            7: "hugangtong",
            10: "new3board",
            11: "shengangtong",
        }
        if isinstance(account_type, str):
            return account_type
        return mapping.get(account_type, "stock")

    def _set_context_account(self, account_id, account_type=None):
        if self.context is None or not account_id:
            return
        try:
            if account_type not in (None, ""):
                self.context.set_account(str(account_id).strip(), str(account_type).upper())
            else:
                self.context.set_account(str(account_id).strip())
        except Exception:
            self.context.set_account(str(account_id).strip())

    def _enable_auto_trade_callback(self):
        if self.context is None or self.auto_trade_callback_enabled:
            return
        func = getattr(self.context, "set_auto_trade_callback", None)
        if callable(func):
            try:
                result = func(True)
                self.auto_trade_callback_enabled = True
                self._log("auto trade callback enabled result=%s" % result)
                return
            except Exception as e:
                self._log("auto trade callback enable failed:%s" % e)
                return
        func = self._get_callable("set_auto_trade_callback")
        if not callable(func):
            self._log("auto trade callback enable skipped: set_auto_trade_callback not found")
            return
        try:
            result = func(self.context, True)
            self.auto_trade_callback_enabled = True
            self._log("auto trade callback enabled result=%s" % result)
        except TypeError:
            try:
                result = func(True)
                self.auto_trade_callback_enabled = True
                self._log("auto trade callback enabled result=%s" % result)
            except Exception as e:
                self._log("auto trade callback enable failed:%s" % e)
        except Exception as e:
            self._log("auto trade callback enable failed:%s" % e)
    def _send_trader_event(self, client_id, name, data):
        if client_id:
            self._send_event(client_id, "trader:%s" % name, data)

    def _client_ids_for_account(self, account_id, account_type=None):
        account_id = str(account_id or "").strip()
        if not account_id:
            return []
        account_type = self._account_type_name(account_type).upper() if account_type not in (None, "") else ""
        with self.subscriber_lock:
            if account_type:
                client_ids = set(self.account_subscribers.get((account_type, account_id), set()))
            else:
                client_ids = set()
                for key, ids in self.account_subscribers.items():
                    if isinstance(key, tuple) and len(key) == 2 and key[1] == account_id:
                        client_ids.update(ids)
                    elif key == account_id:
                        client_ids.update(ids)
        if account_type:
            client_ids.update(account_route_client_ids(self.bridge_id, account_id, account_type=account_type))
        return sorted(client_ids)

    def _send_trader_event_to_account(self, account_id, name, data, account_type=None):
        if account_type and isinstance(data, dict):
            data.setdefault("account_type", self._account_type_name(account_type).upper())
        for client_id in self._client_ids_for_account(account_id, account_type=account_type):
            self._send_trader_event(client_id, name, data)

    def _account_subscriber_status(self):
        with self.subscriber_lock:
            status = {}
            for key, client_ids in self.account_subscribers.items():
                if isinstance(key, tuple) and len(key) == 2:
                    label = "%s:%s" % (key[0], key[1])
                else:
                    label = "STOCK:%s" % key
                status[label] = len(client_ids)
        for account_id, count in account_route_status(self.bridge_id).items():
            status[account_id] = max(status.get(account_id, 0), count)
        return status

    def _send_event(self, client_id, name, data, subscription_id=None, meta=None):
        if not client_id or self.tx is None:
            return
        event = pack_event(name, data=data, client_id=client_id, subscription_id=subscription_id, meta=meta)
        self.tx.push("event", event, client_id)

    def _call_variants(self, func, variants):
        last_error = None
        for args, kwargs in variants:
            try:
                return func(*args, **kwargs)
            except TypeError as e:
                last_error = e
                continue
        if last_error:
            raise last_error
        return func()

    def _get_callable(self, *names):
        owners = [self.globals_dict]
        if self.context is not None:
            owners.append(self.context)
            inner_context = getattr(self.context, "context", None)
            if inner_context is not None and inner_context is not self.context:
                owners.append(inner_context)
        for owner in owners:
            for name in names:
                if isinstance(owner, dict):
                    func = owner.get(name)
                else:
                    func = getattr(owner, name, None)
                if callable(func):
                    return func
        return None

    def _load_txl(self):
        raise RuntimeError("LTtx transport is disabled in CFQUANT_LITE")

    def _default_log_file(self):
        base_dir = os.getcwd()
        log_dir = (
            os.environ.get("CFQUANT_QMT_LOG_DIR")
            or os.environ.get("CFQUANT_LOG_DIR")
            or os.path.join(base_dir, "log")
        )
        log_dir = os.path.abspath(log_dir)
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            log_dir = base_dir
        return os.path.join(log_dir, "cfquant_qmt_bridge.log")

    def _log(self, msg, force=False):
        if not force and not get_log_enabled():
            return
        msg = translate_log(msg)
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if self.show:
            print(msg)


def start_tx_trade_bridge(
    context,
    ip="127.0.0.1",
    port=2049,
    token="LTtx",
    request_channel="cfquant.request",
    bridge_id="default",
    account_id="",
    show=True,
):
    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return TxTradeBridge(
        context,
        ip=ip,
        port=port,
        token=token,
        request_channel=request_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
    )

COALESCED_QUERY_ACTIONS = set([
    "xttrader.query_stock_asset",
    "xttrader.query_stock_positions",
    "xttrader.query_stock_orders",
    "xttrader.query_stock_trades",
    "xttrader.query_credit_detail",
    "xttrader.query_credit_subjects",
    "xttrader.query_credit_slo_code",
    "xttrader.query_credit_assure",
    "xttrader.query_stk_compacts",
])


class NormalQmtBridge(TxTradeBridge):
    def __init__(
        self,
        context,
        ip="127.0.0.1",
        port=2049,
        token="LTtx",
        request_channel="cfquant.request",
        callback_event_channel="cfquant.callback.event",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
        schedule_timer=True,
        pump_max_count=20,
        pump_max_ms=0,
    ):
        super(NormalQmtBridge, self).__init__(
            context,
            ip=ip,
            port=port,
            token=token,
            request_channel=request_channel,
            bridge_id=bridge_id,
            account_id=account_id,
            show=show,
            globals_dict=globals_dict,
        )
        self.request_queue = queue.Queue(maxsize=10000)
        self.recv_thread = None
        self.worker_thread = None
        self.worker_event = threading.Event()
        self.worker_source = ""
        self.worker_source_lock = threading.Lock()
        self.pump_max_count = int(pump_max_count)
        self.pump_max_ms = float(pump_max_ms)
        self.coalesce_lock = threading.RLock()
        self.coalesced_requests = {}
        self.coalesce_join_count = 0
        self.coalesce_dispatch_count = 0
        self.subscription_seq = 0
        self.quote_subscriptions = {}
        self.whole_quote_publish_sub_id = None
        self.whole_quote_publish_enabled = False
        self.whole_quote_sub_id = None
        self.schedule_key = None
        self.callback_event_channel = callback_event_channel
        self.bridge_id = bridge_id or "default"
        self.schedule_timer = bool(schedule_timer)

    def start(self):
        if self.running:
            return self
        self.running = True
        txl = self._load_txl()
        self.tx = txl(self.ip, self.port, self.token)
        self.tx.start_tx()
        self.tx.start_txg(self.request_channel)
        self.recv_thread = threading.Thread(target=self._recv_loop)
        self.recv_thread.daemon = True
        self.recv_thread.start()
        self._log(
            "normal bridge started LTtx=%s:%s request_channel=%s"
            % (self.ip, self.port, self.request_channel)
        )
        self._publish_runtime_report("start")
        return self

    def set_context(self, context):
        self.context = context
        self._subscribe_internal_whole_quote()
        self._start_worker_thread(context)
        if self.schedule_timer:
            self._schedule_timer()
        self._log("normal bridge worker is released by quote/timer/handlebar callbacks")
        self._log("normal bridge context ready")
        self._publish_runtime_report("context_ready")

    def close(self):
        self.running = False
        self.worker_event.set()
        if self.context is not None and self.schedule_key:
            try:
                self.context.cancel_schedule_run(self.schedule_key)
            except Exception:
                pass
        super(NormalQmtBridge, self).close()

    def _recv_loop(self):
        while self.running:
            try:
                raw = self.tx.Q.get()
                if raw is None:
                    break
                self._handle_raw_from_thread(raw)
            except Exception as e:
                if self.running:
                    self._log("normal bridge recv error: %s" % e)
                time.sleep(0.05)

    def _handle_raw_from_thread(self, raw):
        msg = loads_message(raw)
        if not msg or msg.get("type") != "request":
            return
        action = msg.get("action")
        if action == "cfquant.ping":
            self._send_response(msg, {"pong": True, "ts": time.time(), "request_channel": self.request_channel})
            return
        if action == "cfquant.status":
            self._send_response(msg, self._status())
            return
        if action == "xtdata.subscribe_whole_quote":
            self._handle_whole_quote_publish_subscribe(msg)
            return
        if action == "xtdata.subscribe_quote":
            self._handle_quote_subscribe(msg, kind="quote")
            return
        if action == "xtdata.unsubscribe_quote":
            self._handle_quote_unsubscribe(msg)
            return
        if self._try_enqueue_coalesced_request(msg):
            return
        try:
            self.request_queue.put_nowait((msg, time.time(), None))
            self._release_worker("enqueue")
            self._log(
                "normal bridge request queued action=%s id=%s queue_size=%s"
                % (msg.get("action"), msg.get("id"), self.request_queue.qsize())
            )
        except queue.Full as e:
            self._send_error(msg, e)

    def _publish_runtime_report(self, reason):
        super(NormalQmtBridge, self)._publish_runtime_report(reason)
        if self.tx is None or not self.callback_event_channel:
            return
        try:
            data = self._runtime_info()
            data.update({
                "reason": reason,
                "transport": data.get("transport") or ("lite" if not self.port else "lttx"),
                "transport_mode": data.get("transport_mode") or ("lite" if not self.port else "lttx"),
                "runtime_mode": data.get("runtime_mode") or ("lite_extreme_pipe" if not self.port else "lttx"),
                "channel_key": "normal",
                "callback_event_channel": self.callback_event_channel,
            })
            payload = pack_event(
                "cfquant.runtime",
                data=data,
                client_id=self.callback_event_channel,
                meta={
                    "bridge_id": self.bridge_id,
                    "account_id": self.account_id,
                    "source": "qmt_runtime_report",
                },
            )
            result = self.tx.push("event", payload, self.callback_event_channel)
            if isinstance(result, dict):
                try:
                    code = int(result.get("code", 0) or 0)
                except Exception:
                    code = 0
                if code != 0:
                    raise RuntimeError(result.get("msg") or result)
            record_success = globals().get("_record_lite_runtime_report_success")
            if callable(record_success):
                record_success(reason)
            self._log("normal bridge runtime report sent version=%s reason=%s" % (data.get("core_version") or "-", reason))
        except Exception as e:
            record_error = globals().get("_record_lite_runtime_report_error")
            if callable(record_error):
                record_error(reason, e)
            self._log("normal bridge runtime report failed:%s" % e)

    def _start_worker_thread(self, context):
        if self.worker_thread is not None and self.worker_thread.is_alive():
            return
        self.context = context
        self.worker_thread = threading.Thread(target=self._worker_loop, args=(context,))
        self.worker_thread.daemon = True
        self.worker_thread.start()
        self._log("normal bridge worker thread started in init context")

    def _handle_quote_subscribe(self, msg, kind):
        self.subscription_seq += 1
        sub_id = self.subscription_seq
        params = msg.get("params") or {}
        self.quote_subscriptions[sub_id] = {
            "kind": kind,
            "client_id": msg.get("client_id"),
            "stock_code": params.get("stock_code", ""),
            "code_list": params.get("code_list", params.get("stock_list", [])),
        }
        self._send_response(msg, {"subscribe_id": sub_id})
        self._log("normal bridge quote subscribed id=%s kind=%s" % (sub_id, kind))

    def _handle_whole_quote_publish_subscribe(self, msg):
        if self.whole_quote_publish_sub_id is None:
            self.subscription_seq += 1
            self.whole_quote_publish_sub_id = self.subscription_seq
        sub_id = self.whole_quote_publish_sub_id
        params = msg.get("params") or {}
        self.quote_subscriptions[sub_id] = {
            "kind": "whole_quote",
            "client_id": msg.get("client_id"),
            "code_list": params.get("code_list", params.get("stock_list", ["SH", "SZ"])),
            "internal_subscribe_id": self.whole_quote_sub_id,
            "publish_existing": True,
        }
        self.whole_quote_publish_enabled = True
        self._send_response(msg, {
            "subscribe_id": sub_id,
            "internal_subscribe_id": self.whole_quote_sub_id,
            "publish_existing": True,
        })
        self._log(
            "normal bridge whole quote publish enabled id=%s internal_id=%s"
            % (sub_id, self.whole_quote_sub_id)
        )

    def _handle_quote_unsubscribe(self, msg):
        params = msg.get("params") or {}
        sub_id = params.get("subscribe_id")
        removed = self.quote_subscriptions.pop(sub_id, None)
        if removed is None:
            try:
                removed = self.quote_subscriptions.pop(int(sub_id), None)
            except Exception:
                removed = None
        if str(sub_id) == str(self.whole_quote_publish_sub_id):
            self.whole_quote_publish_enabled = False
        self._send_response(msg, True)
        self._log("normal bridge quote unsubscribed id=%s" % sub_id)

    def _try_enqueue_coalesced_request(self, msg):
        coalesce_key = self._coalesce_key(msg)
        if not coalesce_key:
            return False
        received_at = time.time()
        action = msg.get("action")
        with self.coalesce_lock:
            current = self.coalesced_requests.get(coalesce_key)
            if current is not None:
                current["waiters"].append((msg, received_at))
                self.coalesce_join_count += 1
                self._log(
                    "normal bridge request coalesced action=%s id=%s waiters=%s"
                    % (action, msg.get("id"), len(current["waiters"]))
                )
                return True
            entry = {
                "key": coalesce_key,
                "action": action,
                "primary_id": msg.get("id"),
                "waiters": [(msg, received_at)],
            }
            self.coalesced_requests[coalesce_key] = entry
        try:
            self.request_queue.put_nowait((msg, received_at, coalesce_key))
            self._release_worker("enqueue")
            self._log(
                "normal bridge request queued action=%s id=%s queue_size=%s coalesced=1"
                % (action, msg.get("id"), self.request_queue.qsize())
            )
            return True
        except queue.Full as e:
            with self.coalesce_lock:
                if self.coalesced_requests.get(coalesce_key) is entry:
                    self.coalesced_requests.pop(coalesce_key, None)
            self._send_error(msg, e)
            return True

    def _coalesce_key(self, msg):
        action = msg.get("action")
        if action not in COALESCED_QUERY_ACTIONS:
            return None
        params = msg.get("params") or {}
        try:
            params_key = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            params_key = repr(params)
        return "%s|%s" % (action, params_key)

    def pump(self):
        self._release_worker("pump")
        return self.request_queue.qsize()

    def on_timer(self, *args, **kwargs):
        self._release_worker("timer")

    def _release_worker(self, source):
        with self.worker_source_lock:
            self.worker_source = source
        self.worker_event.set()

    def _worker_loop(self, context=None):
        if context is not None:
            self.context = context
        while self.running:
            self.worker_event.wait(0.5)
            if not self.running:
                break
            if not self.worker_event.is_set():
                continue
            self.worker_event.clear()
            with self.worker_source_lock:
                source = self.worker_source or "unknown"
            try:
                self._drain_requests(source)
            except Exception as e:
                self._log("normal bridge worker error source=%s error=%s" % (source, e))

    def _drain_requests(self, source):
        start = time.perf_counter()
        count = 0
        while self.running and count < self.pump_max_count:
            if self.pump_max_ms > 0 and (time.perf_counter() - start) * 1000 >= self.pump_max_ms:
                break
            try:
                item = self.request_queue.get_nowait()
            except queue.Empty:
                break
            msg, received_at, coalesce_key = self._queue_item_parts(item)
            if coalesce_key:
                self._drain_coalesced_request(source, msg, received_at, coalesce_key)
            else:
                self._drain_single_request(source, msg, received_at)
            count += 1
        return count

    def _queue_item_parts(self, item):
        try:
            if len(item) == 3:
                return item
        except Exception:
            pass
        msg, received_at = item
        return msg, received_at, None

    def _drain_single_request(self, source, msg, received_at):
        try:
            result = self._dispatch(msg.get("action"), msg.get("params") or {}, msg)
            self._send_response(msg, result)
            self._log(
                "normal bridge worker response source=%s action=%s id=%s total_ms=%.2f"
                % (source, msg.get("action"), msg.get("id"), (time.time() - received_at) * 1000)
            )
        except Exception as e:
            self._log(
                "normal bridge worker request_error source=%s action=%s id=%s error=%s"
                % (source, msg.get("action"), msg.get("id"), e)
            )
            self._send_error(msg, e)

    def _drain_coalesced_request(self, source, msg, received_at, coalesce_key):
        try:
            result = self._dispatch(msg.get("action"), msg.get("params") or {}, msg)
            with self.coalesce_lock:
                entry = self.coalesced_requests.pop(coalesce_key, None)
                self.coalesce_dispatch_count += 1
            waiters = entry.get("waiters", []) if entry else [(msg, received_at)]
            for waiter_msg, _ in waiters:
                self._send_response(waiter_msg, result)
            self._log(
                "normal bridge worker coalesced_response source=%s action=%s id=%s waiters=%s total_ms=%.2f"
                % (source, msg.get("action"), msg.get("id"), len(waiters), (time.time() - received_at) * 1000)
            )
        except Exception as e:
            with self.coalesce_lock:
                entry = self.coalesced_requests.pop(coalesce_key, None)
                self.coalesce_dispatch_count += 1
            waiters = entry.get("waiters", []) if entry else [(msg, received_at)]
            self._log(
                "normal bridge worker coalesced_error source=%s action=%s id=%s waiters=%s error=%s"
                % (source, msg.get("action"), msg.get("id"), len(waiters), e)
            )
            for waiter_msg, _ in waiters:
                self._send_error(waiter_msg, e)

    def _on_whole_quote(self, data):
        self._release_worker("whole_quote")
        if not self.quote_subscriptions:
            return
        for sub_id, sub in list(self.quote_subscriptions.items()):
            if sub.get("kind") == "whole_quote" and not self.whole_quote_publish_enabled:
                continue
            client_id = sub.get("client_id")
            if not client_id:
                continue
            event_data = data
            if sub.get("kind") == "quote":
                stock_code = sub.get("stock_code")
                if stock_code and isinstance(data, dict):
                    value = data.get(stock_code)
                    if value is None:
                        continue
                    event_data = {stock_code: value}
            event = pack_event(
                "quote:%s" % sub_id,
                data=event_data,
                client_id=client_id,
                subscription_id=sub_id,
            )
            self.tx.push("event", event, client_id)

    def _on_timer(self, *args, **kwargs):
        self.on_timer(*args, **kwargs)

    def _subscribe_internal_whole_quote(self):
        if self.context is None or self.whole_quote_sub_id:
            return
        try:
            self.whole_quote_sub_id = self.context.subscribe_whole_quote(["SH", "SZ"], callback=self._on_whole_quote)
            self._log("normal bridge internal whole quote subscribed id=%s" % self.whole_quote_sub_id)
        except Exception as e:
            self._log("normal bridge internal whole quote subscribe failed: %s" % e)

    def _schedule_timer(self):
        if self.context is None or self.schedule_key:
            return
        try:
            first_time = dt.datetime.now() + dt.timedelta(seconds=1)
            self.schedule_key = self.context.schedule_run(
                self._on_timer,
                first_time,
                repeat_times=-1,
                interval=dt.timedelta(milliseconds=500),
                name="cfquant_normal_bridge_pump",
            )
            self._log("normal bridge timer scheduled key=%s" % self.schedule_key)
        except Exception as e:
            self._log("normal bridge timer schedule failed: %s" % e)

    def _send_response(self, msg, result):
        client_id = msg.get("client_id") or msg.get("reply_channel")
        if not client_id:
            return
        response = pack_response(msg.get("id"), ok=True, result=result)
        self.tx.push("response", response, client_id)

    def _send_error(self, msg, error):
        client_id = msg.get("client_id") or msg.get("reply_channel")
        if not client_id:
            return
        self._log(
            "normal bridge send_error action=%s id=%s client_id=%s error=%s"
            % (msg.get("action"), msg.get("id"), client_id, error)
        )
        response = pack_response(msg.get("id"), ok=False, error=error)
        self.tx.push("response", response, client_id)

    def publish_callback_event(self, event_name, obj):
        if self.tx is None:
            return
        data = self._callback_object_to_dict(obj)
        account_id = self._callback_account_id(obj, data)
        account_type = self._callback_account_type(obj, data)
        payload = {
            "type": "event",
            "event": event_name,
            "account_id": account_id,
            "account_type": account_type,
            "bridge_id": self.bridge_id,
            "source": "CFQUANT",
            "ts": int(time.time() * 1000),
            "data": data,
        }
        self.tx.push("event", json.dumps(payload, ensure_ascii=False), self.callback_event_channel)
        if account_id:
            self._send_trader_event_to_account(account_id, event_name.replace("trader:", "", 1), data, account_type=account_type or None)
        self._log("normal bridge callback event sent event=%s account=%s" % (event_name, account_id or "-"))

    def _callback_object_to_dict(self, obj):
        fields = [
            "account_id",
            "account_type",
            "m_strAccountID",
            "m_strAccountId",
            "m_strAccount",
            "m_accountID",
            "m_nAccountType",
            "m_strAccountType",
            "order_source",
            "source",
            "order_remark",
            "strategy_name",
            "m_strStatus",
            "m_strInstrumentID",
            "m_strExchangeID",
            "m_strInstrumentName",
            "m_nOffsetFlag",
            "m_nVolumeTotalOriginal",
            "m_nVolumeTraded",
            "m_nVolume",
            "m_nCanUseVolume",
            "m_dPrice",
            "m_dTradedPrice",
            "m_dTradeAmount",
            "m_dBalance",
            "m_dAssureAsset",
            "m_dInstrumentValue",
            "m_dTotalDebit",
            "m_dAvailable",
            "m_dPositionProfit",
            "m_dOpenPrice",
            "m_dPositionCost",
            "m_strRemark",
            "m_strOrderRemark",
            "m_strStrategyName",
            "m_strOrderSysID",
            "m_strOrderID",
            "m_nOrderID",
            "m_nOrderStatus",
            "m_strOrderStatus",
            "m_nOrderState",
            "m_strStatusMsg",
            "m_strOrderTime",
            "m_strEntrustTime",
            "m_strInsertTime",
            "m_nOrderTime",
            "m_nEntrustTime",
            "m_nInsertTime",
            "m_strOrderDate",
            "m_strEntrustDate",
            "m_strTradingDay",
        ]
        data = {}
        for field in fields:
            value = self._get_value(obj, field)
            if value is not None:
                data[field] = value
        code = data.get("m_strInstrumentID")
        market = data.get("m_strExchangeID")
        if code and market:
            data["stock_code"] = "%s.%s" % (code, market)
        source_text = " ".join(str(item or "") for item in (
            data.get("order_source"),
            data.get("source"),
            data.get("order_remark"),
            data.get("strategy_name"),
            data.get("m_strRemark"),
            data.get("m_strOrderRemark"),
            data.get("m_strStrategyName"),
        )).strip().lower()
        data["order_source"] = "cfquant" if "cfquant" in source_text else "other"
        return data

    def _callback_account_id(self, obj, data):
        for key in ("account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID"):
            value = data.get(key)
            if value:
                return str(value).strip()
        for name in ("account_id", "m_strAccountID", "m_strAccountId", "m_strAccount", "m_accountID"):
            value = self._get_value(obj, name)
            if value:
                return str(value).strip()
        return str(self.account_id or "").strip()

    def _callback_account_type(self, obj, data):
        candidates = [
            data.get("account_type") if isinstance(data, dict) else None,
            data.get("m_nAccountType") if isinstance(data, dict) else None,
            data.get("m_strAccountType") if isinstance(data, dict) else None,
            self._get_value(obj, "account_type"),
            self._get_value(obj, "m_nAccountType"),
            self._get_value(obj, "m_strAccountType"),
        ]
        for value in candidates:
            if value in (None, ""):
                continue
            text = str(value).strip().upper()
            if text in ("2", "SECURITY", "SECURITY_ACCOUNT", "STOCK_ACCOUNT"):
                return "STOCK"
            if text in ("3", "CREDIT_ACCOUNT", "MARGIN"):
                return "CREDIT"
            return text
        return ""

    def _status_extra(self):
        with self.coalesce_lock:
            coalesced_waiters = sum(len(item.get("waiters", [])) for item in self.coalesced_requests.values())
            coalesced_group_count = len(self.coalesced_requests)
        return {
            "request_queue_size": self.request_queue.qsize(),
            "recv_thread_alive": self.recv_thread.is_alive() if self.recv_thread else False,
            "worker_thread_alive": self.worker_thread.is_alive() if self.worker_thread else False,
            "whole_quote_sub_id": self.whole_quote_sub_id,
            "schedule_key": self.schedule_key,
            "quote_subscription_count": len(self.quote_subscriptions),
            "whole_quote_publish_enabled": self.whole_quote_publish_enabled,
            "whole_quote_publish_sub_id": self.whole_quote_publish_sub_id,
            "schedule_timer": self.schedule_timer,
            "pump_max_count": self.pump_max_count,
            "pump_max_ms": self.pump_max_ms,
            "coalesced_group_count": coalesced_group_count,
            "coalesced_waiter_count": coalesced_waiters,
            "coalesce_join_count": self.coalesce_join_count,
            "coalesce_dispatch_count": self.coalesce_dispatch_count,
        }


def start_normal_bridge(
    context,
    ip="127.0.0.1",
    port=2049,
    token="LTtx",
    request_channel="cfquant.request",
    callback_event_channel="cfquant.callback.event",
    bridge_id="default",
    account_id="",
    show=True,
    schedule_timer=True,
    pump_max_count=20,
    pump_max_ms=0,
):
    import sys

    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return NormalQmtBridge(
        context,
        ip=ip,
        port=port,
        token=token,
        request_channel=request_channel,
        callback_event_channel=callback_event_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
        schedule_timer=schedule_timer,
        pump_max_count=pump_max_count,
        pump_max_ms=pump_max_ms,
    ).start()

DEFAULT_PIPE_NAME = os.environ.get("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub")
PIPE_MESSAGE_PREFIX = "cfpipe:"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
NMPWAIT_WAIT_FOREVER = 0xFFFFFFFF

ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_BUSY = 231
ERROR_NO_DATA = 232
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_PIPE_CONNECTED = 535

DEFAULT_BUFFER_SIZE = 65536
DEFAULT_MAX_FRAME_SIZE = 64 * 1024 * 1024


def is_windows():
    return os.name == "nt"


def normalize_pipe_name(pipe_name=None):
    pipe_name = str(pipe_name or DEFAULT_PIPE_NAME)
    if pipe_name.startswith("\\\\.\\pipe\\"):
        return pipe_name
    name = pipe_name.strip("\\/")
    return r"\\.\pipe\%s" % name


def dumps_pipe_message(payload):
    data = dict(payload)
    data.setdefault("protocol", "cfquant_pipe")
    data.setdefault("ts", int(time.time() * 1000))
    return PIPE_MESSAGE_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def loads_pipe_message(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str) or not raw.startswith(PIPE_MESSAGE_PREFIX):
        return None
    try:
        data = json.loads(raw[len(PIPE_MESSAGE_PREFIX):])
    except Exception:
        return None
    if data.get("protocol") != "cfquant_pipe":
        return None
    return data


class _Kernel32(object):
    def __init__(self):
        if not is_windows():
            raise OSError("named pipe transport requires Windows")
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self.INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        self.dll.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.dll.CreateFileW.restype = wintypes.HANDLE

        self.dll.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        self.dll.CreateNamedPipeW.restype = wintypes.HANDLE

        self.dll.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self.dll.ConnectNamedPipe.restype = wintypes.BOOL

        self.dll.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        self.dll.DisconnectNamedPipe.restype = wintypes.BOOL

        self.dll.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self.dll.ReadFile.restype = wintypes.BOOL

        self.dll.WriteFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self.dll.WriteFile.restype = wintypes.BOOL

        self.dll.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self.dll.FlushFileBuffers.restype = wintypes.BOOL

        self.dll.CloseHandle.argtypes = [wintypes.HANDLE]
        self.dll.CloseHandle.restype = wintypes.BOOL

        self.dll.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self.dll.WaitNamedPipeW.restype = wintypes.BOOL

        self.cancel_io_ex = getattr(self.dll, "CancelIoEx", None)
        if self.cancel_io_ex is not None:
            self.cancel_io_ex.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
            self.cancel_io_ex.restype = wintypes.BOOL

    def last_error(self):
        return ctypes.get_last_error()

    def raise_last_error(self, message):
        error = self.last_error()
        raise OSError(error, "%s failed with winerror=%s" % (message, error))

    def invalid_handle(self, handle):
        return handle in (None, 0, self.INVALID_HANDLE_VALUE)


_kernel32 = None
_kernel32_lock = threading.Lock()


def kernel32():
    global _kernel32
    with _kernel32_lock:
        if _kernel32 is None:
            _kernel32 = _Kernel32()
        return _kernel32


class NamedPipeConnection(object):
    def __init__(self, handle, name="", owner_server_side=False, max_frame_size=DEFAULT_MAX_FRAME_SIZE):
        self.handle = handle
        self.name = name
        self.owner_server_side = bool(owner_server_side)
        self.max_frame_size = int(max_frame_size)
        self.write_lock = threading.RLock()
        self.closed = False

    def read_frame(self):
        header = self._read_exact(8)
        if header is None:
            return None
        size = struct.unpack("!Q", header)[0]
        if size > self.max_frame_size:
            raise ValueError("named pipe frame too large: %s > %s" % (size, self.max_frame_size))
        if size == 0:
            return ""
        data = self._read_exact(size)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    def write_frame(self, payload):
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = bytes(payload)
        frame = struct.pack("!Q", len(data)) + data
        self._write_all(frame)

    def close(self):
        if self.closed:
            return
        self.closed = True
        k32 = kernel32()
        try:
            if k32.cancel_io_ex is not None:
                try:
                    k32.cancel_io_ex(self.handle, None)
                except Exception:
                    pass
            if self.owner_server_side:
                try:
                    k32.dll.DisconnectNamedPipe(self.handle)
                except Exception:
                    pass
        finally:
            try:
                k32.dll.CloseHandle(self.handle)
            except Exception:
                pass

    def _read_exact(self, size):
        chunks = []
        remaining = int(size)
        k32 = kernel32()
        while remaining > 0:
            chunk_size = min(remaining, DEFAULT_BUFFER_SIZE)
            buf = ctypes.create_string_buffer(chunk_size)
            read = wintypes.DWORD(0)
            ok = k32.dll.ReadFile(self.handle, buf, chunk_size, ctypes.byref(read), None)
            if not ok:
                error = k32.last_error()
                if error in (ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_PIPE_NOT_CONNECTED):
                    return None
                raise OSError(error, "ReadFile failed with winerror=%s" % error)
            if read.value == 0:
                return None
            chunks.append(buf.raw[:read.value])
            remaining -= read.value
        return b"".join(chunks)

    def _write_all(self, data):
        offset = 0
        total = len(data)
        k32 = kernel32()
        with self.write_lock:
            while offset < total:
                chunk = data[offset:offset + DEFAULT_BUFFER_SIZE]
                buf = ctypes.create_string_buffer(chunk)
                written = wintypes.DWORD(0)
                ok = k32.dll.WriteFile(self.handle, buf, len(chunk), ctypes.byref(written), None)
                if not ok:
                    error = k32.last_error()
                    raise OSError(error, "WriteFile failed with winerror=%s" % error)
                if written.value <= 0:
                    raise OSError("WriteFile wrote zero bytes")
                offset += written.value


def connect_pipe(pipe_name=None, timeout_ms=3000):
    pipe_name = normalize_pipe_name(pipe_name)
    k32 = kernel32()
    deadline = time.time() + max(float(timeout_ms), 1.0) / 1000.0
    last_error = None
    while True:
        handle = k32.dll.CreateFileW(
            pipe_name,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not k32.invalid_handle(handle):
            return NamedPipeConnection(handle, pipe_name, owner_server_side=False)
        last_error = k32.last_error()
        if last_error == ERROR_PIPE_BUSY:
            wait_ms = min(250, max(1, int((deadline - time.time()) * 1000)))
            k32.dll.WaitNamedPipeW(pipe_name, wait_ms)
        elif last_error in (ERROR_FILE_NOT_FOUND, ERROR_ACCESS_DENIED):
            time.sleep(0.05)
        else:
            time.sleep(0.05)
        if time.time() >= deadline:
            raise OSError(last_error or 0, "connect named pipe timeout pipe=%s winerror=%s" % (pipe_name, last_error))


def create_pipe_instance(pipe_name=None, in_buffer_size=DEFAULT_BUFFER_SIZE, out_buffer_size=DEFAULT_BUFFER_SIZE):
    pipe_name = normalize_pipe_name(pipe_name)
    k32 = kernel32()
    handle = k32.dll.CreateNamedPipeW(
        pipe_name,
        PIPE_ACCESS_DUPLEX,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
        PIPE_UNLIMITED_INSTANCES,
        int(out_buffer_size),
        int(in_buffer_size),
        0,
        None,
    )
    if k32.invalid_handle(handle):
        k32.raise_last_error("CreateNamedPipeW")
    return NamedPipeConnection(handle, pipe_name, owner_server_side=True)


def wait_for_pipe_client(connection):
    k32 = kernel32()
    ok = k32.dll.ConnectNamedPipe(connection.handle, None)
    if ok:
        return True
    error = k32.last_error()
    if error == ERROR_PIPE_CONNECTED:
        return True
    raise OSError(error, "ConnectNamedPipe failed with winerror=%s" % error)


class PipeTxClient(object):
    """
    QMT-side tx-like adapter over a named pipe hub.

    It intentionally exposes start_tx/start_txg/push/close so bridge classes can
    reuse the existing LTtx-oriented dispatch code without changing behavior.
    """

    def __init__(
        self,
        pipe_name=None,
        request_channel="cfquant.request",
        request_channels=None,
        bridge_id="default",
        endpoint_name="qmt",
        show=True,
        connect_timeout_ms=3000,
        reconnect_interval=1.0,
    ):
        self.pipe_name = normalize_pipe_name(pipe_name)
        self.request_channel = request_channel
        self.request_channels = self._normalize_channels(request_channels or [request_channel])
        self.bridge_id = bridge_id or "default"
        self.endpoint_name = endpoint_name or "qmt"
        self.show = show
        self.connect_timeout_ms = int(connect_timeout_ms)
        self.reconnect_interval = float(reconnect_interval)
        self.Q = queue.Queue(maxsize=10000)
        self.running = False
        self.rx_conn = None
        self.tx_conn = None
        self.conn_lock = threading.RLock()
        self.thread = None

    def start(self):
        if self.running:
            return self
        self.running = True
        self.thread = threading.Thread(target=self._connect_loop)
        self.thread.daemon = True
        self.thread.start()
        return self

    def start_tx(self):
        return self.start()

    def start_txg(self, request_channel=None):
        if request_channel:
            self.request_channel = request_channel
        return {"code": 0, "msg": "pipe request channel registered"}

    def push(self, key, payload, channel):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        envelope = dumps_pipe_message({
            "type": "publish",
            "role": "qmt_tx",
            "bridge_id": self.bridge_id,
            "request_channel": self.request_channel,
            "request_channels": self.request_channels,
            "endpoint_name": self.endpoint_name,
            "key": key,
            "channel": channel,
            "payload": payload,
        })
        conn = self._get_tx_conn()
        if conn is None:
            return {"code": -1, "msg": "pipe not connected"}
        try:
            conn.write_frame(envelope)
            return {"code": 0, "msg": "ok"}
        except Exception as e:
            self._log("pipe push failed: %s" % e)
            self._drop_conn(conn)
            return {"code": -1, "msg": str(e)}

    def close(self):
        self.running = False
        try:
            self.Q.put_nowait(None)
        except Exception:
            pass
        self._drop_conns(self._get_conns())

    def _connect_loop(self):
        while self.running:
            rx_conn = None
            tx_conn = None
            try:
                rx_conn = connect_pipe(self.pipe_name, timeout_ms=self.connect_timeout_ms)
                rx_conn.write_frame(dumps_pipe_message({
                    "type": "hello",
                    "role": "qmt_rx",
                    "bridge_id": self.bridge_id,
                    "request_channel": self.request_channel,
                    "request_channels": self.request_channels,
                    "endpoint_name": self.endpoint_name,
                }))
                tx_conn = connect_pipe(self.pipe_name, timeout_ms=self.connect_timeout_ms)
                tx_conn.write_frame(dumps_pipe_message({
                    "type": "hello",
                    "role": "qmt_tx",
                    "bridge_id": self.bridge_id,
                    "request_channel": self.request_channel,
                    "request_channels": self.request_channels,
                    "endpoint_name": self.endpoint_name,
                }))
                with self.conn_lock:
                    self.rx_conn = rx_conn
                    self.tx_conn = tx_conn
                self._log(
                    "pipe connected pipe=%s request_channel=%s bridge_id=%s"
                    % (self.pipe_name, self.request_channel, self.bridge_id)
                )
                self._read_loop(rx_conn)
            except Exception as e:
                if self.running:
                    self._log("pipe connect/read failed: %s" % e)
            finally:
                self._drop_conns((rx_conn, tx_conn))
            if self.running:
                time.sleep(self.reconnect_interval)

    def _read_loop(self, conn):
        while self.running and self._get_rx_conn() is conn:
            raw = conn.read_frame()
            if raw is None:
                break
            envelope = loads_pipe_message(raw)
            if envelope:
                payload = envelope.get("payload")
                if payload:
                    self.Q.put(payload)
                continue
            self.Q.put(raw)

    def _get_rx_conn(self):
        with self.conn_lock:
            return self.rx_conn

    def _get_tx_conn(self):
        with self.conn_lock:
            return self.tx_conn

    def _get_conn(self):
        return self._get_rx_conn()

    def _get_conns(self):
        with self.conn_lock:
            return self.rx_conn, self.tx_conn

    def _drop_conn(self, conn):
        self._drop_conns((conn,))

    def _drop_conns(self, conns):
        with self.conn_lock:
            for conn in conns:
                if conn is None:
                    continue
                if self.rx_conn is conn:
                    self.rx_conn = None
                if self.tx_conn is conn:
                    self.tx_conn = None
        for conn in conns:
            if conn is None:
                continue
            try:
                conn.close()
            except Exception:
                pass

    def _log(self, msg):
        if self.show and get_log_enabled():
            prefix = "cfquant pipe tx" if get_log_language() == "en" else "cfquant 管道客户端"
            print("%s %s" % (prefix, translate_log(msg)))

    def _normalize_channels(self, channels):
        result = []
        for channel in channels or []:
            channel = str(channel or "").strip()
            if channel and channel not in result:
                result.append(channel)
        return result or [self.request_channel]

class PipeNormalQmtBridge(NormalQmtBridge):
    def __init__(
        self,
        context,
        pipe_name=None,
        request_channel="cfquant.normal.request",
        request_channels=None,
        callback_event_channel="cfquant.callback.event",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
        schedule_timer=True,
        pump_max_count=20,
        pump_max_ms=0,
        connect_timeout_ms=3000,
    ):
        super(PipeNormalQmtBridge, self).__init__(
            context,
            ip="127.0.0.1",
            port=0,
            token="",
            request_channel=request_channel,
            callback_event_channel=callback_event_channel,
            bridge_id=bridge_id,
            account_id=account_id,
            show=show,
            globals_dict=globals_dict,
            schedule_timer=schedule_timer,
            pump_max_count=pump_max_count,
            pump_max_ms=pump_max_ms,
        )
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.request_channels = request_channels or [request_channel]
        self.connect_timeout_ms = int(connect_timeout_ms)

    def start(self):
        if self.running:
            return self
        self.running = True
        self.tx = PipeTxClient(
            pipe_name=self.pipe_name,
            request_channel=self.request_channel,
            request_channels=self.request_channels,
            bridge_id=self.bridge_id,
            endpoint_name="normal",
            show=self.show,
            connect_timeout_ms=self.connect_timeout_ms,
        ).start()
        self.tx.start_txg(self.request_channel)
        self.recv_thread = threading.Thread(target=self._recv_loop)
        self.recv_thread.daemon = True
        self.recv_thread.start()
        self._log(
            "pipe normal bridge started pipe=%s request_channel=%s"
            % (self.pipe_name, self.request_channel)
        )
        return self

    def close(self):
        self.running = False
        self.worker_event.set()
        if self.context is not None and self.schedule_key:
            try:
                self.context.cancel_schedule_run(self.schedule_key)
            except Exception:
                pass
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass
        self._log("pipe normal bridge stopped")

    def _status_extra(self):
        data = super(PipeNormalQmtBridge, self)._status_extra()
        data.update({
            "transport": "lite",
            "transport_mode": "lite",
            "pipe_transport": "pipe",
            "pipe_name": self.pipe_name,
            "pipe_request_channels": list(self.request_channels),
            "pipe_connected": self.tx is not None and self.tx._get_conn() is not None,
        })
        return data


class PipeTradeBridge(TxTradeBridge):
    def __init__(
        self,
        context,
        pipe_name=None,
        request_channel="cfquant.trade.request",
        bridge_id="default",
        account_id="",
        show=True,
        globals_dict=None,
        connect_timeout_ms=3000,
    ):
        super(PipeTradeBridge, self).__init__(
            context,
            ip="127.0.0.1",
            port=0,
            token="",
            request_channel=request_channel,
            bridge_id=bridge_id,
            account_id=account_id,
            show=show,
            globals_dict=globals_dict,
        )
        self.pipe_name = pipe_name or DEFAULT_PIPE_NAME
        self.connect_timeout_ms = int(connect_timeout_ms)

    def start(self):
        if self.running:
            return self
        self.running = True
        self.tx = PipeTxClient(
            pipe_name=self.pipe_name,
            request_channel=self.request_channel,
            bridge_id=self.bridge_id,
            endpoint_name="trade",
            show=self.show,
            connect_timeout_ms=self.connect_timeout_ms,
        ).start()
        self.tx.start_txg(self.request_channel)
        self._log(
            "pipe trade bridge started pipe=%s request_channel=%s"
            % (self.pipe_name, self.request_channel)
        )
        return self

    def close(self):
        self.running = False
        tx = self.tx
        self.tx = None
        if tx is not None:
            try:
                tx.close()
            except Exception:
                pass
        self._log("pipe trade bridge stopped")

    def poll(self, max_messages=100, timeout=0):
        self.start()
        count = 0
        while self.running and count < max_messages:
            try:
                raw = self.tx.Q.get(timeout=timeout if count == 0 else 0)
            except queue.Empty:
                break
            except Exception:
                break
            if raw is None:
                break
            self._handle_raw(raw)
            count += 1
        return count

    def _status_extra(self):
        return {
            "transport": "lite",
            "transport_mode": "lite",
            "pipe_transport": "pipe",
            "pipe_name": self.pipe_name,
            "pipe_connected": self.tx is not None and self.tx._get_conn() is not None,
        }


def start_pipe_normal_bridge(
    context,
    pipe_name=None,
        request_channel="cfquant.normal.request",
        request_channels=None,
        callback_event_channel="cfquant.callback.event",
    bridge_id="default",
    account_id="",
    show=True,
    schedule_timer=True,
    pump_max_count=20,
    pump_max_ms=0,
    connect_timeout_ms=3000,
):
    import sys

    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return PipeNormalQmtBridge(
        context,
        pipe_name=pipe_name,
        request_channel=request_channel,
        request_channels=request_channels,
        callback_event_channel=callback_event_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
        schedule_timer=schedule_timer,
        pump_max_count=pump_max_count,
        pump_max_ms=pump_max_ms,
        connect_timeout_ms=connect_timeout_ms,
    ).start()


def start_pipe_trade_bridge(
    context,
    pipe_name=None,
    request_channel="cfquant.trade.request",
    bridge_id="default",
    account_id="",
    show=True,
    connect_timeout_ms=3000,
):
    import sys

    try:
        globals_dict = sys._getframe(1).f_globals
    except Exception:
        globals_dict = {}
    return PipeTradeBridge(
        context,
        pipe_name=pipe_name,
        request_channel=request_channel,
        bridge_id=bridge_id,
        account_id=account_id,
        show=show,
        globals_dict=globals_dict,
        connect_timeout_ms=connect_timeout_ms,
    ).start()

_normal_bridge = None
_trade_bridge = None
_trade_thread = None
_trade_request_queue = queue.Queue(maxsize=10000)
_trade_timer_key = None
_trade_loop_started_at = 0
_trade_loop_error = ""
_trade_recv_count = 0
_trade_dispatch_count = 0
_trade_direct_dispatch_count = 0
_trade_reroute_count = 0
_trade_queue_full_count = 0
_trade_last_recv_at = 0
_trade_last_dispatch_at = 0
_runtime_report_sent_at = 0.0
_runtime_report_last_attempt_at = 0.0
_runtime_report_pending_log_at = 0.0
_runtime_report_count = 0
_runtime_report_last_error = ""
_runtime_report_retry_until = 0.0
DEFAULT_ACCOUNT_ID = ""
USER_BRIDGE_ID = "default"
BRIDGE_ID = os.environ.get("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID)
PIPE_NAME = os.environ.get("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub")
RUNTIME_CONFIG_PATH = ""
RUNTIME_CONFIG = {}
RUNTIME_CHANNELS = {}
PIPE_CONNECT_TIMEOUT_MS = int(os.environ.get("CFQUANT_PIPE_CONNECT_TIMEOUT_MS", "3000"))
TRADE_LOOP_IN_THREAD = os.environ.get("CFQUANT_CTYPE_TRADE_THREAD", "1").strip().lower() in ("1", "true", "yes", "on")
NORMAL_PUMP_MAX_COUNT = int(os.environ.get("CFQUANT_CTYPE_NORMAL_PUMP_MAX_COUNT", "100"))
NORMAL_PUMP_MAX_MS = float(os.environ.get("CFQUANT_CTYPE_NORMAL_PUMP_MAX_MS", "0"))
TRADE_SLEEP_SECONDS = float(os.environ.get("CFQUANT_CTYPE_TRADE_SLEEP_SECONDS", "0.001"))
TRADE_PUMP_MAX_COUNT = int(os.environ.get("CFQUANT_CTYPE_TRADE_PUMP_MAX_COUNT", "100"))
TRADE_PUMP_MAX_MS = float(os.environ.get("CFQUANT_CTYPE_TRADE_PUMP_MAX_MS", "0"))
TRADE_TIMER_INTERVAL_MS = int(os.environ.get("CFQUANT_CTYPE_TRADE_TIMER_INTERVAL_MS", "20"))


def _entry_file_path():
    path = globals().get("__file__") or ""
    path = str(path or "").strip()
    if path and not path.startswith("<"):
        try:
            return os.path.abspath(path)
        except Exception:
            return path
    return ""


def _entry_base_dir():
    entry_file = _entry_file_path()
    if entry_file:
        return os.path.dirname(entry_file)
    for name in ("CFQUANT_QMT_SCRIPT_DIR", "CFQUANT_SCRIPT_DIR", "CFQUANT_ENTRY_DIR"):
        path = str(os.environ.get(name) or "").strip()
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    try:
        cwd = os.path.abspath(os.getcwd())
        if (
            os.path.isfile(os.path.join(cwd, "CFQUANT_LITE.py"))
            or os.path.isfile(os.path.join(cwd, "cfquant_bridge_config.json"))
            or os.path.isdir(os.path.join(cwd, "cfquant"))
        ):
            return cwd
    except Exception:
        pass
    for path in sys.path:
        path = str(path or "").strip()
        if path and os.path.isdir(path):
            base = os.path.abspath(path)
            if (
                os.path.isfile(os.path.join(base, "CFQUANT_LITE.py"))
                or os.path.isfile(os.path.join(base, "cfquant_bridge_config.json"))
                or os.path.isdir(os.path.join(base, "cfquant"))
            ):
                return base
    try:
        return os.path.abspath(os.getcwd())
    except Exception:
        return ""


def _runtime_log_path():
    try:
        base_dir = _entry_base_dir()
        parent_dir = os.path.dirname(base_dir)
        configured = os.environ.get("CFQUANT_QMT_LOG_DIR") or os.environ.get("CFQUANT_LOG_DIR")
        if configured:
            candidates = [configured]
        elif os.path.basename(base_dir).lower() == "python":
            candidates = [
                os.path.join(parent_dir, "bin.x64", "log"),
                os.path.join(parent_dir, "log"),
                os.path.join(base_dir, "log"),
            ]
        else:
            candidates = [
                os.path.join(base_dir, "log"),
                os.path.join(parent_dir, "bin.x64", "log"),
                os.path.join(parent_dir, "log"),
            ]
        candidates.extend([
            os.path.join(parent_dir, "bin.x64", "tx_log"),
            os.path.join(base_dir, "tx_log"),
            os.path.join(parent_dir, "tx_log"),
            base_dir,
        ])
        for log_dir in candidates:
            if not log_dir:
                continue
            try:
                os.makedirs(log_dir, exist_ok=True)
                return os.path.join(log_dir, "cfquant_lite_bridge.log")
            except Exception:
                if os.path.isdir(log_dir):
                    return os.path.join(log_dir, "cfquant_ctype_bridge.log")
    except Exception:
        pass
    return ""


def _write_runtime_log(message):
    try:
        path = _runtime_log_path()
        if not path:
            return
        log_dir = os.path.dirname(path)
        if log_dir and not os.path.isdir(log_dir):
            os.makedirs(log_dir)
        with open(path, "a") as f:
            f.write("%s %s\n" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def _ensure_path():
    try:
        base_dir = _entry_base_dir()
        parent_dir = os.path.dirname(base_dir)
        env_paths = [p for p in os.environ.get("CFQUANT_PYTHONPATH", "").split(os.pathsep) if p]
        if os.path.basename(base_dir).lower() == "python":
            candidates = env_paths + [os.path.join(parent_dir, "bin.x64"), base_dir, parent_dir]
        else:
            candidates = env_paths + [
                base_dir,
                os.path.join(base_dir, "bin.x64"),
                parent_dir,
                os.path.join(parent_dir, "bin.x64"),
                os.path.join(parent_dir, "python"),
            ]
        ordered = []
        seen = set()
        for path in candidates:
            if not path or not os.path.isdir(path):
                continue
            path = os.path.abspath(path)
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(path)
        if ordered:
            sys.path[:] = ordered + [
                path for path in sys.path
                if os.path.normcase(os.path.abspath(path or os.curdir)) not in seen
            ]
    except Exception:
        pass


def _runtime_config_paths():
    try:
        base_dir = _entry_base_dir()
        parent_dir = os.path.dirname(base_dir)
        candidates = []
        env_path = os.environ.get("CFQUANT_BRIDGE_CONFIG_FILE")
        if env_path:
            candidates.append(env_path)
        if os.path.basename(base_dir).lower() == "python":
            candidates.append(os.path.join(parent_dir, "bin.x64", "cfquant_bridge_config.json"))
            candidates.append(os.path.join(base_dir, "cfquant_bridge_config.json"))
        else:
            candidates.append(os.path.join(base_dir, "cfquant_bridge_config.json"))
            candidates.append(os.path.join(base_dir, "bin.x64", "cfquant_bridge_config.json"))
        candidates.append(os.path.join(parent_dir, "cfquant_bridge_config.json"))
        result = []
        seen = set()
        for path in candidates:
            if not path:
                continue
            path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            result.append(path)
        return result
    except Exception:
        return []


def _load_runtime_config():
    for path in _runtime_config_paths():
        if not os.path.isfile(path):
            continue
        for index, opener in enumerate((
            lambda: io.open(path, "r", encoding="utf-8"),
            lambda: open(path, "r"),
        )):
            try:
                with opener() as f:
                    data = json.loads(f.read())
                if isinstance(data, dict):
                    return path, data
            except Exception as e:
                if index == 1:
                    _write_runtime_log("cfquant lite runtime config read failed path=%s error=%s" % (path, e))
    return "", {}


def _config_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off", "disable", "disabled", "closed", "close"):
        return False
    if text in ("1", "true", "yes", "on", "enable", "enabled", "open"):
        return True
    return default


def _env_allows_runtime_override(name, default_value=""):
    value = str(os.environ.get(name) or "").strip()
    if not value:
        return True
    if str(os.environ.get("%s_SOURCE" % name) or "").strip() == "cfquant_entry":
        return True
    return bool(default_value and value == default_value)


def _apply_runtime_config():
    global BRIDGE_ID, PIPE_NAME, RUNTIME_CONFIG_PATH, RUNTIME_CONFIG, RUNTIME_CHANNELS

    path, data = _load_runtime_config()
    RUNTIME_CONFIG_PATH = path
    RUNTIME_CONFIG = data
    if not data:
        _write_runtime_log("cfquant lite runtime config not found")
        return
    if data.get("bridge_id") and _env_allows_runtime_override("CFQUANT_BRIDGE_ID", USER_BRIDGE_ID):
        BRIDGE_ID = data.get("bridge_id")
    if data.get("pipe_name") and _env_allows_runtime_override("CFQUANT_PIPE_NAME", r"\\.\pipe\cfquant_pipe_hub"):
        PIPE_NAME = data.get("pipe_name")
    channels = data.get("channels") or {}
    if isinstance(channels, dict):
        RUNTIME_CHANNELS = channels
    if not os.environ.get("CFQUANT_QMT_LOG_LANGUAGE") and data.get("qmt_log_language"):
        os.environ["CFQUANT_QMT_LOG_LANGUAGE"] = str(data.get("qmt_log_language") or "zh")
    if not os.environ.get("CFQUANT_QMT_LOG_ENABLED") and "qmt_log_enabled" in data:
        os.environ["CFQUANT_QMT_LOG_ENABLED"] = "1" if _config_bool(data.get("qmt_log_enabled"), True) else "0"
    _write_runtime_log(
        "cfquant lite runtime config loaded path=%s bridge_id=%s pipe=%s"
        % (path, BRIDGE_ID, PIPE_NAME)
    )


def _print_log(message):
    if not get_log_enabled():
        return
    translated = translate_log(message)
    print(translated)
    _write_runtime_log(translated)


_apply_runtime_config()
_write_runtime_log("cfquant lite entry executing from {} cwd {}".format(_entry_file_path() or "<string>", os.getcwd()))

_ENTRY_VERSION = LITE_ENTRY_VERSION
BRIDGE_ID = normalize_bridge_id(BRIDGE_ID)
if not os.environ.get("CFQUANT_BRIDGE_ID"):
    os.environ["CFQUANT_BRIDGE_ID"] = BRIDGE_ID
    os.environ["CFQUANT_BRIDGE_ID_SOURCE"] = "cfquant_entry"
if PIPE_NAME and not os.environ.get("CFQUANT_PIPE_NAME"):
    os.environ["CFQUANT_PIPE_NAME"] = PIPE_NAME
    os.environ["CFQUANT_PIPE_NAME_SOURCE"] = "cfquant_entry"
BRIDGE_CHANNELS = channels_for_bridge(BRIDGE_ID)
for _channel_key in ("normal", "trade", "callback"):
    _channel_value = RUNTIME_CHANNELS.get(_channel_key) or RUNTIME_CONFIG.get("%s_channel" % _channel_key)
    if _channel_value:
        BRIDGE_CHANNELS[_channel_key] = str(_channel_value).strip()

_normal_bridge = start_pipe_normal_bridge(
    None,
    pipe_name=PIPE_NAME,
    request_channel=BRIDGE_CHANNELS["normal"],
    request_channels=[BRIDGE_CHANNELS["normal"]],
    callback_event_channel=BRIDGE_CHANNELS["callback"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
    schedule_timer=True,
    pump_max_count=NORMAL_PUMP_MAX_COUNT,
    pump_max_ms=NORMAL_PUMP_MAX_MS,
    connect_timeout_ms=PIPE_CONNECT_TIMEOUT_MS,
)

_trade_bridge = start_pipe_trade_bridge(
    None,
    pipe_name=PIPE_NAME,
    request_channel=BRIDGE_CHANNELS["trade"],
    bridge_id=BRIDGE_ID,
    account_id=DEFAULT_ACCOUNT_ID,
    show=True,
    connect_timeout_ms=PIPE_CONNECT_TIMEOUT_MS,
)

_print_log("cfquant lite extreme bridge module loaded")
_print_log("cfquant lite extreme entry version:%s" % _ENTRY_VERSION)
_print_log("cfquant lite bridge id:%s pipe:%s normal_channel:%s trade_channel:%s callback_channel:%s" % (
    BRIDGE_ID,
    PIPE_NAME,
    BRIDGE_CHANNELS["normal"],
    BRIDGE_CHANNELS["trade"],
    BRIDGE_CHANNELS["callback"],
))
_print_log("cfquant lite trade loop in thread:%s sleep_seconds:%s" % (TRADE_LOOP_IN_THREAD, TRADE_SLEEP_SECONDS))



def _record_lite_runtime_report_success(reason):
    global _runtime_report_sent_at, _runtime_report_count, _runtime_report_last_error

    _runtime_report_sent_at = time.time()
    _runtime_report_count += 1
    _runtime_report_last_error = ""


def _record_lite_runtime_report_error(reason, error):
    global _runtime_report_last_error

    _runtime_report_last_error = "%s:%s" % (type(error).__name__, error)


def _publish_lite_runtime_report(reason="startup", force=False):
    global _runtime_report_last_attempt_at, _runtime_report_pending_log_at, _runtime_report_last_error

    now = time.time()
    if not force and now - _runtime_report_last_attempt_at < 1.0:
        return False
    _runtime_report_last_attempt_at = now
    if not _normal_bridge:
        return False
    try:
        tx = getattr(_normal_bridge, "tx", None)
        if tx is None:
            raise RuntimeError("normal bridge tx not ready")
        get_tx_conn = getattr(tx, "_get_tx_conn", None)
        if callable(get_tx_conn) and get_tx_conn() is None:
            if now - _runtime_report_pending_log_at >= 30.0:
                _runtime_report_pending_log_at = now
                _print_log("cfquant lite runtime version report pending reason=%s" % reason)
            return False
        _normal_bridge._publish_runtime_report(reason)
        if _runtime_report_last_error:
            return False
        _print_log(
            "cfquant lite runtime version report sent reason=%s version=%s entry_version=%s"
            % (reason, CORE_VERSION, LITE_ENTRY_VERSION)
        )
        return True
    except Exception as e:
        _record_lite_runtime_report_error(reason, e)
        _print_log("cfquant lite runtime version report failed:%s" % _runtime_report_last_error)
        return False


def _attach_normal_status_extra():
    if not _normal_bridge:
        return
    original_status_extra = _normal_bridge._status_extra

    def status_extra_with_trade():
        data = original_status_extra()
        data.update({
            "transport": "lite",
            "transport_mode": "lite",
            "qmt_runtime_mode": "lite_extreme_pipe",
            "qmt_runtime_label": "极致模式",
            "qmt_runtime_core_version": CORE_VERSION,
            "qmt_runtime_entry_version": LITE_ENTRY_VERSION,
            "qmt_runtime_entry_script": "CFQUANT_LITE.py",
            "qmt_runtime_report_sent_at": _runtime_report_sent_at,
            "qmt_runtime_report_count": _runtime_report_count,
            "qmt_runtime_report_last_error": _runtime_report_last_error,
            "qmt_runtime_module_file": _entry_file_path() or "<string>",
            "qmt_runtime_entry_file": _entry_file_path() or "<string>",
            "ctype_trade_bridge_running": bool(_trade_bridge and _trade_bridge.running),
            "ctype_trade_thread_alive": bool(_trade_thread and _trade_thread.is_alive()),
            "ctype_trade_queue_size": _trade_request_queue.qsize(),
            "ctype_trade_timer_key": _trade_timer_key,
            "ctype_trade_loop_started_at": _trade_loop_started_at,
            "ctype_trade_loop_error": _trade_loop_error,
            "ctype_trade_recv_count": _trade_recv_count,
            "ctype_trade_dispatch_count": _trade_dispatch_count,
            "ctype_trade_direct_dispatch_count": _trade_direct_dispatch_count,
            "ctype_trade_reroute_count": _trade_reroute_count,
            "ctype_trade_queue_full_count": _trade_queue_full_count,
            "ctype_trade_last_recv_at": _trade_last_recv_at,
            "ctype_trade_last_dispatch_at": _trade_last_dispatch_at,
            "ctype_trade_request_channel": BRIDGE_CHANNELS["trade"],
            "ctype_trade_loop_in_thread": TRADE_LOOP_IN_THREAD,
            "ctype_trade_sleep_seconds": TRADE_SLEEP_SECONDS,
            "ctype_trade_pump_max_count": TRADE_PUMP_MAX_COUNT,
            "ctype_trade_pump_max_ms": TRADE_PUMP_MAX_MS,
            "ctype_trade_timer_interval_ms": TRADE_TIMER_INTERVAL_MS,
            "ctype_trade_dispatch_thread": "qmt_timer_or_handlebar",
            "ctype_trade_route_mode": "xttrader_to_normal_worker",
        })
        return data

    _normal_bridge._status_extra = status_extra_with_trade


def _run_trade_loop():
    global _trade_loop_error, _trade_recv_count, _trade_queue_full_count, _trade_last_recv_at

    while _trade_bridge and _trade_bridge.running:
        try:
            tx = _trade_bridge.tx
            if tx is None:
                time.sleep(0.05)
                continue
            raw = tx.Q.get(timeout=TRADE_SLEEP_SECONDS)
            if raw is None:
                continue
            _trade_request_queue.put_nowait(raw)
            _trade_recv_count += 1
            _trade_last_recv_at = time.time()
        except Exception as e:
            if isinstance(e, queue.Empty):
                continue
            if isinstance(e, queue.Full):
                _trade_queue_full_count += 1
                _trade_loop_error = "trade request queue full"
            else:
                _trade_loop_error = "%s:%s" % (type(e).__name__, e)
            _print_log("cfquant lite extreme trade loop error:%s" % _trade_loop_error)
            try:
                time.sleep(0.05)
            except Exception:
                pass


def _drain_trade_requests(source):
    global _trade_dispatch_count, _trade_last_dispatch_at, _trade_loop_error

    if not _trade_bridge:
        return 0
    start = time.perf_counter()
    count = 0
    while count < TRADE_PUMP_MAX_COUNT:
        if TRADE_PUMP_MAX_MS > 0 and (time.perf_counter() - start) * 1000 >= TRADE_PUMP_MAX_MS:
            break
        try:
            raw = _trade_request_queue.get_nowait()
        except queue.Empty:
            break
        try:
            _handle_trade_raw(raw)
            _trade_dispatch_count += 1
            _trade_last_dispatch_at = time.time()
        except Exception as e:
            _trade_loop_error = "%s:%s" % (type(e).__name__, e)
            _print_log("cfquant lite extreme trade dispatch error source=%s error=%s" % (source, _trade_loop_error))
        count += 1
    return count


def _handle_trade_raw(raw):
    if _should_reroute_trade_raw(raw) and _normal_bridge:
        return _reroute_trade_raw_to_normal(raw)
    _handle_trade_raw_direct(raw)


def _should_reroute_trade_raw(raw):
    msg = loads_message(raw)
    if not msg or msg.get("type") != "request":
        return False
    action = str(msg.get("action") or "")
    return action.startswith("xttrader.") or action == "cfquant.query_info"


def _reroute_trade_raw_to_normal(raw):
    global _trade_reroute_count

    _normal_bridge._handle_raw_from_thread(raw)
    _trade_reroute_count += 1


def _handle_trade_raw_direct(raw):
    global _trade_direct_dispatch_count

    _trade_bridge._handle_raw(raw)
    _trade_direct_dispatch_count += 1


def _start_trade_loop():
    global _trade_thread, _trade_loop_started_at, _trade_loop_error

    if not _trade_bridge:
        return
    if _trade_thread is not None and _trade_thread.is_alive():
        return
    if TRADE_LOOP_IN_THREAD:
        _trade_loop_error = ""
        _trade_loop_started_at = time.time()
        _trade_thread = threading.Thread(target=_run_trade_loop)
        _trade_thread.daemon = True
        _trade_thread.start()
        _print_log("cfquant lite extreme trade loop started in worker thread")
        return
    _print_log("cfquant lite extreme trade loop entering current QMT thread")
    _run_trade_loop()


def cfquant_ctype_trade_timer(*args, **kwargs):
    _drain_trade_requests("timer")


def _schedule_trade_timer(ContextInfo):
    global _trade_timer_key

    if _trade_timer_key or ContextInfo is None:
        return
    try:
        first_time = dt.datetime.now() + dt.timedelta(seconds=1)
        _trade_timer_key = ContextInfo.schedule_run(
            cfquant_ctype_trade_timer,
            first_time,
            repeat_times=-1,
            interval=dt.timedelta(milliseconds=TRADE_TIMER_INTERVAL_MS),
            name="cfquant_lite_trade_bridge_pump",
        )
        _print_log("cfquant lite extreme trade timer scheduled key:%s interval_ms:%s" % (_trade_timer_key, TRADE_TIMER_INTERVAL_MS))
    except Exception as e:
        _print_log("cfquant lite extreme trade timer schedule failed:%s" % e)


_attach_normal_status_extra()
_runtime_report_retry_until = time.time() + 60.0
_publish_lite_runtime_report("module_loaded")
if TRADE_LOOP_IN_THREAD:
    _start_trade_loop()


_QMT_TRADE_CALLBACK_REGISTERED = False


def _register_qmt_trade_callback(ContextInfo, stage):
    global _QMT_TRADE_CALLBACK_REGISTERED

    if ContextInfo is None or _QMT_TRADE_CALLBACK_REGISTERED:
        return
    func = getattr(ContextInfo, "register_callback", None)
    if not callable(func):
        _print_log("cfquant lite qmt trade callback register skipped stage=%s reason=missing register_callback" % stage)
        return
    try:
        func(0)
        _QMT_TRADE_CALLBACK_REGISTERED = True
        _print_log("cfquant lite qmt trade callback registered stage=%s" % stage)
    except Exception as e:
        _print_log("cfquant lite qmt trade callback register failed stage=%s error=%s" % (stage, e))


def _refresh_auto_trade_callback(stage):
    for bridge_name, bridge in (("normal", _normal_bridge), ("trade", _trade_bridge)):
        if bridge is None or not hasattr(bridge, "_enable_auto_trade_callback"):
            continue
        try:
            bridge.auto_trade_callback_enabled = False
            bridge._enable_auto_trade_callback()
            _print_log("cfquant lite auto trade callback refreshed stage=%s bridge=%s" % (stage, bridge_name))
        except Exception as e:
            _print_log("cfquant lite auto trade callback refresh failed stage=%s bridge=%s error=%s" % (stage, bridge_name, e))


def _callback_brief(obj):
    try:
        parts = []
        for name in ("account_id", "m_strAccountID", "m_strInstrumentID", "m_strExchangeID", "m_strOrderSysID", "m_nOrderID", "m_strRemark"):
            value = getattr(obj, name, None)
            if value is None and hasattr(obj, "get"):
                value = obj.get(name)
            if value not in (None, ""):
                parts.append("%s=%s" % (name, value))
        return " ".join(parts) or type(obj).__name__
    except Exception:
        return type(obj).__name__


def _object_to_callback_dict(obj):
    if hasattr(obj, "items"):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {"value": str(obj)}

def init(ContextInfo):
    global _runtime_report_retry_until

    _register_qmt_trade_callback(ContextInfo, "init")
    if _normal_bridge:
        _normal_bridge.set_context(ContextInfo)
        _print_log("cfquant lite normal context ready version:%s" % _ENTRY_VERSION)
    if _trade_bridge:
        _trade_bridge.set_context(ContextInfo)
        _print_log("cfquant lite extreme trade context ready version:%s" % _ENTRY_VERSION)
    _start_trade_loop()
    _schedule_trade_timer(ContextInfo)
    _runtime_report_retry_until = time.time() + 60.0
    if not _runtime_report_sent_at:
        _publish_lite_runtime_report("context_ready", force=True)


def after_init(ContextInfo):
    _register_qmt_trade_callback(ContextInfo, "after_init")
    _refresh_auto_trade_callback("after_init")


def handlebar(ContextInfo):
    if TRADE_LOOP_IN_THREAD:
        _start_trade_loop()
    _drain_trade_requests("handlebar")
    if not _runtime_report_sent_at and time.time() <= _runtime_report_retry_until:
        _publish_lite_runtime_report("startup_retry")
    if _normal_bridge:
        _normal_bridge.pump()


def stop(ContextInfo):
    global _normal_bridge, _trade_bridge, _trade_timer_key

    if ContextInfo is not None and _trade_timer_key:
        try:
            ContextInfo.cancel_schedule_run(_trade_timer_key)
        except Exception as e:
            _print_log("cfquant lite extreme trade timer cancel failed:%s" % e)
        _trade_timer_key = None

    if _trade_bridge:
        _trade_bridge.close()
        _trade_bridge = None
        _print_log("cfquant lite extreme trade bridge stopped")
    if _normal_bridge:
        _normal_bridge.close()
        _normal_bridge = None
        _print_log("cfquant lite normal bridge stopped")


def _publish_callback(event_name, obj):
    try:
        _print_log("cfquant lite raw qmt callback received event=%s %s" % (event_name, _callback_brief(obj)))
        if _normal_bridge:
            _normal_bridge.publish_callback_event(event_name, obj)
    except Exception as e:
        _print_log("cfquant lite extreme callback publish failed event=%s error=%s" % (event_name, e))


def account_callback(ContextInfo, accountInfo):
    _publish_callback("trader:on_stock_asset", accountInfo)


def order_callback(ContextInfo, orderInfo):
    _publish_callback("trader:on_stock_order", orderInfo)


def deal_callback(ContextInfo, dealInfo):
    _publish_callback("trader:on_stock_trade", dealInfo)


def trade_callback(ContextInfo, tradeInfo):
    _publish_callback("trader:on_stock_trade", tradeInfo)


def position_callback(ContextInfo, positionInfo):
    _publish_callback("trader:on_stock_position", positionInfo)


def order_error_callback(ContextInfo, orderError):
    _publish_callback("trader:on_order_error", orderError)


def orderError_callback(ContextInfo, passOrderInfo, msg):
    data = _object_to_callback_dict(passOrderInfo)
    data["error_msg"] = msg
    _publish_callback("trader:on_order_error", data)


def cancel_error_callback(ContextInfo, cancelError):
    _publish_callback("trader:on_cancel_error", cancelError)


def cancelError_callback(ContextInfo, cancelError):
    _publish_callback("trader:on_cancel_error", cancelError)


def order_stock_async_response_callback(ContextInfo, response):
    _publish_callback("trader:on_order_stock_async_response", response)


def cancel_order_stock_async_response_callback(ContextInfo, response):
    _publish_callback("trader:on_cancel_order_stock_async_response", response)
