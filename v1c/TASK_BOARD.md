# OPDF-V1-C 四阶段任务板

主控签收标准见CONTRACT.md，用户原指令见communications/user_instruction.txt。V1-B基线不可覆盖。

| 阶段 | 责任线程 | 所有权/交付 | 通过门槛 | 当前 |
|---|---|---|---|---|
| 1 连续片段/ROS1 bag | DATA-01 | sequence_io、预览/抽取/冻结预计算/ROS1导出与验证 | 30连续帧有来源；每条PointCloud2字段/XYZ/RGB/slot/双时间精确readback | 完成：30×11=330消息逐条通过 |
| 2 ROS1逐帧/中间层/ROI | RESEARCH-03，MASTER实测 | ROS1 RViz配置、同步frame-review、ROI差异、运行证据 | 真正prev/next/pause/play；不改header伪同步；GUI实测与未验分开 | 完成：真实330组合与clock、顺序RAW/CLASS实景；seq覆写缺陷已返修 |
| 3 门控诊断 | PIPE-02，MASTER接续 | 不改阈值的单门/联合/保护重叠/全帧和ROI反例 | 分母/availability/净效应准确；真实连续片段来源 | 完成：30帧精确重构；全帧/3ROI/7个单变量反事实 |
| 4 受控候选 | MASTER | 新配置/新run，suspect附加mask不改labels | Stage3后；同rawslot单项消融；不授权suspect抑制 | 完成：relative/uniform30×2；原48数组不变，C390回读/网络通过，Suspect GUI实拍 |
| 独立QA | 原QA-04 partial；QA-04-B最终 | 新旧版本、来源、时点序、ROS1/显示/标签边界 | 实际抽验；必须返修项关闭；无GT不造性能 | 完成：QA-04-B限离线PASS；最终主文档hash和黄色Suspect GUI已签收 |

本轮停止点：完成可实际播放的ROS1调试bag/逐帧工具、解释诊断和至少3待审ROI、受控候选行为对照及QA。缺可靠标签允许止于诊断；训练/上车/Phase3仍未授权。

最终关闭：evidence/qa_backup_master_report_check.json无事实错误/必修项/坏链接。原QA阶段稿保留未最终PASS，正式结论见reports/qa_backup.md；白色E弱冲突层仅native/network验证、未单独GUI，Global Status Warn详情未知。11321及本轮RViz均已清理，原roscore/rosmaster保留。本轮停止，不继续扩实验。
