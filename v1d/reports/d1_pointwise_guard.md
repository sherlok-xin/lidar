# D1追加：逐点可用性保护的显示对照

2026-11-01，DATA-01。该追加实验响应真实143候选中的逐点scan不可用反例；**原D1报告、源码、30帧76字段、Core/hard/labels及D2输入全部保持不变**。原始143候选仍是有效的簇级诊断记录，不悄改成108。新增仅为更保守的默认查看mask，没有重算localground、重抽bag、改生产占据或材料分类。

## 三种数量不能混称

[独立增量运行](../outputs/d1_pointwise_guard/run_summary.json)：30帧COMPLETE，2.478651s。逐帧delta NPZ仅保存原`raw_slot_id`和三个新bool数组，sidecar用原D1整NPZ SHA、原JSON SHA、seq/header/record关联，不能脱离源D1独立当点云。原source各76字段只读，前后stat一致；写入的delta也逐数组回读一致。

```text
Candidate = 原 d1__low_clutter_mask（143，不变）
Suppressible = Candidate & scan_available & spatial_available & ~原hard
Deferred = Candidate & ~Suppressible
GuardedDisplay = 原NongroundStrict & ~Suppressible
```

|概念|计数|解释|
|---|---:|---|
|原簇级LowClutter Candidate|143|保留原几何提案；不是143个可独立忽略点|
|逐点Suppressible|108|只允许当前调试视图排除；仍不是软草、尘或安全可删标签|
|Deferred|35|证据逐点不够，保留为材料UNKNOWN|
|原Strict|2354709|不变|
|原cluster Display|2354566|不变，作为143簇级基线|
|新Guarded Display|2354601|比旧Display多保留35点；建议用户默认查看此层|

108中原B-G=88、原U=20；35 deferred中原B-G=17、原U=18。这里仍不能报告清草/去尘正确率，或把更多点被隐藏称为进步。即使逐点几何可用，浅硬表面与软杂波也可能混淆，材料风险仍UNKNOWN。

## 真反例已恢复显示

[143点逐项表](../outputs/d1_pointwise_guard/candidate_slots.csv)及[JSON](../outputs/d1_pointwise_guard/candidate_slots.json)记录每个原slot的逐点可用性、原hard、candidate/suppressible/deferred和guarded保留状态。

- seq245846/rawslot84249，header1789629270563782454、record1789629270577751611：scan_available=false、spatial_available=true、原hard=false。原Candidate仍true，新增suppressible=false、deferred=true、guarded_display_retained=true。
- seq245858/rawslot84182，header1789629271763680935、record1789629271778004837：同样因scan不可用deferred并恢复显示。

它们证明修订按逐点证据保留了已发现的反例；不证明这两个点是已确认硬物，也不证明其余108为真低杂波。

## 增量接口与实际检查

入口：[manifest.json](../outputs/d1_pointwise_guard/manifest.json)，其`frames[].path`相对`output_dir`；逐帧sidecar保存`source_d1_npz`与`source_d1_npz_sha256`。展示时应先核对源NPZ hash，再核对delta与源`raw_slot_id`精确一致，仅将新mask作为新查看层；不覆盖原76字段或传给D2作为改动的算法输入。

新增数组：

- `d1__low_clutter_suppressible_mask`
- `d1__low_clutter_deferred_mask`
- `d1__nonground_guarded_display_mask`（建议默认Display）

实现：[run_d1_pointwise_guard.py](../scripts/run_d1_pointwise_guard.py)。实际运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 opdf_v1/v1d/scripts/run_d1_pointwise_guard.py
```

[原日志](../evidence/d1_pointwise_guard_run.log)，stderr为空；没有删除/覆盖原run。新输出目录拒绝覆盖。

[5项实际测试](../evidence/d1_pointwise_guard_tests_final.log)全部通过（.027s）：缺scan、缺spatial、已有hard分别defer；候选分割/源数组不改；非Candidate不新增抑制；错误slot域拒绝；全部真实143点与原证据ledger逐点比对、108/35计数及84249/84182恢复保留。该软件检验不构成人工材料GT。

**D1原版与逐点guard增量分别正式提交。下一步渲染/ROS默认Display接入由MASTER/EVAL执行；DATA在此停止，不做D2。**
