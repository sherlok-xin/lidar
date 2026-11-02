# V1-D 五类候选ROI与盲审协议

日期：2026-11-01；EVAL沿用RESEARCH-03线程。原bag、B/C及既有30帧结果均只读；全部新case、MPL/tmp/pytest缓存在v1d，禁旧pycache。不启动ROS master或GUI、不扩抽bag、不训练。

## 入口与真实来源

已实际生成 `outputs/raw_five_roi/catalog.json`。每例以源seq245847为中心，真实邻帧245846、245848共同显示，使用相同几何bbox、相同相机、原始xyz/intensity，不先展示算法类别。source message SHA、双stamp、manifest/NPZ/侧JSON hash和原slot列表均保存。原slot只在各源帧内标识测量槽位，邻帧相同slot不代表同一物理表面点或刚体对应。

| 候选选区（名称不是确认材料） | bbox `[xmin,xmax,ymin,ymax,zmin,zmax]` | seq846/847/848精确有限点 |
|---|---|---|
| vehicle_structure_candidate | [-7,12,-6,6,-0.8,3.5] | 20660 / 20532 / 20801 |
| near_ground_rough_vegetation_candidate | [3,18,-16,-6,-1.8,-0.5] | 4079 / 4096 / 4074 |
| aerosol_surface_ambiguity | [7,10,1,4,-1,2.5] | 2014 / 2624 / 3441 |
| vehicle_body_edge_candidate | [4,7,-2,2,-0.6,1.6] | 397 / 192 / 183 |
| possible_low_obstacle_unknown | [7,9,5,7,-1.5,-0.9] | 163 / 166 / 163 |

前三例只沿用C的几何bbox/camera；后两例由助手根据RAW有限点位置/高程和起伏选择，属于 **ASSISTANT_GEOMETRIC_CANDIDATE_SELECTION**。新低矮选区不是已识别石块或硬障碍：地面、软杂物、硬物、粒子或混合来源均UNKNOWN。新车边选区也只是贴近旧结构候选的局部边缘假设，车辆身份未确认。不可给整区赋E/A/G。

`blind_raw/`是先打开的盲审入口：`raw_neighbors.png`三帧同视角，以及逐帧真实3D PNG/离线HTML、精确四原始字段NPZ。每例`algorithm_evidence_unblinded/`另存三帧所选全部48个B数组；初始RAW盲审前不要打开此处标签/分数/理由，以免把算法答案当真值。显示最多4000点/帧只影响截图；精确导出和上表分母不受cap影响。所有未知区域/无效槽位不解释为自由空间。

## 可复制命令

在宿主机现有Python3.10/numpy/Matplotlib环境、项目根目录执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B opdf_v1/v1d/scripts/review_d.py \
  --init-five --output opdf_v1/v1d/outputs/raw_five_roi --max-points 4000
```

上述目录本轮已生成，再执行必须用**新的output目录**，工具拒绝覆盖。如建立新选区：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B opdf_v1/v1d/scripts/review_d.py \
  --seq 245847 --bbox 7 9 5 7 -1.5 -0.9 \
  --output opdf_v1/v1d/outputs/new_raw_case
```

默认manifest/frames只读取C已冻结连续30帧。可显式传同源manifest/目录，必须严格匹配原消息SHA、header/record；不通过近邻时间/坐标凑帧。

## 人工输入与未知

当前每例`human_review.json`中reviewer_id/confidence/observation/point_annotations/instance_annotations均null，PENDING_HUMAN_REVIEW；没有真实第二标注者、一致性或精度数据。点或实例可在查看RAW及邻帧后由用户实际提交，未确认材料保持U/unknown。不能自动从ROI名、强度或算法颜色生成参考标签。

结构化导入：`--case <case.json> --import-review <实际用户JSON> --output <新目录>`。JSON须有真实reviewer_id、evidence、匹配的source_message_sha256；point_annotations逐点含raw_slot_id及E/A/U/G，必须是中心帧选区中有效原槽且无重复；instance_annotations含instance_id、evidence、presence_status及可选raw_slot_ids。presence_status区分observed_support、independently_known_no_return、unknown；完全无返回不得虚造E点。confidence仅记录用户实际0..1自报，可为null，不替其生成。

