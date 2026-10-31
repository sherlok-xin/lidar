# OPDF-V1-B：真实 bag 离线实验与主控验收

MASTER；2026-10-31，Asia/Shanghai。独立算法分支，Phase3标注平台仍暂停。

## 交付结论

**OBSERVED：已实现并实际运行V1-B，不止完成方案。** 指定本地ROS1 bag的前、中、尾三个短窗共9帧进入M0→M1-Lite→M2→M3→M5，最终运行全部状态OK。可复现源码、配置、源记录定位、原slot标签/分数/可用性/原因、行为CSV、逐帧三维四联PNG和交互HTML均已保存。[最终运行](../outputs/v1b_real9_final/run_summary.json)、[README命令](../README.md)、[独立QA](qa.md)。

**OBSERVED：QA-04独立41项测试通过，独立原消息核验、缓存重跑、ROI回归、九帧计数复算和实际Chrome检查通过。** QA结论PASS仅覆盖离线启发式原型，0项必须返修实现阻断；其未验项不因主控签收而变为通过。

**UNKNOWN：没有独立材料/障碍GT，没有实测B1公平性能，没有真实误停车、安全通行或部署效果证据。** E/A/G分别是实体、气溶胶、地面候选；颜色、低强度、散乱几何和画面更干净均不能认证其材料。U以及A后方不解释成自由空间。没有监督训练、控制接线或上车。

## M0：来源、预算与可逆映射

唯一实测源为`/home/xin/lidar/data/2026-09-17-15-14-07_1.bag`，2,298,545,120B，ROS1 V2；所有读取以只读方式完成。Topic为`/hesai/pandar_points`，不据其名字推断厂家/型号。实际9帧均H80/W1800，point_step32、row_step57600，frame_id=`rslidar`，is_dense=false。实际声明字段如下，均datatype7/FLOAT32、count1：

| 字段 | 字节offset | 使用与限制 |
|---|---:|---|
| x | 0 | 源坐标，物理车体轴标定未认证 |
| y | 4 | 同上 |
| z | 8 | 仅在近水平/Z向上工作假设下拟合平面 |
| intensity | 16 | 原始数值及局部相对统计，不称物理反射率 |

**OBSERVED：没有声明ring、time、timestamp、return ID/type或Doppler。** 其余槽字节原样保留但不解释成额外字段。字段、header/record整数纳秒时间及消息SHA见[输入manifest](../manifest.json)与`samples/*.json`；QA从本地bag偏移1147135707独立读出middle_seq245847原消息，SHA与缓存一致。

索引声明463个目标Topic帧；实际只解码9帧。首次抽取实际文件读取44,723,210B，其中chunk载荷44,546,992B，缓存序列化消息41,473,017B，读取预算160MiB；未全量解包。抽取记录耗时0.176436s受系统缓存影响，不能当冷盘性能。QA后续只额外抽验一条4,608,113B消息及64KiB文件头；保护检查另有小量头部读取。[DATA报告](data_m0.md)、[抽取日志](../evidence/data_extract_command.json)。

`raw_slot_id=0..H*W-1`保留无效槽，依据实际row_step/point_step获取字节；raw_data保留行padding。`raw_flat→(phase,column)→fixed permutation→80×W`有逆变换。候选版本`phase2-candidate-v1`，置换文件SHA256=`50f7bb8d1425450ae857bb70b11ba39d14a5b71653fbb4a2f8702675177be24c`。该固定几何布局复用Phase2证据，不认证厂家物理束号、发射顺序或逐点时间。W1729、padding、大小端、NaN/Inf、空帧和精确槽字节往返是回归测试；本次9帧没有真实W1729样本。valid_xyz与column coverage分开；未观测列不会补成0米点。

三个短窗是同一bag内采样，**不是三个独立采集事件或训练/测试集**。header时间区间：

| 窗口 | seq | 首/末header_stamp_ns |
|---|---|---|
| early | 245616–245618 | 1789629247564411163 / 1789629247763675451 |
| middle | 245846–245848 | 1789629270563782454 / 1789629270763908386 |
| late | 246076–246078 | 1789629293564550638 / 1789629293764281750 |

## 实现与冻结参数

[接口契约](../CONTRACT.md)、[算法细节与反例](algo.md)对应实际纯函数实现。配置文件`configs/v1b.yaml`是调试启发值；规范化配置SHA256为`6a3f8ee29053b61fdc739602d8fb0b082d51eccd8bb11fc8c3915bdfdc1bc4e1`，与配置文件原文本SHA不是同一种摘要。最终run保存参数快照、原输入manifest及模块源码hash。

