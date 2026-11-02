# D2设计与接口提案：多尺度几何和受控融合

日期：2026-11-01；PIPE/ALGO原线程。状态：**DESIGN_ONLY / WAIT_D1_GATE**。本次仅只读冻结B几何/判决源码、C Stage3/4报告与suspect边界，没有实现D2、计算D2真实特征、修改冻结阈值或把候选ROI当GT。所有新写入仅本`v1d/`设计文件；D2实现与运行必须等待MASTER对D1真实3D验收后明确放行。

## 1. 不重复基础审计的设计依据

- 冻结`opdf/geometry.py:118-155`：空间支撑以同一个自适应半径、最多16个kNN（排除自点后最多15）计算；`surface_score=max(linearity,planarity)`。因此细长结构和局部面都可能为E提供同一标量支撑。大半径若仍使用相同k近邻，可能反复得到同一批点，不能称真正多尺度。
- 冻结`opdf/decision.py:35-62`：E由扫描连续+空间支撑决定；A需光学、扫描断裂、空间弥散并行通过，且不能有near/low/edge/实体支持冲突。D2不修改此文件，也不靠同时降低旧门槛改变B。
- C `reports/stage3_gates.md`记录30帧3,115,334有限点帧观测，三门交集1,607、最终A388；均匀弱数值探针273,322点帧未过相对光学门。它们是门控行为，不是尘真值。
- C `reports/stage4_candidate.md`只新增待审mask，原E/A/U/G不变。D2须真正新增几何与融合判决，不能把141,066个suspect直接翻成A。suspect不是D2真值或独立证据来源。

## 2. 输入输出接口，先与D1统一

建议新文件（尚未实现，按现`v1d/CONTRACT.md`统一为`opdf_d/multiscale.py`、`fusion.py`）：

```python
# 只允许v1d/opdf_d/中实现；不会导入后改写B/C对象
multiscale.compute(frame, ground_d1, config) -> {
    'arrays': dict[str, ndarray], 'diagnostics': JSONdict}

fusion.fuse(frame, baseline_arrays, d1_result, multiscale_result,
            config, *, ablation='geometry_only'|'fusion') -> {
    'arrays': dict[str, ndarray], 'diagnostics': JSONdict}
```

`frame`只作冻结输入的只读视图，集成端可直接从D1完整arrays/meta提供，不要求再次解码bag或重新运行B。所有输出按实际H×W原raw_slot_id对齐，原xyz/intensity/valid/时间、source message SHA、映射版本不变。输入仅冻结30帧seq245832–245861及其真实缓存。`baseline_arrays`是冻结B的48数组，C附加suspect可并排展示但不作为类别或拟合目标。现D1契约明确原labels和48字段不改，D1只追加几何显示层，**没有D1材料新标签或low_clutter新枚举**。

**MASTER已确认的D1公共字段（以下替代早期建议名）：**

| 语义 | 建议array键 | 要求 |
|---|---|---|
| 局部地面估计可用 | `d1__ground_available` bool(N) | 缺支撑false，不能把未知高度设成0 |
| 到局部地面的高度 | `d1__local_height` float(N) | 约定垂直/法向高度及米单位；不可用NaN |
| D1地面 | `d1__ground_core_mask` bool(N) | 不是自由空间/材料真值；D2候选G暂不由此改写 |
| 新硬结构/风险未知 | `d1__hard_structure_protect_mask`,`d1__risk_unknown_mask` bool(N) | D1硬结构阻止新A；风险未知不授予删除 |
| B低物/近地/边缘硬保护 | 原48键`ground__low_object_mask`,`ground__near_ground_mask`,`geometry__edge_protect_mask` | 分别保留审计位，D2不能绕过任一 |
| 低层粗糙/杂波候选 | `d1__low_clutter_mask` bool(N) | 只作几何/高度候选，不自动等于尘或可删除 |
| 严格/显示非地面 | `d1__nonground_strict_mask`,`d1__nonground_display_mask` | 展示层，与正式retained不混用 |
| 原材料标签/D1理由 | 原`labels/reason_code`，追加`d1__reason_code` | D1不改原类；D2将原类保存在b__后再返回新候选 |

集成时任何实际命名差异通过显式adapter处理；不能静默把冻结B单平面height当D1局部height使用。硬保护并集至少含原B low/near/edge和D1硬结构。MASTER已决定先**保留B原G作为D2候选G**，隔离M3/M5变化；D1 GroundCore/LowClutter仅独立展示与保护参考。这一选择必须在正式D2报告显式列出，不能把GroundCore图层变化冒称材料G改变。

### 新几何输出

所有尺度数组第二维固定为3，尺度按small/medium/large排列，不以“哪个有利”动态挑尺度。

