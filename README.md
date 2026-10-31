# OPDF-V1-B：独立单帧纯算法原型

本分支已在指定本地真实bag的三段共9帧运行。入口是M0→M1单平面→M2局部强度→M3扫描/3D几何→M5保守E/A/U/G→M6三维复盘，不是Phase3标注平台或师兄B1移植。

E、A、G都是启发式候选；U保留，INVALID不画成点，缺测不等于自由空间。未使用不存在的Doppler/return ID/逐点时间，没有监督训练、人工GT性能或真实误停车收益。未运行原工程/车辆控制。原bag、原工程、research_ops不改。

## 已有结果

- 最终运行：[outputs/v1b_real9_final/](outputs/v1b_real9_final/)。9帧833106个有效点，行为计数E96183、A82、U532919、G203922。
- 实验说明：[reports/v1b_experiment.md](reports/v1b_experiment.md)，独立验收：[reports/qa.md](reports/qa.md)。状态和局限以报告为准。
- 逐槽原索引/可用性/分数/原因/中间量：`frames/*.npz`；来源/时间/模块自检：配套`.json`；配置、源码hash和输入清单均冻结在run目录。
- `metrics.csv`是行为指标，不是Precision/Recall；`ablations.csv`和`sensitivity.csv`只在同RAW域的三代表帧复用同一模块证据，未与B1排名。
- `figures/*_3d.png`为真实xyz的固定相机四联；`interactive/*.html`无CDN/服务器依赖，可旋转/缩放/查显示点slot/导出视角与截图。大场景默认显示抽样30000点；`review_roi.py`的精确导出不受显示cap影响。

## 本机环境与有界抽帧

使用已有Python3、NumPy、SciPy、Matplotlib、PyYAML、pytest。没有安装Open3D或Plotly；三维固定图用mplot3d，交互用浏览器真实xyz透视和深度排序。当前工具进程无DISPLAY，已实际做Chrome headless浏览器验证，未看到RViz屏幕。Matplotlib系统/user-site冲突由进程内匹配toolkit路径处理，没有改安装或全局环境。

```bash
cd /home/xin/lidar/opdf_v1
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR=/home/xin/lidar/opdf_v1/.cache/matplotlib
export OPENBLAS_NUM_THREADS=2
export OMP_NUM_THREADS=2
python3 -c 'import numpy,scipy,matplotlib,yaml; print(numpy.__version__,scipy.__version__,matplotlib.__version__)'
python3 scripts/inspect_bag.py /home/xin/lidar/data/2026-09-17-15-14-07_1.bag
```

现有`manifest.json`和`samples/`已包含真实9帧缓存（约41MB），优先直接复用。若需重新抽取，使用**新的**目录；脚本不覆盖原bag或已有缓存：

```bash
python3 scripts/inspect_bag.py /home/xin/lidar/data/2026-09-17-15-14-07_1.bag \
  --extract --output-dir /home/xin/lidar/opdf_v1/samples_reextract \
  --frames-per-window 3 --max-frames 9 --max-read-mib 160
```

每帧按实际H/W/stride解析，保留原slot和每点原字节；固定候选相位置换来自`configs/mapping_phase2.json`并存hash。W1729/行padding/大小端/NaN/空帧是回归测试，不能据此宣称本bag9帧实际出现1729。缺列padding与实际无效槽位分开。

## 运行V1-B及测试

```bash
python3 scripts/run_v1b.py --manifest manifest.json --config configs/v1b.yaml \
  --max-frames 9 --render --ablations --sensitivity
python3 -m pytest tests --basetemp=/home/xin/lidar/opdf_v1/.pytest_tmp \
  -o cache_dir=/home/xin/lidar/opdf_v1/.pytest_cache -q
python3 scripts/verify_protected.py
```

每次运行新建run_id目录；不要手写已有run_id。若用重新抽取的缓存，将manifest改为`samples_reextract/manifest.json`。默认配置均是显式调试启发值，没有GT最优含义。处理错误会保留有效点为U并标ERROR/ABSTAIN，CLI不把ERROR当成功。

