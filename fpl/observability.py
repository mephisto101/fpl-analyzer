from __future__ import annotations

import logging


def get_logger(*, name: str = "fpl_app", debug: bool = False) -> logging.Logger:
    """
    Streamlit runs in a long-lived process; avoid adding duplicate handlers.
    Logs go to the Streamlit server console (or terminal) by default.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    # Avoid double-logging if root logger is configured elsewhere.
    logger.propagate = False
    return logger

