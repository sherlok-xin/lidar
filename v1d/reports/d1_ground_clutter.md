# V1-D1：局部地面锚与低杂波显示诊断

2026-11-01，DATA-01原线程。**已实际处理冻结C的30连续帧，并保留全部48个原数组。D1是新增显示分支，原labels/G、占据及生产行为均未改。** 默认Core760,625，LowClutter143；这些数不能解释为真地面、草或尘的正确去除数。D2未由本执行器实现；是否放行由MASTER按实际3D与风险证据决定。

## 输入、源码与接口

仅只读复用`v1c/samples/continuous30`及`v1c/outputs/v1b_continuous30/frames`，seq245832–245861。不再读取/抽取原bag；B/C源码、配置、报告和结果不写。当前基线含本轮前既存文档变动，以`v1d/evidence/frozen_baseline.json`为准，没有修复或覆盖既存文件。bytecode禁写，MPL与临时路径定向D。

- 实现：[ground_clutter.py](../opdf_d/ground_clutter.py)、[run_d1.py](../scripts/run_d1.py)、[d1.yaml](../configs/d1.yaml)。
- 接口：`compute(arrays, metadata, config)->{'arrays':..., 'diagnostics':...}`；metadata接收完整C帧JSON，读取`diagnostics.modules.ground`的可靠性与全局平面。配置使用`config['d1']`。
- 正式输出：[outputs/d1_ground/](../outputs/d1_ground/run_summary.json)。逐帧NPZ/JSON沿用源key/双时间/source_cache_path/hash/原slot；保存`config_snapshot.yaml`、`input_manifest.json`、`method_sources.json`。
- 最终模块SHA256=`739fc0e1bfddba0ed0a0275c32623335417c0631a0b40acbba9dd406a8eb8748`；完整运行源码/配置摘要见[method_sources.json](../outputs/d1_ground/method_sources.json)。本报告补写不改既有30帧结果。

## 局部模型与保守显示规则

1. **可靠全局平面只作锚。** 仅在原`ground__ground_available`范围内估计；全局可靠性失败则Ground Core/Clutter均不可用，所有finite点留在Strict/Display。
2. **真正的局部残差校正。** 在相对锚高度[-.10,+.035]m中取1m格的低分位种子（q=.35、每格至少3点）。以2.5m邻域内至少5个seed-cell、XY跨度/象限覆盖及秩检查，拟合局部残差平面；再做内点/残差MAD、坡度、校正幅度检查。通过才校正每个点的地面高度；否则保留原可靠global锚，不向未覆盖区外推。它不是把原G带全局加宽，也不认证真实地形。
3. **近地簇只作诊断。** 相对局部地面(.035,.55]m内，按XY .30m/Z .08m体素的26邻接组成候选簇；记录高度、横向范围、垂直延展、地面提案邻接及真实双尺度支撑。地面连接是距当前ground-touch提案≤.25m的代理，非已认证的物理接触。支撑为对全部finite点树的.15m/.35m **full-ball数量**，没有复用旧k16截断列表；计数包含查询点自身，不冒称独立回波数。
4. **硬/未知优先保留。** 紧致低凸起、垂直延展、强扫描+空间表面证据、簇几何可用率不足，或above原.035但只有1–3点的稀疏簇都保护。已有逐点强表面证据不被大混合簇稀释，至少保护该点。XYZ/I不能证明软硬，intensity不参与D1材料判定。
5. **LowClutter为保守看图候选。** 默认只允许横向≥1.2m、p95–p05垂直厚度≤.06m、近地基部、ground-touch邻接充分、两尺度支撑充分、簇几何可用率≥.70且无保护冲突的薄簇。核心与eligible-clutter分离，任何保护点不进clutter；`risk_unknown`仍标记非Core的材料未知。

关键新增数组均为完整原slot域：`d1__ground_core_mask/low_clutter_mask/nonground_strict_mask/nonground_display_mask/local_height/ground_available/hard_structure_protect_mask/risk_unknown_mask/reason_code`，另有校正、support、fit MAD、cluster ID/形状/连接/ball-count等。`nonground_strict=finite & ~ground_core`；`nonground_display=strict & ~low_clutter`。无效点从未画成0米点/自由空间；任何新score只表示调试支持，不是概率。