| 键/形状 | 内容 |
|---|---|
| `ms_radius_m` (N,3) | 每点每尺度实际请求半径 |
| `ms_full_neighbor_count` (N,3) | 半径内真实有限邻居数，排除自点；不能用拟合采样数冒充密度 |
| `ms_unique_support_count`,`ms_sample_count` (N,3) | 去重支撑和实际拟合样本数，区分重复坐标与有效几何 |
| `ms_available`,`ms_oversaturated`,`ms_degenerate` (N,3) | 样本不足/超预算/协方差退化明确不可用 |
| `ms_effective_support_radius_m`,`ms_sampling_fraction` (N,3) | 实际样本覆盖和截断比例；证明三个尺度没有偷偷用同一最近15点 |
| `ms_eigenvalues` (N,3,3) | 升序λ0≤λ1≤λ2；保留原m²数值及可选λ/r²诊断 |
| `ms_linearity`,`ms_planarity`,`ms_isotropy`,`ms_scattering` (N,3) | 线、面和体积分开，不再只保留max(linearity,planarity) |
| `ms_normal`,`ms_line_axis` (N,3,3) | 每尺度法向/线轴；各有availability，线状协方差不产生任意“可靠法向” |
| `ms_plane_residual_m`,`ms_line_residual_m` (N,3) | 邻域点到拟合平面/轴的残差，定义和分位数明确 |
| `ms_octant_occupancy`,`ms_radial_shell_coverage`,`ms_phase_support` (N,3) | 三维分布、径向覆盖与软件phase支持；phase不认证物理束号 |
| `normal_consistency`,`line_axis_consistency` (N) | 跨可靠尺度的abs(dot)，避免符号翻转；无可靠对则NaN/不可用 |
| `hard_surface_support`,`hard_line_support`,`volume_candidate`,`geometry_conflict` (N) | 融合需要的解释位，不是材料GT |
| `ms_reason_code` (N) | 不可用、采样/退化、线面/体积冲突来源 |

建议半径族形式为`r_s=clip(k_s*range,rmin_s,rmax_s)`。**候选初始参数仅供D1_GATE后的实现预注册讨论**：k=[.012,.024,.048]，rmin=[.12,.24,.48]m，rmax=[.45,.90,1.80]m；不改B的.014/.18/.90，也不宣称这组最优。可靠最小样本量/特征门槛与预算需在实现前冻结到新D2配置，不能根据候选ROI类别结果挑参。

## 3. 真正多尺度计算与可用性

1. 仅对原有限XYZ建只读KDTree，支撑域默认all finite；D1 ground/low信息记录邻居构成，不通过删输入悄悄改变raw点分母。每尺度查真实radius-ball计数，排除自点与几何重复退化；真实邻居数与采样数分别存。
2. 有界批次查询（例如128/256个query），确定性的空间/径向覆盖采样，而不是只拿相同最近k点；每尺度分别检查有效半径与径向覆盖。最大尺度要实际读取更大支撑，不能用相同局部点重复三遍。
3. 超高密度先获得计数，超过可收集预算时明确oversaturated/unavailable，避免一次生成N×巨大邻域；不得随机少取几点就声称可靠体积。拟合采样上限可按尺度64/96/128作为候选预算，MASTER建议优先64/96控制成本；最终由冻结配置注明。若全点查询成本过高，可用确定体素代表/查询下采样，但每原slot必须保留来源、available和approximation标记；空间近邻只可传播明确近似特征，不能冒充原点身份对应或精确标签。优先保留每原点真实ball计数，采样仅影响拟合支撑。
4. PCA同时保存线/面/体积特征。法向可靠要求λ1−λ0有充分特征间隔，线轴可靠要求λ2−λ1间隔；单线的法向平面本来不唯一，不能用任意小特征值特征向量做跨尺度法向变化。
5. 跨尺度法向/线轴比较用符号无关的abs(dot)，同时检查残差、样本量、尺度覆盖和支撑维数。体积支持需多个尺度的三维扩展/非零最小特征值、分区占据、径向壳覆盖共同成立；一个各向同性分数不充分。
6. 稀疏、重复、退化、单phase不足或尺度支撑几乎相同则不可用/冲突，保留U或D1原保护。新几何的统计可用性不代表独立物理证据或尘材料认证。

## 4. 两个受控判决版本

**共同硬约束：** INVALID和B原G保持；D1 GroundCore独立展示；所有原low/near/edge及D1硬结构保护点不得新增A；缺可靠地面参照或多尺度可用性不足不新增A。保留原点，不补点/改坐标/伪造time、Doppler、return或回波。任何变化都写新D标签，不修改B/C/D1输出。标准labels/score/available/reason/retain改指D候选前，原值分别保存`b__同名`；新证据全部`d2__`前缀。

### Geometry-only

