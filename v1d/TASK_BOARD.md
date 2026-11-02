# V1-D任务板

| 阶段 | 责任 | 实际交付与验收 | 状态 |
|---|---|---|---|
| 冻结/来源 | MASTER | 当前B241+C668文件快照；既存2文档差异单列，不改旧文件 | 已核 |
| D1 | DATA + PIPE审阅，MASTER | 30帧COMPLETE；4上界消融；稀疏低凸起反例返工；143候选/108逐点可显示抑制/35保留；源码、命令、日志见d1两份报告 | 已验收离线行为，材质风险UNKNOWN |
| D1/ROI | RESEARCH | 5类RAW邻帧盲审、同slot/view三维图和完整ROI集合；37低物点进Core明确保留未知 | 已交付；真实人工标签PENDING |
| D2 | PIPE + RESEARCH对照 | 30×2模式COMPLETE及uniform-off；真实半径/PCA/原因、跨源身份、转移、13反例、139114风险 | 已验收离线候选，性能有效性未认证 |
| D3 | MASTER | D1/D2门后30帧/29对实际探针，背景配准不足/对象对应未知，未改标签 | COMPLETE；M4=UNAVAILABLE |
| ROS1 | MASTER + RESEARCH | 新D适配复用C播放器；23话题/690原生消息与实际pubsub全匹配；同窗固定相机D1五层/D2四层 | 已实际显示；GlobalWarn未解释 |
| QA | QA-04-D及原QA-04接续 | 独立49测试/384球PCA/115native消息/全30跨源复算；原QA接续9张真实固定GUI/文档/低物CSV核验 | PASS仅限离线交付；reports/qa_final.md |

停止门槛：本轮D1/D2可执行算法和真实30帧/5ROI/ROS1对照、可解释改善与新风险、D3决定、独立QA；不自动训练/上车。

2026-11-02：实际输出已齐备，MASTER综合报告及README已提交独立QA。首次D1 np.bool_序列化失败、初次QA脚本错误与旧跨窗口视角不一致均保留日志，不作为成功证据。没有材料GT，没有现场停车改善/10Hz/部署验收。

最终状态：COMPLETE，独立限定PASS且MASTER复核收据通过。本轮停止；高风险UNKNOWN包括139114与低物Core37，M4不启用，不训练/上车。最终文件清单为DELIVERY_MANIFEST.json，真实线程映射/通信只在D续存。
