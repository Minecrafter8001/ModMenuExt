from __future__ import annotations

import logging
from pathlib import Path


LOGGER_NAME = "modmenuext"


def get_logger(name: str | None = None) -> logging.Logger:
    logger_name = LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}"
    return logging.getLogger(logger_name)


def configure_logging(write_to_file: bool = False) -> logging.Logger:
    logger = get_logger()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if write_to_file:
        file_handler = logging.FileHandler(Path("modmenu.log"), encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.info("Logging initialized%s", " with file output" if write_to_file else "")
    return logger
