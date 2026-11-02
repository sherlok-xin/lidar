# V1-D 实际评估与离线可视化交付

日期：2026-11-02。EVAL使用原RESEARCH-03原生线程。全部新输出在v1d；B/C源码、原包和冻结30帧只读，无训练、无参数回调、无新增原bag采样。本执行器没有启动ROS master/节点/GUI。MASTER负责独立11331跨进程消息与RViz验收，QA结论另行提交。

## 已观察结果与解释边界

D1最终30帧、D2 geometry_only/fusion最终30帧及本执行器的完整原slot复核均已完成。最终fusion调试包30×23=690条消息native Noetic逐条精确回读通过；五个固定候选ROI、额外slot139114及真实RAW邻帧入口已生成。没有材料/实体GT，当前Precision/Recall/F1、实体漏检率、实际粒子抑制率、误停车率、安全收益全部NOT_COMPUTED。所有E/A/U/G是算法候选；U可能含实体，A不等于已确认尘点。无效槽位、缺测、地面、unknown都不等于已知自由空间。

## 最终全30精确分母与B-D转移

独立消费端入口`--summarize-d2`实际读取全部manifest帧，缺任一帧则拒绝；没有随机帧丢弃、显示cap或坐标近邻GT匹配。原slot/xyz/intensity/NaN位模式/dtype严格一致，B48被改写的标准决策必须用b__保留并与冻结B逐位核对。完整全部特征由原source NPZ+SHA定位，风险CSV逐行保存原slot/XYZI/新旧label、score/available/reason和源文件SHA。

证据：`outputs/d2_final_full_behavior/run_behavior.json`、`per_frame_behavior.csv`、`candidate_risk_exact_slots.csv`及30份`seq*_exact_changes.npz`；实际命令日志`evidence/d2_final_full_behavior.log`。输入为最终`outputs/d2_candidate/fusion/frames`，D2配置hash为`95fc444a51306857c6ed3297a0fb03502463d0d42774c9420ded481db2cb78d6`。

| 分母/标签候选 | 冻结B | D2 geometry_only | D2 fusion |
|---|---:|---:|---:|
| 原始槽位观测 | 4320000 | 4320000 | 4320000 |
| finite原点观测 | 3115334 | 3115334 | 3115334 |
| invalid槽位 | 1204666 | 1204666 | 1204666 |
| E候选 | 422220 | 374435 | 374435 |
| A候选 | 388 | 386 | 56329 |
| U候选 | 1939023 | 1986810 | 1930867 |
| 标签G | 753703 | 753703 | 753703 |

fusion精确变化108018点帧观测：U→A55943、E→U49929、U→E2144、A→U2、E→A0。原G mask原位不变；D1独立GroundCore760625，与标签G753703分列。E→U仍处于E+U retained集合，是拒判保留，不能称49929个实体点被删除。原U→新A属于候选抑制风险，不能因direct_E_to_A=0推断没有实体漏删。以上不是独立样本数或真/假阳性。

range分箱用原xyz的3D范数；raw_z分箱为传感器坐标，不能称已标定物体高度。每帧候选率及各分母在CSV中，仅作行为诊断，无参考标签则不算性能。

## 最终五ROI与重点反例

RAW盲入口：`outputs/raw_five_roi/catalog.json`，中心seq245847及邻帧245846/245848真实xyz/I，共享bbox/camera；物理对象身份和材料UNKNOWN。前三框沿用旧几何选区；车边和低矮物由助手选区，低矮物不是已确认石块/硬物。人工reviewer/confidence/observation/点与实例标签仍null/PENDING，没有伪造二次标注。

最终对照分别在`outputs/d2_final_five_roi`（fusion）与`outputs/d2_final_geometry_five_roi`。每例B/D保存相同camera、bbox、deterministic raw-slot显示样本的PNG及离线交互3D HTML、全部精确slot特征NPZ、转移和风险CSV。截图cap只影响显示，完整计数不受影响。小ROI192/166等点全部显示。已经实际检视车边及139114局部D图，未把像素外观认证为材料真值。