## 实际30帧结果与计时

[run_summary.json](../outputs/d1_ground/run_summary.json)、[metrics.csv](../outputs/d1_ground/metrics.csv)、[原日志](../evidence/d1_run_final.log)：**30帧全部OK，failures=[]**。每帧在保存后重新打开NPZ，按dtype/shape/字节SHA核对全部48个原数组；labels、XYZ/I、valid和raw_slot均不变。

|全30帧行为|点/槽计数|
|---|---:|
|finite XYZ|3,115,334|
|ground_available|2,986,548|
|实际使用局部校正|1,832,962|
|Ground Core|760,625|
|LowClutter显示候选|143|
|Nonground Strict|2,354,709|
|Nonground Display|2,354,566|
|硬结构/未知保护|661,180|
|非Core材料risk_unknown|2,354,709|

旧B-G为753,703，新Core与其重合704,274；49,429个旧G回到Strict，56,351个原非G进入Core，净增加仅6,922。**不可用净数掩盖点身份变化，也不能将新Core称为旧G的严格扩张。** 独立主控复算见`master_d1_identity_delta.json`；本执行器对应[组件与身份变动记录](../evidence/d1_component_counterexamples.json)。

总54.916s；单帧中位：输入读取/哈希92.27ms、D1 compute498.39ms、NPZ/JSON保存1095.66ms、原48数组回读91.51ms。这不是10Hz实现，也不含RViz/ROS导出。实际命令：

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 \
  python3 opdf_v1/v1d/scripts/run_d1.py
