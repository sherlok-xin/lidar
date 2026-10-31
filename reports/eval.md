# OPDF-V1-B EVAL 实现与真实结果验证

日期：2026-10-31（Asia/Shanghai）；责任线程为原RESEARCH-03，当前承担EVAL独立实现。仅写 `opdf_v1/`，不属Phase3、不训练、不读取更多原bag、不修改原工程或research_ops。算法由ALGO实现，本报告仅说明可视化、行为计数、精确复核与调试发布。

## 实现交付

- `opdf/visualization.py`：`render_frame(npz_path, *, output_png, output_html=None, view=None, max_points=30000, roi=None)`。同一finite/ROI、同一按原slot排序的确定性cap、同一视角，四联RAW/LABELS/A_ONLY/E_U。PNG是mplot3d透视；HTML是实际XYZ透视投影、按深度排序的Canvas四面板，可拖拽orbit、滚轮zoom、点选原slot/强度/理由/分数、显示ROI、保存view与截图；不依赖CDN。RAW强度着色只用于显示，E青绿/A橙/U紫/G灰，图例均为heuristic candidates。
- `opdf/evaluation.py`：`frame_metrics`与`write_run_report`输出候选计数、有效点分母、距离/原始Z段比例、模块时间和不可用/拒判数量。U不从分母排除，空分母NA。没有GT，不算Precision/Recall/F1/accuracy或安全/误停性能。L2导入validator核NPZ与侧JSON原消息hash、独立标注声明及真实有效slot，**只验证结构，不认证语义、不计算成绩**。
- `scripts/view_frame.py`：直接读取结果NPZ，生成PNG/离线HTML。
- `scripts/review_roi.py`：原始slot或inclusive bbox精确查询。`exact_slots.npz`保留所选所有slot-aligned特征与reason；`.npy`保存完整精确slot列表，另存来源/原消息与配置hash、定位、view、PNG/HTML和人工记录。显示cap只影响截图，不影响导出。原slot查询可选无效实测槽位作诊断，无效点不画；不存在的slot拒绝。已有case目录不覆盖。
- `scripts/publish_rviz.py`：只发布 `/opdf_v1/raw`、`/solid`、`/aerosol_candidate`、`/unknown`、`/ground` 五个debug Topic，无TF/规划/控制。固体保护集为E+U，因此U也会单独出现在unknown Topic。显式localhost与50..232非默认域guard、最多30次/10Hz。原RAW优先从既有缓存恢复原字段/组织/原point bytes；各消息header/frame保持原值。`--selfcheck`不建节点；`--self-receive`才做有界DDS自收。

相机JSON固定为version1、projection=perspective、target三坐标、distance、azimuth_deg、elevation_deg、fov_deg、up_axis=z；view可传dict或JSON路径。ROI为六个边界或`{bbox:[...],raw_slot_ids:[...]}`交集。PNG/HTML四面板共享相机，但Matplotlib与Canvas并非逐像素相同渲染器。

## 盲复核与回归约定

`--blind`不是把算法类别改成U：盲版导出/HTML实际只含原XYZ、强度、valid mask、原slot，不嵌入labels/scores/reason。PNG也是纯原始3D强度显示；相机仍共享，原NPZ/消息/配置身份在case.json中保留。`human_review.json`中的reviewer/confidence/human_label默认均null、状态PENDING_HUMAN_REVIEW；没有自动答案。只有用户显式输入reviewer与confidence才允许记录其human-label；该输入仍不是已认证独立GT。

`--regress <case目录>`核原NPZ、原缓存与config_snapshot的hash，仅读已有`.ros1msg`缓存，以同一配置/原ablation通过当前pipeline重跑到**新目录**。输出逐slot新旧label/reason、变化数量、代码hash与同view截图；这是行为回归，非正确率或标签真值。盲case回归截图继续不显示算法判断。

## 实际命令与结果

命令均从 `/home/xin/lidar/opdf_v1` 执行，MPL/pytest/Chrome/ROS缓存与测试产物均在本分支。

```bash
MPLCONFIGDIR=/home/xin/lidar/opdf_v1/.cache/matplotlib python3 -m pytest tests/test_evaluation_contract.py --basetemp=/home/xin/lidar/opdf_v1/evidence/eval_pytest_tmp -o cache_dir=/home/xin/lidar/opdf_v1/.cache/pytest -q
```

