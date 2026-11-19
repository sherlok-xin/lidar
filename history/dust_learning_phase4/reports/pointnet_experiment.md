# Reduced PointNet++：同预算真实训练与单实体loss消融

2026-11-15。PIPE `PIPE`。完成L2_base、L3_entity两个真实小网络，各8固定epochs/664步，保留最后epoch，不按任何评价结果选择checkpoint或超参。不是完整论文复现、不是大网络/时序网络/部署性能。

## 训练身份与公平边界

共同训练query=63,010：UCHILE38录制各2帧共38,912点；原行人24帧11,810点；跟车来源代理24帧12,288点。本轮源/目标帧选择及time角色先冻结。所有本地结果为既往已观察过的同事件时间块EXPLORATORY；跟车标签是SOURCE_LABEL_PROXY，不因新模型训练提升成独立材料GT。原行人train实际只有6车点、跟车train没有人点，不能虚称实体覆盖充分。

每帧最多4个NN512 context、最多512个唯一合法query；B2与两个网络读取完全相同context/query/源索引。anchor只按合法监督身份hash选取，不按dust/entity类别配比；因此这不是全云标签无关随机抽样，评价只代表固定可标query子集。B2使用同context的冻结16维派生特征，网络输入XYZI及无拟合的block中心/半径和logI变换；同context/query预算不等于相同特征表达或优化难度。

基权重按三个域等loss质量，域内binary平衡。L2权重与L1_follow逐字节hash一致；L3仅本地PERSON/VEHICLE reference1/2乘2再全局均值归一，与L1b_follow权重hash一致。没有第二项置信度/噪声loss变化。两个网络同初始参数SHA、同8轮batch顺序及相同随机调用配方，唯loss系数不同。

优化器Adam lr=.001、weight_decay=.0001、batch2、CPU4线程；每batch loss为sum(global query weight*NLL)/(实际batch块数*固定512容量)，忽略query外点但保留其context。每epoch日志为sum(weight*NLL)/sum(weight)，没有按块或局部query数重新归一。

configs/pointnet_training.json在真正fit前落盘，含源码/数据/权重函数hash、推理随机种子配方及固定8轮。训练过程未计算eval指标用于选epoch。L2完成后通过全部epoch loss/grad/参数finite的预声明数值门，再按授权训练L3；数值门不表示训练收敛、分类有效或风险可接受。

## 实际训练与存档

|网络|参数|初/末epoch加权NLL|训练秒|全context推理秒|峰值RSS MiB|权重SHA256|
|---|---:|---|---:|---:|---:|---|
|L2_base|966690|0.720234 / 0.576723|25.960|3.704|370.1|d1b6b290c82772316a21c4301a840c9bf26685cd418ad8862745af5ba44604e4|
|L3_entity|966690|0.697527 / 0.526544|25.328|3.672|368.6|ecf8911f106b706b24bf405e1b1f05086ff07774f60f449d40863774f1e6917d|

Epoch loss存在波动，不声称单调收敛；没有因此加轮次、改lr或挑更好checkpoint。每个网络输出149,504个完整context行的float64分数（由float32网络概率无损升型），原block顺序与cache_start/end精确一致。重叠context只按cache owner计数；未采样全帧位置没有预测，不能通过坐标NN填满。

网络FPS在eval中也有随机起始，故每个block单独固定`int(SHA256("20261114|pointnet-inference|"+block_id).hexdigest()[:8],16)`再forward。`phase4/pointnet_inference.py`可对任意同身份块重推；L2三个块重复调用和存分数均逐元素相等，L3同三块也完全一致。不能把模型内部feature interpolation冒充外部未采样源点的预测或身份。

## 验证风险门先冻结，评价后报告

|网络|本轮验证策略|最大预算内validation dustR|阈值|
|---|---|---:|---:|
|L2_base|INFEASIBLE_NONTRIVIAL_RECALL|3.158%|None|
|L3_entity|VALIDATION_FEASIBLE_EXPERIMENTAL_ONLY|12.958%|0.8544325828552246|

实际验证支持person1469点/8帧、vehicle4505点/16帧、dust6174点，达到100点/3帧支持门。L2不是支持不足，而是预算内最大Recall3.158%达不到预声明10%，明确INFEASIBLE，不能拿零候选当成功。L3阈值来自本轮local validation，已先写phase4_policy.json才计算eval/test角色指标。1%仅实验预算。

## 固定0.5，共同query域的实际对照

|模型|UCHILE test F1 / AP|行人eval F1 / 人FP|跟车eval F1 / 车FP|
|---|---|---|---|
|L1_follow|0.8667 / 0.9254|0.4642 / 913/4028|0.8783 / 74/3686|
|L1b_follow|0.8396 / 0.8850|0.5874 / 567/4028|0.8972 / 2/3686|
|L2_base|0.4320 / 0.5964|0.3347 / 1583/4028|0.6893 / 1953/3686|
|L3_entity|0.4683 / 0.7511|0.1784 / 3748/4028|0.5444 / 3686/3686|

全部模型在同query域对照，禁止与历史整云/全事件数值直接排高低。当前固定预算下，两个网络未提供相对B2的可验证优势；L3 .5对跟车eval全部3686个来源vehicle点预测dust，为应保留的严重负面行为，不隐藏、不回调测试阈值。该现象不能仅凭关联归因于特定物理材质、BatchNorm、过拟合或某单一机制。

## L3冻结风险门的具体失败

|域|dustR|人FP / 分母|车FP / 分母|
|---|---:|---|---|
|original_pedestrian_dust|25.31%|0/4028|0/0|
|high_speed_following_dust|41.96%|0/0|326/3686|

跟车326/3686=8.844%车抑制，超1%预算；行人评价虽0/4028人抑制，但车辆分母0，无权宣称双方风险认证。UCHILE test上L3风险门dustRecall=0，明确零覆盖，不能称安全收益。无真正物理实例认证，整实例漏失UNAVAILABLE。

## 复核与停止决定

`evidence/pointnet_recheck.json`：两网络相同初始化、相同batch顺序/63,010query身份，权重hash与B2共享函数匹配，冻结代码/缓存hash未漂移；全部149,504分数/模型/cache身份校验通过。`probe_reinference_L2.json`以及L3重推反例记录可复现exact score。该报告为实现者复核，独立QA由另一个真实执行器完成，不伪称已通过。

本分支不再训练更多网络或凭这些eval结果追加epochs。当前不足以支持增大模型或开始时序网络；优先人工核验困难实体/混合边缘、补齐跨事件实体覆盖，再设计独立的后续实验。所有历史输入、源标签和旧Phase3A BLOCKED门保持只读。

## 实际运行命令与保护

```bash
# 已各执行一次；已存在checkpoint会拒绝重训/覆盖：
PYTHONNOUSERSITE=1 $HISTORICAL_ROOT/dust_learning_phase4/.venv/bin/python -s -B $HISTORICAL_ROOT/dust_learning_phase4/scripts/train_pointnet.py L2_base
PYTHONNOUSERSITE=1 $HISTORICAL_ROOT/dust_learning_phase4/.venv/bin/python -s -B $HISTORICAL_ROOT/dust_learning_phase4/scripts/train_pointnet.py L3_entity
# 准确推理接口（CPU venv中）：
# from phase4.pointnet_inference import load_checkpoint,predict_blocks
# predict_blocks(load_checkpoint("L2_base"), blocks, block_ids)
```

统一evaluate_saved在host原评价环境运行；outputs/evaluation/L2_base与L3_entity已有结果会拒绝覆盖。训练CPU环境与B2 host环境版本均有记录，同预算不冒称相同软件栈。
