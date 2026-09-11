"""Create QMT's locally verified unprotected, single-Python RZRK format."""

import hashlib
import json
import re


def _aes_module():
    try:
        from Crypto.Cipher import AES
        return AES
    except ImportError as crypto_error:
        try:
            from Cryptodome.Cipher import AES
            return AES
        except ImportError:
            raise RuntimeError(
                "QMT 策略打包需要 pycryptodome，请使用当前 Web Python 执行 "
                "'python -m pip install pycryptodome>=3.20' 后重启 Web"
            ) from crypto_error


def _cipher():
    AES = _aes_module()
    seed = bytes((a + b) & 255 for a, b in zip(b"rzrk2012", b"RZRK8888"))
    material, previous = b"", b""
    # QMT uses EVP_BytesToKey(SHA1, no salt, count=5), AES-256-CFB128.
    while len(material) < 48:
        previous = hashlib.sha1(previous + seed).digest()
        for _ in range(4):
            previous = hashlib.sha1(previous).digest()
        material += previous
    return AES.new(material[:32], AES.MODE_CFB, iv=material[32:48], segment_size=128)


def build_package(name, source, stock="SH000300", period=86400):
    if not re.fullmatch(r"CFQ_[A-Z0-9_]{1,59}", name):
        raise ValueError("Invalid managed QMT strategy name")
    if not source or "\x00" in source or len(source.encode("utf-8")) > 16 * 1024 * 1024:
        raise ValueError("Invalid QMT strategy source")
    detail = {
        "showName": name, "realName": name + ".py", "luaScript": "", "mainGraph": 0,
        "m_runPeriod": period, "m_runStock": stock, "m_nDrType": 3, "DataCount": 0,
        "arguName": [], "arguMax": [], "arguMin": [], "argDefault": [], "arguSteps": [],
        "outPutVars": [], "outputVarsPrecise": [], "defaultPeriod": -1, "scriptType": 1,
        "minDataCount": 0, "visualAndEditableLevel": 2, "intro": "cfquant account bridge",
        "isEncrypt": False, "pwd": "", "exportUsePwd": False, "importUsePwd": False,
        "brief": "", "arguTypes": [], "childFormula": [], "strArguName": [],
        "strArguDefault": [], "strArguInits": [], "investNames": [], "tradeBuyParam": "",
        "tradeSellParam": "", "tradeName": "", "buyOrderSetting": "", "sellOrderSetting": "",
        "createAccountType": 0, "closeUpdate": 0, "dataUpdateTime": 0, "dataType": [],
        "ScriptType": 1, "m_backTestOff": 0, "m_backTestMoney": 1000000,
        "m_backTestDeposit": 1, "m_backTestSlippage": 0, "m_backTestTypes": [],
        "m_backTestAmounts": [], "m_backTestNums": [],
        "m_backtestparam": {
            "m_starttime": "2017-01-01 00:00:00", "m_endtime": "2020-12-31 00:00:00",
            "m_benchmark": "000300.SH", "m_dInitialAsset": 1000000, "m_dInitialMargin": 0.05,
            "m_multiplier": 0, "m_slippageType": 2, "m_slippage": 0, "m_maxVolRate": 0,
            "m_rate": {key: 0 for key in ("m_comsissonType", "m_close_today_commission",
                       "m_min_commission", "m_open_tax", "m_close_tax", "m_open_commission",
                       "m_close_commission")},
        },
    }
    document = {"isgroup": False, "content": source, "detail": detail,
                "formulaCatalog": [bytes.fromhex("ced2b5c4b2dfc2d4").decode("utf-8", "surrogateescape")],
                "formulaCatalogModelType": 4, "simplerun": False}
    plaintext = json.dumps(document, ensure_ascii=False, allow_nan=False,
                           separators=(", ", " : ")).encode("utf-8", "surrogateescape")
    return _cipher().encrypt(plaintext)
