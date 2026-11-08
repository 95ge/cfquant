import logging

from cfquant.client import CfquantError
from cfquant.diagnostic_context import CFQUANT_VERSION, get_logger, versioned_message
from cfquant.protocol import encode_error, loads_message, pack_response


def test_cfquant_error_and_wire_error_include_version():
    error = CfquantError("bridge unavailable", details={"code": "QMT_BRIDGE_NOT_CONNECTED"})
    assert CFQUANT_VERSION in str(error)
    assert error.cfquant_version == CFQUANT_VERSION
    encoded = encode_error(error)
    assert encoded["cfquant_version"] == CFQUANT_VERSION
    assert CFQUANT_VERSION in encoded["message"]
    response = loads_message(pack_response("request-1", ok=False, error=error))
    assert response["error"]["cfquant_version"] == CFQUANT_VERSION


def test_project_logger_adds_version_without_breaking_formatting(caplog):
    logger = get_logger("cfquant.test.diagnostic_context")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        logger.warning("route failed channel=%s", "cfquant.trade.request")
    assert len(caplog.records) == 1
    assert CFQUANT_VERSION in caplog.records[0].message
    assert caplog.records[0].cfquant_version == CFQUANT_VERSION


def test_versioned_message_does_not_duplicate_tag():
    message = versioned_message("already reported [cfquant %s]" % CFQUANT_VERSION)
    assert message.count("[cfquant %s]" % CFQUANT_VERSION) == 1
