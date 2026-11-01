# OPDF-V1-C 工作契约

2026-10-31，用户附件为本轮授权；所有新产物仅本目录。V1-B原源码/配置/脚本/九帧与报告不改，冻结241条摘要见evidence/v1b_frozen_baseline.json。原bag/师兄工程/research_ops只读，无训练/生产控制/部署。

1. Stage1 DATA：有界索引+缩略预览选择30连续候选帧，samples/continuous30/manifest.json（旧manifest格式、key=seqNNNNNN、双时间/sha/locator），冻结V1-B只读导入处理outputs/v1b_continuous30/frames/*.npz+.json，导出ROS1 bag+逐消息readback。源码/缓存/写bag计时分开。
2. Stage2 EVAL：configs/opdf_debug_ros1.rviz、scripts/frame_review_ros1.py与ROI对照工具。真实ROS1消息、同源帧全topic逻辑分组，不能声称网络原子；原header与record不伪造，倒退时clock/显示刷新有说明与测试。MASTER负责实际隔离master/GUI试验。
3. Stage3 PIPE：冻结48字段门控统计，全帧/ROI/分组/保护重叠与单一反事实，先交可反证证据，不调参数。
4. Stage4 MASTER审Stage3后单独放行。首选附加aerosol_suspect mask且原E/A/U/G不变，不自动抑制、不替代GT，不同时降低多个阈值。比较同一raw_slot域，源/方法/参数hash。
5. QA实现后启动，独立抽验原始来源/逐消息ROS1 bag/clock和倒退/语义/E-only与E+U/新旧回归/标签边界。PASS限离线交付，GUI是否实际打开与观察独立列证据。

DATA所有权：opdf_c/sequence_io.py、select_sequence/precompute_v1b/export_ros1_bag/validate_ros1_bag脚本、test_sequence*、stage1报告。EVAL所有权：frame_review_ros1/review_compare脚本、ROS1 RViz配置、test_review*、stage2/review报告。PIPE所有权：gate_diagnostics/diagnose_gates/test_gates*、stage3报告，Stage4获门槛后新增文件。MASTER其余集成/保护/总结，不互相覆盖。

Debug frame index: outputs/v1b_continuous30/debug_frame_index.json = {bag_path:absolute,topics:[...],frames:[{key,seq,header_stamp_ns,record_stamp_ns,topics:[...]}]}。

ROS1白名单主8topic /opdf_v1/{raw,nonground,class_rgb,entity_only,aerosol_strong,unknown,ground,retained}，中间层 /opdf_v1/{optical_rgb,scan_rgb,spatial_rgb}。raw精确源schema/字节；派生有限点24B x/y/z/intensity/rgb(float32 bitpacked)/raw_slot_id(uint32)，不把INVALID画为真实点。Eonly=E，retained=E+U，G另通道，无solid混称。RGB算法类别与RAWintensity颜色分开。诊断Marker若有是可视增强不是回波。

隔离ROS_MASTER_URI=http://127.0.0.1:11321，ROS_IP=127.0.0.1，ROS_HOSTNAME不设。容器host网络，禁止生产master。先检查端口不占用；所有ROS日志/测试tmp/GUI截图写v1c。容器名称ros-noetic，同路径bind /home/xin/lidar，rn别名docker exec -it ros-noetic bash。新建debug bag拒覆盖，不复制原bag非感知Topic。

OBSERVED/INFERRED/UNKNOWN/PROPOSED分开；选区名/用户观察不自动成GT。每提交源文件+真实命令+原日志+失败/未验。跨模块依赖必须经MASTER转发。最终停止，不扩训练/Phase3/上车。
