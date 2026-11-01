# OPDF-V1-C：ROS1连续回放与证据诊断

V1-B冻结成果保持不变。本目录包含同一真实bag的30连续帧（seq245832–245861，约2.9秒），已预计算的冻结B与两个C诊断变体、原生ROS1调试bag、逐帧播放器、完整原slot证据和待审ROI。C仅增加suspect/conflict诊断，**原E/A/U/G和保留规则不变**；没有监督训练或已证实去尘精度改善。

## 先在你自己的ROS1 RViz中看

以下三个主机终端各先输入`rn`进入现有ros-noetic容器，再执行同一个环境脚本：

```bash
source /home/xin/lidar/opdf_v1/v1c/scripts/ros1_env.sh
```

该脚本只改变当前终端环境：Noetic、127.0.0.1:11321隔离master、日志/GUI配置缓存全部写v1c；关闭Noetic EOL弹窗并采用已实测可用的软件渲染。没有source车辆工程。当前主控测试结束会关闭自己创建的master/节点；以下命令由你重新启动。

**终端A：**

```bash
roscore -p 11321
```

**终端B：**（在RViz启动前设置仿真时间）

```bash
rosparam set /use_sim_time true
rviz -d /home/xin/lidar/opdf_v1/v1c/configs/opdf_debug_ros1.rviz
```

**终端C：**使用包含C附加诊断的390消息bag，初始暂停于seq245847：

```bash
python3 -B /home/xin/lidar/opdf_v1/v1c/scripts/frame_review_ros1.py \
  --index /home/xin/lidar/opdf_v1/v1c/outputs/v1c_uniform_pair/debug_frame_index.json \
  --seq 245847 --clock --rate 3
```

在终端C输入命令后按Enter：

| 命令 | 操作 |
|---|---|
| `play` / `pause` | 连续播放 / 暂停 |
| `n` / `p` | 下一个 / 上一个完整源帧（全部13层同源分组） |
| `seq 245847` | 跳到准确源seq |
| `rate 1` | 每墙钟秒1源帧，便于慢看 |
| `status` | 当前源seq、播放状态 |
| `q` | 结束该播放器 |

播放器保留原header seq/stamp/frame_id，每次源帧全部层按原record时间发`/clock`；多Topic是逻辑分组，**不是网络原子事务**。向后切帧允许clock真实回退，先发不含点的清缓存云，再发目标帧；暂停默认2Hz整组刷新。RViz采用Decay0/Queue1，固定frame为原`rslidar`，没有假TF、外参或补点。`rospy`自动覆盖seq的真实缺陷已用局部消息适配修复，并经实际跨进程完整字节比对。

RViz默认只开RAW intensity。先关闭它，再勾`Classes RGB`查看E青绿/A橙/U紫/G灰。`Entity E`只有E；`Retained E+U`包括未知U，G单独一层。`Optical/Scan/Spatial`是证据热度，不是材料标签（不可用灰色）。`Suspect REVIEW`黄色仅待审，`E weak conflict`白色仅提示实体候选与弱光线索共存；两者默认关闭且不参与删除。A点稀少可只开`Aerosol A`并增大Size(Pixels)。所有派生点都是真实原回波，有raw_slot_id；没有额外Marker假点。

鼠标左键旋转、中键平移、滚轮缩放；使用File→Save Config As保存到v1c新路径固定你的视角。观察错误时先`pause`/`status`记录seq，使用Select工具选择派生层中的点查XYZ/I/raw_slot_id。RAW保持原字段，原来没有raw_slot字段，需用Classes/Entity/Retained等派生层查slot。截图中仍可见Global Status Warn，具体原因未展开认证；真实点云已显示，不能把它说成状态全绿或坐标已标定。

仅查看冻结B的11层时，将`--index`改为：

```text
/home/xin/lidar/opdf_v1/v1c/outputs/v1b_continuous30/debug_frame_index.json
```

## 也可用原生rosbag连续播放

同一时间仅运行一个播放器。结束终端C的frame-review后，在终端C执行：

```bash
rosbag info /home/xin/lidar/opdf_v1/v1c/outputs/v1c_uniform_pair/opdf_debug_ros1.bag
rosbag play --clock --pause -r 0.5 \
  /home/xin/lidar/opdf_v1/v1c/outputs/v1c_uniform_pair/opdf_debug_ros1.bag
```

