# OPDF-V1-B 独立实现 QA

日期：2026-10-31（Asia/Shanghai）；QA-04原生任务 `/root/qa_04`，线程 `01a187a2-e6d8-7650-ac91-cbf49dadbe02`。

## 结论

**PASS：OPDF-V1-B可作为本次九帧真实输入上的离线启发式原型交付。** 本次独立运行测试、原始消息/缓存核验、真实单帧及ROI回归、九帧行为复算和实际Chrome检查均通过，未发现必须返修的实现阻断项。没有独立材料/障碍GT，不认证去尘正确率、实体安全、误停车改善或部署资格；也不形成对原B1工程的优劣比较。

此前Phase1/Phase2的PASS不覆盖本实现。本次QA所有新增文件仅写opdf_v1；没有训练、运行生产ROS/车辆节点或修改bag/research_ops/原工程。QA自己未启动ROS节点；ROOT后续补做的同进程debug DDS收发已只读复核，RViz GUI仍未验。真实浏览器仅用于离线页面自检。

## 实际执行与证据

| 独立检查 | 命令/证据 | 结果与范围 |
|---|---|---|
| 关键回归测试 | `python3 -m pytest -q tests --basetemp=/home/xin/lidar/opdf_v1/.pytest_tmp/qa_independent`；[命令与环境](../evidence/qa_pytest.json)、[原日志](../evidence/qa_pytest.log) | **41 passed in 3.51s**；QA独立进程执行，不引用ROOT的通过结果代替 |
| 原bag与精确缓存 | [qa_implementation_check.py](../evidence/qa_implementation_check.py)、[结果](../evidence/qa_implementation_check.json) | 只从本地bag读取一条4,608,113B原消息及64KiB指纹头；未重扫/再抽九帧 |
| 真实单帧复跑 | 同脚本，`process_frame`实际执行；`qa_real_cache_rerun.npz` | middle_seq245847约0.964s，状态OK；labels、reason、slot、两score及availability全部一致 |
| 真实ROI回归 | `python3 scripts/review_roi.py --regress outputs/v1b_real9_final/cases/aerosol_surface_ambiguity --output evidence/qa_case_regression` | [regression.json](../evidence/qa_case_regression/regression.json)：全帧/ROI label变化0、全帧reason变化0，状态OK |
| 实际Chrome | `python3 evidence/qa_browser_check.py`；[实际命令/结果](../evidence/qa_browser_check.json)、[DOM](../evidence/qa_browser_dom.html)、[截图](../evidence/qa_browser.png) | Chrome真实执行final ROI HTML；rendered=true、selftest=PASS、四canvas共享相机；QA已查看截图 |
| ROOT补充实际debug DDS | 只读核对[实际记录](../evidence/ros_debug_actual_selfreceive.json)、[原日志](../evidence/ros_debug_actual.log)与publisher源码，QA不重启节点 | 5个允许Topic同进程自收各3次，header/data字节无不匹配；跨进程与RViz GUI未验 |
| 输入保护 | `python3 scripts/verify_protected.py`；[QA保留副本](../evidence/qa_protection_check.json) | research_ops 165文件与原工程316文件摘要未变；bag大小/mtime/头4096摘要未变，不冒充全bag哈希 |

所有测试临时目录、Matplotlib配置、浏览器profile和证据均置于opdf_v1。浏览器正常进程所需沙箱提升经工具审核获准；未修改Chrome或系统安装。QA未再次运行九帧完整生产任务，九帧结果通过逐个NPZ读取检查与行为复算，而非虚称独立重跑九帧。

## M0与来源、动态形状

独立抽验的本地源为 `/home/xin/lidar/data/2026-09-17-15-14-07_1.bag`；seq245847消息起始偏移 `1147135707`。直接读取的序列化字节与缓存完全相同，SHA256为 `23bf647a6131d831ddda2d402edad1b8a44f6ef017f38ef1a1969dd40706651a`。独立小解析器读出80×1800、四个FLOAT32字段、step32/row57600、rslidar和104479个finite XYZ；与FrameData和真实输出相符。raw_slot保持原始完整顺序，点字节图像变换往返一致。

源文件stat和首64KiB哈希与manifest一致；缓存加载会核验消息SHA及元数据别名一致性，不能仅凭同名文件/外盘历史偏移冒充本地来源。本轮九个真实缓存均1800列；**1729列、行padding、大端、指定NaN payload/Inf、空帧、错误字段/stride及缓存篡改由合成回归测试覆盖，不宣称这九帧实测过这些全部条件。** 没有回到另一bag补抽变宽数据。

无效XYZ保留原槽位和mask；row padding留在raw_data但不成为测点；动态W与双mask不把未交付列伪造为零距离/气溶胶或自由空间。物理beam、逐点时间、回波身份仍未认证，不通过32B填充或软件phase映射补造。

## M1/M2/M3/M5保守门控

QA实际执行的测试包含：

- 地面拟合覆盖失败/陡面不产生硬G；近地低凸起受到保护。
- 低强度但连续实体形状不因强度单项成为A；扫描边缘/细长支撑进入保护。
- 光学、扫描或空间证据任一缺失，不允许按残余线索输出A；退化/缺邻居情况保留U。
- INVALID仅对应实际无效XYZ；空/全无效/错高度或映射不可用时ABSTAIN，不制造点或清空后声称成功。
- M4 enabled但不可用时实际回退单帧结果，labels/score一致并记录告警；没有用帧差伪造粒子速度。
- 模块异常返回ERROR并保留有效点U，不把异常当正常空clean；同种子/分批确定性有对应回归。