实际 **8 passed**。覆盖共享真实3D相机与确定性cap、exact ROI/无效slot、全部特征导出、盲HTML无隐藏答案、U分母/ABSTAIN、L2伪造消息hash拒绝以及RViz域guard。此处synthetic fixture只做软件合同测试，不是实际人工标签或性能实验。

真实输入为ROOT已生成的 `outputs/v1b_real9_baseline/frames/middle_seq245847.npz`，没有重新读bag：

- `evidence/eval_real/real_3d.png/.html`：bbox[-20,20,-15,25,-4,5]中81,956有限点，显示7,000个确定性原slot；四面板同camera与sample。已实际打开PNG检查为3D四联；A_ONLY显示样本中1个候选点，**不是全帧A总量**。
- `evidence/eval_real/roi_unblinded/`：bbox[-10,10,-10,20,-3,3]精确62,545槽位、47个slot-aligned特征；完整NPZ独立按bbox重算，slot和reason逐项一致。截图cap3,000不改变62,545的导出数量。
- `evidence/eval_real/roi_blind/`：相同精确槽位，导出仅4个原始字段，未分配reviewer、confidence或label。`evidence/eval_real/actual_check.json`保存实查。

独立新Python进程真实盲CLI也已执行通过（避免测试顺序提前加载mplot3d掩盖依赖问题）：

```bash
MPLCONFIGDIR=/home/xin/lidar/opdf_v1/.cache/matplotlib python3 scripts/review_roi.py outputs/v1b_real9_baseline/frames/middle_seq245847.npz --output evidence/eval_real/blind_fresh_cli --bbox -10 10 -10 20 -3 3 --blind --max-points 1000
```

```bash
MPLCONFIGDIR=/home/xin/lidar/opdf_v1/.cache/matplotlib python3 scripts/review_roi.py --regress evidence/eval_real/roi_unblinded --output evidence/eval_real/regression
```

实际回归完成：全帧label变化0、reason变化0，status=OK；来源/配置hash都核验。结果在`evidence/eval_real/regression/regression.json`，原baseline run输出未改。

本机无Playwright，未安装。ROOT已用实际非盲viewer通过Chromeheadless自检；本执行器另外对盲HTML执行本地headless自检，浏览器子进程需要的正常沙箱提升获准后成功。证据 `evidence/eval_blind_browser_dom.html` 与 `eval_blind_browser_check.json`：`data-rendered=true`、`data-selftest=PASS`，四面板相机一致、改变azimuth导致真实XYZ投影变化。它是实际JS执行验证，不是人工鼠标屏幕验收或RViz成功。

ROS2实际自检命令：

```bash
source /opt/ros/humble/setup.bash
ROS_LOCALHOST_ONLY=1 ROS_DOMAIN_ID=218 ROS_LOG_DIR=/home/xin/lidar/opdf_v1/evidence/eval_ros_logs python3 scripts/publish_rviz.py outputs/v1b_real9_baseline/frames/middle_seq245847.npz --domain-id 218 --selfcheck --log evidence/eval_rviz_serialization.json
```

五条消息CDR往返PASS，raw=原缓存point bytes，frame=rslidar、stamp_ns=1789629270666355610保持不变；raw144000槽位，solid84492、aerosol_candidate11、unknown70455、ground19976。后四项是算法候选/保护集合数量，非GT计数。没有创建ROS节点，没有DDS/RViz屏幕验收；`rviz_gui_verified=false`明确保留。

后续用户本机可在同显式本地域中执行不带`--selfcheck`的有界发布，加`--self-receive`可额外检查DDS；RViz固定frame用原rslidar、Sensor Data QoS。这里只准备调试工具，不发布TF或替换原始frame/stamp以伪造可视成功。

## 已遇限制与仍未验证

- 本机Matplotlib用户版本与系统预加载mpl_toolkits冲突：ROOT已修主render的同版本toolkit路径；盲截图独立执行相同局部注册，fresh CLI通过。没有安装包或修改环境文件。
- 当前无DISPLAY/Xvfb；不能宣称RViz或本机屏幕人工交互成功。Chromeheadless成功不替代这些验证。
- HTML ROI查询/点选只覆盖显示样本，界面和导出JSON均明确这一点；精确全NPZ查询须用review_roi。少数A可能未落入cap，不能拿显示比例当全点比例。
- shared camera/bytes/回归一致只证明软件行为可复查，没有证明E/A/G语义正确、点云几何完好、车辆不会漏检或误停车减少。

EVAL实现与本轮验证已完成，交ROOT集成与QA；未开始任何训练、调模型或实际车辆实验。
