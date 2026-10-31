# OPDF-V1 数据接口与 M0 输入交付

日期：2026-10-31（Asia/Shanghai）。执行器 DATA-01。此为独立 OPDF-V1 分支，未恢复 Phase3；本次短续仅完善缓存校验、测试与报告，没有重新读取/抽取源bag或新增样本，也没有运行ROS节点。

## 已交付接口

- `opdf/cloud_schema.py`：CONTRACT约定的`FrameData`字段，以及`metadata()`、`to_image()`、`from_image()`、`point_bytes()`。
- `opdf/io_rosbag.py`：`decode_pointcloud2()`、`extract_frames()`、`load_cached_frame()`，另提供有界`inspect_bag()`。
- `scripts/inspect_bag.py`：可实际执行的索引检查/`--extract`命令行。
- `tests/test_io_schema.py`：13项合成回归测试，明确不作为实测场景证据。

原始槽位总数始终为实际`H*W`，包含非有限XYZ，`raw_slot_id=uint64 arange(N)`。按消息的实际height/width/point_step/row_step读取；`raw_data`保留全部行padding，`point_bytes()`仅提取原槽位字节。NaN位模式与未声明槽内填充不解释成额外字段，也不因转图删除。默认加载`configs/mapping_phase2.json`固定置换并记录SHA256；这是几何候选布局，非厂家束/逐点时间认证。非80高度默认标记映射不可用，供pipeline保守ABSTAIN；缩宽帧不虚构缺失列或回波。

缓存加载会核对所有已提供的`raw_message_sha256`、`sha256`及嵌套fingerprint消息SHA，防止正确的顶层别名掩盖冲突的嵌套指纹。该修订没有改变API。缓存/sidecar来源仍是记录级provenance，不构成签名认证，也不自动验证整个源bag哈希。

## 九帧真实输入与本地文件核查

唯一实测源：`/home/xin/lidar/data/2026-09-17-15-14-07_1.bag`，以`rb`打开。本轮直接核查本地文件的ROS1 V2 magic、bag头、首64KiB及最终connection/CHUNK_INFO索引，没有盲用外盘偏移，也没有全量读取约2.3GB文件。

[manifest.json](../manifest.json)为正式入口；其中`frames[].path`相对`output_dir=/home/xin/lidar/opdf_v1`解析，各缓存有同名JSON sidecar。

|项目|实际记录|
|---|---|
|本地文件大小|2,298,545,120B|
|首64KiB SHA256|`7f31e71b6129997c8bc181aa049058ae3bf3071c05e5a7ef24bf9ad6f11b0ef6`|
|最终index_pos|2,298,434,969，位于本地EOF内|
|头/最终索引声明|464 chunks、14 connections，数量一致|
|raw topic/索引帧数|`/hesai/pandar_points`，463帧（索引声明，不是全程解码数）|
|实际窗口|前/中/尾各3连续帧，共9帧；选中chunk索引0/1/2、230/231/232、460/461/462|
|源实际读取字节|44,723,210B，包含头/索引/所选chunk等实际文件读取|
|其中chunk载荷|44,546,992B|
|上限|160MiB读取、60帧；本次9帧|
|序列化缓存总量|41,473,017B（9×4,608,113B），小于100MB|
|首次抽取耗时|0.176436秒；这是该次受系统缓存影响的耗时，不是冷盘/实时性基准|
|源前后stat|size/mtime一致；未计算整个bag哈希|
|状态/失败|COMPLETE；failures=[]|

实际帧：early seq245616–245618、middle seq245846–245848、late seq246076–246078。九帧均为80×1800，字段x/y/z/intensity、point_step32、row_step57600；每条原序列化消息SHA256、整数纳秒时间、连接/chunk/消息原偏移均在manifest与邻接JSON，不用图片或系统输出替代源记录。本轮没有从这个本地bag实测1729宽帧；1729、行padding和大端等由下述合成回归验证。

首次真实执行命令及输出保存在[命令结果](../evidence/data_extract_command.json)，stderr为空：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 opdf_v1/scripts/inspect_bag.py \
  /home/xin/lidar/data/2026-09-17-15-14-07_1.bag \
  --extract --output-dir /home/xin/lidar/opdf_v1
```

此命令拒绝覆盖已有manifest或cache，不应为复现而直接重跑并覆盖本次输入。后续算法直接调用`load_cached_frame(cache_path)`使用这9个原始缓存；不必重读bag。父控已据此进行M0 pipeline运行，算法行为及集成验收由父控/QA另报，本报告不声称算法准确率或GT。

## 实际回归测试

2026-10-31短续实际执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s opdf_v1/tests -p 'test_io*.py' -v
```

[最终日志](../evidence/data_io_tests_m0_final.log)：**13项通过，0失败**（0.345秒）。此前12项记录保留在`evidence/data_io_tests.log`。

覆盖：80×1729动态宽度、原slot/image往返、完整32B槽位字节往返、行padding保留、大端数值、指定NaN payload与Inf有效掩码、零宽/完全空帧、非80高度映射不可用、非法offset/重叠/重复字段/type/count、截短/多余序列化字节、短row_step、错误image维度/非置换索引、缓存数据与metadata/fingerprint哈希冲突，以及实际读取预算在额外read前停止。测试fixture只在`opdf_v1/tests/`临时目录内创建并清理；没有以合成数据替代九帧实测输入。

## 边界与正式提交

新增代码/日志/缓存/报告均在`opdf_v1/`。原`research_ops`、原工程和源bag保持只读；禁写bytecode以免旧cache被改。没有安装依赖、启动ROS/车辆节点、改ground/algo/viewer或生成语义GT。首64KiB哈希与源stat不是全文件完整性证明；索引完整不等于全载荷语义完整；三个短窗也不是三个独立实验事件。

**DATA-01接口、真实九帧manifest、13项测试与本报告正式提交。待父控统一集成检查和独立QA。**