| 原seq245847候选ROI | finite点 | fusion U→A | geometry_only U→A | 两模式E→U | fusion全标签变化 |
|---|---:|---:|---:|---:|---:|
| 车形结构候选 | 20532 | 721 | 0 | 955 | 1705 |
| 近地粗糙/杂草候选 | 4096 | 0 | 0 | 0 | 0 |
| 颗粒/表面歧义 | 2624 | 127 | 0 | 303 | 430 |
| 车体边缘候选 | 192 | 1 | 0 | 7 | 8 |
| 可能低矮物UNKNOWN | 166 | 0 | 0 | 0 | 0 |

这五例均无E→A。车形区域新A721是需要人工复核的实际候选风险；原U可能是实体，保护规则零违规不能认证安全。geometry_only是同源单帧对照，表中精确ROI计数不是把全30效果外推。`evidence/d2_final_smoke_exact_arrays.json`确认两模式最终seq245847均139数组逐位和smoke一致，连NPZ SHA也相同；最终fusion源SHA=`f4bbda656811563cd97060b77814fd8cfd17fa66fc714dcc73bdc6ea3e7985b3`。本轮未重算或修改模型。

重点slot139114：真实xyz=[6.71716880798,1.88279950619,0.00121125847]m，I=4，B-U→D-A，score_a≈0.282932（启发证据非概率），reason33536=NEW_VOLUME|OPTICAL_RELATIVE_CUE|U_TO_A_CANDIDATE。三尺度r=[.12,.24,.48]m、邻居[21,93,252]、样本[21,93,96]，大尺度采样比例.381、approximation=true；volume_support=[false,true,true]、hard plane/line/any-scale=false；relative_z=-1、weak≈.667、relative cue=true、uniform cue=false；D1 local_height≈1.445m，原low/near/edge/D1hard均false。因此它满足新U→A机制，但其真实材料/实体身份仍UNKNOWN。

`outputs/d2_smoke_slot139114_raw_context/blind_raw/raw_neighbors.png`及逐帧HTML提供±0.3m邻域的三帧RAW盲图；此入口为同一个冻结RAW来源，文件名smoke不代表新取数据。邻帧同slot不证明同一物理点。最终未盲对照/全139特征JSON/NPZ在`outputs/d2_final_slot139114_comparison`，159点局部中U→A3、E→U12。小框不整体赋E/A，混合邻域/车边结构是假设，不将候选误抑制风险写成已确认误删。

## D1显示集合及逐点保护

最终D1五联图：`outputs/d1_final_preview/seq245832_d1_sets.png`与`outputs/d1_roi_final/*/d1_sets.png`；全部D1/B ROI特征与交叉计数：`outputs/d1_roi_evidence`。原始48数组及labels未变。GroundCore、LowClutter、Strict、Display是诊断集合，不是材料标签或生产占据。

D1 finite3115334，Core760625，Strict2354709，HardProtect661180；候选clutter143。原D1候选Display2354566是strict−143的历史诊断，最终ROS显示已采用独立pointwise guard：143=108 suppressible+35 deferred，guarded display2354601；candidate143原mask不变，35延期保留。五个固定ROI没有clutter；低矮物ROI有37个原B-U进入GroundCore，属于需要人工复核的地面划分风险，不是已确认37个实体点损失。

loader实际读取带d1__前缀的增量3数组，核source D1 NPZ SHA/JSON SHA、消息SHA、原slot和双时间戳；显式缺文件/错键/错SHA报错。sup/deferred必须划分原候选，display=strict−sup；sup要求逐点scan/spatial/ground可用且无HardProtect。未提供guard时明确GUARD_UNAVAILABLE_NO_SUPPRESSION，显示strict不抑制，禁止直接抑制143。seq245846/84249及245858/84182继续保留，有真实缓存回归。`evidence/guard_full30_ros_layer_preflight.json`实际30帧构造/源核对PASS，108/35一致。

## ROS1离线导出及命名空间