| 模块 | 已实现行为 | 保守回退与局限 |
|---|---|---|
| M1-Lite | 1m格低分位种子，确定性RANSAC平面z=ax+by+c，象限/径向覆盖、坡度、整体与近远残差自检 | 不通过不硬G；z范围仅选种子，不是全局删除。G窄带[-.10,+.035]m，近地/低凸起保护；3.5cm以内突出物仍可能误G |
| M2 | 距离、原I、局部median/MAD、相对弱光分数与有效邻居数 | 无I*r²反射率假设；弱光不能独立给A；均匀弱尘可能不突出 |
| M3 | 可信角邻接内扫描连续/跳变，距离自适应3D邻域与PCA、细长/边缘保护 | 不跨首尾接缝，不拿无效作0米；少样本/退化unavailable。密度受最多15个非自身支撑截断，不是真实无限制密度 |
| M5 | E需扫描与空间表面支持；A需三类可用证据共同过门且无实体/近地/边缘冲突，其余U | 分数为启发值；不可用不当低实体分。INVALID独立，G独立；ERROR保留有效点U，ABSTAIN不冒充成功 |
| M4接口 | 时序请求不可用时精确退回单帧，记录原因 | 未实施短窗材料运动过滤，不用NN位移当颗粒速度，不补点 |

9帧平面自检均通过，截距c约[-1.4251,-1.3566]m。middle_seq245847拟合a≈.002351、b≈.001472、c≈-1.417649m，所选内点残差中位数约.0477m、内点率约.7757；这是算法选择结果，不是真实地面验收。`plane_residual_m`是垂直高度差绝对值，不是法向欧式距离。

导出包括raw_slot、xyz/I/mask/labels、E/A score及availability、reason位码和各模块中间量；真实ROI共48个slot对齐数组。保留云为E+U，G单通道；要复原全部未标A的有限点还须加回G。调试Topic的`solid`含U，不意味着都已确认实体。

## 实际运行结果：仅算法行为

唯一正式结论使用`outputs/v1b_real9_final/`；早期baseline保留作回归证据，不能当另一组独立数据。9帧、1,296,000槽，finite XYZ=833,106，INVALID=462,894；E=96,183，A=82，U=532,919，G=203,922。E+U=629,102，含G保留=833,024。A=82仅为准备抑制的候选点数，不能称82个真尘、漏检/误检数或正确删除数。

| frame | 有效XYZ | E | A | U | G | compute ms |
|---|---:|---:|---:|---:|---:|---:|
| early_seq245616 | 83316 | 8241 | 5 | 53100 | 21970 | 792.52 |
| early_seq245617 | 83040 | 8248 | 6 | 53608 | 21178 | 771.25 |
| early_seq245618 | 82858 | 8067 | 3 | 53446 | 21342 | 779.72 |
| middle_seq245846 | 104757 | 13709 | 14 | 63833 | 27201 | 807.97 |
| middle_seq245847 | 104479 | 14037 | 11 | 70455 | 19976 | 810.85 |
| middle_seq245848 | 104482 | 13967 | 27 | 63189 | 27299 | 816.32 |
| late_seq246076 | 90589 | 10054 | 10 | 59230 | 21295 | 787.40 |
| late_seq246077 | 90163 | 10040 | 4 | 59835 | 20284 | 769.71 |
| late_seq246078 | 89422 | 9820 | 2 | 56223 | 23377 | 789.48 |

完整含源bag双时间戳、距离/原z/拟合平面高度带、可用性与耗时的表为[metrics.csv](../outputs/v1b_real9_final/metrics.csv)，模块自检为[diagnostics.jsonl](../outputs/v1b_real9_final/diagnostics.jsonl)。全部分母和统计属于行为，不计算Precision/Recall/F1或真实FN。UNKNOWN不能从有效分母偷偷删去以提高所谓成绩。

实际final全任务30.2504s含9帧计算、PNG/HTML及保存。单帧compute约.77–.82s，中位789.48ms；模块中位约M1 192.19ms、M2 208.67ms、M3 360.55ms、M5 19.54ms。模块中位之和不必等于总中位。**当前不满足10Hz实时要求**；QA独立单帧约.964s是另次进程计时，不与final绘图总时长混用。

