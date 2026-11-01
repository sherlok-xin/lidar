# V1-C Stage1/2：ROS1按源帧复核与显示规范

日期：2026-10-31；EVAL执行器沿用RESEARCH-03线程。本阶段不改算法。新文件仅在v1c，V1B代码只读；禁bytecode，Matplotlib缓存转到v1c。DATA负责源缓存、冻结V1B连续30帧结果与ROS1调试bag；本执行器只实现播放器、RViz配置和ROI复核。ROS节点、容器与GUI实测由MASTER统一执行，其原始日志未提交前不宣称屏幕成功。

## 可执行入口

- `scripts/frame_review_ros1.py`：不需numpy，仅标准库、rosbag/rospy/PointCloud2/Clock。读取DATA的`debug_frame_index.json`及debug bag，按源seq与精确record纳秒定位，检查所有Topic齐全、header seq/stamp/frame一致后才发布。
- `configs/opdf_debug_ros1.rviz`：ROS1 `rviz/PointCloud2`，Fixed Frame=`rslidar`；RAW强度默认唯一开启，CLASS RGB默认关闭，用户关RAW后再开CLASS；其他层按需开启。所有点云Queue Size1、Decay Time0，不发布假TF，不补额外回波。
- `scripts/review_compare.py`：由manifest+seq定位实际NPZ，bbox/rawslot导出完整原始与中间特征，固定视角截图、可选B/C精确变化；使用冻结旧review_roi只读函数，输出与缓存全部转到v1c。

八主Topic为`/opdf_v1/raw,nonground,class_rgb,entity_only,aerosol_strong,unknown,ground,retained`（完整路径均带`/opdf_v1/`）。`entity_only`只为E，`retained`为E+U，不使用solid一词；optical_rgb/scan_rgb/spatial_rgb仅中间证据热度。E青绿/A橙/U紫/G灰是启发式候选类别，RAW保持原intensity显示，不能把算法颜色解释成材料真值。

## 容器操作（命令给主控/用户，非本报告执行证明）

主机`rn`等价进入`docker exec -it ros-noetic bash`。容器内先设置隔离环境，不能沿用生产master：

```bash
source /opt/ros/noetic/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export ROS_MASTER_URI=http://127.0.0.1:11321
export ROS_IP=127.0.0.1
unset ROS_HOSTNAME
export ROS_LOG_DIR=/home/xin/lidar/opdf_v1/v1c/evidence/ros_logs
export DISABLE_ROS1_EOL_WARNINGS=1
export LIBGL_ALWAYS_SOFTWARE=1
```

仅在该隔离master尚未运行时，在独立终端启动`roscore -p 11321`。本工具强制拒绝11311、非本机地址或写到v1c外的日志目录；不会代为启动ROS。

```bash
python3 -B /home/xin/lidar/opdf_v1/v1c/scripts/frame_review_ros1.py \
  --index /home/xin/lidar/opdf_v1/v1c/outputs/v1b_continuous30/debug_frame_index.json \
  --seq 245847 --clock --rate 10
```

另一个采用相同环境的终端：

```bash
DISABLE_ROS1_EOL_WARNINGS=1 LIBGL_ALWAYS_SOFTWARE=1 rviz -d /home/xin/lidar/opdf_v1/v1c/configs/opdf_debug_ros1.rviz
```

键盘命令均以Enter提交：`n`下一源帧，`p`上一源帧，`seq 245847`跳到索引中的准确seq，`play`自动播放、`pause`暂停、`rate 2`改为2源帧/墙钟秒，`status`打印状态，`q`退出。只在已导出连续窗口内导航，不用rosbag的`s`冒充一次完整源帧推进。rate是播放速度，不代表计算达到实时。

非TTY自动验证接口：

```bash
python3 -B /home/xin/lidar/opdf_v1/v1c/scripts/frame_review_ros1.py \
  --index /home/xin/lidar/opdf_v1/v1c/outputs/v1b_continuous30/debug_frame_index.json \
  --seq 245847 --clock --commands 'show,next,prev,seq:245847,play:0.5,pause,quit' \
  --log /home/xin/lidar/opdf_v1/v1c/evidence/player_scripted_events.jsonl
```

`play:0.5`在0.5墙钟秒内正常自动逐帧播放，其余命令默认间隔0.2墙钟秒，可用`--command-delay`调整。`--selfcheck`只逐帧读bag检查完整Topic与header，不创建ROS节点；`--once --hold-seconds 2`可有界发布当前源帧。

## 同步、向后跳转与缓存的边界

同帧源header与bag record分别保留；`/clock`选择原record纳秒，绝不改header伪造单调时间。每个源帧先完整读取/校验，再在一个逻辑batch中发布所有Topic；事件日志含batch、seq、双stamp及每个Topic header。**ROS1多Topic在网络上不是原子事务**，订阅端应以源seq/header归组；不能把各Topic的任意最新消息拼成一帧。注意以下真实发布回归中发现并已修复的rospy序号自动改写：仅发布前日志不是线缆保持证明。

向后跳转允许clock真实回退，先给每个debug Topic发布使用目标原header的空点云清缓存，再发布实际目标帧；空cloud不含额外回波。配置Decay0/Queue1，加暂停时全帧2Hz墙钟刷新（无latch），使新订阅者得到当前整组而不保留旧帧；`--refresh-hz 0`可关闭。没有用错误stamp或假TF掩盖时间回退。缓存策略已经实现，实际RViz可见清理效果仍须MASTER屏幕验证。若GUI残留，应查Display/时间缓存，不修改原消息时间。

