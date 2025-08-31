#!/usr/bin/env python3
import os
import re
import shlex
import shutil
import json
from typing import Dict, Any, List

from ruamel.yaml import YAML

WORKING_DIR = "/home/container"
CONFIG_FILE = "/start_hook.json"
MCDR_CONFIG_FILE = "config.yml"
INSTALLATION_MARK_FILE = os.path.join(WORKING_DIR, ".mcdr_installed")


def log(s: str):
    if os.getenv("DEBUG_START_HOOK") == "true":
        print(f"[StartHook] {s}", flush=True)


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
        log("Warning: Failed to build start command list from environment variables.")
    log(f"Built start command list: {parts}")
    return parts


class ConfigurationPatcher:
    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf8") as f:
            self.config = json.load(f)

    def _to_native_type(self, value: str) -> Any:
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

    def _read_yaml(self, file_path: str) -> Dict:
        with open(file_path, "r", encoding="utf8") as f:
            return YAML().load(f)

    def _write_yaml(self, data: Dict, file_path: str):
        with open(file_path, "w", encoding="utf8") as f:
            yaml = YAML()
            yaml.width = 4096
            yaml.indent(mapping=2, sequence=4, offset=2)
            yaml.dump(data, f)

    def _expand_variables(self, value: Any) -> Any:
        if isinstance(value, str):

            def repl(match):
                var_name = match.group(1)
                return os.getenv(var_name, f"{{{{_UNDEFINED_{var_name}}}}}")

            expanded_value = re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", repl, value)
            return self._to_native_type(expanded_value)
        elif isinstance(value, dict):
            return {k: self._expand_variables(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._expand_variables(v) for v in value]
        else:
            return value

    def _set_nested_value(self, data: Dict, path: str, value: Any):
        keys = re.split(r"\.(?![^\[]*\])", path)
        current_level = data
        for i, key in enumerate(keys[:-1]):
            match = re.match(r"(\w+)\[(\d+)\]", key)
            if match:
                key_name, index = match.groups()
                index = int(index)
                if key_name not in current_level:
                    current_level[key_name] = []
                while len(current_level[key_name]) <= index:
                    current_level[key_name].append({})
                current_level = current_level[key_name][index]
            else:
                if key not in current_level or not isinstance(
                    current_level.get(key), dict
                ):
                    current_level[key] = {}
                current_level = current_level[key]

        last_key = keys[-1]
        match = re.match(r"(\w+)\[(\d+)\]", last_key)
        if match:
            key_name, index = match.groups()
            index = int(index)
            if key_name not in current_level:
                current_level[key_name] = []
            while len(current_level[key_name]) <= index:
                current_level[key_name].append(None)
            current_level[key_name][index] = value
        else:
            current_level[last_key] = value

    def _get_nested_value(self, data: Dict, path: str) -> Any:
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

    def _parse_yaml(self, file_path: str, rules: Dict):
        log(f"  -> Parsing YAML file: {file_path}")
        try:
            data = self._read_yaml(file_path)
        except FileNotFoundError:
            log(f"     File not found, creating a new one.")
            data = {}

        for match, replace_with in rules.items():
            final_value = None
            if replace_with == "DYNAMICALLY_GENERATED_BY_START_HOOK":
                final_value = build_start_command_list()
            else:
                final_value = self._expand_variables(replace_with)

            log(f"     - Setting '{match}' -> '{str(final_value)[:100]}'")
            if ".*." in match:
                prefix, suffix = match.split(".*.")
                if prefix in data and isinstance(data[prefix], dict):
                    for server_key in data[prefix]:
                        nested_path = f"{prefix}.{server_key}.{suffix}"
                        current_val = self._get_nested_value(data, nested_path)
                        if isinstance(final_value, dict) and current_val in final_value:
                            self._set_nested_value(
                                data, nested_path, final_value[current_val]
                            )
            else:
                self._set_nested_value(data, match, final_value)
        self._write_yaml(data, file_path)

    def _parse_properties(self, file_path: str, rules: Dict):
        log(f"  -> Parsing Properties file: {file_path}")
        lines = []
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf8") as f:
                lines = f.readlines()

        processed_keys = set()
        output_lines = []

        for line in lines:
            stripped_line = line.strip()
            if (
                not stripped_line
                or stripped_line.startswith("#")
                or "=" not in stripped_line
            ):
                output_lines.append(line)
                continue

            key = stripped_line.split("=", 1)[0].strip()
            if key in rules:
                final_value = self._expand_variables(rules[key])
                new_line = f"{key}={final_value}\n"
                output_lines.append(new_line)
                log(f"     - Replacing line '{key}' -> '{new_line.strip()}'")
                processed_keys.add(key)
            else:
                output_lines.append(line)

        for key, value in rules.items():
            if key not in processed_keys:
                final_value = self._expand_variables(value)
                new_line = f"{key}={final_value}\n"
                output_lines.append(new_line)
                log(f"     - Adding new line '{new_line.strip()}'")

        with open(file_path, "w", encoding="utf8") as f:
            f.writelines(output_lines)

    def _parse_file(self, file_path: str, rules: Dict):
        log(f"  -> Parsing generic file: {file_path}")
        if not os.path.exists(file_path):
            log(f"     Warning: File '{file_path}' not found, skipping.")
            return

        with open(file_path, "r", encoding="utf8") as f:
            lines = f.readlines()

        output_lines = []
        for line in lines:
            original_line = line
            for match_prefix, replace_line in rules.items():
                if line.strip().startswith(match_prefix):
                    final_line = self._expand_variables(replace_line)
                    line = (
                        final_line if final_line.endswith("\n") else final_line + "\n"
                    )
                    log(
                        f"     - Replacing line: '{original_line.strip()}' -> '{line.strip()}'"
                    )
                    break
            output_lines.append(line)

        with open(file_path, "w", encoding="utf8") as f:
            f.writelines(output_lines)

    def apply_patches(self, phase: str):
        log(f"Applying file modifications for phase '{phase}'")
        phase_config = self.config.get(phase, {})
        files_to_patch = phase_config.get("files", {})

        if not files_to_patch:
            log("No files to patch found in this phase.")
            return

        for file_path, instructions in files_to_patch.items():
            parser_type = instructions.get("parser")
            find_rules = instructions.get("find", {})

            if not parser_type or not find_rules:
                continue

            dir_name = os.path.dirname(file_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            log(f"Processing file: {file_path} (using parser: {parser_type})")

            if parser_type in ["yaml", "yml"]:
                self._parse_yaml(file_path, find_rules)
            elif parser_type == "properties":
                self._parse_properties(file_path, find_rules)
            elif parser_type == "file":
                self._parse_file(file_path, find_rules)
            else:
                log(
                    f"Warning: Unknown parser type '{parser_type}', skipping file '{file_path}'"
                )


def is_first_launch() -> bool:
    if not os.path.exists(INSTALLATION_MARK_FILE):
        log("First launch detected, applying install configuration.")
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

    try:
        with open(MCDR_CONFIG_FILE, "r", encoding="utf8") as f:
            mcdr_config_data = YAML().load(f)
        working_directory = mcdr_config_data.get("working_directory", "server")
        dest_path = os.path.join(working_directory, eula_file)
        if os.path.isdir(working_directory) and not os.path.exists(dest_path):
            log(f"Moving '{eula_file}' to '{dest_path}'")
            shutil.move(eula_file, dest_path)
    except Exception as e:
        log(f"Failed to move EULA file: {e}")


def main():
    if not os.path.samefile(os.getcwd(), WORKING_DIR):
        raise SystemExit(
            f"Error: Working directory {os.getcwd()} does not match expected {WORKING_DIR}"
        )

    patcher = ConfigurationPatcher(CONFIG_FILE)

    if is_first_launch():
        patcher.apply_patches("install")

    patcher.apply_patches("pre_start")

    move_minecraft_eula()

    log("Start hook executed successfully.")


if __name__ == "__main__":
    main()
