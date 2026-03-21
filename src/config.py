"""설정 파일 로드 및 검증."""

import copy

import yaml

REQUIRED_KEYS = ["output_dir", "crawled_dir", "source"]

DEFAULTS = {
    "crawl": {
        "timeout": 10,
        "delay": 1.5,
        "max_content_length": 2000,
        "max_workers": 5,
        "yt_delay": 2.0,
        "max_articles_per_source": 15,
        "delay_factor": 0.3,
    },
    "preprocessor": {
        "dedup_threshold": 0.5,
        "grouping_threshold": 0.3,
        "min_title_length": 5,
        "max_summary_length": 300,
    },
    "feedback": {
        "file": "feedback/weekly_feedback.md",
    },
}


def load_config(config_path: str = "config.yaml") -> dict:
    """설정 파일을 로드하고 검증한다.

    Args:
        config_path: YAML 설정 파일 경로

    Returns:
        검증 및 기본값이 머지된 설정 dict

    Raises:
        FileNotFoundError: 설정 파일이 없을 때
        ValueError: 필수 키가 누락되었을 때
    """
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if config is None:
        config = {}

    # 필수 키 확인
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(
            f"설정 파일에 필수 키가 누락되었습니다: {', '.join(missing)}\n"
            f"필수 키: {REQUIRED_KEYS}\n"
            f"설정 파일: {config_path}"
        )

    # 기본값 머지 (config에 없는 키는 DEFAULTS에서 채움)
    for section, defaults in DEFAULTS.items():
        if section not in config:
            config[section] = copy.deepcopy(defaults)
        elif isinstance(config[section], dict) and isinstance(defaults, dict):
            for key, value in defaults.items():
                if key not in config[section]:
                    config[section][key] = value

    return config
