# 数据契约 V1

一条采集可以有多种来源表示。dataset/sequence/sensor/ordinal（或既有经审核来源 UID）确定帧，不能用毫秒文件名覆盖。sequence.json 记录序列格式、来源、证据等级与范围；frames.jsonl 保留 source_ref、point_ref、label_ref、处理域、原索引域、顺序、各自的时钟状态、姿态/标定状态和 stored/valid。源点索引是整数，不与坐标拼成 float32。纳秒时间为十进制字符串或缺失；记录时钟、消息header、包内时间与行序分开。0值/重复不认证采集日期。event_group 是防泄漏分组依据或明确的未认证候选，不是有同一物体的跟踪真值。

读取结果包含 xyz、attributes、attribute_available、source_point_index、semantic_raw、semantic_source_schema、task_label、supervision_mask、entity_type、frame_meta；另有几何有效掩码。可读完整存储槽和同步过滤后的视图。不可用的标签、位姿、标定等不生成占位真值；无标签点不计 TN。source_point_index 按来源分别是 NPY 行、BIN 存储槽、PLY.original_index 或对应云消息内的原槽；解码原始网络包另记包、块与通道关联。PC2 按字段表、stride、字节序和 organized 形状读取。回投或配准最近邻只能是模型/几何估计，不是原点身份。

时序样本只从同角色、同事件和同序列的合资格过去取；同一时钟、匹配文件或能读里程计不代表对齐可靠。没有合法历史返回不可用。不能使用未知是否看过未来的累计地图或派生运动缓存作因果输入。
