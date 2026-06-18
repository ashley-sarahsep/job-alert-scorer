"""Load the YAML config and resolve everything relative to the config file.

Config is located in this order:
  1. an explicit path (``--config`` / the ``config_path`` argument)
  2. the JOB_SCORER_CONFIG environment variable
  3. the bundled default at ``<repo>/config/config.yaml``

All path-like settings (candidate profile, credentials, caches, output dir) are
resolved relative to the config file's own directory, so a private config and
its personal files can live together in one folder, pointed to with --config.
"""

import os

# Settings interpreted as filesystem paths, resolved relative to the config dir.
PATH_KEYS = (
    "candidate_profile", "candidate_addendum", "credentials_file", "token_file",
    "last_run_file", "fetch_cache_file", "scored_cache_file", "output_directory",
)


def find_config_path(config_path=None):
    if config_path:
        return config_path
    env = os.environ.get("JOB_SCORER_CONFIG")
    if env:
        return env
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "config", "config.yaml")


def _load_env_file(base_dir):
    """Load KEY=VALUE pairs from a .env in the config dir into the environment."""
    env_path = os.path.join(base_dir, ".env")
    if not os.path.exists(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(config_path=None):
    """Load and return the config dict (with paths resolved)."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required. Install it with: pip install pyyaml") from exc

    path = find_config_path(config_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config not found at '{path}'.\n"
            "Copy config/config.example.yaml to config/config.yaml and edit it, "
            "or pass --config /path/to/config.yaml (or set JOB_SCORER_CONFIG)."
        )

    with open(path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}

    base_dir = os.path.dirname(os.path.abspath(path))
    config["_config_dir"] = base_dir
    _load_env_file(base_dir)

    for key in PATH_KEYS:
        value = config.get(key)
        if isinstance(value, str) and value and not os.path.isabs(value):
            config[key] = os.path.normpath(os.path.join(base_dir, value))

    return config
