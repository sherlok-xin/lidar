# D2：真实多尺度几何与融合候选实验

日期：2026-11-02；PIPE/ALGO原线程。D1_GATE由MASTER于2026-11-01 18:59明确放行，11-02恢复后完成测试与实际运行。**交付状态：13项受控反例、真实单帧成本、30帧geometry-only/fusion及单参数uniform-off消融全部COMPLETE；全30交叉源/硬不变量检查通过。** 真实ROI三维和最终QA由主控/RESEARCH另行验收，本执行器不冒称已代做。

本实验不是恢复原ROS生产B1。原bag、师兄工程、research_ops、B/C源码/配置/报告/结果均只读；所有新增实现/配置/日志/输出仅`v1d/`。不训练、不使用Doppler/真实逐点time/return、不运行ROS或车辆控制、不启动D3。没有独立材料GT，不报告准确率、真实去尘率、误停车改善或部署安全。

## 1. 已实现的新算法与冻结参数

新增实现为`opdf_d/multiscale.py`、`fusion.py`和`scripts/run_d2.py`；预先冻结配置`configs/d2.yaml`。单帧试跑和正式30帧使用相同配置hash：`95fc444a51306857c6ed3297a0fb03502463d0d42774c9420ded481db2cb78d6`，没有按A数量再调阈值。

### 真多尺度，非重复同一组k近邻

三个半径为`clip(k*range,rmin,rmax)`：k=.012/.024/.048，最小.12/.24/.48m，最大.45/.90/1.80m。支撑树包含所有有限原始XYZ；查询点仅B非G有效点，B-G保持分类并明确标为未查询，不伪造其几何availability。

每原查询点、每尺度分别计算**真实radius-ball观测邻居数**（排除自点，重复XYZ仍属于原观测数）；超过4096收集预算明确oversaturated/unavailable。拟合采样cap为64/96/96，先覆盖有支撑的八象限×内外径向壳分区，保留各区远支撑，再按原rawslot顺序分散取样。不是三个大半径均使用相同最近15点。

完整观测数与拟合样本数分开保存。`unique_support_count`仅指实际拟合样本的不同XYZ数，**不是完整球邻域去重计数**。`feature_approximation_mask`表明PCA使用截断采样；此版未用查询下采样/NN传播特征，所有查询仍绑定其原点身份。有效支撑半径、采样比例和预算拒判均保存。

PCA分别导出linearity、planarity、isotropy=λ0/λ2、scattering=3λ0/Σλ，保留m²特征值。法向只有平面特征间隔足够时才可用，线轴只有线特征间隔足够才可用；线的任意法向不会拿来判跨尺度变化。平面RMS=√λ0、线RMS=√(λ0+λ1)，是样本到质心拟合结构的RMS，不是真实物体残差GT。

硬面/线至少有两尺度可靠支持且相应轴abs(dot)≥.94。存储的一致性分数是**存在的最一致可靠尺度对**，不是三尺度都相同的证明。任一尺度可靠局部硬结构也单独阻止新增A，避免大尺度混合覆盖小尺度实体。

volume候选需至少两尺度（含large）的各向同性/最小特征值支持、至少6象限、两径向壳、至少3个软件phase支撑；新增A额外要求三尺度全部可用。软件phase来自原slot%H，只是冻结布局的多行支撑，不认证厂家物理束号或独立脉冲。

### 两个消融共享同一份特征

- **geometry_only**：可靠多尺度实体结构+冻结扫描实体支撑可把原U给为新E；原E如与可靠体积冲突且无稳定跨尺度硬结构，可E→U保留拒判；不会直接E→A，也不新增A。
- **fusion**：在同一几何处理上，仅对**原B的U**加入多尺度volume+光学辅助的新增A候选。光学是冻结相对弱线索，或已在C明确的I≤3、局部median≤3、|relative_intensity_z|≤.1（无量纲强度相对量，非空间坐标z）的均匀弱数值cue。它们同源且都不是材料真值。新假设明确**以多尺度volume替代旧scan断裂AND**，没有偷偷降低原B三阈值。

