# OPDF-V1-D：离线算法与真实30帧复盘

2026-11-02。D1、D2及有限D3均已实际运行；新代码、参数、报告、输出仅在本目录。当前为离线候选实验，无独立材料GT，不是生产过滤或安全通行认证。主报告见 [v1d_experiment.md](reports/v1d_experiment.md)，独立审核见 [qa_final.md](reports/qa_final.md)。

## 直接查看已有结果

- [D1近地ROI三维对照](outputs/d1_roi_final/near_ground_rough_vegetation_candidate/d1_sets.png)、[可能低硬物ROI](outputs/d1_roi_final/possible_low_obstacle_unknown/d1_sets.png)。Core是相对地面候选，不等于确认可忽略；这两个ROI的Low-clutter均为0。
- [D1原生RViz同窗固定相机](evidence/fixed_gui_d1/views/)、[D2原生RViz同窗固定相机](evidence/fixed_gui_d2/views/)。每组有实际截图与camera_and_layers.json；旧跨窗口GUI图片不作为同视角证据。截图仍显示Global Status: Warn，未认证所有RViz状态/外参正常。
- [五个RAW邻帧盲审入口](outputs/raw_five_roi/catalog.json)、[D2五ROI对照](outputs/d2_final_five_roi/)、[139114反例](outputs/d2_final_slot139114_comparison/)。材料名均为复核假设；尚无用户独立点级标签。
- [30帧逐帧行为CSV](outputs/d2_final_full_behavior/per_frame_behavior.csv)、[D2转移矩阵/全槽位摘要](outputs/d2_final_full_behavior/run_behavior.json)、[uniform-off消融](outputs/d2_uniform_off_ablation/)、[D3未启用M4的证据](outputs/d3_feasibility_final/summary.json)。均非分类准确率。

## ROS1逐帧与动态RViz：复用现有rn容器

本机`rn`对应既有`ros-noetic`容器。以下三个终端各自先执行：

```bash
rn
source /home/xin/lidar/opdf_v1/v1d/scripts/ros1_env.sh
```

若当前主机shell没有rn别名，以`docker exec -it ros-noetic bash`进入同一容器。环境固定`ROS_MASTER_URI=http://127.0.0.1:11331`、`ROS_IP=127.0.0.1`，缓存和ROS日志只写D；不连接用户原C的11321。11331若已占用，先确认是否为你自己正在使用的D会话，不自动终止任何现有进程。

终端A：

```bash
roscore -p 11331
```

终端B（先设置模拟时间，再开RViz）：

```bash
rosparam set /use_sim_time true
rviz -d /home/xin/lidar/opdf_v1/v1d/configs/opdf_debug_ros1.rviz
```

终端C（默认暂停在指定帧；无需重算D2）：

```bash
python3 -B /home/xin/lidar/opdf_v1/v1d/scripts/frame_review_ros1.py \
  --index /home/xin/lidar/opdf_v1/v1d/outputs/d2_candidate/fusion/debug_frame_index.json \
  --seq 245847 --clock --rate 3 \
  --log /home/xin/lidar/opdf_v1/v1d/evidence/user_player_events.jsonl
```

播放器键入`n`、`p`、`seq 245846`、`play`、`pause`、`rate 1`、`status`、`q`，回车执行。范围245832–245861。播放rate是预计算结果回放速度，不是算法速度。往前跳帧会使`/clock`回退，属于已实测的调试行为；RViz有异常时暂停并重新选择图层，不给生产消费者使用该时钟。

RViz Fixed Frame为实读的`rslidar`；各层来自同帧原始XYZ，派生消息含`raw_slot_id`。只有RAW保留源32字节点布局；派生层为24字节XYZ/I/RGB/slot调试格式。没有补造点、物体、TF或材料GT。

| 显示名/Topic尾名 | 含义 |
|---|---|
| RAW intensity / raw | 原始点强度；可旋转缩放、冻结观察 |
| Classes RGB / class_rgb | D2候选E青绿、A橙、U紫、G灰；INVALID不伪画 |
| Ground G / ground | 冻结B原G，D2本轮固定；不同于下项 |
| Ground Core / ground_core | D1局部锚定地面候选，未改D2标签/占据 |
| Low-clutter ? / low_clutter_candidate | 143点帧候选全集，不认证柔软杂草 |
| Nonground Strict / nonground_strict | 有效原点减D1 Core |
| View minus Low / nonground_display_only | 仅显示再减逐点guard通过的108点帧；35候选因证据不足恢复保留；不是生产删点 |
| B Entity、B Aerosol / b_entity、b_aerosol | 同原槽位的冻结B候选 |
| Entity B-D delta / entity_evidence_change | 新E青、离开E紫红；另有分数变化层点 |
| Aerosol B-D delta / aerosol_evidence_change | 新A红、离开A绿；分数增橙减蓝；是变化而非真实误删/真尘 |
| Suspect REVIEW、E weak conflict | 冻结C诊断语义，来自原B域，不是D新标签判决 |
| Optical、Scan、Spatial | 冻结B特征热度；D新多尺度证据看NPZ/ROI报告，不冒称已换成新热图 |

标准E/A/U/G及`/opdf_v1/retained`（E+U）表示D2融合候选；U依然保留，A后方未知不等于free。详细23个Topic定义、颜色与payload见`outputs/d2_candidate/fusion/schema.json`。

