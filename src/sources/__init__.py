"""소스 어댑터 레지스트리.

config.yaml의 source 값에 따라 적절한 어댑터를 호출한다.
새 소스를 추가하려면 이 패키지에 파일을 만들고 @register 데코레이터를 사용하면 된다.
"""

from typing import Callable

from log import get_logger

logger = get_logger("sources")

_ADAPTERS: dict[str, Callable[[dict], list[dict]]] = {}


def register(name: str):
    """소스 어댑터 등록 데코레이터."""
    def decorator(func: Callable[[dict], list[dict]]) -> Callable[[dict], list[dict]]:
        _ADAPTERS[name] = func
        return func
    return decorator


def load_sources(config: dict) -> list[dict]:
    """config의 source 값에 맞는 어댑터를 호출하여 URL 목록을 반환한다."""
    source_name = config.get("source", "tab_groups")
    adapter = _ADAPTERS.get(source_name)
    if not adapter:
        raise ValueError(
            f"알 수 없는 소스: '{source_name}'\n"
            f"사용 가능: {list(_ADAPTERS.keys())}"
        )
    logger.info("소스 로드: %s", source_name)
    return adapter(config)


# 어댑터 모듈을 임포트하여 등록시킨다
from . import file  # noqa: E402, F401
