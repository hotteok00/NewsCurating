"""프로젝트 공용 로거."""

import logging


def get_logger(name: str) -> logging.Logger:
    """프로젝트 공용 로거를 반환한다.

    Args:
        name: 로거 이름 (예: "main", "crawler")

    Returns:
        설정된 logging.Logger 인스턴스
    """
    logger = logging.getLogger(f"newscurating.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
