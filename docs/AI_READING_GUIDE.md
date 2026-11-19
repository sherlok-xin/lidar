# 建议阅读顺序

1. [项目状态](PROJECT_STATE.md) 与[完整实验报告](../temporal_open3d_v1/reports/temporal_experiment.md)：先分清排序增益、固定阈值误删、验证风险门不可用这三件事。
2. [历史数据协议](../temporal_open3d_v1/reports/dataset_protocol.md)、[本轮数据源](DATASETS.md)、[标签映射](LABEL_MAPPING.md)：检查设备、处理域和证据等级。历史清单是冻结实验，本轮数据入口并未给历史模型增加 DustX 训练数据。
3. 对照 [temporal.py](../temporal_open3d_v1/temporal.py)、[probes.py](../temporal_open3d_v1/probes.py)、[模型/投票](../temporal_open3d_v1/randla_core.py)、[训练循环](../temporal_open3d_v1/network_train.py)、[逐行评价](../temporal_open3d_v1/evaluate.py)。只在训练上拟合标准化，按验证宏 AP 选权重；同域原索引不同于最近邻回投。
4. [各种子/录制原始统计表（种子197）](../temporal_open3d_v1/analysis/197/metrics.csv)、[负对照共同分母](../temporal_open3d_v1/analysis/paired_differences.csv)、[50 个风险政策](../temporal_open3d_v1/analysis/risk.csv) 和[独立 QA](../temporal_open3d_v1/reports/qa.md)。不要把不同可用点交集上的两个 AP 直接相减。
5. [原生 RViz 固定视角案例](FIGURES.md)、[工程师方案审查](../engineering_reviews/scfnr_review.md)、[下一轮建议](NEXT_TRAINING_PLAN.md)。想审查训练源身份或运行时，请看[复现说明](REPRODUCING.md)和[发布清单](../publication_manifest.csv)。
