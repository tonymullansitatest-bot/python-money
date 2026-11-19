from pathlib import Path
from platformdirs import user_data_dir

APP_NAME = "PersonalFinanceManager"
APP_AUTHOR = "PersonalFinanceManager"


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    return f"sqlite:///{(data_dir() / 'finance_manager.db').as_posix()}"