两版共用原low/near/edge+D1 hard_structure保护并集，新增A不能越过任何一项。任何原A遇保护/任一可靠新硬结构时，两版统一回收U；未触发的新证据缺失不自动证明旧A或旧E错误。此版保留**B原G**以隔离M3/M5变化，D1 GroundCore/LowClutter仍独立显示，不能把D1Core当D2材料G。D1曾有37个可能低硬候选入Core的材料风险没有被此选择“解决”。

标准labels/score/availability/reason/retained指D候选，对应B原值另存`b__同名`。原其余48字段和D1辅助字段不改，所有rawslot、XYZ/I与来源双时间保持。原C7辅助数组在交换D标签前，以原B48和冻结C函数计算，语义仍是**旧C诊断域**，不是由D新标签重新解释。

## 2. 实际命令、日志与受控反例

所有命令工作目录均为`/home/xin/lidar/opdf_v1`，使用`PYTHONDONTWRITEBYTECODE=1`避免向冻结目录写pycache，BLAS/OMP各2线程。

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s v1d/tests -p 'test_d2*.py' -v

OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
  python3 v1d/scripts/run_d2.py --seq 245847 \
  --output v1d/outputs/d2_smoke_20261102

OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
  python3 v1d/scripts/run_d2.py --output v1d/outputs/d2_candidate