### 同RAW域消融与阈值敏感性

实际仅在每窗首帧3个代表帧复用冻结模块证据，未重复大规模读bag。B0有限点全保留；M1及M1+M2没有几何授权，A均0；M1+M3产生E但A仍0；完整M1+M2+M3+M5的A为5/14/10。这说明门控按设计依赖多证据，不能证明完整方法更准确。[ablations.csv](../outputs/v1b_real9_final/ablations.csv)。

三项A阈值同时按-.1/0/+.1扰动，A数分别early 8/5/2、middle 23/14/7、late 17/10/6，三帧总计48/29/15。[sensitivity.csv](../outputs/v1b_real9_final/sensitivity.csv)。没有据此选GT最优参数，正式默认配置不变。此扰动不代表所有参数已穷尽。原B1为另一处理层，未获得同层冻结POST_LIO身份域，不参加RAW-V1排名。

## M6：真实3D、可复核风险案例与人工入口

主视图9张PNG/9个HTML均基于真实XYZ，四panel同帧、同坐标裁剪、同相机与同一rawslot显示样本。颜色E青绿/A橙/U紫/G灰；INVALID不绘成点。默认显示上限30000，抽样可能遗漏少量A；完整NPZ和精确ROI才是全量slot依据。交互HTML支持共享旋转、缩放、冻结视角保存、截图及显示点查询；ROI CLI可精确查询未显示slot并回归案例。

**OBSERVED：MASTER与QA实际查看三例固定视角PNG；QA另实际启动Chrome执行最终ROI HTML，DOM/selftest通过且已查看浏览器截图。** 当前无DISPLAY，没有伪称在物理屏幕或RViz看见效果。Open3D/Plotly未装，采用mplot3d与自包含真实xyz透视/深度排序HTML；不是二维XY/XZ散点替代。browser自检布尔标记不能单独证明所有3D渲染正确。

三例均来自middle_seq245847，header_ns=1789629270666355610，完整原slot集/48特征/源hash/配置/视角/原因码定义已保存。名字描述候选观察区域，不是已证对象身份：

| case与链接 | ROI XYZ范围/m | 全量slot/行为 | 待核问题 |
|---|---|---|---|
| [vehicle_structure_candidate](../outputs/v1b_real9_final/cases/vehicle_structure_candidate/review.html) | [-7,12]×[-6,6]×[-.8,3.5] | 20532；E6463/A4/U14065 | 车辆形结构附近4个A是否属于实体边缘？车辆身份未独立确认 |
| [near_ground_rough_vegetation_candidate](../outputs/v1b_real9_final/cases/near_ground_rough_vegetation_candidate/review.html) | [3,18]×[-16,-6]×[-1.8,-.5] | 4096；U3946/G150/A0 | 近地粗糙/植被候选中150个G是否吞低矮障碍？尚无草/石GT |
| [aerosol_surface_ambiguity](../outputs/v1b_real9_final/cases/aerosol_surface_ambiguity/review.html) | [7,10]×[1,4]×[-1,2.5] | 2624；E544/A3/U2077 | 弱/散乱的3个A与邻近表面的身份混淆，重点反证删除规则 |

最后一例raw_slot138364：XYZ≈(8.522149,2.390589,.016924)m，I=3，score_A≈.841167，reason32880。它通过弱光/扫描断裂/弥散等门控而成为A；**INFERRED：存在邻近表面误删风险；UNKNOWN：并未确认是尘或误删实体。** 该分数不是84.1%沙尘概率。主控不把此风险包装成确认失败，也不因只有3点而认为无风险。

三个`human_review.json`的reviewer/confidence/human_label均null、状态PENDING。MASTER助手选区和QA工程检查不是人类材料标签。盲模式独立验证仅含XYZ/I/valid/rawslot，无模型label/score/reason；显示cap不缩减精确导出。案例回归和独立真实缓存重跑均0标签/原因差异。[案例清单](../evidence/final_case_manifest.json)、[QA回归](../evidence/qa_case_regression/regression.json)。未来L2导入接口核验独立来源与slot关联，但不会把来源声明自动认证为真值。

## ROS2只读调试边界

已提供独立publisher与`configs/opdf_debug.rviz`。实际同一节点内发布/订阅、ROS_DOMAIN_ID104、ROS_LOCALHOST_ONLY1，仅五Topic，每个实际收3条、header/data字节无差异：[实际记录](../evidence/ros_debug_actual_selfreceive.json)。它保留源frame/stamp；`solid`=E+U；`unknown`另发布U供调试，不能把两Topic相加当互斥全集。

