# 阶段和结论

| 阶段 | 真实工作与结果 | 主要限制 |
|---|---|---|
| OPDF V1/V2 | 逐点几何规则、实体保护与区域占据代理。另有[工程师方案审查](../engineering_reviews/scfnr_review.md) | 规则、栅格或框不是逐点材料真值，未见规划安全认证 |
| [Pilot](../history/dust_learning_pilot/reports/experiment.md) | 公开监督和本地 POST-LIO 迁移；B2 公开 F1 0.8037，本地 0.1111 | 源域好不代表本地能用 |
| [Phase 2](../history/dust_learning_phase2/reports/adaptation_experiment.md) | 冻结消融、有限本地监督和阈值预算 | 单一已曝本地事件只能探索；不能据相关性断定物理原因 |
| [Phase 3B](../history/dust_learning_phase3b_pilot/reports/experiment.md) | 267 帧来源代理；C 在0.5时 F1 0.7932，旧风险操作点车辆误抑制24.63% | 两个数字不是同一阈值；Phase3A 独立测试仍 BLOCKED |
| [Phase 4](../history/dust_learning_phase4/reports/experiment.md) | B2 与 Reduced PointNet++ 有界查询对照 | 部分查询，不当成整云；未确认深网络或额外损失满足实体保护预算 |
| [多帧与 RandLA](../temporal_open3d_v1/reports/temporal_experiment.md) | 8次网络、3种子×14个线性探针。8录制共同点上 N0→N1 宏AP .8325→.9172 | 手工乱序与远历史对照削弱短时有序演化解释。N1 在本地回退 N0。50个政策均未达双实体风险与最低尘召回要求 |
| 数据入口 V1 | 原生读取、来源/索引、两个 bag 格式试点和 train-only 输入输出检查，见 [hub 报告](dataset_hub_report.md) | 新增数据不自动进入冻结测试；本轮无新正式训练 |

本仓库发布的是有依据的研究代码与行为、来源标签评价和局部反例，不含驾驶决策。既有学习方法不得通过模型输出自造新 GT。