```

13个合成/门控反例检查通过（2.342s），原日志`evidence/d2_tests_20261102.log`。前次12项日志`d2_tests.log`也保留，没有覆盖。本轮没有失败测试后靠追A调参的过程。

| 已执行合成反例 | 实际接受观察 | 证据边界 |
|---|---|---|
| 均匀暗平面 | 有稳定硬面、新E>0、新A=0 | 构造平面，不代表真实暗车准确率 |
| 暗轮胎几何环面/曲面 | 新A=0 | 几何轮胎反例，不是实测车轮标签 |
| 暗相交面交界+原edge保护 | 交界保护区域新A=0，实际几何函数可用 | 原edge保护为构造已知输入，不证明所有真实边缘都会被B捕获 |
| 细杆直线 | 线轴可靠、法向不可用且NaN、新A=0 | 不把法向不唯一误作体积非刚体 |
| 密集三维体积群 | 球邻域数随尺度变、覆盖半径增长、截断标志真实；fusion可新A，geometry_only新A=0 | 合成体积不等于真实尘，有新A不证明有效去尘 |
| 无光学辅助的同体积群 | 新A=0 | 多尺度几何不单独授权A |
| 原E体积冲突 | E→U存在，E→A=0 | 拒判保留，不称原E已证错误 |
| 每种old low/near/edge/D1hard保护 | 各自新A=0；保护原A在两版相同回收U | 硬约束测试，不证明保护本身是GT |
| 低石高度/low-clutter候选 | near/low保护阻止新增A | clutter候选不授予删除 |
| 全B-G与D1Core不一致 | B-G保持，D1Core不偷改材料G | 隔离D1与D2作用，未解决原G语义风险 |
| 超球邻域预算、空/NaN/重复点 | 明确不可用，无伪点/新A | 不可用不当free/不存在障碍 |
| 确定性/输入保护 | 重算特征一致，原输入数组未修改 | 软件行为保证，不是语义正确保证 |

## 3. 实际单帧成本与可用性

源为D1 `seq245847`（144000槽、104479有效XYZ），真实source NPZ SHA已记录在各输出JSON，未再次读原bag。run `outputs/d2_smoke_20261102/` COMPLETE，总34.736s；多尺度特征29.501s、两版融合约27ms/版、序列化约2.43s/版；算法特征、读取、C辅助、融合、序列化、回读独立计时，不能把融合27ms当整算法实时帧率。

| 项目 | small | medium | large |
|---|---:|---:|---:|
| 有效特征点数（B非G查询84503） | 39926 | 71292 | 81954 |
| 完整球观测数P50（全部查询域） | 7 | 27 | 100 |
| 拟合样本数P50（各自可用域） | 19 | 41 | 96 |
| 有效支撑半径P50（各自可用域，m） | .1195 | .2400 | .4889 |
| over-budget不可用 | 0 | 0 | 0 |

三个尺度全部可用39886；volume候选12028。这些数字支持“实际查询不同空间尺度”，不是物体材料认证。完整统计来自独立读取NPZ后的`evidence/d2_smoke_independent_counts_20261102.json`，各列分母如表注明，不把不同可用子域的分位数混作同一批点。

| seq245847行为 | B | geometry_only | fusion |
|---|---:|---:|---:|
| E | 14037 | 12220 | 12220 |
| A | 11 | 11 | 1755 |
| U | 70455 | 72272 | 70528 |
| G | 19976 | 19976 | 19976 |
| 原U→新E | — | 65 | 65 |
| 原E→U | — | 1882 | 1882 |
| 原U→新A | — | 0 | 1744 |

fusion新A1744中均匀弱cue905、相对弱cue839；仅717与原C suspect重叠，原C suspect4275仍保持旧诊断域，**不是把suspect都转A**。所有保护新A、原E直A、B-G变化、INVALID变化违例均0。

代表slot仅供精确复盘：新A开头47/127/234/287/299/367/376/379，E→U开头207/214/238/281/361/475/616/665。完整差异表保存每帧`*_changes.npz`，含rawslot、前后类和新reason；这些不是确认尘或误分类名单。

### 五个真实候选ROI的全量行为（seq245847）

独立按冻结坐标窗复算，未使用显示cap：

| 候选ROI（不是对象/材料GT） | 有效槽位 | fusion新增A | E→U | 说明 |
|---|---:|---:|---:|---|
| vehicle_structure_candidate | 20532 | 721 | 955 | 原U转A未证明真尘，车形区域必须逐点核验 |
| near_ground_rough_vegetation_candidate | 4096 | 0 | 0 | B材料类完全保持，D1Core312另列 |
| aerosol_surface_ambiguity | 2624 | 127 | 303 | “aerosol”仅候选命名，不确认实际气溶胶 |
| vehicle_body_edge_candidate | 192 | 1 | 7 | 新A rawslot139114，是优先反证点 |
| possible_low_obstacle_unknown | 166 | 0 | 0 | D材料G0保持，D1Core37风险仍另列 |

rawslot139114的XYZ≈(6.717169,1.882800,.001211)m、I=4，由B-U→D-A；四个既有保护mask均false，未违反mask约束，但**这不证明真实实体边缘安全**。球邻居21/93/252、拟合21/93/96、三尺度可用；medium/large各向同性/弥散等通过，small弥散.3549未过，硬线/面均未通过；相对弱光cue成立、uniform cue不成立。它展示“现有边缘mask未覆盖、两尺度volume+光学赋A”的具体风险机制，真实材质UNKNOWN，不能据此确认误删或正确删尘。未因此改参数。

详细证据`evidence/d2_smoke_five_roi_counts_20261102.json`和`d2_smoke_representative_slots_20261102.json`；独立核对D1非decision字段、b__备份、同seq既存冻结C55的七aux全部精确一致，见`d2_smoke_crosssource_validation_20261102.json`。

## 4. 文件与元数据消费约定

正式run父目录 `outputs/d2_candidate/` 中同一特征每帧计算一次，分别写`geometry_only/frames/seqNNNNNN.npz+.json`与`fusion/frames/...`；每mode均有config_snapshot/input_manifest/method_sources/run_summary，父目录另有共享特征计时、转移矩阵、各尺度分布和完整日志。

`*_changes.npz`是差异证据，不是一个额外点云帧；EVAL/ROS应按input_manifest列出的seq读正式帧，不把changes文件当输入帧计数。保存的139数组含原D1、C7、新几何、b__备份和标准D字段。

每帧JSON保留B/D1来源metadata与原`diagnostics`，D2真实计数/理由/版本在`d2_multiscale_diagnostics`、`d2_fusion_diagnostics`，D2配置hash单列`d2_config_sha256`。**不能把继承的`diagnostics.modules.decision`旧B计数当D计数**；标准NPZ labels明确为D候选，原B见b__，C7诊断仍旧C域。

## 5. 已知限制与风险

- 均匀暗实体也可触发光学cue；密集细碎几何、交叉小枝、粗糙物、薄壳采样不足都可能呈多尺度体积分布。合成反例不能替代真实ROI审查或材料GT。
- 稀疏小尺度不可用会阻止新A；极密邻域超预算也不可用。未获得证据不能解释成没有尘或障碍。
- 采样cap64/96/96会改变协方差。记录真实ball数、实际样本/覆盖/截断标志；没有假装对所有邻域点做完整PCA。
- 新E也只是结构候选；原E→U的保留拒判不等于原E已证假。原G固定保留包含旧地面潜在误吞风险，D1Core是另一个显示层。
- 使用旧B edge保护只能保证不越过已有mask，不保证所有真实实体边缘都曾被保护；新A需要真实3D和精确ROI逐点复盘。
- 本版真正多尺度约29.5s/样本帧，没有10Hz实时性保证；不以A增加或图像变干净作为改进。

## 6. 正式30帧运行状态更新

正式run `outputs/d2_candidate/`已COMPLETE，30帧seq245832–245861、60个mode输出，原日志`evidence/d2_continuous30_20261102.log`及run内`actual.log`。全run1009.041s，包含一次/帧共享特征和双输出；没有在配额恢复后重算邻域。

| 全30行为（点帧，非材料GT） | 冻结B | D2 geometry_only | D2 fusion |
|---|---:|---:|---:|
| 总槽位 | 4320000 | 4320000 | 4320000 |
| 有限XYZ | 3115334 | 3115334 | 3115334 |
| INVALID | 1204666 | 1204666 | 1204666 |
| E | 422220 | 374435 | 374435 |
| A | 388 | 386 | 56329 |
| U | 1939023 | 1986810 | 1930867 |
| G | 753703 | 753703 | 753703 |
| B-U→新E | — | 2144 | 2144 |
| B-E→U | — | 49929 | 49929 |
| B-U→新A | — | 0 | 55943 |
| B-A→U | — | 2 | 2 |

两个回收候选A的精确记录为seq245841/rawslot140130与seq245844/rawslot89543，均A→U、D reason8736（包括D1硬保护、光学线索与回收位），不是已证实纠错。完整原slot转移在`transitions.json`和各mode每帧`*_changes.npz`，没有把E先变U再在同次变A。

B非G查询域2,361,631点帧；小/中/大可用1,197,802 /1,998,365 /2,282,276，三尺度全可用1,196,712；volume候选334,368。三个尺度均无真实超4096预算事件，但合成超预算路径已经测试。见`evidence/d2_full30_feature_recall_summary_20261102.json`；availability只表示计算支撑，不代表材料可辨。

正式run计时中位数：读取/原字段hash133.97ms、旧C辅助24.13ms、共享多尺度28849.44ms、融合27.29ms、每mode序列化2359.46ms、B备份/slot回读13.26ms。源码内部树/球计数/采样/PCA/跨尺度细分均在每帧`d2_multiscale_diagnostics.timings_ms`，不得把融合毫秒数当完整实时性能。

## 7. 已授权的单项光学消融：只关uniform cue

主控追加授权后，新增独立脚本`scripts/run_d2_uniform_ablation.py`和独立run `outputs/d2_uniform_off_ablation/`，原D2源码/config/run不改。每帧读已存ms特征、以`b__`恢复九个B标准字段，再调用同一fusion；**不重算多尺度、不重读bag**。

实际命令：

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 \
  python3 v1d/scripts/run_d2_uniform_ablation.py
```

