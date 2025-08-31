#!/bin/bash
# shellcheck disable=SC1091

set -euo pipefail

readonly WORKING_DIR="/home/container"
readonly MCDR_INSTALL_MARK_FILE="${WORKING_DIR}/.mcdr_installed"

log() {
    echo "[Entrypoint] $*"
}

error_exit() {
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "[Entrypoint] 错误: $*" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    exit 1
}


initialize_mcdr_if_needed() {
    if [ ! -f "${MCDR_INSTALL_MARK_FILE}" ]; then
        log "检测到首次启动, 正在初始化 MCDReforged..."
        python3 -m mcdreforged init
        touch "${MCDR_INSTALL_MARK_FILE}"
        log "初始化完成"
    fi
}

generate_server_command_parts() {
    unset MCDR_CMD_PART_EXEC MCDR_CMD_PART_JVM MCDR_CMD_PART_MAIN MCDR_CMD_PART_ARGS

    local mem_val=${JAVA_MEMORY:-1024M}
    mem_val=$(echo "${mem_val}" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')

    local memory_flag
    if [[ "$mem_val" =~ ^[0-9]+$ ]]; then
        memory_flag="-Xmx${mem_val}M"
    elif [[ "$mem_val" =~ ^[0-9]+[GM]$ ]]; then
        memory_flag="-Xmx${mem_val}"
    else
        log "警告: JAVA_MEMORY ('${JAVA_MEMORY}') 格式无法识别, 使用默认值 -Xmx1024M"
        memory_flag="-Xmx1024M"
    fi

    if [[ "${MCDR_HANDLER}" == "forge_handler" ]]; then
        log "检测到 Forge Handler, 正在生成 Forge/NeoForge 启动参数..."
        if [ ! -f "../forge_versions.txt" ]; then error_exit "未找到 forge_versions.txt 文件"; fi
        source ../forge_versions.txt

        if [[ -z "${MC_VERSION:-}" || "${MC_VERSION}" == "<你的 MC 版本>" || -z "${FORGE_VERSION:-}" || "${FORGE_VERSION}" == "<你的 (Neo)Forge 版本>" ]]; then
            error_exit "请先在 forge_versions.txt 中填写正确的版本号"
        fi

        local args_file="libraries/net/minecraftforge/forge/${MC_VERSION}-${FORGE_VERSION}/unix_args.txt"
        if [ ! -f "${args_file}" ]; then args_file="libraries/net/neoforged/neoforge/${MC_VERSION}-${FORGE_VERSION}/unix_args.txt"; fi
        if [ ! -f "${args_file}" ]; then
            error_exit "未找到 unix_args.txt 文件, 请确认版本号正确且服务端已完整安装"
        fi

        log "使用参数文件: ${args_file}"
        export MCDR_CMD_PART_EXEC="java"
        export MCDR_CMD_PART_JVM="@${args_file}"
        export MCDR_CMD_PART_ARGS="--nogui"
    else
        log "使用标准模式启动..."
        if [ -z "${SERVER_JARFILE:-}" ]; then error_exit "环境变量 SERVER_JARFILE 未设置"; fi
        
        export MCDR_CMD_PART_EXEC="java"
        export MCDR_CMD_PART_MAIN="-jar ${SERVER_JARFILE}"

        if [[ "${MCDR_HANDLER}" == "velocity_handler" || "${MCDR_HANDLER}" == "bungeecord_handler" || "${MCDR_HANDLER}" == "waterfall_handler" ]]; then
            export MCDR_CMD_PART_JVM="-Xms128M ${memory_flag}"
            export MCDR_CMD_PART_ARGS=""
        else
            export MCDR_CMD_PART_JVM="${memory_flag} @../args.txt"
            export MCDR_CMD_PART_ARGS="--nogui"
        fi
    fi
    log "服务端命令参数已生成"
}

main() {
    cd "${WORKING_DIR}"

    log "--- 环境信息 ---"
    log "Java 版本: $(java -version 2>&1 | awk -F '\"' '/version/ {print $2}')"
    log "Python 版本: $(python3 -V)"
    log "------------------------"

    initialize_mcdr_if_needed

    cd server || error_exit "'server' 目录创建或进入失败, 无法继续"
    generate_server_command_parts
    
    cd "${WORKING_DIR}"
    
    log "执行 Python 启动挂钩以应用配置..."
    python3 /start_hook.py

    local startup_cmd
    startup_cmd=$(echo "${STARTUP}" | sed -e 's/{{/${/g' -e 's/}}/}/g')
    
    log "执行启动命令: ${startup_cmd}"
    eval "${startup_cmd}"
}

main