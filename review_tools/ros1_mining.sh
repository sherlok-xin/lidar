#!/usr/bin/env bash
set -eo pipefail
tools_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
: "${DERIVED_ROOT:?Set DERIVED_ROOT to the writable derived data tree}"
port="${MINING_REVIEW_PORT:-11483}"
case_dir="${MINING_REVIEW_CASE:-$DERIVED_ROOT/validation/mining_train_view}"
output="${1:?Pass a fresh local output directory}"
source "${ROS_NOETIC_SETUP:-/opt/ros/noetic/setup.bash}"
set -u
export ROS_MASTER_URI="http://127.0.0.1:$port" ROS_IP=127.0.0.1
unset ROS_HOSTNAME
export DISPLAY="${DISPLAY:-:1}" QT_X11_NO_MITSHM=1 LIBGL_ALWAYS_SOFTWARE=1
export DISABLE_ROS1_EOL_WARNINGS=1 PYTHONDONTWRITEBYTECODE=1
scratch="$(mktemp -d -t mining-review-XXXXXXXX)"
export ROS_HOME="$scratch/ros" ROS_LOG_DIR="$scratch/ros/log" XDG_CACHE_HOME="$scratch/cache"
export XDG_CONFIG_HOME="$scratch/config" XDG_RUNTIME_DIR="$scratch/runtime" OGRE_LOG_DIR="$scratch"
mkdir -p "$ROS_LOG_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
opts=()
if test "${MINING_CAPTURE:-1}" = 1; then
    renderer="${RENDER_SOURCE:-$tools_dir/../temporal_open3d_v1/rviz_render.cpp}"
    g++ -shared -fPIC -std=c++14 -I/usr/include/OGRE "$renderer" -o "$scratch/render.so" -lOgreMain
    opts=(--renderer "$scratch/render.so")
fi
python3 -B "$tools_dir/mining_rviz.py" session --port "$port" --case-dir "$case_dir" --out "$output" "${opts[@]}"