实际COMPLETE：30帧，总26.714s（包含全30交叉源验收），日志`evidence/d2_uniform_off_20261102.log`。语义配置差逐键核验只有`d2.uniform_low_enabled: true→false`；新配置hash `7e4a8a673983d8254a3fa6e3c2b51e38d0c4041da3b75af96e3205a3a00acfb2`。脚本/source SHA、原NPZ SHA、双时间/原source metadata、配置快照和每帧增量标签/reason保留；原大特征仍引用源NPZ，没有重复复制或暗中改写。

| 全30行为 | uniform-on fusion | uniform-off唯一参数消融 |
|---|---:|---:|
| E | 374435 | 374435 |
| A | 56329 | 21277 |
| U | 1930867 | 1965919 |
| G | 753703 | 753703 |
| INVALID | 1204666 | 1204666 |
| 相比B新增A | 55943 | 20891 |
| 相比uniform-on新增/消失A | — | 0 /35052 |

这是35,052个候选A恢复U的可复现行为，不是“减少35,052个误检”或“漏掉35,052个真尘”。原E/G/INVALID均不变，没有据此挑最优参数。

五个冻结候选坐标窗在30帧的A行为（点帧，不是跟踪同一对象）分别为：vehicle_structure 15438→8191、near_ground 0→0、aerosol_ambiguity 1770→1288、vehicle_body_edge 424→224、possible_low_obstacle 0→0。seq245847相应为725→461、0→0、130→127、1→1、0→0。**边缘风险rawslot139114关uniform后仍是A**，因为它由相对弱光cue支持；此消融没有消除此具体风险，也不证明uniform-off更安全。