```

正式目录拒绝覆盖；本次没有重跑已有30帧来补报告。

## 单变量上界消融、距离与残差

只变`ground_upper_m`，其他局部种子/模型/簇/保护证据固定。实际调用同一阈值函数复用固定特征，不重复拟合；测试已验证与相同上界fresh-compute的mask一致。[upper_ablation.csv](../outputs/d1_ground/upper_ablation.csv)为30×4=120行。

|上界 m|Core|LowClutter|Strict|Display|
|---:|---:|---:|---:|---:|
|.035|758634|143|2356700|2356557|
|.070（预设默认）|760625|143|2354709|2354566|
|.100|761763|143|2353571|2353428|
|.150|763055|143|2352279|2352136|

在固定局部模型与保护条件下，扩大上界影响有限；没有按“清得最多”改默认，也没有把Core更多解释成更准确。

[range_bands.csv](../outputs/d1_ground/range_bands.csv)按原finite分母：

|range m|finite|地面可用|局部校正|Core|Clutter|保护|
|---|---:|---:|---:|---:|---:|---:|
|0–10|1274352|1274352|791846|218730|33|68812|
|10–20|1088837|1088837|773042|331779|110|333545|
|20–40|559652|559652|253881|189442|0|235572|
|40+|192493|63707|14193|20674|0|23251|

[distributions.json](../outputs/d1_ground/distributions.json)保存每帧range/global-height/local-height/校正/seed拟合MAD/Core高度及两尺度计数的p01/p10/p50/p90/p99。各帧局部seed拟合MAD中位数约.00711–.00905m，跨帧中位.00818m；这是拟合seed的残差而非独立地面误差。局部校正分布包含fallback的0值，各帧全可用域p50为−.00816至0m；不能因全域中位0否认局部模型实际使用1,832,962点。Core自身被高度带选中，其高度分布不能当准确率；无独立地面/障碍标签，不报告真去地率。

## 143个候选与必须保留的真实反例

[全部143槽证据](../evidence/d1_candidate143_points.json)逐点记录seq、header/record整数ns、原slot、XYZ/I、源消息SHA/偏移、原B标签、局部/全局高度、校正、簇形状/可用性/理由；材料和human_label均未知/null。

候选只在8帧：245841=7、245843=13、245844=8、245846=51、245849=9、245853=9、245857=11、245858=35。**143中105个原B-G、38个原U，没有原E/A；不能把143称新增清草/去尘成功。**

|真实待审反例|双时间（header / record ns）|观察与风险|
|---|---|---|
|seq245841，slot105813，XYZ≈(-1.101,7.163,-1.316)，原G|1789629270063777685 / 1789629270080312454|global相对高.00709→局部高.04495，校正−.03786m；9点簇厚.01055m、跨度1.26075m。2个强hard点仍保护，其余7候选。它可能是浅地形/硬表面；不能称草。|
|seq245846，slot84249，XYZ≈(-11.769,9.023,-1.289)，原U|1789629270563782454 / 1789629270577751611|local高.08583m；39点簇跨度1.73766m、厚.04942m、contact.87179、簇geometry可用率.71795。**该点scan_available=false**，仍随簇进入显示clutter；簇级可用不等于逐点有软物证据。|
|seq245858，slot84182，XYZ≈(-11.906,8.005,-1.300)，原U|1789629271763680935 / 1789629271778004837|local高.09512m；40点簇跨度1.81940m、厚.05024m、contact.925、簇geometry可用率.70；该点scan也不可用。潜在低硬表面被隐藏风险仍在，risk_unknown=true。|

**默认显示排除不是可删除授权。** 上述逐点证据不足例需人工核验；不能因组件规则通过，就声称已区分草/石/尘。原始点与labels/全特征都保留，Strict视图也保留这些clutter候选。

[组件反例](../evidence/d1_component_counterexamples.json)记录32,012簇，仅9簇达到几何eligible。保护/不满足门控的计数相互重叠：geometry不足28,271簇、厚度超限9,384簇、ground-touch不足21,267簇、多尺度不足28,765簇。大簇可把路面起伏/草/石候选连成十几至几十米范围并整体保守留住，不能靠调阈值保证清草。例seq245832一簇6,270点、跨度25.667m、垂直p95–p05=.25399m、geometry可用率.53174，因垂直/不可用保护而保留；材料未知。

真实稀疏保留例：seq245832 slot178，local高.05709m、簇2点；slot910，高.05955m、簇3点，均hard_protect/risk_unknown/Strict/Display=true。原本“样本不足就未触发hard”会使它们被宽Core吞入；最终版已显式修复。

## 软件反例、真实失败与3D验收边界

[测试最终日志](../evidence/d1_tests_final.log)：**12项实际通过（.230s）**，含低石、细杆、车轮、暗平面、强hard单点不被混合簇稀释、1/2/3点h=.05稀疏低凸起、地面失败/几何不可用全保留、full-ball计数大于15、原数组/无效槽/集合关系与上界消融等价。它们是软件反例，不是实测材料GT。极低凸起（尤其≤原.035 seed带）、未被几何区分的浅硬面或错误global锚仍可能进入Core或显示clutter，测试通过不构成安全保证。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s opdf_v1/v1d/tests -p 'test_d1*.py' -v
```

**真实初次失败保留：** 首帧NPZ已写后，diagnostics中的NumPy bool未转Python bool使strict JSON写入失败，原日志`evidence/d1_run.log/d1_run.stderr`与`outputs/d1_ground_failed_initial/`保留；该半成品不计成功。修正显式bool序列化，并按MASTER稀疏反例增加保护后，新建正式run，未覆盖失败目录。没有按真实候选数量调参数。

EVAL/MASTER已生成真实XYZ五联图；本执行器只读查看了[中帧共同视角图](../outputs/master_d1_gate/seq245847_sets.png)，其[view/count记录](../outputs/master_d1_gate/render.json)明确crop85,522点、显示16,000样本；Core14,873、Clutter0、Strict/Display70,649。此帧Clutter=0不代表全部30帧=0；5panel共用相机/crop/原slot采样，完整计数与显示数分开。此截图不是ROS1 GUI验收，全部材料身份仍未知。其余5ROI实际3D和Gate结论由EVAL/MASTER报告，不由DATA代签。

**D1源码、30真实输出、120行单变量表、143槽反例、测试/失败/计时正式提交并停止。等待MASTER判定阶段门，不自行实现D2或启动ROS/GUI。**
