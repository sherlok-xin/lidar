# QA-04-B 独立备用审核

2026-10-31。真实 canonical task：`/root/qa_v1c_backup`；真实线程 UUID `01a1927f-5e85-7f83-a28b-aa7adf36b515`，MASTER先核实回传，本执行器随后也直接只读对应原生session文件首条session_meta，确认id及source.subagent.thread_spawn.agent_path一致，非猜测。本报告来自备用原生执行器；原 QA-04 因用量退出的 partial evidence 不视为最终 PASS，也未作为本报告独立抽验的替代。

**最终结论：PASS（限本轮离线软件/数据/诊断交付）。** Stage1–4、B/C原生ROS1调试消息、接收端精确clock、实际RAW/CLASS固定视角及C黄色suspect GUI、三个B/C精确ROI复盘均已补审通过；已知seq自动改写和窗口遮挡失败保留并关闭。本 PASS 不包含材料识别准确率、安全部署、实时性能或人类语义标签，白色entity_optical_conflict层仍未单独GUI实拍。

## OBSERVED：本执行器独立检查

1. 冻结基线清单的 241 个文件逐个比对实际 size/SHA256，全部一致。源 bag 只读；没有修改冻结 opdf/scripts/configs/原 reports/九帧 final，没有安装、训练、部署或启动 ROS master/车辆节点。
2. 直接从原始 bag 读取 seq245847：先解析真实 CHUNK header，再按 chunk 内 record 偏移解析 MESSAGE_DATA header，核连接号、record 时间和消息绝对偏移 1147135707，随后读取一条 4,608,113B serialized PointCloud2；完整字节与缓存及 manifest SHA 一致。单次真实源读取为 4,608,208B，含 95B 两级记录头。宿主机审计先后执行两次（第二次补充机制探针验证），均只抽同一条消息，合计源读取 **9,216,416B**；未全扫或计算全 bag SHA。源 size/mtime 前后不变。
3. 对 seq245832–245861 全部 30 帧缓存，以本审计脚本自己的 struct/stride/endian 解码器恢复实际 H/W/schema/XYZ/intensity。缓存 SHA、manifest/index/NPZ 的双时间、seq、slot、XYZ/I 全部一致；本窗均 80×1800，解码器仍按实际 W/row_step 处理。48 数组保留完整 4,320,000 槽，有限 XYZ 3,115,334。逐帧调用只读冻结 `decision.classify`，保存的 labels/reason/availableE/A/scoreE/A 六输出逐元素精确一致。
4. 独立重算全帧门控、三门联合模式和 7 个单变量反事实，匹配已交 Stage3 汇总。行为计数 INVALID/E/A/U/G = 1,204,666 / 422,220 / 388 / 1,939,023 / 753,703；三门通过 1,607；反事实新增 A = 0/0/917/7/1/0/253。独立核机制探针：均匀低 I 273,322 且全未过相对弱光门；连续密集探针 801,894；三门通过缺拟合地面参考 17。它们均为点帧行为计数。全 30 帧 × 4 个全帧/ROI scope 的距离、地面高度（含 unavailable）、最终类分组数量守恒通过。
5. 在已有 `ros-noetic` 容器内，以自己的新审计脚本原生离线读调试 bag 的首/中/末 seq245832/245847/245861 共 **33 消息，62,489,721B 完整 serialized payload**。bag topic 元数据为精确 11 个感知白名单、每个 30 条，共330条。抽验的 raw 全 serialized 字节等于源缓存；所有派生消息 schema/stride/点数、XYZ/I 四字节词、RGB 位、raw_slot 与原始顺序均精确一致。E-only=E，retained=E+U，G 单列；没有 invalid 假点，没有控制 topic。
6. 同一原生容器独立检查实际安装的 `rospy.msg.serialize_message` 和参数转换路径：33 条消息适配后传输计数314159265仍保留原 seq/header 且 wire payload 与 bag 精确相等；普通 PointCloud2 负对照确实被改 seq271828182。33 个清空云保持目标 seq/stamp 且 width0/data空。PointCloud2 基类 `_has_header`、全局 serializer 未改；没有创建 ROS 节点。此独立检查不等于本执行器启动过网络或 GUI。
7. 三个 Stage2 待审 ROI 的确切点数 2,624 / 4,096 / 20,532，分别显示 2,624 / 4,096 / 5,000；全部 48 个槽对齐特征逐元素与原 NPZ 精确一致。显示 cap 不影响 exact 导出或计数。候选名称不作材料标签；reviewer/confidence/observation/整区语义均 null，PENDING_HUMAN_REVIEW。
8. 本执行器实际运行本轮测试：**24 passed, 1 skipped**。host skip 为缺原生 rospy 的序列化项，上述容器原生独立抽验已补；synthetic fixture 不当真实场景证明。