Space切换暂停，`s`只前进**一条消息**，13Topic时并非一个完整点云帧；精确复盘请用上面的frame-review。rosbag的播放时钟会按播放进度更新，不保证每一tick等于源record；frame-review才逐帧发原record纳秒。bag内原header与record都保持。终止后不启动原ROS工程或车辆节点。

## 从疑似错误定位到完整ROI

以下在**主机Python3.10**运行，容器播放器不依赖这些科学计算库。示例选择seq245847、XYZ范围及B/C对照，输出须为新目录：

```bash
cd /home/xin/lidar/opdf_v1
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR=/home/xin/lidar/opdf_v1/v1c/.cache/matplotlib
python3 v1c/scripts/review_compare.py --seq 245847 \
  --bbox 7 10 1 4 -1 2.5 \
  --c-results v1c/outputs/v1c_uniform_pair/frames \
  --output v1c/outputs/my_review_245847
```

可用`--slots 138364`替代bbox，或`--slots-file`加载精确列表；`--view`复用相机。输出B/C固定视角PNG/交互HTML、完整48/55数组、原slot集合、诊断CSV、变化表及源/配置hash。显示cap只限画图，完整ROI导出和统计不受影响。C分类图相同是预期，新增诊断mask在数组与ROS1附加层中查看。

人工记录允许`--reviewer 姓名 --confidence 0.8 --observation suspected_entity_removed --note '实际观察'`，其他类别见`--help`。没有实际人工输入时均null/PENDING，候选ROI不整区赋GT。`--point-notes`可记录有reviewer/evidence的逐点E/A/U/G笔记，但仍待独立核验；未标点保持未知。`--blind`不嵌入模型答案。

已有三例：[review_v1c/](outputs/review_v1c/)。详见[标注/复盘协议](reports/review_protocol.md)。

## 实验、源码与验收

- [综合交付报告](reports/v1c_experiment.md)、[Stage1数据](reports/stage1_data.md)、[Stage2显示](reports/stage2_visualization.md)、[Stage3门控](reports/stage3_gates.md)、[Stage4候选](reports/stage4_candidate.md)。
- [独立备用QA](reports/qa_backup.md)：原QA线程因用量限制未完成最终报告，备用真实线程独立复核；最终结论以该报告为准，不拿V1-B PASS替代。
- [真实ROS1 RAW截图](evidence/ros1_gui_sequential/rviz_raw.png)、[同视角分类截图](evidence/ros1_gui_sequential/rviz_classified.png)、[黄色Suspect独立实拍](evidence/ros1_gui_suspect/rviz_suspect.png)。此前遮挡/错误窗口截图和初次seq覆写失败均保留，不能拿旧文件名当正确图。
- `outputs/v1b_continuous30/`：原生11层330消息bag，原30帧48数组，分阶段metrics，逐消息验证；`outputs/v1c_uniform_pair/`：13层390消息bag，55数组和附加诊断；`v1c_relative_pair/`是单项消融。
- `outputs/gates_continuous30/`：全帧/3候选ROI、距离/拟合高度/最终类别、单门/联合/保护重叠、每个单变量反事实原slot。所有数均行为统计，没有GT精度。

```bash
cd /home/xin/lidar/opdf_v1
mkdir -p /home/xin/lidar/opdf_v1/v1c/.pytest_tmp
python3 -m pytest -q v1c/tests \
  --basetemp=/home/xin/lidar/opdf_v1/v1c/.pytest_tmp/user_check \
  -o cache_dir=/home/xin/lidar/opdf_v1/v1c/.pytest_cache
python3 v1c/scripts/verify_frozen.py
```

无须再次抽bag或重写已有bag。若重现实验，请在脚本支持的**新目录**运行，不能覆盖交付run。冻结B约716ms/帧仍非10Hz；C约25ms是复用B特征的额外诊断，不能当完整算法加速。预计算、序列化、bag写入/readback及RViz播放计时分别报告；屏幕FPS不是算法FPS。

无独立材料GT，无可靠逐点时间/多回波/Doppler，无已校准相机外参。suspect/A/G后方都不作为自由空间；画面更干净不代表安全通行。本轮至离线诊断/可视化验收停止，不训练、不改生产工程、不上车、不恢复Phase3。