源文件：`opdf_d/ros_layers.py`、`scripts/export_debug_ros1.py`。只读复用冻结C sequence_io的derived_points/FIELDS/PALETTE/STAGE2，兼容容器Noetic Python3.8，不导入旧FrameData。C7必须与冻结`v1c_uniform_pair`同seq/消息/slot域逐位相符，D2已有C7也必须比对，不在D新label域重算旧证据。B48也与冻结C原域比特一致。旧optical/scan/spatial热层属于冻结B；新D证据变化层单独命名。

实际最终命令（已完成）：

```bash
docker exec ros-noetic bash -c 'source /opt/ros/noetic/setup.bash && PYTHONDONTWRITEBYTECODE=1 python3 -B /home/xin/lidar/opdf_v1/v1d/scripts/export_debug_ros1.py --run /home/xin/lidar/opdf_v1/v1d/outputs/d2_candidate --mode fusion --guard-dir /home/xin/lidar/opdf_v1/v1d/outputs/d1_pointwise_guard/frames --d1-source-run /home/xin/lidar/opdf_v1/v1d/outputs/d1_ground' > opdf_v1/v1d/evidence/ros1_export_final30.log 2>&1
```

最终bag：`outputs/d2_candidate/fusion/opdf_debug_ros1.bag`，871514588 bytes；index/schema/native_readback/export_execution/summary同目录。690/690逐条native readback整条serialized payload SHA、原seq/frame/header stamp/record stamp、fields/flags/stride/点数均精确；整条payload覆盖所有派生XYZ/I/RGB位模式与raw_slot。RAW精确保留原32B点含invalid/padding与原4字段；派生只用实际有效原点，24B xyz/I/rgbfloat32bits/raw_slot uint32，不造回波/TF/控制消息。写前也独立按原slot核XYZ/I位模式和原finite mask。耗时23.658s是离线构造/写入/读回，不是实时频率。

23层：原8主层（raw/nonground/class_rgb/entity_only/aerosol_strong/unknown/ground/retained）、原B三热层、冻结C两层suspect/conflict、D十层（ground_core/low_clutter_candidate/nonground_strict/nonground_display_only/b_entity/b_aerosol/entity_evidence_change/aerosol_evidence_change/hard_structure_protect/low_risk_unknown）。E-only≠E+U retained。D变化层为label xor或共同可用score差±.1，仅debug阈值不是校准概率/安全门槛；E→U是保留。多topic是同帧逻辑组，不是ROS网络原子传输。

消费端覆盖新D输出reason_definitions：标准reason_code只用d2_fusion_diagnostics.reason_bits；b__reason_code及原特征归B命名空间。D/case.json heuristic_config_sha256指实际d2_config_sha256，base B hash另存。source side中继承B/D1 diagnostics/modules/original_labels_unchanged不可解读为新D2决策说明。源run未改，原B regress_case不等于D2回归。

本执行器未启动任何ROS节点/GUI；真实690跨进程pubsub、clock倒退、RViz新图层由MASTER接续独立验证。11321是用户现有环境不能碰；D隔离11331。离线readback不是RViz成功或车辆控制认证。

## 测试、失败记录和未知

`evidence/eval_export_final_tests.log`实际13 passed：原slot/数据域、blind无标签、人工输入真实来源、D2 b__留存及reason/config命名空间、完整分母/缺帧拒绝、缺guard零抑制、两处真实deferred保留等合同。测试不产生物理GT。中间eval_export_ready_tests的1项失败是synthetic manifest fixture漏key，补齐合同后重跑，失败日志保留。

此前小包`ros1_export_smoke3`69消息及`ros1_export_d2_smoke1`23消息保留作阶段证据；最新最终690包的export_execution.json记录实际argv/当前源码hash/manifest hash。旧D1 failed_initial及preview不作最终验收。

PIPE实际D2 run_summary为1009.04s，shared_multiscale中位28849.44ms/帧、fusion27.29ms、serialize2359.46ms，shared features每源帧只算一次供两模式复用；这不是10Hz实时或包含RViz/控制的端到端时延。没有独立GT、标定认证或现场车控实验，不能声称学习/部署或安全效果。当前已交离线EVAL材料，最终阶段结论待ROOT独立ROS/GUI及QA审核。
