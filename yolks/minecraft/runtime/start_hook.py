#!/usr/bin/env python3
import os
import shlex
import shutil
import subprocess
from typing import Dict, Any, List

from ruamel.yaml import YAML

WORKING_DIR = "/home/container"
CONFIG_FILE = "/start_hook.yml"
MCDR_CONFIG_FILE = "config.yml"
INSTALLATION_MARK_FILE = os.path.join(WORKING_DIR, ".mcdr_installed")


def log(s: str):
    if os.getenv("DEBUG_START_HOOK") == "true":
        print(f"[StartHook] {s}", flush=True)


def read_yaml(file_path: str):
    with open(file_path, "r", encoding="utf8") as f:
        return YAML().load(f)


def write_yaml(data, file_path: str):
    with open(file_path, "w", encoding="utf8") as f:
        yaml = YAML()
        yaml.width = 4096
        yaml.dump(data, f)


def _to_native_type(value: str) -> Any:
    if not isinstance(value, str):
        return value
    val_lower = value.lower()
    if val_lower == "true":
        return True
    if val_lower == "false":
        return False
    if val_lower.isdigit():
        return int(val_lower)
    return value


def build_start_command_list() -> List[str]:
    parts = []
    for part_env in [
        "MCDR_CMD_PART_EXEC",
        "MCDR_CMD_PART_JVM",
        "MCDR_CMD_PART_MAIN",
        "MCDR_CMD_PART_ARGS",
    ]:
        part_val = os.getenv(part_env)
        if part_val:
            parts.extend(shlex.split(part_val))
    if not parts:
        log("警告: 未能从环境变量构建启动命令列表")
    log(f"构建的启动命令列表: {parts}")
    return parts


def apply_modifications(phase: str, config: Dict):
    log(f"Applying file modifications for phase '{phase}'")
    for file_path, patch in config.get(phase, {}).items():
        if not os.path.isfile(file_path):
            log(f"Skipping file '{file_path}' as it does not exist")
            continue

        log(f"Modifying file '{file_path}'")
        data = read_yaml(file_path)
        modified = False

        for key, value in patch.items():
            if key == "start_command":
                final_value = build_start_command_list()
                if not final_value:
                    continue
            else:
                expanded_value = os.path.expandvars(str(value))
                final_value = _to_native_type(expanded_value)

            keys = key.split(".")
            current_level = data
            for i, k in enumerate(keys[:-1]):
                if k not in current_level or not isinstance(current_level.get(k), dict):
                    current_level[k] = {}
                current_level = current_level[k]

            last_key = keys[-1]
            if last_key not in current_level or current_level[last_key] != final_value:
                log(
                    f"  - Setting '{key}': {current_level.get(last_key)} -> {final_value}"
                )
                current_level[last_key] = final_value
                modified = True

        if modified:
            write_yaml(data, file_path)
            log(f"File '{file_path}' has been updated.")
        else:
            log(f"No changes made to file '{file_path}'.")


def handle_first_launch():
    if not os.path.exists(INSTALLATION_MARK_FILE):
        log("First launch detected. Initializing MCDReforged environment...")
        subprocess.run("python3 -m mcdreforged init", shell=True, check=True)
        with open(INSTALLATION_MARK_FILE, "w") as f:
            f.write("installed")
        return True
    return False


def move_minecraft_eula():
    eula_file = "eula.txt"
    if not os.path.isfile(eula_file):
        return
    with open(eula_file, "r") as f:
        if "eula=true" not in f.read().lower():
            return
    working_directory = read_yaml(MCDR_CONFIG_FILE).get("working_directory", "server")
    dest_path = os.path.join(working_directory, eula_file)
    if os.path.isdir(working_directory):
        log(f"Moving '{eula_file}' to '{dest_path}'")
        shutil.move(eula_file, dest_path)


def main():
    if not os.path.samefile(os.getcwd(), WORKING_DIR):
        raise SystemExit(
            f"Error: Unexpected working dir {os.getcwd()}, should be {WORKING_DIR}"
        )
    config = read_yaml(CONFIG_FILE)
    if handle_first_launch():
        apply_modifications("install", config)
    apply_modifications("pre_start", config)
    move_minecraft_eula()
    log("Start hook finished.")


if __name__ == "__main__":
    main()
