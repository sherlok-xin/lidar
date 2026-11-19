# 复现路径与证据等级

代码依赖见根目录 requirements.txt；历史 GPU 镜像为 Python 3.12.3 / torch 2.6.0a0+df5bbc09d1.nv24.11 / CUDA 12.6 / numpy 1.26.4 / scipy 1.14.1 / scikit-learn 1.5.2，单卡 RTX 3090。发布依赖文件不安装或升级主机驱动；原实现是固定上游 RandLA 前向图+自有采样、训练及投票，不是未经修改的原生 Open3D pipeline。原生 GUI 另需 ROS1 Noetic、RViz、可用的显示环境。

先在有权使用的数据盘设置 DATA_ROOT（内有 dataset_polvo 等原目录）、DERIVED_ROOT（仅写派生数据）、RUN_ROOT（全新的本次任务目录），OPEN3D_ML_ROOT 指向本地固定版本上游源码。默认不下载数据。公开版不含轨迹、私有标签、旧机器路径或逐点预测。

从仓库根目录：
```bash
python3 -B temporal_open3d_v1/tests/test_temporal.py
python3 -B temporal_open3d_v1/tests/test_evaluate.py
cd temporal_open3d_v1
(cd manifests && sha256sum -c public_centers.json.sha256)
python3 -B - <<'PY'
from data_protocol import read_manifest,load_frame
m=read_manifest("manifests/public_centers.json")
r=next(r for r in m["frames"] if r["role"]=="train")
f=load_frame(r); print(r["uid"],len(f["xyz"]),f["valid"].sum())
PY
```

取得合法数据并核对上游提交 a3d0f7a51d4eef0b94b9000a7d74af05e2d54c4f 后，以下为**历史训练复现说明，本轮未运行新训练**：
```bash
python -B network_train.py --manifest manifests/public_centers.json --model N0 --scope public --seed 197
```
完整联合/配对历史重建须获得私有授权的原444中心清单及其 .sha256、配套原始标签和运行目录，不能用公开子集假冒。用完整清单和训练/验证/测试全量原分数执行：
```bash
python -B evaluate.py --manifest "$FULL_MANIFEST" --runs "$RUNS_ROOT" --out "$NEW_EVAL"
python -B summarize.py --runs "$RUNS_ROOT" --analysis "$NEW_EVAL"
python -B window_sensitivity.py --runs "$RUNS_ROOT" --manifest "$FULL_MANIFEST" --out "$NEW_EVAL"
```
权重只能从获授权的内部保管者取得，放到 RUNS_ROOT 下对应任务名；核验 analysis/checkpoints.csv 的 SHA-256。网络目录需 best.pt、config.json、preprocessing.json；做 N1 回退还需相同协议/种子 N0 的对应预测。network_export.py 只允许代码指纹一致，或 release_compatibility.json 列出的原源码和可移植源码双摘要对。它不会把换清单运行认作原权重的正式复现。恢复训练的验证结论是状态可加载，但下一参数更新未达到逐位相同，不要把它写成严格确定性复现。

历史报告中的私有逐帧清单、原始运行目录、额外 QA 输入及错误点文件需单独取得；这些引用用于识别当时的证据。仓库实际交付的文件以根目录 publication_manifest.csv 为准。