## 离线真实3D与精确ROI复核

```bash
xdg-open outputs/v1b_real9_final/interactive/middle_seq245847.html
python3 scripts/view_frame.py outputs/v1b_real9_final/frames/middle_seq245847.npz \
  --png outputs/custom_3d.png --html outputs/custom_3d.html \
  --view outputs/v1b_real9_final/view.json --bbox -10 10 -10 20 -3 3
```

HTML拖任一panel会同步旋转，滚轮缩放，点击显示点查看raw_slot/XYZ/I/score/reason；保存view.json后用`--view`重现。RAW按源intensity着色，百分位只用于显示，不改算法输入、不代表物理反射率。四panel共享相机、裁剪和同一显示采样池；A_ONLY的显示数可能小于全部A，需精确ROI/slot查询。

```bash
python3 scripts/review_roi.py outputs/v1b_real9_final/frames/middle_seq245847.npz \
  --output outputs/my_review --bbox 7 10 1 4 -1 2.5 --max-points 30000
python3 scripts/review_roi.py outputs/v1b_real9_final/frames/middle_seq245847.npz \
  --output outputs/my_blind_review --bbox 7 10 1 4 -1 2.5 --blind
python3 scripts/review_roi.py outputs/v1b_real9_final/frames/middle_seq245847.npz \
  --output outputs/my_slot_query --slots 138364
python3 scripts/review_roi.py --regress outputs/my_review --output outputs/my_review_regression
```

case输出精确slot集合、完整特征（非盲）、来源/配置hash、视角、PNG/HTML和`human_review.json`。盲模式只含原始字段，不嵌入标签/分数/理由。`reviewer/confidence/human_label`默认null，不生成假人工意见。真实用户可显式提供`--reviewer`、`--confidence`、`--human-label`及`--note`；这些自述仍不自动认证独立GT。案例回归读取冻结缓存/配置，不重读bag，报告行为变化而非准确率。

已存三例位于最终run的`cases/`：车辆形结构候选、近地粗糙/杂草候选、A与表面混淆风险。对象具体材料身份均UNKNOWN，人工复核待完成；不声称确认车辆/草点或误删真值。

## 可选ROS2/RViz2调试

只用当前bag实际frame `rslidar`和原header stamp，仅发布五个`/opdf_v1/`点云Topic。`solid`明确为E+U保留云，不是独立确认实体。以下先做无节点序列化检查：

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=104
export ROS_LOCALHOST_ONLY=1
export ROS_LOG_DIR=/home/xin/lidar/opdf_v1/evidence/ros_logs
python3 scripts/publish_rviz.py outputs/v1b_real9_final/frames/middle_seq245847.npz \
  --domain-id 104 --selfcheck
```

本机图形终端A运行：

```bash
rviz2 -d /home/xin/lidar/opdf_v1/configs/opdf_debug.rviz
```

同环境终端B运行（有界重复同一帧，非连续序列或实时性能测试）：

```bash
python3 scripts/publish_rviz.py outputs/v1b_real9_final/frames/middle_seq245847.npz \
  --domain-id 104 --repeat 20 --rate 2
```

已实际通过同一节点内五topic各3次发布/订阅自收，回调检查原header和完整data字节一致；未验跨进程RViz画面或物理坐标标定。若实际bag的frame改变，先读源metadata再改Fixed Frame，不能伪造TF。无规划/油门/制动发布，禁止启动原ROS1 launch。

## 当前限制

原型CPU计算约0.77–0.82秒/帧，含绘图存储的9帧运行约30秒，不是10Hz实时实现。单平面/低强度/扫描散乱仍可能混淆草、低石、车身边缘与尘；G不授予安全通行。M4缺经核平台/目标对应，固定退回单帧，不预测生成点。无GT/B1公平比较/跨session验证，也未证明减少真实误停车。下一步先复核候选ROI与地面误分，再决定优化或新实验；本分支不恢复Phase3、不自动训练或上车。