共享同一多尺度特征，只使用几何更新实体支撑与拒判：可靠跨尺度面/线支撑可支持E；B/D1的E如与可靠多尺度体积证据冲突、又缺硬面/线支撑，可E→U，属于保留拒判而非删除。该消融不因几何体积单独新增A，体积候选单列。缺特征本身不能作为“实体已被证伪”；失去可用性最多标U/未决，且记录降级原因。

已有A是否因新硬实体/保护冲突转U，必须统一在此版和fusion版实施，作为“撤销旧删除候选”的安全回收，不能只在某版做有利比较。实现前由MASTER冻结该行为。

### Fusion candidate

只在geometry-only上追加多类证据一致的候选判决：

- 硬面/硬线支持优先；明确几何冲突保持U。**不直接把E转A**；E与材料/体积线索冲突先拒判U。
- 新A来源默认仅B保留下来的U：多个可靠尺度（至少含large）的各向同性/体积分区支持、没有任一可靠尺度的硬面/线支撑，加光学辅助线索及可审阅的扫描/三维分布支持；仍满足全部原low/near/edge和D1硬结构保护。D1 clutter不能被当可删除入口。
- 光学辅助允许冻结B相对弱线索或另列的均匀弱数值cue；两者同源，不当两份独立证据。均匀暗面、暗车轮也可能满足cue；没有新体积/无硬表面反证则不新增A。
- 不强制把C suspect当候选入口、标签或成功目标；可以输出`C_suspect_overlap`仅作诊断，所有suspect都转A是明确禁止的实现。
- 新E/A/U/G变化是算法候选行为，没有GT时不称识别改进、正确删尘或安全提升。

这两个版本共享完全相同输入和多尺度特征，差别只有光学辅助参与A融合；不得同时更改旧门槛、地面模型或观察ROI再给“对照”。

## 5. 比较与交付要求

分别保留B、C附加层、D1、D2 geometry-only、D2 fusion。按原raw_slot输出逐帧转移矩阵、所有新增/消失E与A的精确slot、之前/之后标签及独立原因；同坐标跨帧不是同一个对象GT。low/near/edge覆盖点新增A必须0，INVALID与源点字节/来源hash不能变。

每帧/同一ROI分别统计真实邻居数、拟合样本数、有效半径、每尺度availability/退化/超预算、面线体积支撑/冲突、G/low/near/edge重叠，不能仅报A增加。真实30帧范围冻结，不新读其他bag，不新增训练；复用缓存也不冒称独立事件泛化。

计时分开：读取、树构建、真实邻域查找/计数、采样/PCA、跨尺度一致性、fusion、序列化/可视。geometry-only/fusion复用特征时，不能把fusion增量耗时与B全compute比成加速。实时10Hz无本轮保证。

## 6. 受控反例设计（未运行）

| 构造/真实候选ROI | 可证伪要求与边界 |
|---|---|
| 合成均匀暗平面/暗曲面 | 光学弱但跨尺度面支持，不能新A；有硬支撑可E，否则U |
| 合成深度边缘/相交平面 | 小尺度面与大尺度混合不能被误判体积尘；原edge保护严格有效 |
| 合成密集三维体积群 | 在各尺度充分样本/体积分区支持、光学辅助且无保护时，fusion可新增A；geometry-only仅体积候选，不假称该合成形状证明真实尘有效性 |
| 合成稀疏体积/重复点/同一最近邻尺度 | unavailable或冲突，不能因空缺/退化推出A；证实不是三次相同kNN |
| 合成低石/凸台/低植被 | 使用D1真实高度/保护，新增A为0；G误吞问题仍由D1及人工ROI审核，D2不能把G=free |
| 合成细杆/线束 | 可靠线轴而法向不唯一；不能以法向跳变制造体积尘，应E/U保留 |
| 合成车轮/圆柱/轮胎暗面 | 小尺度可靠局部曲面可保护，大尺度各向同性或法向转动不能单独给A；暗强度不推材料 |
| NaN/Inf、empty、实际缩宽、coverage洞、非升角phase | 原索引/有效性保持，特征不可用原因明确，不补观测 |
| 真实vehicle/near_ground/aerosol ambiguity三旧ROI和30帧中相应坐标窗 | 同视角精确slot差异，候选命名非GT；新A逐点回放审查，low物/E边缘不因A多被当成功 |

上述是未来测试的接受条件，没有在本次设计阶段运行，不能写成PASS。需要的材料参考标签仍缺；后续报告只能区分合成反例检验、真实点级行为和未知语义。

## 7. 停止点

D1_GATE未收到。当前交付为设计提案与接口沟通，不生成D2模块/配置/运行结果，不提前调参。公共字段/保持原G/保护并集已依据MASTER更新，仍须MASTER完成D1真实3D验收后明确下发D2实现范围。
