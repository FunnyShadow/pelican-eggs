#!/usr/bin/env python3
import os
import re
import json
from typing import Dict, Any

from ruamel.yaml import YAML

WORKING_DIR = "/home/container"
CONFIG_FILE = "/start_hook.json"

VARIABLE_MAPPING = {
    "server.build.default.port": "SERVER_PORT",
    "server.build.default.ip": "SERVER_IP",
    "server.memory": "SERVER_MEMORY",
    "server.uuid": "P_SERVER_UUID",
    "server.location": "P_SERVER_LOCATION",
}


def log(s: str):
    if os.getenv("DEBUG_START_HOOK") == "true":
        print(f"[StartHook] {s}", flush=True)


def to_native_type(value: str) -> Any:
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


def expand_variables(value: Any) -> Any:
    if isinstance(value, str):

        def repl(match):
            placeholder = match.group(1).strip()
            env_var_name = VARIABLE_MAPPING.get(placeholder) or placeholder
            env_val = os.getenv(env_var_name)
            return env_val if env_val is not None else match.group(0)

        expanded_value = re.sub(r"\{\{([^}]+)\}\}", repl, value)
        return to_native_type(expanded_value)
    elif isinstance(value, dict):
        return {k: expand_variables(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_variables(v) for v in value]
    else:
        return value


def set_nested_value(data: Dict, path: str, value: Any):
    keys = re.split(r"\.(?![^\[]*\])", path)
    current_level = data
    for i, key in enumerate(keys[:-1]):
        match = re.match(r"(\w+)\[(\d+)\]", key)
        if match:
            key_name, index = match.groups()
            index = int(index)
            if not isinstance(current_level.get(key_name), list):
                current_level[key_name] = []
            while len(current_level[key_name]) <= index:
                current_level[key_name].append({})
            current_level = current_level[key_name][index]
        else:
            if not isinstance(current_level.get(key), dict):
                current_level[key] = {}
            current_level = current_level[key]

    last_key = keys[-1]
    match = re.match(r"(\w+)\[(\d+)\]", last_key)
    if match:
        key_name, index = match.groups()
        index = int(index)
        if not isinstance(current_level.get(key_name), list):
            current_level[key_name] = []
        while len(current_level[key_name]) <= index:
            current_level[key_name].append(None)
        current_level[key_name][index] = value
    else:
        current_level[last_key] = value


def patch_yaml_file(file_path: str, rules: Dict):
    log(f"  -> Parsing YAML file: {file_path}")
    yaml = YAML()
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    try:
        with open(file_path, "r", encoding="utf8") as f:
            data = yaml.load(f)
    except FileNotFoundError:
        log(f"     File not found, creating a new one.")
        data = {}

    for match, replace_with in rules.items():
        final_value = expand_variables(replace_with)
        log(f"     - Setting '{match}' -> '{str(final_value)}'")
        set_nested_value(data, match, final_value)

    with open(file_path, "w", encoding="utf8") as f:
        yaml.dump(data, f)


def patch_properties_file(file_path: str, rules: Dict):
    log(f"  -> Parsing Properties file: {file_path}")
    props = {}
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf8") as f:
            for line in f:
                stripped_line = line.strip()
                if (
                    stripped_line
                    and not stripped_line.startswith("#")
                    and "=" in stripped_line
                ):
                    key, value = stripped_line.split("=", 1)
                    props[key.strip()] = value.strip()

    for key, value in rules.items():
        final_value = expand_variables(value)
        log(f"     - Setting '{key}' -> '{str(final_value)}'")
        props[key] = str(final_value)

    with open(file_path, "w", encoding="utf8") as f:
        for key, value in props.items():
            f.write(f"{key}={value}\n")


def patch_generic_file(file_path: str, rules: Dict):
    log(f"  -> Parsing Generic file: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        log(
            f"     File '{file_path}' not found. It will be created with specified values."
        )
        lines = []

    new_lines = []
    keys_to_patch = set(rules.keys())
    patched_keys = set()

    for line in lines:
        stripped_line = line.strip()
        matched = False
        for key in keys_to_patch:
            if stripped_line.startswith(key):
                final_value = str(expand_variables(rules[key]))
                log(f"     - Replacing line starting with '{key}' -> '{final_value}'")
                new_lines.append(final_value + "\n")
                patched_keys.add(key)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    for key in keys_to_patch - patched_keys:
        final_value = str(expand_variables(rules[key]))
        log(f"     - Appending missing key '{key}' -> '{final_value}'")
        new_lines.append(final_value + "\n")

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main():
    if not os.path.samefile(os.getcwd(), WORKING_DIR):
        os.chdir(WORKING_DIR)

    with open(CONFIG_FILE, "r", encoding="utf8") as f:
        config = json.load(f)

    for file_path, instructions in config.get("files", {}).items():
        parser_type = instructions.get("parser")
        find_rules = instructions.get("find", {})
        if not parser_type or not find_rules:
            continue

        full_path = os.path.join(WORKING_DIR, file_path)
        dir_name = os.path.dirname(full_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        log(f"Processing file: {full_path} (using parser: {parser_type})")

        if parser_type in ["yaml", "yml"]:
            patch_yaml_file(full_path, find_rules)
        elif parser_type == "properties":
            patch_properties_file(full_path, find_rules)
        elif parser_type == "file":
            patch_generic_file(full_path, find_rules)
        else:
            log(f"Warning: Parser '{parser_type}' is not supported, skipping.")

    log("File patching completed successfully.")


if __name__ == "__main__":
    main()