已生成 [opdf_debug_ros1.bag](outputs/d2_candidate/fusion/opdf_debug_ros1.bag)：871514588字节，30帧×23话题=690消息；原生ROS1读回及实际跨进程发布/订阅全量匹配。SHA256：`169aecb14b550a73986b035ac5f79edfc24225f822895442d3b74595f3bebaaa`。仅可视化话题及播放器调试时钟，没有规划/油门/制动节点。

## 主机上的复核与有界重跑

主机`python3`已有numpy/scipy/yaml/matplotlib/pytest；无需安装依赖。B/C导入只读，禁止向旧目录生成pycache。以下在**主机**执行（不要用Noetic的Python3.8跑需要3.10的离线入口）：

```bash
cd /home/xin/lidar/opdf_v1
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
export MPLCONFIGDIR=/home/xin/lidar/opdf_v1/v1d/.cache/matplotlib
export TMPDIR=/home/xin/lidar/opdf_v1/v1d/.cache/tmp
mkdir -p "$MPLCONFIGDIR" "$TMPDIR"
df -h /home/xin/lidar/opdf_v1/v1d
python3 -B -m pytest -q v1d/tests -p no:cacheprovider --basetemp=v1d/.pytest_tmp/user_check
python3 -B v1d/scripts/verify_frozen.py
```

49项实际测试通过，独立日志`evidence/qa_tests.log`。D保护检查以本轮入口字节快照核验B241/C668、research_ops165及原工程316文件；原bag只核大小/mtime/首4096字节，不虚称全文件hash。B `.gitignore`与C README在D开始时已有历史清单差异，已原样冻结，作者/原因未知。

审计偏差：MASTER一次依赖版本查询遗漏MPLCONFIGDIR，matplotlib曾自动生成一个`/tmp`临时缓存；已只清理该确切自建目录并恢复D环境，见`evidence/dependency_probe_cache_correction.json`。没有原始数据/旧文件修改。末次端口探测11331与11321均无监听，原C会话何时结束未知；未停止/接管原C进程。

现有输出应直接复盘，重跑必须选**不存在的D子目录**，先看剩余容量；下例只跑一个D2帧，约35秒，源仍为已完成D1，不重读原bag：

```bash
python3 -B v1d/scripts/run_d2.py --seq 245847 \
  --output v1d/outputs/user_d2_single_check
```

完整可复现入口（下列均为可选，预计算结果已交付；勿重复覆盖）：

```bash
python3 -B v1d/scripts/run_d1.py --output v1d/outputs/user_d1_replay
python3 -B v1d/scripts/run_d1_pointwise_guard.py \
  --source-run v1d/outputs/user_d1_replay --output v1d/outputs/user_d1_guard_replay
python3 -B v1d/scripts/run_d2.py \
  --source-run v1d/outputs/user_d1_replay --output v1d/outputs/user_d2_replay
python3 -B v1d/scripts/run_d2_uniform_ablation.py \
  --source-run v1d/outputs/user_d2_replay --output v1d/outputs/user_uniform_off
python3 -B v1d/scripts/run_d3_probe.py \
  --run v1d/outputs/user_d2_replay/fusion --output v1d/outputs/user_d3_probe
```

D1入口含上界单变量消融；D2同特征分别输出geometry_only/fusion，配置`configs/d2.yaml`标明启发式。全30 D2实际1009.04秒，多尺度中位28.85秒/帧，远未达到10Hz。D1不重算B基础特征，不能把D增量耗时当整条RAW处理速度。D3只是可行性探针，不改标签，M4=UNAVAILABLE。

## RAW邻帧盲审、原slot查询与真实人工参考

先打开`outputs/raw_five_roi/<case>/blind_raw/raw_neighbors.png`，再看算法目录。对应RAW NPZ、case.json、view.json、方法/source hash均已保存。五个`human_review.json`仍PENDING，未由算法替用户填写。图像显示cap只影响绘图，CSV/NPZ统计使用完整原slot域。

```bash
python3 -B v1d/scripts/review_d.py --seq 245847 \
  --bbox 4 7 -2 2 -0.6 1.6 --output v1d/outputs/user_edge_blind
python3 -B v1d/scripts/review_d.py --compare-d2 \
  --case v1d/outputs/raw_five_roi/vehicle_body_edge_candidate/case.json \
  --d2-dir v1d/outputs/d2_candidate/fusion/frames \
  --output v1d/outputs/user_edge_compare
```

全量同slot变化在各帧`*_changes.npz`及`outputs/d2_final_full_behavior/candidate_risk_exact_slots.csv`；ROI导出包含XYZ/I、标签、分数、可用性及原因。D标准reason必须按帧JSON `d2_fusion_diagnostics.reason_bits`解释；原B reason在`b__reason_code`，不能混用继承B diagnostics。

真实人工标注接口见[roi_protocol.md](reports/roi_protocol.md)。提交JSON至少含case源消息SHA、真实reviewer_id、evidence、point_annotations（raw_slot_id、E/A/U/G）或带独立证据的instance_annotations；未标点保持未知。可用`review_d.py --case <case.json> --import-review <真实提交.json> --output <新D目录>`结构校验和保存来源；校验通过不自动认证GT。未提交真实参考前不计算Precision/Recall、真实误停车或全场景性能。

本轮到此停止，不自动恢复标注平台、训练、重构原工程或启用M4。下一步最小工作是优先复核37个低矮Core点和rawslot139114及其邻帧，获得有来源的有限人工参考，再决定算法门控或更可靠时序验证。
