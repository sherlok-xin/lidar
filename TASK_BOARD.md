# OPDF-V1-B 实现与真实运行任务板

这是独立纯算法分支，Phase3标注平台仍暂停；不是上车授权。原bag、原工程、research_ops不改。全部新输出仅本目录，原生线程复用见thread_registry.json。

| ID | 所有权/输入 | 实际交付和验收 | 状态 |
|---|---|---|---|
| MASTER | CONTRACT/config/pipeline/run/README/集成 | 稳定枚举与接口、9帧真实运行、消融/敏感性、行为报告、原保护校验、QA关项 | 已完成，综合报告签收后停止 |
| DATA-01 | cloud_schema/io_rosbag/inspect_bag/IO测试 | 本地唯一bag只读索引抽3窗9帧；shape/stride/NaN/原slot字节可逆；实际IO日志 | 已验收：reports/data_m0.md，13项IO测试，9条真实缓存 |
| ALGO (PIPE-02) | ground_lite/optical/geometry/decision/算法测试 | M1/M2/M3/M5纯函数、可用性/分数/原因、保守E/A/U/G、实际样本运行 | 已验收：reports/algo.md，15项算法不变量测试，集成9帧OK |
| EVAL (RESEARCH-03) | visualization/evaluation/view_frame/review_roi/publish_rviz | 真实3D共享视角四联、交互旋转缩放、ROI精确slot/盲评/回归、行为CSV及只调试发布 | 已验收：reports/eval.md，实际Chrome/ROI/盲审；ROOT另补同节点DDS自收 |
| QA-04 | 实现后独立检查源码/测试/真实run | reports/qa.md，直接运行单测/真实样本检查，来源/保守决策/未知/3D同视角反例 | 已提交PASS，仅离线原型；独立41测试，0项必须返修实现问题 |

缓存初轮9帧，最多60帧/600MB；本轮不扩其他bag采样。动态W回归仅测试或既有事实，不假装优先bag已出现1729。无GT不报告precision/recall，不把颜色或模型输出当标签。M4仅在V1-B跑通后以真实帧时序和缺口判断可行性，未证配准/刚体对应则保持unavailable。

2026-10-31关闭记录：正式输出outputs/v1b_real9_final；三短窗属一个bag，不是三独立事件。41项测试中另含8项evaluation契约、5项pipeline回退/异常。首次3D依赖冲突失败日志保留，后续实际成功且独立QA通过。综合报告/README另经QA只读核验，见evidence/qa_master_report_check.json。RViz GUI/跨进程DDS、独立GT与安全效果未验；本轮不自动继续M4、训练、Phase3或部署。
