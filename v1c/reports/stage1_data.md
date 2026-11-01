# V1-C Stage 1：连续30帧与ROS1调试bag

2026-10-31，DATA-01原线程。**数据、冻结V1-B预计算和ROS1离线bag逐消息校验已完成；RViz屏幕与播放器操作由MASTER/EVAL另行验收，本报告不冒称GUI成功。** 没有启动ROS master/节点、原工程或车辆控制。所有新文件只写`opdf_v1/v1c/`，冻结V1-B只读导入且禁bytecode。

## 1. 候选选择与真实连续输入

唯一原始输入为`/home/xin/lidar/data/2026-09-17-15-14-07_1.bag`。先直接读取本地文件头及最终连接/CHUNK_INFO索引，从中段前/中/后各读一条CompressedImage及少量record header，跳过大点云载荷；实际读297,362B。[预览记录](../evidence/selection_preview/preview_manifest.json)、[before](../evidence/selection_preview/before.jpg)、[center](../evidence/selection_preview/center.jpg)、[after](../evidence/selection_preview/after.jpg)均有原时间/偏移。

执行器实际查看三张上下文：车形物位置变化，近地存在弥散拖尾候选，故选择中段附近连续30帧，而非按算法A数量选区。它们只是**助手选择的车辆/颗粒混合候选**，未由实际人类确认材料，也未将未标定相机投影为点级尘标签。

正式入口：[samples/continuous30/manifest.json](../samples/continuous30/manifest.json)。`frames[].path`相对其`output_dir`解析，各`.ros1msg`有邻接JSON；保留冻结V1-B manifest字段，并采用`seqNNNNNN`键。

|项|实测|
|---|---|
|连续序号|245832–245861，共30帧，逐相邻seq+1|
|原云topic|`/hesai/pandar_points`|
|header时间首/末 ns|1789629269164361477 / 1789629272063874722|
|bag record时间首/末 ns|1789629269180218168 / 1789629272078258562|
|首/末消息绝对偏移B|1072799640 / 1216165134|
|时间范围|约2.900s header跨度，双时间严格递增；不证明硬件同步/精确10Hz|
|实际数据形状|本30帧均80×1800；读取仍按每条实际H/W/stride，不硬编码1800|
|实际原文件读取|148,512,515B，其中chunk载荷148,335,268B，低于160MiB上限|
|单遍抽取耗时|0.455456s，受系统页缓存影响，非冷盘基准|
|原文件前后stat|size/mtime一致，无写入|
|状态|COMPLETE，failures=[]|

预览与抽取的原bag读取合计148,809,877B，未全量解包。缓存随后用于计算/导出，不反复读取原bag。源指纹含本地size、mtime、首64KiB SHA及final index；每条原消息另有SHA、双时间和原偏移。首64KiB摘要不等于全bag完整性证明。这个30帧窗不是30个独立事件，也不形成跨session验证。

实际命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 opdf_v1/v1c/scripts/select_sequence.py --preview-only
PYTHONDONTWRITEBYTECODE=1 python3 opdf_v1/v1c/scripts/select_sequence.py --count 30 \
  --reason 'Read-only assistant inspected three bounded middle-neighborhood camera contexts before/center/after: vehicle-shaped objects change position with low-altitude diffuse trails; select this 30-frame sequence only as an unconfirmed vehicle/particle mixed candidate. No camera-LiDAR point projection or material GT.'
```

命令输出：[预览](../evidence/data_preview_command.json)、[抽取](../evidence/data_sequence_extract.json)。已存在的序列目录会拒绝覆盖。

## 2. 冻结V1-B预计算

[run_summary.json](../outputs/v1b_continuous30/run_summary.json)记录30帧全部状态OK。运行前按`v1b_frozen_baseline.json`核对冻结模块/配置hash；本轮没有修改算法、调阈值、训练或开启M4。

- 输出：`outputs/v1b_continuous30/frames/seq*.npz`及邻接JSON，保留完整原slot、XYZ/I/mask、labels、scores/availability/reasons和所有模块中间量。
- `config_snapshot.yaml`为旧配置原文副本；规范化配置SHA=`6a3f8ee29053b61fdc739602d8fb0b082d51eccd8bb11fc8c3915bdfdc1bc4e1`。
- metadata记录`source_cache_path/source_cache_sha256`及原header/record时间。`input_manifest.json`与`method_sources.json`冻结实际输入和源码来源。
- 行为合计：4,320,000槽；finite3,115,334；INVALID1,204,666；E422,220；A388；U1,939,023；G753,703。这是**算法行为计数，不是真尘/实体正确数或性能提升**。

[metrics.csv](../outputs/v1b_continuous30/metrics.csv)分开计时：缓存读取/解码中位11.28ms、算法compute中位716.09ms、NPZ/JSON保存中位846.02ms；30帧总47.672s。模块compute中位约ground160.63ms、optical176.12ms、geometry358.35ms、decision18.06ms。总计时不是10Hz能力；也不含ROS1导出或RViz播放。

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
  python3 opdf_v1/v1c/scripts/precompute_v1b.py
```

[实际原日志](../evidence/data_precompute.log)，stderr为空。输出目录拒绝覆盖；不更新旧`outputs/latest_run.txt`。

## 3. 真正的ROS1调试bag

实际文件：[opdf_debug_ros1.bag](../outputs/v1b_continuous30/opdf_debug_ros1.bag)，**625,613,107B；30帧×11白名单Topic=330条消息**。使用现有`ros-noetic`容器及`/opt/ros/noetic`的原生rosbag离线写入，未初始化ROS节点。主机`docker exec`经正式工具权限审核执行。

