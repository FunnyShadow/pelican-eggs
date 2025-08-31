#!/bin/bash
# shellcheck disable=SC1091

set -e

cd /home/container

echo "--- Environment Info ---"
echo "Java version: $(java -version 2>&1 | awk -F '\"' '/version/ {print $2}')"
echo "Python version: $(python3 -V)"
echo "------------------------"

python3 /start_hook.py

cd server || { echo "错误: 'server' 目录创建或进入失败, 无法继续。" >&2; exit 1; }

parse_memory() {
    local mem_val=${JAVA_MEMORY:-1024M}
    mem_val=$(echo "${mem_val}" | tr -d '[:space:]')
    mem_val=$(echo "${mem_val}" | tr '[:lower:]' '[:upper:]')

    if [[ "$mem_val" =~ ^[0-9]+$ ]]; then
        echo "-Xmx${mem_val}M"
    elif [[ "$mem_val" =~ ^[0-9]+[GM]$ ]]; then
        echo "-Xmx${mem_val}"
    else
        echo "警告: JAVA_MEMORY ('${JAVA_MEMORY}') 格式无法识别, 使用默认值 -Xmx1024M" >&2
        echo "-Xmx1024M"
    fi
}
MEMORY_FLAG=$(parse_memory)

unset MCDR_CMD_PART_EXEC MCDR_CMD_PART_JVM MCDR_CMD_PART_MAIN MCDR_CMD_PART_ARGS

if [[ "${MCDR_HANDLER}" == "forge_handler" ]]; then
    echo "[Entrypoint] 检测到 Forge Handler，正在生成 Forge/NeoForge 启动参数..."
    if [ ! -f "../forge_versions.txt" ]; then echo "[Entrypoint] 错误: 未找到 forge_versions.txt 文件" >&2; exit 1; fi
    source ../forge_versions.txt
    if [[ -z "${MC_VERSION}" || "${MC_VERSION}" == "<你的 MC 版本>" || -z "${FORGE_VERSION}" || "${FORGE_VERSION}" == "<你的 (Neo)Forge 版本>" ]]; then
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
        echo "[Entrypoint] 错误: 请先在 forge_versions.txt 中填写正确的版本号" >&2
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
        exit 1
    fi
    ARGS_FILE="libraries/net/minecraftforge/forge/${MC_VERSION}-${FORGE_VERSION}/unix_args.txt"
    if [ ! -f "${ARGS_FILE}" ]; then ARGS_FILE="libraries/net/neoforged/neoforge/${MC_VERSION}-${FORGE_VERSION}/unix_args.txt"; fi
    if [ ! -f "${ARGS_FILE}" ]; then
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
        echo "[Entrypoint] 错误: 未找到 unix_args.txt 文件" >&2
        echo "请确认版本号正确且服务端已完整安装" >&2
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
        exit 1
    fi
    echo "[Entrypoint] 使用参数文件: ${ARGS_FILE}"
    export MCDR_CMD_PART_EXEC="java"
    export MCDR_CMD_PART_JVM="@${ARGS_FILE}"
    export MCDR_CMD_PART_ARGS="--nogui"
else
    echo "[Entrypoint] 使用标准模式启动..."
    if [ -z "${SERVER_JARFILE}" ]; then echo "[Entrypoint] 错误: 环境变量 SERVER_JARFILE 未设置" >&2; exit 1; fi
    
    export MCDR_CMD_PART_EXEC="java"
    export MCDR_CMD_PART_MAIN="-jar ${SERVER_JARFILE}"

    if [[ "${MCDR_HANDLER}" == "velocity_handler" || "${MCDR_HANDLER}" == "bungeecord_handler" || "${MCDR_HANDLER}" == "waterfall_handler" ]]; then
        export MCDR_CMD_PART_JVM="-Xms128M ${MEMORY_FLAG}"
        export MCDR_CMD_PART_ARGS=""
    else
        export MCDR_CMD_PART_JVM="${MEMORY_FLAG} @../args.txt"
        export MCDR_CMD_PART_ARGS="--nogui"
    fi
fi

cd /home/container

STARTUP_CMD=$(echo "${STARTUP}" | sed -e 's/{{/${/g' -e 's/}}/}/g')
STARTUP_EXPANDED=$(eval echo "\"$STARTUP_CMD\"")
echo ":/home/container$ ${STARTUP_EXPANDED}"
eval "${STARTUP_EXPANDED}"