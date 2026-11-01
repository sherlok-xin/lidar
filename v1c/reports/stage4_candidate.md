# Stage4：受控诊断候选版，不改删除决策

2026-10-31，MASTER实施。Stage1真实30帧/原生330消息回读与Stage2跨进程全330组合已通过，实际RViz可显示真实分类；Stage3冻结门控诊断已定位瓶颈后，才运行本附加诊断实验。GUI布局/截图遮挡问题另在最终顺序窗口实测中关闭，不把前期坏截图当最终对照。没有改冻结V1-B、正式A/E阈值或部署。

## 单一改变与消融

两个run同一30帧、4,320,000原slot，全部原48数组逐元素保持：xyz/I/valid/slot、E/A/U/G、两score/availability、reason、E+U及含G保留mask均原样。所有输入、配置快照、代码摘要和源B NPZ SHA在run中。

- `outputs/v1c_relative_pair/`：optical相对弱光、scan断裂、spatial弥散三类中至少两类过冻结门槛，标记有效非G且非A的`aerosol_suspect_mask`。
- `outputs/v1c_uniform_pair/`：**唯一配置差异**为uniform_low_enabled=true。仅把Stage3已经定义的原I≤3、local median≤3、|relative z|≤.1的可用光学数值探针纳入附加光学线索；仍必须再有扫描或空间过门，不能仅因低强度给suspect，更不产生A。

I=3等阈值是明确的调试探针，不是材料阈值或标定反射率，也没有基于GT调参。本轮没有修改多尺度几何或强行实现M4。原分类保持提供可公平追溯的诊断入口；不宣称改进了实际去尘效果。

## OBSERVED：行为差异

| 观测量（点帧单位） | 相对线索版 | 加均匀弱线索版 |
|---|---:|---:|
| 原E/A/U/G | 422220 / 388 / 1939023 / 753703 | 完全相同 |
| 原label/reason/保留mask变化 | 0 | 0 |
| suspect，仅待审 | 76095 | 141066 |
| suspect中的E / U | 1591 / 74504 | 4730 / 136336 |
| suspect中的A/G/INVALID | 0 | 0 |
| suspect且受near/low/edge保护 | 43655 | 55614 |
| E与光学弱线索共存的conflict | 53775 | 119867 |

附加suspect新增64971、移除0，仅显示数值/几何线索共存的区域，不是新增正确尘点。部分E同时满足光学/弥散探针，反映当前PCA表面支持与弥散指标并非材料互斥判据；E保持原样并显式列冲突，不能把它自动翻为A。保护冲突照常保留，不因附加mask越过安全门控。

源函数只返回7个附加数组，根本不返回或修改label/retained。`suspect_reason_code`记录相对弱光、均匀弱数值探针、扫描断裂、空间弥散及near/low/edge/实体冲突位，完整原slot对齐。`aerosol_suspect_available_mask`仅表示附加证据足够计算，不是suspect本身；统计必须按字段名区分。实体冲突层也不等于实体误判真值。

## 真实ROI精确复盘

`outputs/review_v1c/`三个case都以seq245847原始消息SHA与原slot域定位，继承旧ROI/相机而不导入材料真值，B/C截图为同视角，完整48/55数组保存。人类reviewer/confidence/observation仍null，PENDING；不整区伪标。原3D分类图一致正是本实验不改原label的预期，疑似层另在ROS1开关或精确数组中查看。

| 候选ROI | 槽位 | 原E/A/U/G | C suspect | 其中受保护 |
|---|---:|---|---:|---:|
| vehicle_structure_candidate | 20532 | 6463 / 4 / 14065 / 0 | 1018 | 243 |
| near_ground_rough_vegetation_candidate | 4096 | 0 / 0 / 3946 / 150 | 107 | 106 |
| aerosol_surface_ambiguity | 2624 | 544 / 3 / 2077 / 0 | 122 | 42 |

车辆形/杂草/尘表面混合只是候选命名。近地107个suspect中106受保护说明冲突可复查，不证明应取消保护。原slot138364仍是A候选，附近真实材料未知。`comparison.json`、`diagnostic_slots.csv`、`exact_slot_changes.npz`与两侧`exact_slots.npz`可精确查询，显示抽样不改变全量计数。

## ROS1附加层与计时

`outputs/v1c_uniform_pair/opdf_debug_ros1.bag`已在原生Noetic离线生成，631,901,820B，30×13=390消息。原11层330消息的完整序列化内容不变；追加`/opdf_v1/aerosol_suspect`（黄色）及`/opdf_v1/entity_optical_conflict`（白色），只含已有回波的原XYZ/I/slot，不增加伪点。两层默认关闭，不参与retained/A过滤，不与A橙色混称。全部390原生回读验证通过，见`ros1_candidate_validation.json`；实际跨进程回放证据另见最终运行记录，不能把此离线回读当网络或屏幕验证。

相对/均匀版附加compute中位24.54/24.82ms，包含冻结特征门控重构；各自全run约31.19/31.71s含读取和NPZ/JSON输出。两者**复用B特征**，不能与B约716.09ms完整算法compute直接比成加速或实时达标。B读取/算法/序列化、ROS1写入/readback、实际播放均另列计时。本次C bag读构建写1.704s、readback2.606s，均受缓存影响，不是在线帧率。

## UNKNOWN与下一步

无独立点级参考标签，不报Precision/Recall/真实误停车改善。加入suspect仅改善诊断覆盖与可解释性；暗实体、细草、低石、混合表面仍可能被标为待审。下一步最小实验是由实际标注者逐点复核三个冻结ROI及相邻时刻，无法确定者保留U，另采独立事件作留出；不能用当前算法输出给自身当GT。未经下一次授权不扩训练、M4、Phase3或上车。
