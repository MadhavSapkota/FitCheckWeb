from __future__ import annotations

import logging
import os
import re

_SECRET_ENV = [
    "ANTHROPIC_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
    "GSC_SERVICE_ACCOUNT_JSON",
]


class RedactFilter(logging.Filter):
    """Removes any configured secret values from log lines, as a second line of defence."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for name in _SECRET_ENV:
            val = os.environ.get(name)
            if val and len(val) >= 6:
                msg = msg.replace(val, "***")
        msg = re.sub(r"(Bearer|Basic)\s+[A-Za-z0-9._\-+/=]+", r"\1 ***", msg)
        record.msg, record.args = msg, ()
        return True


def setup_logging(logfile: str | None = None) -> logging.Logger:
    logger = logging.getLogger("seo_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if logfile:
        os.makedirs(os.path.dirname(logfile), exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        logger.addHandler(h)
    return logger


log = logging.getLogger("seo_agent")