**UNKNOWN：跨进程DDS与RViz GUI显示仍未实测。** 仅有CDR序列化及后续同节点真实自收；没有宣称桥接整个ROS1 bag、实时连续回放、标定TF或生产消费者成功。未发布规划/油门/制动Topic，未启动原工程launch。

## 失败、回退与未实现项

1. **OBSERVED失败：** 首次真实处理完成一帧计算，绘图报`Unknown projection '3d'`，源于已安装Matplotlib与系统mpl_toolkits路径冲突。失败目录`v1b_real9_initial/FAILED.json`和[原日志](../evidence/run_initial.log)保留，不计为成功运行。改为本进程匹配toolkit路径并注册Axes3D，未安装依赖或改全局环境；后续baseline/final成功，QA实际独立渲染通过。
2. **OBSERVED回归：** baseline至final添加可解释中间量/诊断别名及缓存指纹冲突检查，未改门槛；9帧labels/reasons/rawslot均0变化：[回归记录](../evidence/baseline_final_regression.json)。
3. **OBSERVED执行限制：** 原生线程曾遇用量限制，MASTER接续集成，随后复用原线程完成正式分工报告与独立QA；未虚构替代执行器。真实UUID见[线程登记](../thread_registry.json)，通信归档见`communications/`。
4. **UNKNOWN / M4不实施：** 连续seq与header差约97.55–102.57ms已实读，但不证明始终静止、扫描相位对齐或车辆刚体对应。现有短窗没有建立可信自车/对象配准，故M4 unavailable，保留单帧：[可行性记录](../outputs/v1b_real9_final/m4_feasibility.json)。
5. **UNKNOWN：** 不存在同一激光束多回波或穿尘后表面回波身份的可靠证据，本轮不从邻射线距离跳变推导透射/穿透。坡变、低台阶、暗车/薄杆/草/尘墙混合边界仍可能误E/A/G或大量U；无GT不能列出已确认语义失败率。

## 阶段验收与下一次最小实验

| 门槛 | 签收状态 | 证据/未验范围 |
|---|---|---|
| Milestone0环境/容量/来源保护 | 完成 | 初始可用8,883,617,792B；只用现有依赖；保护摘要与实际核查 |
| Milestone1 M0/动态W/双mask/slot字节逆映射 | 完成 | 9真实缓存与13项IO测试；W1729仅合成回归 |
| Milestone2纯函数+真实样本+参数冻结 | 完成 | final9帧均OK，score/available/reason与快照可查 |
| Milestone3真实3D/ROI/L0报告 | 完成 | 9逐帧双时间戳可溯、三例同视角3D、精确slot/盲审/回归；人工材料标签待补 |
| Milestone4独立QA/反例/保护 | 完成，限离线原型 | 独立41测试及原消息/真实重跑/浏览器核查PASS；未认证效果或安全 |
| M4短窗过滤 | 未实施 | 可靠对应不足，接口与不可用回退已验证 |
| RViz GUI/跨进程、10Hz、安全部署 | 未验/不满足当前实时目标 | 当前离线运行不构成授权或证据 |

**PROPOSED，仅为下一次最小计划，本次不继续执行：** 先由实际标注者盲看三个已冻结ROI，记录材料/对象身份可确定与不可确定部分，优先核对rawslot138364附近、车辆候选A4和近地G150；保留U/未标分母。若需多传感器辅助，先补可靠时间/外参证据，不能靠未标定相机直接生成点GT。再增加一个独立采集事件中的暗色实体、低石/草与尘边界少量ROI作冻结对照，按事件留出，不随机拆邻帧。独立可靠标签到位后仅对已标slot给有边界的局部指标，另报漏标/未知；此前只报告行为。M4先验证平台与对象对应；实时优化优先针对M3邻域与M2统计，但不得边调当前测试候选边宣称泛化。

原bag stat/头摘要、research_ops165个冻结文件和原工程316个受保护文件摘要核查未变：[保护检查](../evidence/protection_check.json)。该检查不是全bag哈希，也不认证整个硬盘或未登记文件。所有新产物仅在本目录。主控据QA证据签收并在此停止，不恢复Phase3、不训练、不改原算法或部署。
