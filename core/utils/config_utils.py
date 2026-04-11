from contextlib import contextmanager
from pathlib import Path
from ruamel.yaml import YAML
import threading

ROOT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
lock = threading.Lock()
_thread_state = threading.local()

yaml = YAML()
yaml.preserve_quotes = True

# -----------------------
# load & update config
# -----------------------


def get_config_path():
    return Path(getattr(_thread_state, "config_path", ROOT_CONFIG_PATH))


def set_config_path(path):
    _thread_state.config_path = str(Path(path))


def reset_config_path():
    if hasattr(_thread_state, "config_path"):
        delattr(_thread_state, "config_path")


@contextmanager
def use_config_path(path):
    previous = getattr(_thread_state, "config_path", None)
    set_config_path(path)
    try:
        yield
    finally:
        if previous is None:
            reset_config_path()
        else:
            _thread_state.config_path = previous

def load_key(key):
    with lock:
        with open(get_config_path(), 'r', encoding='utf-8') as file:
            data = yaml.load(file)

    keys = key.split('.')
    value = data
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            raise KeyError(f"Key '{k}' not found in configuration")
    return value

def update_key(key, new_value):
    with lock:
        config_path = get_config_path()
        with open(config_path, 'r', encoding='utf-8') as file:
            data = yaml.load(file)

        keys = key.split('.')
        current = data
        for k in keys[:-1]:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return False

        if isinstance(current, dict) and keys[-1] in current:
            current[keys[-1]] = new_value
            with open(config_path, 'w', encoding='utf-8') as file:
                yaml.dump(data, file)
            return True
        else:
            raise KeyError(f"Key '{keys[-1]}' not found in configuration")
        
# basic utils
def get_joiner(language):
    if language in load_key('language_split_with_space'):
        return " "
    elif language in load_key('language_split_without_space'):
        return ""
    else:
        raise ValueError(f"Unsupported language code: {language}")

if __name__ == "__main__":
    print(load_key('language_split_with_space'))
