"""Version context for cfquant diagnostics without changing application logging."""
import logging

from .version import __version__ as CFQUANT_VERSION


def versioned_message(message):
    text = str(message)
    tag = "[cfquant %s]" % CFQUANT_VERSION
    return text if tag in text else "%s %s" % (text, tag)


class VersionedErrorMixin:
    cfquant_version = CFQUANT_VERSION

    def __str__(self):
        # Keep .args and structured error codes intact for existing callers.
        return versioned_message(super(VersionedErrorMixin, self).__str__())


class _VersionFilter(logging.Filter):
    def filter(self, record):
        record.msg = versioned_message(record.getMessage())
        record.args = ()
        record.cfquant_version = CFQUANT_VERSION
        return True


_VERSION_FILTER = _VersionFilter()


def get_logger(name):
    logger = logging.getLogger(name)
    logger.addFilter(_VERSION_FILTER)
    return logger
