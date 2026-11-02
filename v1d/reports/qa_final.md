# OPDF-V1-D 最终独立 QA

日期：2026-11-02（Asia/Shanghai）。结论：**PASS，限定为本轮离线候选实现、可追溯行为与调试可视化交付。材料识别质量、安全通行、实体真实召回、误停车改善、跨场景泛化和实时部署均未通过认证。** 本轮可停止交付，不据此启用M4、训练或连接控制。

## 真实执行者与复核范围

本次收尾为原QA-04：`/root/qa_04`，线程`01a187a2-e6d8-7650-ac91-cbf49dadbe02`。前段独立实测由QA-04-D复用`/root/qa_v1c_backup`，线程`01a1927f-5e85-7f83-a28b-aa7adf36b515`完成；其用量中断后，本线程接续GUI及文档审计，不冒称重做其全部实验。

已实际读取前段脚本、JSON与测试日志：`qa_source_and_behavior`、`qa_multiscale_sample`、`qa_native_ros1_sample`、`qa_risks_and_local_ground`、`qa_tests.log`。其实际覆盖30帧跨源字段/九决策重构、128原slot×3尺度=384独立球邻域/PCA样本、5源帧×23话题=115条原生ROS1离线消息、局部地面及风险ROI、49项通过测试。本线程独立逐张看新D1五图/D2四图、核原生相机属性与源码，读取690实际跨进程通信证据，重算已存D3统计及低物ROI166行CSV，并交叉核对最终README、综合报告与CLI源码。未重跑昂贵特征、测试、ROS/master/GUI，原bag读取0字节。所有本线程新写均在v1d。

原证据SHA与个人范围见[qa_final_scope.json](../evidence/qa_final_scope.json)，最终文档/CLI/CSV复核收据见[qa_final_document_check.json](../evidence/qa_final_document_check.json)。

## 验收结果与原证据

| 检查 | 判定与边界 |
|---|---|
| 输入与冻结 | 前段独立核入口B241+C668共909项及原slot/字段；主控另核research_ops165、工程316。D开始前B `.gitignore`、C README与历史清单已有差异，按入口实际字节另冻，作者/原因未知。不能宣称全历史从未变。原bag保护仅size/mtime/head4096，非全文件hash。 |
| D1与逐点guard | 原B48保留，Core760625、Strict2354709；候选143分为108显示可抑制及35证据不足恢复，guard后显示2354601。guard只作用于显示，不认证软草或安全忽略。前段独立局部平面、保护与集合复算通过。 |
| D2与消融 | 两模式及uniform-off九决策重构通过；fusion为E374435/A56329/U1930867/G753703，finite3115334、INVALID1204666。新U→A55943，E→U49929仍保留；关uniform后35052个A恢复U。完整radius计数与64/96/96拟合采样分开；384独立样本支持实现一致性，不是材质真值。 |
| 消息/身份/clock | 前段原生115消息抽验通过；另读取主控690 distinct frame-topic、30完整帧、0缺失/差异与4次clock回退证据。raw32字节源布局与派生24字节XYZ/I/RGB/slot分开。`ros1_d2_actual_full/summary.json`自身gui_verified=false，屏幕验收使用下列独立证据。 |
| 新原生固定视角GUI | **通过**。本线程实际逐张查看D1五图（seq245846）和D2四图（seq245847）；组内同原生窗口、相同相机数值、单独目标点云层、Fixed Frame=rslidar，记录camera_equal=true，场景/网格相容。原生librviz窗口抓取源码与属性读回一致。两组源帧不同，不作跨组同帧差异。 |
| D3停止门 | 本线程只重算已存29相邻对：背景NN中位0.4369468m，重叠中位0.6604，描述门接受0/29；M4=false，未改D2标签。局部低NN或数值满秩不认证物理对应/背景静态，translation不解释成对象位移或速度。STOP_M4与实际证据相容。 |
| 文档/入口 | 最终README与综合报告计数、风险、耗时、身份与未验边界相容；复现参数按源码核查，未再次执行命令。返回的两处措辞已修正并重读关项：删除含混solid显示名；将未认证物理事件数量改为同一连续片段、独立事件/跨session资格未认证。 |

新GUI证据：[D1](../evidence/fixed_gui_d1/views/camera_and_layers.json)、[D2](../evidence/fixed_gui_d2/views/camera_and_layers.json)。旧八张跨窗口图视角不一致的问题**不追认通过**，保留原失败记录；新同窗图关闭固定view验收项。新截图仍可见Global Status:Warn，故只认证实际图层显示与视角一致，不认证全部RViz健康、外参或真实物理布局。

主控披露一次依赖查询遗漏MPLCONFIGDIR而产生`/tmp/matplotlib-1vofocz2`自建缓存，后仅精确清理该目录并恢复D环境，记录于[dependency_probe_cache_correction.json](../evidence/dependency_probe_cache_correction.json)。本报告不将“D产物只写D”扩写成从无临时缓存偏离。末次主控端口probe均无监听，不推断原11321何时结束；本线程未接管或停止任何ROS会话。

## 必须保持未关闭的风险

| 严重度 | 反例/证据 | 未关闭事项与下一步门槛 |
|---|---|---|
| 高：实体潜在抑制 | seq245847/slot139114，原U→A，I4，球计数21/93/252；旧low/near/edge与D1hard均未保护，uniform-off仍A。 | **UNKNOWN**材料，不能称已证误删或真尘。优先RAW与邻帧盲审，获得有来源的点/实例参考后评估边缘拒判。无E直A不保证原U没有实体。 |
| 高：低物进入Core | 可能低物ROI166点，37原U进Core。当前收尾独立CSV重算：129 HardProtect=Strict，与37 Core逐slot互斥互补。 | 129仅为算法mask，37不认证地面。guard修108/35不修这37 Core。无独立软硬/地面GT，不能说低硬物全部安全保留或杂草问题已解决。 |
| 高：无独立评价参考 | 五个人工参考仍待提交；同30帧仅约2.9秒连续片段，物理事件/session独立性未认证。 | 行为计数/同源B/C/传统输出不能当GT。不得计算或承诺材料Precision/Recall、误停车改善或跨场景安全性；锁定真实参考及独立测试资格后再评价。 |
| 高：部署与时序 | D2全30共享特征加两模式约1009.04秒，多尺度中位约28.85秒/帧；D3质量门0/29。 | 未达10Hz。播放器rate是预计算回放速度。缺可信对应时M4维持UNAVAILABLE；未上车、未验生产消费者或控制链。 |
| 中：显示解释 | D1 Core、B-G、D2标签与C suspect属于不同域；旧静态D1图143候选，最终ROS仅108 guard显示抑制。 | 不把显示减少、变化颜色、可用mask或数值拟合当物理材质/已确认纠错。A后缺测不等于free，U仍保留。 |

当前没有未修复的离线交付阻塞项；上表科学与安全门槛仍开放，不能被本次PASS覆盖。建议下一阶段先获得139114、低物37点及邻帧的有限真实人工参考，再决定门控或配准验证。本轮审核结束，不自动启动后续实验。
