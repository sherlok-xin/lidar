# V1-C 精确ROI复盘与B/C对照协议

日期：2026-10-31；状态：已实现复核工具，人工材料真值尚UNKNOWN。ROI命令在宿主机现有Python3.10/numpy/Matplotlib环境执行；ROS1容器负责bag回放和RViz，播放器独立兼容Python3.8且不需numpy。所有命令使用`PYTHONDONTWRITEBYTECODE=1 python3 -B`，新case、缓存、PNG/HTML和结构化文件只写v1c，冻结V1B代码与结果不改。

## 从RViz观察到精确证据

先暂停源帧播放器并记源seq；用RViz XYZ范围或DATA导出的raw_slot字段确定bbox/槽位。固定rslidar相机视角；RViz显示的算法色只作观察线索。执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B opdf_v1/v1c/scripts/review_compare.py \
  --seq 245847 --bbox -7 12 -6 6 -0.8 3.5 \
  --output opdf_v1/v1c/outputs/review_cases/seq245847_case_new
```

默认读取`v1c/samples/continuous30/manifest.json`及`v1c/outputs/v1b_continuous30/frames/`；也可显式传`--manifest`、`--b-results`。slot查询使用`--slots 123 456`或`--slots-file`的JSON整数数组；与bbox同时给出时取交集。bbox边界inclusive。不存在的slot拒绝；明确选择的实际无效槽位可诊断保存但不画假点。显示cap不改变精确导出数量。

来源验收：seq在manifest中必须唯一；NPZ侧JSON的原始消息SHA与双stamp必须匹配该条manifest。不得用相近时间或近邻坐标找到“差不多的帧”。源shape按实际height/width读取，不把padding或缺列当点/已知自由空间。

输出包括：`comparison_case.json`（manifest/NPZ/hash、源定位、ROI、相机）、`B/exact_slots.npz`（所有所选分类及中间特征/理由）、`B/raw_slot_ids.npy`、固定视角`review.png/.html`、`view.json`、`diagnostic_slots.csv`、`comparison.json`和`human_observation.json`。截图是实际xyz三维；任意显示抽样与全部精确点分母分别记录。

## 人工观察不是整区标签

可显式输入：`--reviewer <真实标注者> --confidence <本人0..1自报> --observation <类别>`，类别为：

- `suspected_entity_removed`：疑似实体误删；
- `suspected_aerosol_retained`：疑似颗粒漏滤；
- `entity_evidence_conflict`：实体候选冲突；
- `ground_misclassification`：地面误判；
- `unable_to_confirm`：无法确认。

默认reviewer/confidence/observation均null、PENDING_HUMAN_REVIEW。工具不生成假的reviewer或意见；这些观察类别只描述怀疑，不把整个bbox标E/A/G。`whole_roi_semantic_label`始终null。`--blind`只导出/显示原XYZ/强度/validmask/slot，不嵌入算法答案，并延后输出类别差异；需要看算法解释时另建非盲case，不覆盖原复核。

可选`--point-notes`读取用户实际提供的逐点JSON列表，每条含raw_slot_id、label(E/A/U/G)、reviewer_id、evidence；只允许所选有效、唯一slot。工具记录原文hash与来源，状态为RECORDED_NOT_ADJUDICATED_REFERENCE，不自动转成GT或计算精度。未标注区域仍未知；仅有人类独立核验的有限参考集后，另行决定其范围内的实体保留/颗粒抑制指标，未标注部分继续只报行为。

## B/C精确对照

在同一manifest、同一seq上增加`--c-results <C运行frames目录>`。必须相同原消息hash/双stamp、raw_slot域及顺序、xyz/intensity/validmask；不一致则拒绝，禁止坐标近邻冒充精确GT映射。B/C各保存同一ROI、同一相机、同一确定性显示规则和完整特征。

`exact_slot_changes.npz`保存原slot、B/C label/reason及变化mask；`comparison.json`给E/A/U/G候选数量、转移计数与理由变化。C新增bool suspect mask另计；**suspect不是A或可删除点**，即使suspect增加而label不变，也只能报告额外待审证据。沒有C输入时明确C_NOT_SUPPLIED，不拿复制B的结果假装C。这里所有“差异”均是行为，不是正确率或改进。

已有冻结case可用`--from-case <旧case.json>`复用ROI和camera，**不导入旧材料语义**。本轮三个初始case沿旧middle245847几何范围，保存于`outputs/review_stage2/`：vehicle_structure_candidate、near_ground_rough_vegetation_candidate、aerosol_surface_ambiguity。目录名只是候选选择记号，没有证明是车辆、杂草或气溶胶；人工意见全部待填。实际数量以`evidence/review_stage2_case_creation.json`与每case原slot列表为准。

## 诊断实验与停止条件

先以冻结B的full-frame/ROI特征做光学、扫描、空间、近地/edge/低凸起保护与ground_available门控诊断；报告可用率、单门及联合模式、原slot反例和未知，不用A增加反推真尘。任何反事实关保护/改单阈值须另存配置与运行ID，并标诊断非可部署滤波器。材料未知时，E/U/A颜色与形状均不能作为因果真值。

本工具不会修改算法、训练、自动降阈值或连接车辆。出现新增疑似实体误删、原域不匹配、同步/显示歧义或材料无法确认时保留证据并退回核查，不由程序替人完成裁决。
