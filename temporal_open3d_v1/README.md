# 可移植的历史实验代码

[完整报告](reports/temporal_experiment.md) · [QA](reports/qa.md) · [模型与兼容边界](reports/open3d_baseline.md) · [方法定义](reports/temporal_methods.md) · [原始指标入口](analysis/197/metrics.csv) · [环境与复现](../docs/REPRODUCING.md)。

来自实际训练/推理/评价源码，发布副本将数据与运行位置改为配置，增加缓存身份隔离；原冻结文件不变。网络上游提交、模型源码摘要、兼容补丁的生成逻辑见 randla_core.py。训练许可与代码可审阅不同，未转载整份上游工程。

全部实验有8个网络任务（public-N0、joint-N0 和三种子的 pair-N0/N1）、14×3探针；三种子197、241、3090。每个正式配对 epoch 遍历227个中心，4096点/块、batch 4，最多30个epoch，每3个epoch完整验证，4次未改善提前停。N1用8个时序/可用性通道；精确清单与发表版代码版本不可混用。[权重收据](analysis/checkpoints.csv)保留真实摘要；未声称发布权重。

[公开中心清单](manifests/public_centers.json)只包含384个公开训练/验证/测试中心及其过去帧来源引用，沿用完整清单的角色、顺序及原点域。**这是子集，不是444中心完整冻结清单**。它可用于读取、审查与取得合法公开数据后的公开单帧重跑；不能凭它复算本地风险、恢复旧完整训练状态或重现完整联合实验。