完整`roi_counts.csv`、30个`changes/seq*.npz`及`frames/seq*.npz`增量标准字段都在新run；`evidence/d2_uniform_off_parameter_roi_check_20261102.json`独立核对唯一配置差与ROI汇总。

## 8. 全30交叉源验收与正式提交

新增消融脚本同时对30帧逐项独立核查：

- 实际D1源文件SHA与D2逐帧记录一致；原B48内容hash（标准九字段从b__恢复）与D1保存的原hash一致；原slot=arange(N)、有效mask=XYZ有限性。
- D1所有非decision字段与两版本来源一致；同seq既存冻结C55中的七辅助数组与D2保存C7精确hash一致，两个mode间也一致。
- geometry-only/fusion保存的多尺度特征完全一致；geometry-only无新增A；两个mode B-G身份一致，B标准九字段备份一致。
- fusion新A全部来自原U，原low/near/edge+D1hard保护新A=0，E直A=0，B-G变化=0，INVALID变化=0。60条正式metrics独立求和亦均0违例。
- 当前D2 multiscale/fusion/runner/config与原C suspect源码SHA仍匹配正式run`method_sources.json`；30个原D2 fusion NPZ在消融前后SHA不变。

逐帧结果见`outputs/d2_uniform_off_ablation/source_verification.json`及run_summary，不仅依赖最初runner的内置assert。原D2源码hash：multiscale=`b7f936f32dd7f71ce003bc97020907ed87f644bdfafa14e7994a47bf7c6bb80c`；fusion=`d3f117d5899d7bd40444e2e1a3d4676a8a21aefcae1fcb8a947190a1e76bcae8`。这些校验认证来源/不变量，不认证尘或实体的真实语义。

至此正式提交并停止：不再扩样本、修改冻结参数或追A数量。等待主控独立3D/QA和D2_GATE；D3配准可行性、M4和ROS均未由本执行器启动。
