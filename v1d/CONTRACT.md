# OPDF-V1-D执行契约

2026-11-01；全部新产物仅本目录。原bag、师兄工程、research_ops、V1-B/V1-C代码/配置/报告/结果只读。进入D前，旧.gitignore与C README存在既存差异，作者/原因UNKNOWN；算法/配置/报告/结果摘要匹配，当前文件快照冻结于evidence/frozen_baseline.json，不修复旧文件。

## 顺序与所有权

1. DATA-01拥有opdf_d/ground_clutter.py、scripts/run_d1.py、configs/d1.yaml、test_d1*、D1报告及输出。D1在30已缓存真实帧上实际运行，局部相对地面/地面上界单变量消融，低矮硬结构风险与仅查看clutter抑制。
2. RESEARCH-03拥有opdf_d/visualization.py、scripts/review_d.py、test_review_d*、ROI协议/评估报告及三维/盲审输出。实际选5类候选ROI（车形、车边、疑似颗粒、近地杂草、可能低硬物），材料身份UNKNOWN，无真实人工输入保持null。
3. PIPE-02先读D2设计，不执行；MASTER确认D1真实结果/反例/3D后给D1_GATE。随后拥有opdf_d/multiscale.py、fusion.py、run_d2.py、d2.yaml/test_d2*/D2报告，分别保存单模块与融合消融。不得把整个C suspect转A，不用单PCA当刚体GT。
4. MASTER负责统一接口、阶段验收、冻结保护、D3有界短窗配准可行性、重用ROS1导出/播放器/RViz并实际验证及总报告。D3须在D1/D2已提交后再决定/执行，可靠对应不足则UNAVAILABLE，不把NN位移当尘速度。
5. 原生独立QA实现和真实运行提交后启动，优先复用现有QA线程；核真实反例/风险/源索引/标签边界与实际GUI，不止软件能跑。

## 数据契约

输入复用v1c/outputs/v1b_continuous30/frames/48数组及v1c/samples/continuous30/manifest.json；如保留C附加mask，可只读调用v1c/opdf_c/suspect.py，不改C文件。sys.dont_write_bytecode=True，所有MPL/pytest/ROS/Qt日志缓存只写D。

D1 compute(arrays,metadata,config)->{arrays,diagnostics}，metadata为原完整帧JSON。新增d1__ground_core_mask、low_clutter_mask、nonground_strict_mask、nonground_display_mask、local_height、ground_available、hard_structure_protect_mask、risk_unknown_mask、reason_code与局部/簇诊断，全部原slot对齐。GroundCore/LowClutter互斥，严格非地面=finite~core，显示抑制=严格非地面~clutter。原labels与原48字段保留；D1显示结果不修改生产占据、不把薄矮等同柔软材质。

D2传入D1完整arrays/meta/config。统一新增d2__前缀，保留原xyz/I/valid/raw_slot；如改变labels/score/available/reason/retain，先将对应B原数组另存b__同名，标准labels等字段指D候选，并明确GroundCore是单独显示层还是参与候选G。必须保存E/A新增/消失slot和转移，不把新标签冒充GT。保留旧near/low/edge保护的审计位；不能悄悄让粒子证据绕过硬物保护。异常/缺证据拒判U/UNAVAILABLE，不清空云伪成功。

输出D1暂定outputs/d1_ground，D2暂定outputs/d2_candidate；frames/seq*.npz+.json和config_snapshot.yaml/input_manifest.json，原source/cache/双timestamp/locator保持，raw_slot_id含全部原槽，显示cap与全量统计分开。所有run拒覆盖，参数显式启发值，单变量消融不宣称最优。

## ROS1复用

原C逐帧脚本与消息序号修复只读复用，D适配仅扩展明确感知Topic白名单并将缓存/日志导向D；保留n/p/seq/play/pause/rate和原header/record、清缓存/clock回退，不改旧C。D bag只含感知debug，不含控制；实测11321已有用户环境，D改用空闲11331，不连接/停止11321，日志/Qt仅D，结束只清理本轮进程。重点新层GroundCore/LowClutter/Strict/DisplayOnly及B-D实体/颗粒变化（原始回波，无伪点）。已有Noetic容器使用需工具正常审核，不安装依赖。

全部结论分类OBSERVED/INFERRED/UNKNOWN/PROPOSED。无独立参考标签不报真精度/安全/去尘率；用户视觉判断只作候选来源。每人交源码、真实命令、原日志、反例、计时、未知；跨模块问题经MASTER转发。无训练、车辆部署、生产控制。
