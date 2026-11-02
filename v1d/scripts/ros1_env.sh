# Source after entering the existing rn container, in each D terminal.
source /opt/ros/noetic/setup.bash
export OPDF_D_ROOT=/home/xin/lidar/opdf_v1/v1d
export ROS_MASTER_URI=http://127.0.0.1:11331
export ROS_IP=127.0.0.1
unset ROS_HOSTNAME
export ROS_HOME="$OPDF_D_ROOT/.ros"
export ROS_LOG_DIR="$OPDF_D_ROOT/evidence/user_ros_logs"
export XDG_CACHE_HOME="$OPDF_D_ROOT/.cache"
export XDG_CONFIG_HOME="$OPDF_D_ROOT/.config"
export XDG_RUNTIME_DIR="$OPDF_D_ROOT/.runtime"
export PYTHONDONTWRITEBYTECODE=1
export DISABLE_ROS1_EOL_WARNINGS=1
export LIBGL_ALWAYS_SOFTWARE=1
mkdir -p "$ROS_HOME" "$ROS_LOG_DIR" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
