# Source this inside the existing `rn` / ros-noetic shell, in every terminal.
# Only this shell's environment changes. No production ROS workspace is sourced.
source /opt/ros/noetic/setup.bash
export OPDF_C_ROOT=/home/xin/lidar/opdf_v1/v1c
export ROS_MASTER_URI=http://127.0.0.1:11321
export ROS_IP=127.0.0.1
unset ROS_HOSTNAME
export ROS_HOME="$OPDF_C_ROOT/.ros"
export ROS_LOG_DIR="$OPDF_C_ROOT/evidence/user_ros_logs"
export XDG_CACHE_HOME="$OPDF_C_ROOT/.cache"
export XDG_CONFIG_HOME="$OPDF_C_ROOT/.config"
export XDG_RUNTIME_DIR="$OPDF_C_ROOT/.runtime"
export PYTHONDONTWRITEBYTECODE=1
export DISABLE_ROS1_EOL_WARNINGS=1
export LIBGL_ALWAYS_SOFTWARE=1
mkdir -p "$ROS_HOME" "$ROS_LOG_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
