# -*- coding: utf-8 -*-
from . import xtconstant


class DictObject(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @classmethod
    def from_any(cls, value):
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if hasattr(value, "__dict__"):
            return cls(**vars(value))
        if isinstance(value, dict):
            return cls(**value)
        return value

    def __repr__(self):
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join("%s=%r" % item for item in sorted(self.__dict__.items())),
        )


class StockAccount(object):
    def __new__(cls, account_id, account_type="STOCK"):
        if not isinstance(account_id, str):
            return "资金账号必须为字符串类型"
        return super(StockAccount, cls).__new__(cls)

    def __init__(self, account_id, account_type="STOCK"):
        account_type = account_type.upper()
        for int_type, str_type in xtconstant.ACCOUNT_TYPE_DICT.items():
            if account_type == str_type:
                self.account_type = int_type
                self.account_id = account_id
                return
        raise Exception("不支持的账号类型：{}！".format(account_type))


class XtAsset(DictObject):
    pass


class XtOrder(DictObject):
    pass


class XtTrade(DictObject):
    pass


class XtPosition(DictObject):
    pass


class XtOrderError(DictObject):
    pass


class XtCancelError(DictObject):
    pass


class XtOrderResponse(DictObject):
    pass


class XtCancelOrderResponse(DictObject):
    pass


class XtAccountStatus(DictObject):
    pass


class XtBankTransferResponse(DictObject):
    pass


class XtSmtAppointmentResponse(DictObject):
    pass


def to_objects(values, cls=DictObject):
    if values is None:
        return None
    if isinstance(values, list):
        return [cls.from_any(v) for v in values]
    return cls.from_any(values)