这些是可执行不变量和合成反例，不是已证明真实车身、尘团或低障碍均正确识别。E/A/G仍为启发式候选，分数没有独立概率校准；U保留也不是已确认实体或安全净空。地面单平面模型和局部几何在坡地/遮挡/混合材料上的实际误差仍需独立标签核验。

## 九帧真实行为与效率范围

QA逐个读取final run九份NPZ/JSON，核对原slot、INVALID与finite mask一致、状态均OK、相同config hash，并独立复算：

| 行为量 | 数量 |
|---|---:|
| 原槽位 | 1,296,000 |
| finite XYZ | 833,106 |
| INVALID | 462,894 |
| E候选 | 96,183 |
| A候选 | 82 |
| U | 532,919 |
| G候选 | 203,922 |

这些数与final run summary一致。A=82不是82个已证实尘点；E/U/G也未获语义正确性认证。行为计数未计算precision、recall、F1、安全率或真实误停车率。

ROOT记录的完整final run约30.25s包括九帧算法、PNG/HTML和保存；QA单帧复跑约0.964s是当前进程/输入下的计算记录。两者范围不同，均不证明10Hz车辆全链实时；没有以ROOT或QA计时冒充原生产工程性能。

初次真实运行的`ValueError: Unknown projection '3d'`日志和失败目录保留；之后将本进程mplot3d查找路径与Matplotlib匹配并注册投影，baseline/final成功。QA已读取失败日志并独立实际渲染盲case、ROI回归和运行全部渲染测试，未将失败隐去或描述成首次即通过。未安装/替换系统依赖。

## 可视化、精确ROI与盲审

QA实际查看final run三个真实ROI的PNG：`vehicle_structure_candidate`、`aerosol_surface_ambiguity`、`near_ground_rough_vegetation_candidate`。RAW/LABELS/A_ONLY/E_U使用相同3D透视、裁剪与原slot显示样本；没有发现为突出效果而改变相机或坐标范围。近地候选A_ONLY为0、气溶胶歧义候选仅3个A显示点，不能把图名当材料真值。

独立核查三个ROI的完整NPZ导出：2624、4096、20532槽位，各有 **48个slot-aligned数组**；每个导出值与原NPZ按raw_slot逐项一致，显示cap不截断完整证据。case消息/配置/NPZ hash、同view及reason定义可追溯。三个human_review的reviewer/confidence/human_label均null，没有伪造人类答案。

QA另外从真实中帧选取四个原slot生成 [独立盲case](../evidence/qa_blind_real_case/review.html)：显示cap2，但精确导出仍含4槽位；盲NPZ与HTML嵌入数据仅有原XYZ/intensity/valid/slot，没有算法label、score或reason答案。该选择是QA测试盲模式泄漏的工程输入，不是独立人工语义标注。

Chrome实际DOM与截图验证四面板共享state.camera及旋转自检通过；真实XYZ透视与深度排序实现另经源码核对。`real_3d_depth_sort=true`是自检输出中的固定标记，**不将这个布尔字段单独当独立运行验证**。截图是headless浏览器产物，非人工鼠标操作验收、物理显示器画面或RViz。

ROOT在QA期间新增实际debug DDS证据：domain104、localhost、仅五个允许debug Topic，node_created=true且各收到3条、receive_mismatches为空。QA已读原日志及代码确认；其回调实际比较header与完整data字节，不能把这描述成逐项schema元数据独立比对。此运行是同进程pub/sub，不证明跨进程、跨机或RViz可见。早先EVAL记录的无节点CDR自检属于当时较窄范围，和后续实际自收须分开引用。

PNG/HTML主视图有确定性显示采样上限；点数少的A可能被主图抽样遗漏，精确判断须用完整NPZ和ROI导出。页面裁剪/点选只作用于嵌入显示样本，页面已提示这一范围，不能作为全帧无A/无障碍证明。

## 尚未验收及交付边界

| 未验项 | 结论限制 |
|---|---|
| 独立尘/实体/地面/遮挡与实例标签 | 无准确率、召回、安全或误停收益；ROI候选名不作GT |
| 坡地、远稀疏/暗色/薄杆、浓尘墙与混合边界的大范围真实测试 | 当前保守门控可能过度保U或错误给E/A/G，合成测试不覆盖所有真实情况 |
| M4可靠时钟/自车与目标对应、逐点时间/双回波 | 继续单帧V1-B；不启用未证实材料运动或穿透捷径 |
| RViz/跨进程DDS/GUI | 五Topic CDR及ROOT同进程debug DDS已通过；跨进程、跨机与RViz屏幕尚无验证，Chrome成功不替代它 |
| 原B1同层公平比较、车辆规划/控制与实际停止原因 | 本实现是新的离线启发式算法，不声称胜过B1或可直接减少车辆误停 |
| 实车时延/安全预算与部署 | 当前计算不构成实时或部署批准，不运行车辆节点 |

**需返修的实现阻断项：0；本报告明确未验项保持未验。** 可将当前代码、真实九帧输出、可复核case与命令作为离线原型签收；后续语义核验、训练、生产接线或上车均不由本PASS授权。