原始脚本、真实命令与 stdout/stderr：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B opdf_v1/v1c/evidence/qa_backup_host_audit.py
docker exec ros-noetic bash -lc 'source /opt/ros/noetic/setup.bash; PYTHONDONTWRITEBYTECODE=1 python3 -B /home/xin/lidar/opdf_v1/v1c/evidence/qa_backup_native_audit.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B opdf_v1/v1c/evidence/qa_backup_review_audit.py
PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/home/xin/lidar/opdf_v1/v1c/.cache/matplotlib python3 -B -m pytest opdf_v1/v1c/tests --basetemp=/home/xin/lidar/opdf_v1/v1c/evidence/qa_backup_pytest_tmp -o cache_dir=/home/xin/lidar/opdf_v1/v1c/.cache/qa_backup_pytest -q
```

对应 `evidence/qa_backup_{host_audit,native_audit,review_audit}.{py,json,log,stderr}`，测试 `evidence/qa_backup_tests.{log,stderr}`。宿主审计/ROI审计分别执行两次，最终日志对应补充后脚本，原 bag 总读取以上文两次合计为准。Noetic 执行通过正式工具 require_escalated，动作仅离线读已有 bag 和 v1c 内写证据。

## OBSERVED 与 INFERRED：播放器/网络/GUI 边界

- 源码审查确认先完整读取/校验一帧所有 topic，再按 batch 发布；跨 ROS topic 不保证网络原子，报告和日志明确 `network_atomic=false`。本审计独立核旧 player 日志全部30帧、header/record映射、4次向后清空及目标 header 一致。向后播放采用真实倒退 record `/clock`、目标 header 空云、墙钟短等候、再真实云；暂停墙钟刷新不伪造源时间。Queue1/Decay0、无 latch，清空云不增加回波。
- MASTER 的真实跨进程证据 `evidence/ros1_actual_fixed/summary.json` 报330组合/30帧完整，mismatches/missing为空，接收端4次clock倒退、各层4个空云。检查器实际订阅后用完整 ROS serialized SHA 对 bag 比较；这是 MASTER 的网络实测，备用 QA 独立审其源码和产物，不冒称由本执行器独立重跑。
- 发现证据缺口并已即时告 MASTER：旧检查器只保存接收 clock 的倒退次数，没有持久化 `received_clock_ns` 或核每值属于源 index 的 record ns。播放器源码/发布日志支持“发原record时间”（INFERRED），旧 summary 的 `simulated_clock=exact source record ns` 尚欠接收侧精确数值证据；等待补审。
- 本执行器已实际查看旧 `rviz_classified.png`：EOL modal遮挡、侧栏占大部，前景 RAW enabled，窄云区可见。它证明真实 RViz 窗口已打开、有云，但不足作为清晰分类GUI对照验收，不能仅据文件名或 `gui_verified=true` 判理想显示 PASS。修整 GUI 待补审。
- 局部 PointCloud2 子类仅跳过 rospy 的 seq改写，继承原Type/MD5/serializer；不改 ROS 全局类、原 bag、原 payload。隔离 master 环境受 loopback:11321 约束。`/use_sim_time` 影响隔离 master 的所有节点，退出不还原该参数；在本轮独占且有界销毁的 debug master 里可接受，不能拿此代码去接生产 master。

## UNKNOWN

本窗只有约2.9s、同一 bag 连续事件；没有独立材料 GT、跨session验证、相机外参逐点标签、实际去尘正确率、地面可通行性或10Hz算法能力。候选A与疑似区域都不能转为真尘或删除授权。GUI里的点云、暂停刷新与源批次检查不能证明场景识别正确。

Stage4 两组正式结果、报告与三个B/C案例已补审，通过范围见下。C版两附加层已有原生bag与实际网络验证，默认关闭；黄色suspect层已有独立实际GUI看图，白色entity_optical_conflict层尚未单独GUI实拍。任何画面都不代表C附加层已被人类语义核验。

## PROPOSED：补审门槛及关闭

1. 已关闭：Stage4 在同一 raw_slot 域逐帧核原48数组、E/A/U/G与正式保留/删除候选mask完全不变，suspect仅附加bool诊断mask；配置/方法/源hash、单项消融、原因/反例及计时分项通过，无GT只报行为。
2. 已关闭：MASTER最终顺序GUI有同源帧/固定相机RAW与CLASS实拍和真实操作日志，云区可读、无modal遮挡；接收端精确 `/clock` 已落盘并核对。旧失败保留。
3. 本报告已据补审更新最终范围与结论。停止新增抽读或实验，不覆盖原 QA-04 身份或其 partial evidence。后续人工材料核验属于下一次授权范围。

## Stage4 与最终 clock 补审（已完成）

备用QA实际执行 `PYTHONDONTWRITEBYTECODE=1 python3 -B opdf_v1/v1c/evidence/qa_backup_stage4_audit.py`，原脚本/JSON/log/stderr同名前缀落盘。该独立脚本不调用 suspect 或 gate_diagnostics，实现自己的布尔判据并核实际60个NPZ：

- relative/uniform 各30帧，源48数组逐字段逐元素精确一致，包括 labels/reason/score/available/XYZ/I/slot/retain_solid_mask/retain_with_ground_mask/aerosol_candidate_mask；新增7字段精确一致，suspect为bool，不包含INVALID/A/G。
- 每条源metadata、源B NPZ SHA、配置canonical hash、方法源hash与manifest核验通过。两配置唯一差异 `diagnostic_candidate.uniform_low_enabled`，冻结ground/optical/geometry/decision参数不变。
- relative 的 suspect/protected/conflict 为76,095 / 43,655 / 53,775；uniform 为141,066 / 55,614 / 119,867。新增suspect64,971、移除0。均匀暗数值线索若无至少一个通过的几何类别，不会单独触发suspect。原分类/保留不变，suspect不授权删除；这些不是提升或正确识别量。
- 时长31.193s和31.714s包含保存B特征读取、mask计算及序列化，明确不是完整算法加速或实时能力。材料身份仍UNKNOWN。

MASTER 已在 `evidence/ros1_actual_final/summary.json` 修补接收侧精确clock证据。备用QA自己从index重构集合，逐个核74个接收clock值，30个唯一值恰好等于全部30个源record ns；4次倒退、无未知值/缺值，330网络组合/30源帧完整且0 mismatch。旧缺口已关闭。

本执行器实际查看该run两张PNG，分类图清晰、RAW关/CLASS开、无modal；但 raw.png前景标题和勾选均为classified窗口，因此**该raw截图拒收**。原失败hash和观察保留 `evidence/qa_backup_gui_final_attempt.json`，不覆盖失败记录。要求最终提供真正RAW强度窗口，同源seq245847/固定相机再对照分类；Global Status Warn在图中可见但未展开，原因尚未从该静态图确认。

MASTER随后以 `master_gui_check.py` 在新的 `evidence/ros1_gui_sequential/` 逐个启动/截图/关闭RAW与CLASS窗口，避免QScreen截图被其他窗口遮挡。备用QA已实际 `view_image` 两图：RAW勾选/CLASS关闭、CLASS勾选/RAW关闭，正确的强度色与E/U/G类别色分别可见，主云区约75%宽度、无modal、无重叠遮挡。独立核两配置的Views/Global Options相同，70个播放刷新批次全为源seq245847；真实子进程全正常退出。`evidence/qa_backup_gui_sequential_audit.json` 保存独立核验与真实PNG/hash。**静态同帧GUI对照验收通过**，旧遮挡失败保留。

动态播放/上一帧/下一帧/暂停/降速由真实跨进程脚本、完整消息与clock证据支持；本执行器没有自行启动GUI或声称观察了逐操作GUI录像。最终截图仍可见Global Status Warn，具体原因未展开，不能称“完全无警告”；在同源固定frame正确渲染的静态验收范围内不阻断本PASS，不引入假TF去掩盖它。

## 最终新增交付补审与停止

最终 `stage4_candidate.md` 与 `outputs/review_v1c/` 三个B/C案例已审。备用QA独立核每个case的原ROI bbox选择、B48/C55完整特征、slot列表、源SHA、相机、变化NPZ及人工记录；labels/reasons变化全0，suspect/受保护数为vehicle 1,018/243、near-ground 107/106、ambiguity 122/42，全部为待审线索。`evidence/qa_backup_final_cases.json`保存结果。报告将B完整compute与C复用特征的约24.5ms附加mask计算明确分开，没有宣称真实去尘或加速达标。

C版新增390消息bag也由备用QA独立在现有Noetic容器原生抽验首/中/末39消息：33条原11层与B bag全serialized字节精确一致，6条附加层的XYZ/I/uint32 slot/RGB位/完整schema及目标双时间与C NPZ精确对应；真实serializer适配保持header不变，没有节点创建。命令为：

```bash
docker exec ros-noetic bash -lc 'source /opt/ros/noetic/setup.bash; PYTHONDONTWRITEBYTECODE=1 python3 -B /home/xin/lidar/opdf_v1/v1c/evidence/qa_backup_candidate_ros1_audit.py'
```

同名前缀 `.py/.json/.log/.stderr`保存原始证据。C版完整390回读是MASTER交付证据，备用QA为上述39消息独立抽验。`evidence/ros1_candidate_actual/summary.json`为MASTER另外实际执行的跨进程390组合/30帧，0 mismatch/0 missing；备用QA从index重核38个接收clock值、全部30源record集合和4次倒退一致，具体核验与源码SHA见 `qa_backup_final_cases.json`。13个topic精确白名单、两附加层默认关、suspect黄色/冲突白色且不授权删除；没有追加控制topic。

最终源码改动后再次实际跑完整本轮测试，**24 passed, 1 skipped，0.50s**，日志 `evidence/qa_backup_final_tests.log/.stderr`。独立再次核冻结241项size/SHA无变化，记录 `evidence/qa_backup_final_frozen.json`；此次未再读原bag。备用QA全部原bag实际读取仍为两次同一seq245847，共9,216,416B。

本执行器没有接管MASTER的隔离master/GUI，没有伪装成原QA-04，没有新增材料标注。最终PASS严格停在本报告注明的软件、精确来源/消息、可执行回放和诊断层范围；保留GLOBAL WARN详情、白色entity_optical_conflict层单独GUI实拍和材料身份为UNKNOWN，不以它们推导安全或准确率。

## 黄色suspect GUI与最终主文档补审

MASTER新增 `evidence/ros1_gui_suspect/` 单个自有RViz窗口实拍。备用QA已实际 `view_image`：Suspect REVIEW勾选且黄色原回波清楚可见，RAW/CLASS/A与白冲突层都关，云区宽约75%、没有modal或其他窗口遮挡；仍显示未展开的Global Status Warn。配置与player日志定位C索引seq245847，同源header/record、13层整组刷新，进程正常退出。此处只通过黄色suspect的实际静态显示，不将白层或材料身份冒充已看图核验。

已只读交叉检查最终 `README.md`、`reports/v1c_experiment.md`、`reports/stage4_candidate.md` 与 `scripts/ros1_env.sh`：计数、源字段与frame、B48/C55保护不变、330/390消息、header/record分开、clock精确性与rosbag通用clock区别、suspect不授权删除、性能分项与无GT边界均对应现有证据。三终端先rn/source相同环境脚本，再11321 master、sim time/RViz、C逐帧播放器，路径与操作语义一致；脚本仅本shell环境及v1c日志/缓存目录，不source车辆工程。正式QA索引正确指向本报告，原qa.md继续保持partial。两份主文档摘要及最终核验结果保存 `evidence/qa_backup_master_report_check.json`。