## 本执行器实际测试

实际执行：

```bash
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/home/xin/lidar/opdf_v1/v1c/.cache/matplotlib \
python3 -B -m pytest opdf_v1/v1c/tests/test_review_workflow.py \
  --basetemp=/home/xin/lidar/opdf_v1/v1c/evidence/pytest_review_tmp \
  -o cache_dir=/home/xin/lidar/opdf_v1/v1c/.cache/pytest -q
```

结果**6 passed**：导航原seq/时间不变、生产master拒绝、完整8Topic后才返回帧、RViz层默认不叠加、exact B/C域与附加suspect不改labels、manifest源hash与人工记录空值。测试里的ROS消息是synthetic fixture，不冒充实际ROS发布；真实容器/显示结果以MASTER后续证据为准。`--help`已在实际主机独立运行通过。

真实连续结果seq245847已导出3个待审ROI，目录`outputs/review_stage2/`，明细在`evidence/review_stage2_case_creation.json`。精确点特征和截图是真实NPZ产物；人工意见仍PENDING，材料未确认。协议与后续B/C操作见[review_protocol.md](review_protocol.md)。

## 当前未知与验收限制

没有独立语义GT、实际误停原因或本轮实时计算目标；显示/选择成功不证明去尘有效。MASTER实际ROS1初次发布验证失败记录于`evidence/ros1_actual/summary.json`：预期330个seq/topic组合未匹配，订阅收到的seq为1、2等传输计数，GUI未验证。该失败原件保留。没有安装依赖或修改冻结V1B。Stage2显示工具已交付，算法诊断与改变必须在后续独立阶段记录。

## 实际rospy序列化返修（2026-10-31）

EVAL在现有Noetic容器实读`/opt/ros/noetic/lib/python3/dist-packages/rospy/msg.py`及Publisher调用：`serialize_message`在具体消息类`_has_header=True`时执行`header.seq=publisher计数`；`args_kwds_to_message`则按原MD5匹配保留传入实例。首次检查未source环境而ModuleNotFoundError；source现有Noetic后读取与回归成功，未安装依赖。

播放器现在只在自身局部创建继承原PointCloud2的子类、设`_has_header=False`，使用原生成的serialize、原_type/MD5/slots和原header副本；Publisher仍声明`PointCloud2`。普通发布与清缓存空cloud都经过此适配。没有改rospy全局函数/PointCloud2基类，没有用AnyMsg把Topic类型变成`*`，也没有更改实际Header值。这个类属性仅阻止rospy覆盖seq，原Header仍在原位置序列化。

实际在容器执行（不创建ROS节点）：

```bash
source /opt/ros/noetic/setup.bash
PYTHONDONTWRITEBYTECODE=1 python3 -B /home/xin/lidar/opdf_v1/v1c/tests/test_review_ros1_serialization.py \
  --index /home/xin/lidar/opdf_v1/v1c/outputs/v1b_continuous30/debug_frame_index.json \
  --output /home/xin/lidar/opdf_v1/v1c/evidence/source_header_serialization_check.json
```

结果PASS：真实seq245847的11个Topic，在传输计数987654321下，去掉4B长度前缀的线上序列化字节与原导出bag消息逐字节完全相同；标准PointCloud2反序列化后仍seq245847，原缓存header未改，类型/MD5/字段不变。负对照普通PointCloud2确实被已安装rospy改成seq123，说明测试覆盖了真实缺陷。证据JSON保留实际函数源码、逐Topic长度与hash。该检查证明实际序列化路径，不替代修复后网络订阅/GUI验证；MASTER将以新run_id重新验证全部330组合。播放器CLI不变，旧失败日志不能被新结果覆盖。

## 网络通过与GUI布局返修

MASTER修复后实际独立进程测试记录于`evidence/ros1_actual_fixed/summary.json`：330/330 seq/Topic组合、30完整源帧、4次clock倒退通过，消息字节与导出源一致。真实RViz窗口已打开并截图`rviz_raw.png`，但截图中的ROS1 EOL模态弹窗与大侧栏挡住主要画面，不能将“窗口出现”作为观察体验验收。

本次只改v1c配置：默认仅保留Displays面板；Views/Selection/Time不默认加载（Select工具保留，必要时可从Panels菜单重新打开面板）；图层名缩短到13字符以内。RAW intensity与Classes RGB仍只开前者，Entity E与Retained E+U含义不变。隐藏右dock，保留简短左面板；避免把未经核验的复杂Qt二进制布局写入配置。主控新GUI-only复验以**主渲染至少70%窗口宽度**为目标，修订配置的实际dock比例尚待新截图确认；若窗口仍保留旧侧栏宽度，应拖左dock分隔线至约300px并保存该v1c配置，不能据静态配置宣称70%已达成。

可复制启动命令已加`DISABLE_ROS1_EOL_WARNINGS=1 LIBGL_ALWAYS_SOFTWARE=1`，仅当前RViz子进程生效，不修改系统环境或安装驱动。前者关闭每次EOL模态提示，后者使用现有软件OpenGL；不绕过数据/Topic检查。本执行器没有另启GUI。原失败与首次受遮挡截图保留；新GUI证据与备用独立QA尚未最终完成，不能冒称整体验收PASS。