[debug_frame_index.json](../outputs/v1b_continuous30/debug_frame_index.json)提供绝对bag_path、topics及逐帧key/seq/header/record/frame/topics/点数/缓存指纹。**同一源帧全部Topic使用完全相同的原header与record时间**，用于EVAL按帧组装；`rosbag s`只前进消息，不能当一个完整帧。

主8层为`/opdf_v1/{raw,nonground,class_rgb,entity_only,aerosol_strong,unknown,ground,retained}`，附加`optical_rgb/scan_rgb/spatial_rgb`。没有底盘、油门、转向、刹车或其他控制Topic，也不用`solid`混淆E-only和E+U。

- **raw**：原字段、H/W/stride/endian/dense、header.seq/stamp/frame与完整原data保持；原serialized消息整体精确往返，不删除NaN槽或改填充字节。
- **派生**：只包含finite XYZ，height1、实际选中点数W、point_step24；字段x/y/z/intensity FLOAT32 @0/4/8/12，rgb FLOAT32位打包 @16，raw_slot_id UINT32 @20。空类别有0点消息，不补假点。
- **entity_only=E；retained=E+U；ground另层；nonground=有效且非G。** 保留/过滤均不授予自由空间或安全标签。
- RGB位是`0x00RRGGBB`，不是浮点数值。E青绿[0,220,180]、A橙[255,120,0]、U紫[160,80,220]、G灰[140,140,140]。
- 三个Stage2色层保留真实XYZ和slot，仅显示弱光/扫描不连续/空间弥散的score热度，**不是材料标签**。不可用显示灰[100,100,100]，不当0证据；score0蓝至score1红，具体key/availability与色表均在[schema.json](../outputs/v1b_continuous30/schema.json)。完整原因/中间量仍从NPZ按slot查询。

实际离线命令：

```bash
docker exec ros-noetic bash -lc 'source /opt/ros/noetic/setup.bash; export PYTHONDONTWRITEBYTECODE=1; python3 /home/xin/lidar/opdf_v1/v1c/scripts/export_ros1_bag.py'
docker exec ros-noetic bash -lc 'source /opt/ros/noetic/setup.bash; export PYTHONDONTWRITEBYTECODE=1; python3 /home/xin/lidar/opdf_v1/v1c/scripts/validate_ros1_bag.py'
```

容器内（用户已用`rn`进入后）可直接source并运行相同脚本绝对路径；导出拒绝覆盖已有bag。当前已有文件无需再导出。播放器、ROS1 RViz配置及GUI由EVAL/MASTER负责，DATA没有假称其完成。

## 4. 每一条实际消息的回读验证

[ros1_bag_validation.json](../outputs/v1b_continuous30/ros1_bag_validation.json)：**PASS；330/330条验证，failures=[]；4.680501s**。[实际原日志](../evidence/data_ros1_validation.log)，stderr为空。验证是对真正生成的bag执行原生`rosbag.read_messages()`，不是仅构造消息或序列化自检。

- Topic集合精确为11白名单，每个源帧每个Topic恰一条，record匹配，无缺失/重复。
- 每条header seq/stamp/frame和bag记录时间与源manifest/cache核对。
- raw重新序列化后与原缓存**完整字节相等**，并核对全部PointField、H/W/stride/endian/dense。
- 派生独立从原label集合计算预期slot（不调用写入用的`derived_points`），分别验证E-only/E+U/A/U/G/non-ground；原NPZ的XYZ/I/valid/slot也先与原缓存核对。
- 对所有派生点核对x/y/z/intensity字节、packed RGB、slot顺序/范围、完整字段类型/offset/count、点数、步长及flags。颜色期望共享公开schema，但子集和payload读取独立计算。

ROS1离线写入总3.535s；单帧读/解码/NPZ约28ms、构造各层约74ms、rosbag.write约14ms（逐帧原值见[ros1_export_summary.json](../outputs/v1b_continuous30/ros1_export_summary.json)）。这些缓存环境下的写/读时长不是RViz播放FPS、冷盘性能或实时计算证明。

## 5. 回归、失败与保护边界

[sequence测试原日志](../evidence/data_sequence_tests.log)：**9项通过**，包括真实manifest连续性/预算/双时间，以及合成payload的E-only≠E+U、各类别子集、XYZ/I/RGB/slot布局、热度不可用灰、空A层、slot uint32溢出、白名单、写路径边界。合成fixture不充当场景实证。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s opdf_v1/v1c/tests -p 'test_sequence*.py' -v
```

**保留的真实失败：** 首次容器导出在打开bag前，因冻结`cloud_schema.py`的Python3.10风格`dict[str,Any]`注解与容器Python3.8不兼容而失败，见[data_ros1_export.stderr](../evidence/data_ros1_export.stderr)。仅在新`v1c`适配层把冻结IO改为主机路径惰性导入，并用原生ROS1解码进行容器验证，同时兼容Path边界检查；没有修改冻结文件。修订后第二次导出成功，见[attempt2日志](../evidence/data_ros1_export_attempt2.log)。首次没有生成partial bag，也没有把失败当成功。

当前验收限于真实连续数据、冻结算法预计算、感知调试bag与逐消息一致性。没有材料GT、人工确认尘区、独立跨session、生产控制、安全或去尘正确率证据。原bag只读，V1-B配置/模块/旧输出、research_ops和师兄工程均未写；没有安装依赖、改算法或运行生产节点。

**DATA-01 Stage1正式提交并停止。交由MASTER/EVAL完成播放器与GUI，再由QA独立审核。**
