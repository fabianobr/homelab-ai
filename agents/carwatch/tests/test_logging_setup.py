"""tests/test_logging_setup.py"""
import json
import logging

from carwatch.logging_setup import configure_logging


def test_configure_logging_emits_json(capsys):
    logger = configure_logging("INFO")
    logger.info("fetch.result", domain="example.com", status=200)

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["event"] == "fetch.result"
    assert payload["domain"] == "example.com"
    assert payload["status"] == 200