导入只做结构/来源检查，记USER_SUPPLIED_NOT_INDEPENDENTLY_ADJUDICATED，不自动认证GT或计算性能。未标注点保持未知。只有独立依据、复核范围和标签版本另行验收后，才考虑该有限范围的实体保留/粒子抑制指标；当前无此输入，所有效果指标均NOT_COMPUTED。

## D1与D2对照边界

D1渲染入口：`--render-d1 --cases <raw五例目录> --d1-dir <D1frames> --output <新目录>`。读取D1真实原slot mask，五联RAW/GroundCore/LowClutter/NongroundStrict/NongroundDisplay共用一次cap、bbox与view；full_roi_counts用全部有效选中点。GroundCore、LowClutter是诊断集合，不是材料真值或可删除类别。低杂波显示抑制不代表生产占据被清空，ground_available缺失/false也不代表地面。

全量档案入口：`--summarize-d1 --cases <raw五例目录> --d1-dir <D1frames> --output <新目录>`。逐例验证原48数组未变，保存全部D1特征/原slot和B类×Core/Clutter/Strict/Display交叉计数、低物/近地/边缘保护重叠及局部高度可用性；不受截图cap影响。最终实际结果在`outputs/d1_roi_final/`及`outputs/d1_roi_evidence/`，有源NPZ/JSON/消息hash；旧failed_initial预览不验收。

D2入口：`--compare-d2 --case <case.json> --d2-dir <D2frames> --output <新目录>`。拒绝B/D原slot顺序、xyz/intensity/valid或原消息身份不一致，不做NN伪精确匹配。原B和D候选同camera/bbox保存全部点特征与截图，逐原slot输出转移和risk CSV。E→A/U→A只称**候选风险转移**，不是已确认误删；E→U仍在E+U保留集合，不能写成物理点被删除。

任何被D2改写的标准labels/score/available/reason/retain数组，须在`b__同名`准确保留原B；工具会核对，不能只用新label覆盖来源。该检查仅是可追溯合同，不让D标签获得GT身份。

MASTER当前决定D2标签G保留B-G以隔离E/A/U融合；D1 GroundCore是独立地面显示层，数量可能与labels G不同。报告必须分列B_G、D_label_G、D1_GroundCore，不用“地面改进”混称。D2必须经D1_GATE放行后才运行；本工具不会自行启动算法或修改阈值。

ROS1离线bag/新图层由EVAL按MASTER新增授权导出，真实节点/RViz由MASTER负责。D现用隔离127.0.0.1:11331，不连接被占用11321；本执行器不启动或停止任何master。


2026-11-02 D2消费端更新：D输出标准reason_code须使用source `d2_fusion_diagnostics.reason_bits`，不能用继承的B diagnostics/modules；新的case记录d2_config_sha256为heuristic配置，原B配置另记。D2同源RAW/slot/NaN位模式和dtype严格比特核对。D1pointwiseguard显示层须以108 suppressible/35 deferred代替候选143全抑制，原候选不变；未知仍保留。

额外风险盲入口：`outputs/d2_smoke_slot139114_raw_context/blind_raw/raw_neighbors.png`，围绕seq245847原slot139114的±0.3m几何bbox，邻帧846/848同camera。该slot在smoke由B-U变D-A，但材料和物体身份未知；不可将算法A当人工答案。`outputs/d2_smoke_slot139114_comparison`是后打开的全特征/算法对照档案。所有人工字段继续null/PENDING。


最终真实对照已生成：`outputs/d2_final_five_roi`（fusion）、`outputs/d2_final_geometry_five_roi`（同seq245847 geometry_only）、`outputs/d2_final_slot139114_comparison`；完整30帧行为与风险CSV见`outputs/d2_final_full_behavior`。最终seq245847两模式139数组均与smoke逐位一致，证据`evidence/d2_final_smoke_exact_arrays.json`。无真实标签仍不计算性能。
