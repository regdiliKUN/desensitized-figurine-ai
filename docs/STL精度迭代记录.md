# STL 产出物 59 轮迭代记录

对象：`E:\AI` 现有项目的 STL 链路产出物 —— `mesh_fidelity.py`、`convert_3d.py`、
`fig.py`、`repair_mesh_blender.py`、`tests/test_mesh_fidelity.py`、两份复审报告与最终
STL/报告/渲染图。

约束（全程遵守）：核心需求（参考图驱动的 STL 几何保真 + 可打印性）与整体结构不变；
不引入未使用的技术选型；每轮只做一个质量维度上的实质改动，改动后立刻自检；
自检失败如实记录并修正，不做凑数式修改。

维度分布：正确性 R1/R2/R6/R12/R14/R18/R23/R24；边界情况 R3/R4/R5/R13/R15/R16；
性能 R7/R8/R9/R10；一致性 R11/R17/R22；完整性 R19/R21；可读性 R20；
可复现性/边界情况/一致性 R25（交付复核时发现的换环境缺陷）；
完整性/正确性 R26（深层复审发现的文件级验收缺口，见下文）；
完整性/一致性/边界情况 R27（再深一层发现"复验只是旁路工具、主链路未闭环"）；
完整性/正确性/边界情况 R28（复审落地模型连通性，发现"多实体也判水密、悬空碎块从未被验收"）；
正确性/完整性/一致性 R29（把 R28 只告警的碎块真正从成品中剔除，并重跑转换产出单实体 `final5`）；
可复现性/一致性/完整性/边界情况 R30（发现 `final5` 只能绕过产品入口、直接跑底层脚本才生成，
把三项质量门禁接到 `fig.py` 与 `control_server.py` 并做逐字节复现验证）；
边界情况/正确性/一致性 R31（复审**验收工具自身**时发现独立复验假定 STL 永远是清单第一个输出，
用户默认的多格式导出会被误判 FAIL，改为按路径定位并补 6 项回归）；
正确性/完整性/一致性 R32（再深一层发现独立复验只信主链路汇总的 `pass` 字段，
逐项 `checks` 被写反/清空仍能 12/12 PASS，改为逐项核对 + 与独立重算的几何判据交叉比对）；
正确性/边界情况/一致性 R33（再换一侧复审 `verdict` 自身，发现裸 `all(values())` 可被
字符串/整数/删减判据/整体替换伪造键绕过，按 `build_verdict` 固定契约校验结构、
重算汇总并与磁盘几何交叉绑定）；
正确性/一致性/可读性 R34（把上一轮深审搁置的真实缺陷做实：`verdict.pass` 实为
「内存判据 ∧ 文件级复验」的复合结论，R33 只按内存判据重算，会把诚实的不合格报告
误报为「汇总不一致」；改为按复合语义重算、精确分类诊断，并把跨模块契约核验固化为回归）；
正确性/一致性/完整性 R35（复审「清单与报告是否互相印证」时发现把 `file_verification`
整段删掉即可静默退回旧口径，用清单作为第二证据源建立存在性契约、恒定保留检查项并补强制开关）；
正确性/边界情况/一致性/可读性 R36（复审**验收工具的调用契约与证据写出**：发现 `--stl-only`
会把用户显式传入的 `--report` / `--manifest` / `--require-file-verification` 静默丢弃却仍
PASS，`--json` 写盘失败会抛裸 traceback、误指向 STL 更会覆盖交付成品；改为参数冲突显式拒绝、
原子写与证据文件保护）。
正确性/边界情况/一致性 R37（再深一层复审**畸形证据文件**：顶层为数组/字符串/null 时复验抛裸
`AttributeError` + traceback + rc=1，与「验收不通过」混淆；`extents_xyz` 畸形值直接让复验崩；
改为顶层对象校验、畸形数值判该项 FAIL、残余属性异常兜底映射 rc=2）；
边界情况/完整性/一致性 R38（把 R36 自认的残留风险做实：实证 `--json` 覆盖同目录 `run.log`
与三视图仍 rc=0；改为 `evidence_paths()` 枚举全部派生证据 + 「目标必须 `.json`」通用护栏）。
正确性/边界情况/一致性 R39（换到**主链路生成侧**复审：发现 `build_verdict` 对跳过/畸形指标
抛栈中断导出，`bool("false")` 与 `False == 0` 会把不合格报告判成 PASS；改为有限数值 +
严格布尔/零值契约，与复验侧 R33/R37 对齐）；
正确性/一致性 R40（换到**报告元数据生成源头**深审：实证 `save_report` 的 `setdefault`
让假/旧溯源哈希、伪 schema 与假指标口径原样落盘，源文件缺失时字段静默省略；改为权威值
覆盖 + `metadata_corrections` / `source_hashes_unverifiable` 审计）；
完整性/正确性/边界情况 R41（实证**报告里两个溯源哈希完全无人消费**：改成
`TAMPERED_INPUT` / 全零 / 整段删除，独立复验仍 12/12 PASS；新增默认关闭的
`--require-source-provenance`，按「报告 ↔ 清单 ↔ 磁盘源文件」三重印证，并纳入
`--stl-only` 冲突契约，默认输出逐字节不变）；
正确性/完整性/一致性 R42（把残留风险第 13 条**做实**：实证把 `final_mesh.silhouette_iou`
改成 0.20、`min_iou` 改成 0.99、`aspect_error_pct` 改成 99，独立复验仍 12/12 PASS；
现按「报告 ↔ 清单 parameters」双源阈值重算两项数值判据，并把生成侧宽高比容差的
魔法数提成两侧共享常量。默认生效、不增检查项、不改 12 项口径，正常报告输出逐字节不变）；
完整性/正确性/边界情况/一致性 R43（换到**交付证据生成链**深审，并修复一次真实发生的
证据误伤：三视图被替换/删除后复验仍 12/12 PASS，且清单里没有任何哈希可用于发现或恢复；
现新增零依赖 PNG 容器 CRC 校验、`--write-evidence-index` 证据基线与
`--require-evidence-index` opt-in 门禁，校验 SHA256/字节数/尺寸/三视图互异/日志非空/
路径不越界，默认输出逐字节不变）；
正确性/完整性/边界情况/一致性 R44（把 R43 残留风险第 17 条**做实**：实证把侧视图
换成另一模型的合规渲染图并同步更新证据基线，旧复验仍 13/13 PASS —— SHA256 只能
证明「文件与基线自洽」，不能证明像素来自本次 STL；现新增零依赖 PNG 像素解码与
前景轮廓比例绑定，front/back 对齐 X/Z、side 对齐 Y/Z，作为 `evidence_index_valid`
的内部子判据，不新增检查项、默认输出零变化，并补 7 项回归）；
边界情况/正确性/一致性 R45（对 R44 **刚引入的新解码器**做深审，把「畸形 IHDR
导致裸 traceback」做实：CRC 完好的 `2^32×2^32` 声明能通过容器校验，但 C 层解压
上限抛 `OverflowError` 且无人捕获；现把单边尺寸/像素数/解压字节三项上限显式化，
残余资源异常统一映射 rc=2，并补 3 项回归）；
一致性/正确性/边界情况/完整性 R46（换到「生成侧 ↔ 复验侧」契约层深审，做实两条
自相矛盾：缺 `trimesh` 的 CLI 裸 Traceback + rc=1 把执行错误伪装成验收不通过；
`--write-evidence-index` 不跑 R44 几何绑定，能对换模型图打印 `[OK]` 写出复验
必然 FAIL 的基线。现新增零依赖 STL 本体包围盒解析让两侧共用判据、缺依赖统一
rc=2，补 8 项回归；基线 schema 与交付逐字节不变）；
一致性/正确性/边界情况/可读性 R47（把 R36 同类缺口换到「写基线」独立动作：
实证 5 个验收硬门禁被静默吞掉仍 `[OK] rc=0`；现把 8 类冲突收进
`check_mode_contract` 唯一真值，CLI 不再各写一份，补 4 项回归）；
正确性/边界情况/一致性/可读性 R48（再换到**「输出目标覆写」**层面：实证
`--write-evidence-index --evidence-index` 指向报告/清单/复验结果/任意既有
JSON/他人合法基线时全部 `[OK] rc=0` 静默覆写；现补写基线专用的 protected
集合与「目标已存在须属本次 STL」内容护栏，并把写出诊断参数化，补 5 项回归）；
正确性/一致性/完整性 R49（换回**主链路生成侧**复审 R46 的副作用：
`geometry_checks` 改抛 `MissingDependencyError`（RuntimeError 子类）后，
`verify_exported_stl` 的 `except ImportError` 成死代码，缺依赖被
`except Exception` 吞成一句「几何复验失败」且与文档承诺的 skip 语义相反；
现显式分类 `dependency_missing` 并结构化 fail-closed，补 2 项回归）；
正确性/一致性/边界情况 R50（实证把证据基线 `front_view` 改指向同目录另一张
合规 PNG 并同步改哈希/字节数仍 13/13 PASS —— 角色只验集合不验文件名，
正面渲染图可整体脱出哈希链；现以 `_evidence_names` 为单一真值强制绑定，
补 3 项回归）；
正确性/完整性/边界情况/一致性 R51（把 R44「只比宽高比」的两类绕过做实：
比例凑对的纯色矩形、改绝对取景但比例不变的轮廓图都能 13/13 PASS；
现增加前景轮廓形状指标（填充率/逐行宽度变异/四边背景同质性）与
三视图在同一正交相机下的像素尺度互校，补 5 项回归并升级两处正例夹具）；
正确性/边界情况/一致性 R52（实证清单/报告使用相对路径、从别的 CWD 复验时
合法交付被误判 FAIL；现统一按证据文件自身所在目录解析，覆盖清单输出、
`file_verification.stl`、输入溯源三处，补 4 项回归）；
性能/正确性 R53（`geometry_checks` 两次完整解析 37MB STL、单实体又重算
一遍体积；现单次加载 + `copy()/process()` 并复用已算体积，用「load 恰好
一次」「多实体不被短路」「真实交付指标逐字段不变」3 项回归锁定）；
一致性/完整性/可读性 R54（把 R48 自认的残留风险做实：两份 protected
手工列表靠回归偶然锁定；现由 `DELIVERY_ARTIFACTS` 单一清单派生，
新增派生产物两种动作自动同步保护，补 3 项回归）；
正确性/边界情况 R55（显式 `--ref-image` 失效时旧链路仍 rc=0 导出无保真报告的 STL；
现按「显式要求 / 自动发现 / 明确 opt-out」三类区分，显式失效一律 rc=2 且导出前停止）；
正确性/完整性 R56（实证三张菱形假图凑齐全部形状统计量后仍全过；现用 STL 三角形
正交投影掩膜与 PNG 前景算轮廓 IoU，阈值 0.65，仅在显式证据验收启用）；
正确性/完整性/一致性 R57（实证导出器写一半抛错会把既有完好成品截成半成品；
现 8 种格式统一 staging → 回读复验 → 原子替换，失败只清理临时文件）；
正确性/完整性/边界情况 R58（实证 HTTP 200 的 JSON 错误页被当成合法 GLB 覆盖既有成品；
现按目标类型校验魔数/GLB 长度/PNG 签名，改用唯一临时文件并 finally 清理）；
边界情况/正确性 R59（`Retry-After` 为 RFC 7231 HTTP-date 时 `float()` 裸抛 ValueError；
现统一解析秒数与日期、夹到 [0,30]、非法值退回指数退避）。
R55–R59 全部不改几何、不改默认输出、不重新生成交付基线。

---

## 一、初始版本基线（迭代前）

| 项 | 初始状态 |
|---|---|
| 测试 | 9 用例；`TestAlignment.setUpClass` 未实现"样本缺失跳过" |
| 报告 | 无 schema 版本/时间戳/输入哈希/指标口径；`aspect_error_pct=0` 被放在显眼位置却只是强制对齐的自检值 |
| 报告可信度 | `build_report(extra=...)` 可静默覆盖 `silhouette_iou`、`watertight` 等核心指标 |
| 输入 | 忽略 EXIF 旋转；RGBA 透明区被当成黑色前景；损坏/全白图直接抛异常 |
| 退化网格 | 空网格 / NaN·Inf 顶点会让 `min()`、`astype(int)`、`mesh.area` 抛异常 |
| 参数 | 10 个数值参数无区间校验；负高度会做负缩放 |
| 退出码 | 导出失败仍返回 0；自动化无法察觉 |
| 数据安全 | 默认 `--to` 含 `glb` 且默认输出目录 = 输入目录，会**覆盖原始输入 GLB** |
| 朝向 | 正/背面只靠"最小旋转角"假设，IoU 噪声可把背面选成正面 |
| 性能 | 拓扑统计用二维 `np.unique(axis=0)`（0.89s）；视觉外壳逐行 Python 循环；朝向搜索 24 次重复做 40 万点有限性过滤；表面采样固定 297 万点 |
| 可复现 | 无 manifest，产物被覆盖后无法追溯命令/输入 |
| 环境兼容 | `mesh_fidelity.py` 5 处 `from scipy import ndimage` 硬依赖；缺 scipy 时参考图预处理直接 `ModuleNotFoundError`，换台机器 14/32 用例报错；`fig.py` 却已有"无 scipy 退化"约定，跨模块不一致 |
| 文件级复验 | 无独立复验程序；`verdict` 只评价内存网格，5 项 checks 无"法线外向/正体积"，也没有核对磁盘 STL 与报告/清单是否同一个东西 |
| 验收 | 无顶层结论；非水密仍静默导出 |

---

## 二、逐轮记录（R1–R59）

| 轮 | 维度 | 本轮目标 | 具体改动 | 改进理由 | 自检结果 |
|---|---|---|---|---|---|
| R1 | 正确性/可读性 | 消除互相矛盾的坐标契约 | 统一 `_fit_mask`/`silhouette`/展示层文档为"行号递增 == +Z 递增，第 0 行脚底"，补契约说明 | 旧 docstring 一处说第 0 行是头顶、一处说是脚底，会误导后续维护者写出倒立朝向 | PASS：合成"+Z 宽"网格验证投影与参考掩膜方向一致（7707 vs 991、1566 vs 810），旧矛盾文本清除。**首次自检断言方向写反，修正后通过** |
| R2 | 正确性 | 让注释承诺的"校正前误差"真正落地 | `build_report` 新增 `aspect_error_before_pct`、`aspect_error_is_evidence=False`，改写 `aspect_error_note` | docstring 声称同时给校正前误差，实现却没有；0.00% 被误当保真证据 | PASS：校正前 15.0% / 校正后 1.57%，证据标记为 False；无对齐信息时正确置 null |
| R3 | 边界情况 | 统一读图入口并修两类真实误判 | 新增 `_load_rgb`（EXIF 旋转 + RGBA 合成白底 + 缺失/损坏明确异常），三处调用共用 | 手机横躺图被当竖图；透明底图前景占比虚高到近 100% | PASS：RGBA 前景 0.21（原接近 1.0）；EXIF rot90 后 200×400→400×200；缺失/损坏给出 `FileNotFoundError`/`ValueError` |
| R4 | 边界情况 | 门禁不得抛异常 | `validate_3d_input` 结构化返回拒绝；`_fit_mask` 输出 `empty_mask` 标记；新增"无主体"拒绝理由 | 门禁抛栈时用户只看到 traceback，拿不到可读拒绝原因 | PASS：不存在/损坏/全白三类均 `pass=false` 且带 reasons；干净样本仍 `pass=true` |
| R5 | 边界情况 | 退化网格不崩 | 新增 `_finite_rows`、`_safe_metric`；`make_projector`/`_points_mask`/`_occ_from_points`/`rasterize_silhouette`/`topology_metrics`/`build_report` 全部加空网格与非有限值防护；采样降级原因写进 geom | 空网格 `min()` 抛错、NaN 转 int 越界、`mesh.area` 异常会让整条链路崩 | PASS：空网格两种 accurate 模式均返回全空掩膜；NaN/Inf 网格正常出图与报告；空网格 `watertight_indexed=False`（不再误报 True） |
| R6 | 正确性 | 减少细长三角面误裁 | `crop_to_reference` 默认改"重心+三顶点"四点投票（≥2 票保留），保留 `mode="centroid"` 作 A/B 对照 | 单点重心判定会把横跨轮廓边界的发丝三角形误删 | PASS：新投票保留 1,367,754 面 vs 旧 1,366,396 面（多保 1,358 个跨界面），固定投影 IoU 0.7954 vs 0.7961（代价 0.0007）；2 项对齐回归测试通过 |
| R7 | 性能 | 加速拓扑统计 | 顶点对编码成单个 int64 后一维 `np.unique`，替代 `(N,2)` 二维唯一化 | 74 万面产生 222 万条边，二维唯一化是报告最慢一步 | PASS：0.89s → 0.07s（**12.5×**），边界/非流形/共享边/水密四项逐项一致 |
| R8 | 性能 | 加速 24 朝向的视觉外壳 | `_visual_hull` 用累积极值向量化求最近左右采样点；并加密度自适应（<2% 用逐行稀疏路径） | 逐行逐点 Python 循环是朝向搜索热点 | PASS：12 组随机掩膜逐像素等价；真实顶点投影 0.046s→0.024s（**1.9×**）。**首次在极稀疏合成掩膜上测得 0.3× 退化，故补密度自适应**：稀疏 0.9×（持平）、真实 1.9× |
| R9 | 性能 | 消除朝向搜索的重复拷贝 | `cube_rotations` 缓存；新增 `_cube_rotations_axes` 预提取轴/符号；`_points_mask(assume_finite=True)`；入口一次性 `_finite_rows` | R5 引入的有限性过滤在每个朝向重复 40 万点全量拷贝 | PASS：投影与矩阵乘最大误差 0；最优 IoU/idx 完全一致。**首次只做缓存+索引取列测得 0.9×（更慢），定位到真瓶颈是重复过滤，补强后 1.1× 且结果一致** |
| R10 | 性能/一致性 | 采样量与评估分辨率匹配 | `rasterize_silhouette` 按 `2×size²` 定采样（20 万–100 万上限），seed 与采样数写进 geom/报告 | 512² 网格只有 26 万像素，却按 4×面数采 297 万点 | PASS：先扫描 20 万→300 万采样，IoU 仅差 0.0004；3M→524,288 点后 512 网格 IoU 0.8284→0.8281，耗时 0.95s→0.20s；`test_final_target_stl_is_watertight_and_faithful` 仍通过 |
| R11 | 一致性/完整性 | 报告可事后复核 | `save_report` 统一写 `schema_version=2.0`、UTC 时间、`metric_dictionary`（10 项口径）、输入/参考图/网格 SHA256；哈希按 (path,mtime,size) 缓存 | 两份报告混在一起无法判断谁生成、用哪张图、0% 能否当证据 | PASS：哈希与文件逐字节一致；重复写报告 0.028s→0.006s（缓存生效） |
| R12 | 正确性/一致性 | 核心指标不可被覆盖 | `build_report` 设 `protected` 字段集，冲突时忽略并记 `extra_overrides_ignored`；`ref_info` 无路径时用最近邻重采样掩膜而非 `KeyError` | `report.update(extra)` 允许喂一个好看的 IoU；内存构造的 ref_info 会崩 | PASS：伪造 `silhouette_iou=0.99`/`faces=1`/`watertight_indexed=False` 均被拒，真实值 0.8281/741,524/True 保留，合法附加字段仍生效；无路径重采样 IoU 0.824 |
| R13 | 边界情况 | 参数区间校验 | 新增 `validate_args`：10 个数值参数 + `--to` 非空；非法值退出码 2 | 负高度做负缩放、`min-iou 2` 永远拒绝、`voxel-mm -1` 让 Blender 崩 | PASS：8 类非法参数全部拦截，默认值与"0=禁用"语义正确。**首轮把 `height>0` 写成跳过条件导致负高度漏网，自检发现并改为 `!=0`** |
| R14 | 正确性 | 禁止覆盖输入 + 真实退出码 | 导出前比较规范化绝对路径，同名即跳过；`main` 返回 `1 if fail else 0`；输出目录不可写明确提示 | R13 的 CLI 实测用默认 `--to` 把原始 GLB 覆盖成后处理结果，且退出码仍是 0 | PASS：`--to glb` 同名被拒（退出码 1，输入哈希不变）、未知格式退出码 1、正常转换退出码 0。**副作用如实记录：该次实测确曾覆盖 `figure_3d_5b299f5bbb1a_00001_.glb` 且无备份；误生成的 3mf/obj/ply/stl 已隔离到 `print_ready/_verify2/_r14_stray/`** |
| R15 | 边界情况 | Blender 修复失败必须降级 | 捕获 `TimeoutExpired`/子进程异常/坏 stats.json/空输出/保真模块缺失；`_find_blender` 显式无效路径不再静默回退；`_sharp_edge_ratio` 空邻接返回 None；`iou_check=skipped` 显式标注 | 任一异常都会中断整条导出链路 | PASS：程序不存在/超时/子进程异常/空输出/依赖缺失五类全部 `accepted=False` 且回退原网格。**首次自检发现"显式路径被静默替换成别的 Blender 安装"与"跳过 IoU 检查却显示通过"，已一并修正** |
| R16 | 边界情况/可读性 | Blender 脚本 CLI 健壮化 | 参数个数/未知参数/缺值/非数字/负值全部给可读 `SystemExit`；删 `if False` 死代码；导出后校验输出非空；stats 增加 `output_bytes` | 缺参数直接 `IndexError`，负值直接喂给 Blender | PASS：无参数/非数字/负值三种均退出码 1 且信息明确；正常调用退出码 0，stats `output_bytes=28,294,234` 与磁盘一致 |
| R17 | 一致性 | 消除跨模块隐式默认值依赖 | `fig.py` 新增 `PRINT_DEFAULTS` 常量并让 6 个参数引用它；`cmd_print` 始终显式透传 `--smooth`；删除"默认改用 Taubin 平滑"的过时注释 | 注释与实际（smooth=0 + Blender 水密化）矛盾；任一处改默认会静默漂移 | PASS：捕获 `cmd_print` 命令行，`--smooth 0`/`--voxel-mm 0.25`/`--min-iou 0.55`/`--repair-max-iou-drop 0.02` 全部显式且与 `convert_3d.py` 默认值一致 |
| R18 | 完整性 | 顶层验收结论 + 硬门禁 | 新增 `build_verdict`（5 项 checks，基于 `final_mesh`）、`--strict-watertight`（不满足退出码 3），报告写 `verdict` | 报告只有散落指标，没有"是否验收通过"；非水密仍导出可打印性不合格文件 | PASS：默认模式对非水密仍 `pass=true`（保持兼容），严格模式 `pass=false`；CLI 实跑 `--no-blender-repair --strict-watertight` 正确以退出码 3 拒绝导出 |
| R19 | 完整性/可复现性 | 补运行清单 | 新增 `write_manifest`：完整命令、Python/平台、参数、输入与输出 SHA256、耗时、结论，写 `<base>_manifest.json` | 指标报告回答"好不好"，没人回答"这是怎么来的" | PASS：manifest 记录 20 段命令、29 个参数、耗时 5.96s，输出 SHA256 与文件逐字节一致，`fidelity_schema=2.0` |
| R20 | 可读性 | 清理命名与结构 | `convert_3d.py` 中 `extra` 一分为二（`report_extra` dict / `suffix` 字符串）；`_cube_rotations_axes` 移到依赖之后；`iou`/`cube_rotations` 等补类型注解；结尾补成功/失败格式统计 | 同一函数里 `extra` 两种含义，极易误改 | PASS：4 个模块 `py_compile` 通过；`extra` 仅剩 1 处函数关键字；签名含类型注解；9 项既有测试全过 |
| R21 | 完整性 | 回归保护扩到新边界 | `setUpClass` 补 `SkipTest`；新增 12 个用例（EXIF、RGBA、损坏/空白图、空/NaN 网格、视觉外壳等价、裁剪 A/B、报告防篡改、指标口径、schema/哈希、verdict、参数区间、默认值一致性） | 前 20 轮修的缺陷没有回归保护 | PASS：9→**21 用例**；**首次 1 例失败是断言把采样下限 20 万写成 2×128²，且出现 3 处 `ResourceWarning`**；修正后以 `-W error::ResourceWarning` 运行 21 passed |
| R22 | 一致性 | 文档与代码同步 | v1 报告加"历史版本，勿作当前结论"；v2 报告更新 9→21 用例、补"迭代后接口契约（v2）"8 项 | 文档仍写过时默认值与测试数，v1 会被误当当前结论 | PASS：v1 标记存在；v2 无 "9 passed"/"通过 9 项"；三处默认值与 `convert_3d.py` 一致；共享常量只在 `fig.py` 定义。**首次自检表达式 `'x' in s is False` 被解析成链式比较导致误报，改写后通过** |
| R23 | 正确性 | 迭代后链路端到端回归 | 用全部新参数重跑 STL（含 `--strict-watertight`），校验报告/manifest/几何，渲染三视图，全量测试 | 需要证明所有改动在真实产物上生效且精度不退化 | **部分达成，暴露新缺陷**：IoU 0.8310、水密 True、边界/非流形 0、verdict PASS、退出码 0、哈希一致；但 `front` 渲染显示的是**背面**（长发遮脸、无五官） → 触发 R24 |
| R24 | 正确性 | 修正正/背面歧义 | 新增 `front_detail_score`（前表面头部深度起伏）；`best_orientation` 显式识别"绕 Z 180° 候选对"并用细节判据选择，`tie_tol` 0.012→0.02；`front_back_resolution` 写进报告 | IoU 对 180° 近乎对称，两个候选仅差 0.0148 就让背面以噪声分胜出；法线标准差对该翻转天然不变 | PASS：实测正面 0.00893 / 背面 0.00612（差 46%）；选中恒等正面姿态 idx 0，`front_back_resolution` 记录 detail 0.005739→0.007251；旧失败样本朝向提升 0.2959→0.6140 不退化；重生成 `final4` 正面渲染确认有刘海/脸/露肩上衣/裙/四肢/底座；21 测试全过 |
| R25 | 可复现性/边界情况/一致性 | 消除"换解释器就崩"的可选依赖硬编码 | `mesh_fidelity.py` 新增 `_NumpyNdimage`（`label`/`sum`/`binary_dilation`/`binary_erosion`/`binary_closing`/`binary_fill_holes`/`affine_transform` 7 个操作的纯 numpy 等价实现）与带缓存的 `_ndimage()` 探测器，5 处硬 import 全部改走它；测试新增 `TestOptionalScipy` 3 用例（逐像素等价、模拟无 scipy 的参考图/裁剪/轮廓、仿射多参数对照）、`_require_trimesh()` 让必需依赖缺失变 SKIP、复杂背景样本在 `color_fallback` 时显式 SKIP；补项目 venv 复现命令 | 交付复核发现当前 shell（Python 3.13）缺 scipy 时 14/32 用例直接 `ModuleNotFoundError`，而项目主环境 Python 3.12.3 依赖齐全却被默认当成"必然具备"；`fig.py` 早有"无 scipy 退化到纯 Python 洪泛"约定，保真模块单方面硬依赖属跨模块不一致 | PASS：主路径 `_ndimage() is scipy.ndimage`；合成掩膜上 7 类操作逐像素等价；**精确隔离 ndimage 降级后 24 用例全过、0 跳过**（含真实样本 IoU 断言）；全局屏蔽 scipy 21 passed/3 skipped；缺 scipy+trimesh 的 3.13 环境 21 passed/11 skipped（原为 14 errors）；项目 venv（3.12.3）保真 24/全量 38 全过，7 模块编译通过；`final4.stl` SHA256 未变。**三次失败自检如实记录**：① 批量替换把 `_ndimage()` 自身的 import 也改成递归调用，自检发现并改回；② 首版 `affine_transform` 用取整后索引判越界，与 scipy 差 39/4096 像素，"跳过对齐"的保守降级还把 2 个真实样本 IoU 从 0.7158 拉到 0.6427 → 改为「浮点坐标判越界 + `floor(coord+0.5)`」后逐像素等价并撤销跳过；③ 全局屏蔽 scipy 会连带破坏 rembg，使 `reference_mask` 改走 `color_fallback` 掩膜口径变化，定位后按环境契约 SKIP，绝不放宽断言 |
| R26 | 完整性/正确性 | 让交付物可被独立复验，并补上"法线外向"这一可打印性必要条件 | 新增 `verify_deliverable.py`：11 项文件级检查（焊接后闭合 / 绕向一致 / 有符号体积>0 / `is_volume` / SHA256 与清单一致 / 面数 / 焊接顶点数 / 包围盒 / 报告拓扑 / `verdict` 一致性 / schema 2.0）；新增 `tests/test_verify_deliverable.py` 5 用例（正例 + 法线朝内 / 开口网格 / 清单哈希不符 / 缺文件负例）；生成 `target_final4_verify.json` | 深层复审发现：`verdict` 只评价内存网格，5 项 checks 没有正体积/法线朝外，也没有对**磁盘 STL** 的独立复验；且 STL 二进制每面存独立顶点，直接加载会显示"非水密"（2,224,500 顶点 vs 报告 370,672）——这是格式特性不是缺陷，必须按位置焊接后再判 | PASS：正例 11/11 全过、CLI 退出码 0（体积 +34752.2571、法线朝外、`is_volume=True`、尺寸/哈希/面数/焊接顶点数全一致）；法线朝内（体积 -24）、开口网格、清单哈希不符三类负例全部正确拒绝，CLI 退出码 1 / 单测覆盖 / 缺文件退出码 2；全量 **43 测试全过**、9 模块编译通过；`final4.stl` SHA256 未变。**新发现如实记录**：焊接后 `euler_number=-78`（约 40 个拓扑柄），来自长发断环/镂空，不影响水密与正体积，但切片时会产生较多内部轮廓，已列入残留风险 |
| R27 | 完整性/正确性/一致性/边界情况 | 让文件级复验从"旁路 CLI"变成**主链路闭环**：导出 STL 后自动回读磁盘文件复核，结论写进报告、verdict 与清单，失败不再静默 PASS | `convert_3d.py` 新增 `verify_exported_stl`（复用 `verify_deliverable.geometry_checks` 的同一套判据：焊接闭合/绕向/正体积/闭合实体，再叠加面数/焊接顶点/包围盒与内存网格 3 项比对）与 `apply_file_verification`（保持 R18 的 5 项 checks 契约不变，用 `file_verification_pass` 单列并共同决定 `pass`）；导出循环后把结果写入 `fidelity_report["file_verification"]`、重存报告、写入 manifest，复验失败追加 `fail` 使 `main` 返回 1；`verify_deliverable.py` 增加可选第 12 项 `file_verification_consistent`（旧报告无该字段时仍是 11 项，向后兼容）；新增 `tests/test_convert_file_verify.py` 11 用例；`json_safe` 把损坏 STL 产生的 NaN/Inf 转成 None 并以 `allow_nan=False` 写盘 | R26 的 11 项复验**只是手工旁路工具**：`convert_3d.py` 从导出到写清单全程未调用它，`verdict` 只评价内存网格。导出器改写法线、写盘截断、文件与报告不符时，主链路仍打印 `PASS`；且两处若各写一套判据会口径漂移 | PASS：真实保真链路端到端跑通（合成参考图 + 小 GLB），报告/manifest/verdict 三处均写入 7 项全 True 的文件级结论，`verdict.checks` 仍为 5 项；`--no-fidelity` 旁路的 CLI 正例退出码 0、清单含 `pass=true`；注入失败几何复验后 CLI 返回 1 且清单留痕；法线朝内/开口/面数不符/未焊接顶点/尺寸不符/损坏文件/缺依赖共 7 类负例全部按预期处理；全量 **54 测试全过**（venv 3.12.3 / 3.14 / 精确隔离降级三路径，3.13 缺依赖 51 reported + 27 skipped、0 error）；10 模块编译通过；`final4.stl` SHA256 未变。**两次失败自检如实记录**：① 新测试把 `pass=False` 当关键字参数（`pass` 是保留字）导致 SyntaxError，改为先构造 dict 再赋值；② 损坏 STL 使 `trimesh` 算出 NaN 体积/尺寸，`json.dump` 会写出非法 JSON 字面量 `NaN` → 增加 `json_safe` + `allow_nan=False` 并固化回归断言 |
| R28 | 完整性/正确性/边界情况 | 让"悬空碎块"进入验收口径：落地模型连通性可量化、导出时可见、需要时可硬拒绝 | `verify_deliverable.geometry_checks` 新增 6 项指标（`connected_parts` / `main_body_face_ratio` / `floating_parts` / `floating_parts_max_faces` / `floating_volume_ratio` / `degenerate_faces`）+ 结构化 `warnings`；`verify()` 加 `strict_single_body` 参数、CLI 加 `--strict-single-body`（默认关闭，只告警不推翻既有结论）；`convert_3d.verify_exported_stl` 把指标/告警带进主链路报告与清单并在导出时打印；新增 3 项回归用例（双实体软告警 + 硬拒绝、final4 碎块量化、主链路指标透传） | 更深一层复审发现落地 STL 实测有 **7 个连通块、6 个悬空碎块**（最大 968 面 / 2.18mm³，另有 2 个体积 0 的 12 面碎片，总体积占比 0.0094%）；`is_watertight` 对多个互不相连的闭合体同样返回 True，此前 27 轮的"整体水密 + 正体积"完全测不到它。悬空碎块是真实可打印性风险（漂浮件/废料/打印失败点） | PASS：默认复验仍 11/11 PASS 并打印告警（不擅自否定已交付成品）；`--strict-single-body` 对 final4 正确 FAIL 且退出码 1，双实体合成网格默认 PASS / 严格 FAIL；退化面 0；全量 **57 测试全过**（venv 3.12.3 / 3.14，3.13 缺依赖 0 error）、10 模块编译通过；`final4.stl` SHA256 未变。**刻意不删碎块并如实说明**：按面数自动剔除会误删有效发丝细节，且会改变已交付成品的几何与哈希；是否剔除须人工结合三视图决定，故只做量化 + 可选门禁 |
| R29 | 正确性/完整性/一致性/边界情况 | 把 R28「只告警」的悬空碎块真正从成品中剔除，并让主链路自己能硬拒绝多实体；产出单实体的新最终版本 | `convert_3d.py` 新增 `drop_floating_parts`（按**拓扑连通性**保留最大连通块；空网格 / 异常 / 清理后主体非闭合或体积非正一律原样回退并写明原因）与 `enforce_single_body`（把 `single_body` 并入 `file_verification` 的 checks/pass，保持 R18 的 5 项 verdict checks 契约不变）；新增 `--drop-floating-parts`、`--strict-single-body`，`validate_args` 拦截「启用硬门禁但 `--to` 不含 stl」；清洗点放在 8.7 最终评估**之前**，使 `final_mesh` 报告评价的就是真正导出的网格；清理明细写入 `fidelity_report["geometry_cleanup"]` 与 manifest；新增 7 项回归（含 2 个真实 CLI 端到端）；用与 `final4` 完全相同的参数加这两个开关重跑转换，产出 `final5` 及正交三视图 | R28 刻意不删碎块（担心按面数误删发丝细节、改变已交付哈希），但主链路没有 `--strict-single-body`，用户必须绕到旁路 CLI 才能发现；结果是「检测到最高优先级可打印性风险，却既不能修、也不能在正常使用路径里拒绝」。按拓扑连通性（而非面数阈值）剔除不会误删与主体相连的发丝；**重跑转换而非事后改历史文件**，可让报告、清单、哈希与成品四者自洽 | PASS：`final5` 连通块 **7→1**，剔除 6 块 / 1,888 面 / 3.25512 mm³（主体面占比 0.997454）；`final_mesh` IoU **0.8281 与 final4 完全相同**；水密、边界边 0、非流形边 0、体积 +34749.002 mm³、euler -90；主链路文件级复验 8 项（含 `single_body`）全 True、`verdict=PASS`；独立复验 **12/12 PASS、零告警**，`--strict-single-body` 亦 PASS；三视图与 `final4` 差异仅 30 / 142 / 280 像素（0.005%–0.048%），正面刘海/脸/露肩上衣/裙/四肢/底座完整；全量 **64 测试全过**（venv 3.12.3 与 3.14 各 64/64；3.13 缺依赖 collected 64 / reported 61 / 37 skipped / **0 error**）、10 模块编译通过；`final4.stl` SHA256 未变（保留为历史对照），`final5.stl` 新哈希 `5c02f890…`。**本轮是 29 轮中唯一真正改变交付几何的一轮**，如实记录，不沿用前几轮「哈希不变」的说法 |
| R30 | 可复现性/一致性/完整性/边界情况 | 让 R29 的 `final5` 能从**用户实际入口**（`fig.py print` / `all` / `image_print` 及控制中心）复现，而不是只有绕过链路直接调 `convert_3d.py` 才能生成 | `fig.py` 新增 `PRINT_FLAG_DEFAULTS` + `PRINT_FLAG_ARGS`（三项布尔门禁默认全关，键名与上游一一对应），`add_print_opts` 定义 `--strict-watertight` / `--drop-floating-parts` / `--strict-single-body`，`cmd_print` 显式透传并前置校验「硬门禁但 `--formats` 不含 stl」返回 2；`control_server.py` 新增 `PRINT_FLAG_ARGS` 与纯函数 `print_quality_flags(body)`（布尔值/字符串/0/1 归一，非法类型显式报错），在 `auto`/`print`/`image_print` 分支追加开关；新增 `tests/test_print_quality_flags.py` 6 项契约测试（三层键名一致、默认不传、全开透传、格式前置拒绝、四个子命令共用 + 下游开关存在性、控制中心翻译与负例） | 复审上层链路时发现：`convert_3d.py` 有 R18/R29 的三个门禁开关，但 `fig.py` 既未定义也未透传，**`final5` 是绕过产品链路直接跑底层脚本产出的**，用户正常跑一条龙流程永远拿不到单实体成品，也复现不了已交付的最终版本。这同时违反 `fig.py` 自己写明的「`cmd_print` 必须显式传给下游，不能依赖下游默认值」契约，以及 `PRINT_DEFAULTS` 单一真值约定 | PASS：`fig.py print` 端到端退出码 0，文件级复验 8 项（含 `single_body`）全 True、`connected_parts=1`、悬空块 0、退化面 0、IoU 0.8281；**产物 `e2e.stl` 与交付版 `final5.stl` SHA256 完全一致 `5c02f890…`**（逐字节复现），独立复验硬门禁退出码 0；全量 **70 测试全过**（venv 3.12.3 与 3.14 各 70/70；3.13 缺依赖 collected 70 / reported 67 / 37 skipped / **0 error**）、11 模块编译通过；`final4` / `final5` 哈希均未变。本轮**不改任何几何**，只补齐入口契约 |
| R31 | 边界情况/正确性/一致性 | 消除**验收工具自身**「STL 永远是清单第一个输出」的隐含假设，修掉多格式导出时的误判 FAIL | `verify_deliverable.py` 新增纯函数 `find_output_sha256(manifest, stl_path)`：按规范化绝对路径在 `outputs` 中定位待复验 STL 的条目，返回 `(sha256, index)`，容忍 `None`/非 dict/畸形条目与非 dict 清单顶层；`verify()` 的 `file_sha256_matches_manifest` 改为「找到条目且哈希相等」，metrics 增 `manifest_stl_output_index`；`main()` 异常捕获补 `TypeError`；模块 docstring 补第 4 类问题。新增 5 项纯单测 + 1 项真实 CLI 端到端（`--to obj stl`）；同步修正 2 处**失真夹具**（旧夹具条目只有 `sha256` 没有 `path`，与 `write_manifest.describe` 真实结构不符） | 实证复现：`convert_3d.py --to obj stl` 退出码 0、主链路文件级复验 7 项全 True、几何完全正确，但独立复验把 `outputs[0]`（obj）的哈希当成 STL 哈希，`file_sha256_matches_manifest` 误判 FAIL、退出码 1。`fig.py print` 默认 `--formats obj stl 3mf ply`，即**用户默认产品路径**必然触发；此前 30 轮的独立复验只在 `--to stl` 单格式下验证过，属于验收工具自己隐藏的前置假设，会让合格成品被误拒 | PASS：修复后同一多格式样本该项转 PASS（另一项 `verdict_consistent` FAIL 是合成参考图宽高比不符导致的**真实** FAIL，非误判，不放宽判据）；`final5` 独立复验 12/12 + 严格模式 13/13 仍 PASS、退出码 0，成品与 `e2e` 哈希均未变；新增负例覆盖「清单无 STL 条目」「多格式下 STL 哈希被篡改」「None/畸形条目」「清单顶层/outputs 类型异常」全部按预期处理；全量 **76 测试全过**（venv 3.12.3 与 3.14 各 76/76；3.13 缺依赖 reported 73 / 43 skipped / **0 error**）、8 模块编译通过；重生成 `target_final5_verify.json`（12/12 PASS，新增 `manifest_stl_output_index=0`）。**首次自检发现 1 例既有测试失败**：夹具只给 sha256 未给 path，按真实结构修正夹具而非放宽判据。本轮**不改任何几何** |
| R32 | 正确性/完整性/一致性 | 让独立复验真正核对主链路 `file_verification` 的**逐项内容**，堵住「只改汇总 pass 就能绕过验收」 | `verify_deliverable.py` 新增 `FV_SHARED_GEOMETRY_CHECKS` 与 `_flag_true`（只接受布尔真或整数 1，拒绝 `"false"` 这类字符串）；`file_verification_consistent` 由「`fv.pass` + `verdict.file_verification_pass` 两个汇总布尔值」改为：逐项 `checks` 非空且全为真 + 与独立复验自己重算的 4 项几何判据逐项相等 + 路径一致 + 汇总字段为真；畸形 fv 对象/非 dict checks 判 FAIL 而非抛栈；metrics 增 `file_verification_reason` 便于诊断。新增 7 项回归（自洽正例 / 单项 False / 几何判据矛盾 / checks 空·缺·非 dict / 非布尔值 / 畸形 fv / `final5` 真实样本），并修正 1 处夹具（旧夹具 fv.checks 只有 `probe`，缺共享几何判据） | 实证：把 `final5` 报告副本的 `file_verification.checks.single_body` 改为 False、`welded_watertight` 改为 False（与独立复验算出的 True 直接矛盾）、或把 `checks` 清空，**只要保留 `pass: True`，修复前独立复验一律 12/12 PASS、退出码 0**。这违背 R12「核心指标不可被覆盖」与 R27「两处结论不矛盾」的设计意图：独立复验本应核对结论内容，却只信任对方写下的汇总布尔值 | PASS：修复后 baseline 仍 rc=0 PASS，三类篡改全部 `FAIL file_verification_consistent`、rc=1；`final5` 独立复验 12/12 + 严格模式 13/13 仍 PASS、8 项主链路结论逐项自洽；全量 **83 测试全过**（venv 3.12.3 与 3.14 各 83/83；3.13 缺依赖 reported 80 / 50 skipped / **0 error**）、8 模块编译通过；重生成 `target_final5_verify.json`（12/12 PASS）；`final5`/`e2e` SHA256 未变。本轮**不改任何几何** |
| R33 | 正确性/边界情况/一致性 | 让 `verdict` 的验收判据与 `file_verification` 达到同等严格度，堵住「替换/删减判据集合 + 非布尔真值」绕过 | `verify_deliverable.py` 新增 `VERDICT_KNOWN_CHECKS`（`build_verdict` 恒定 5 项契约）、`VERDICT_ALWAYS_REQUIRED`（两种模式下都必需的 2 项）、`_is_bool_flag()` 与 `verdict_checks_valid()`；`verdict_consistent` 由裸 `all(verdict["checks"].values())` 改为：固定 5 项齐全且值全为严格布尔 → `required_checks` 非空、覆盖永远必需项、声明项均存在 → 按 `required_checks` 重算汇总并与 `verdict.pass` 一致 → `evaluated_on == "final_mesh"` → `watertight` 与磁盘 STL 重算的 `welded_watertight` 交叉一致；`final_mesh`/`verdict` 畸形对象一律判 FAIL 不抛 `AttributeError`；metrics 增 `verdict_reason`。新增 12 项回归，并在两个测试文件加 `good_verdict()` 单一真值 helper，替换 4 处失真夹具（旧夹具 `checks` 只有 `{"probe": True}`） | 实证：把 `final5` 报告副本的 `verdict.checks.watertight` 改成字符串 `"false"` / 整数 `2`、删掉任一必需判据（连 `required_checks` 一起删）、或把整个 `checks` 换成 `{"forged": True}`，**修复前独立复验一律 12/12 PASS、退出码 0**。根因是 Python truthy 把非空字符串与非 1 整数判为真，且完全未校验判据集合完整性；R32 只加固了 `file_verification` 一侧，`verdict` 侧仍是 R12「核心指标不可被覆盖」的漏网处 | PASS：修复后 baseline 仍 rc=0 PASS，6 类篡改全部 `FAIL verdict_consistent`、rc=1；默认模式（required 仅 2 项）不误伤，跨层几何矛盾能被拒绝，畸形 verdict 不抛栈；全量 **95 测试全过**（venv 3.12.3 与 3.14 各 95/95；3.13 缺依赖 reported 92 / 62 skipped / **0 error**）、8 模块编译通过；重生成 `target_final5_verify.json`（12/12 PASS，新增 `verdict_checks=5` / `verdict_reason=None`）；`final5`/`e2e` SHA256 未变。本轮**不改任何几何** |
| R34 | 正确性/一致性/可读性 | 修正 `verdict.pass` 的复合语义建模，区分「报告诚实判定不合格」与「汇总字段被篡改」，并把跨模块契约核验固化为回归 | `verify_deliverable.py::verdict_checks_valid` 把 `verdict.pass` 的期望值由「按 `required_checks` 重算的内存结论」改为「内存判据 ∧ `file_verification_pass`」（字段缺失时退化为仅内存判据），并补 `verdict.pass` 自身的严格布尔校验；自洽地判定不合格仍返回 FAIL（交付物必须 PASS），但 reason 精确指向「文件级复验未通过（含 `file_verification_failure` 明细）」或「内存判据未通过」，篡改则报「与复合重算结论不一致」；模块说明补第 7 类问题。新增 6 项回归，含直接调用 `convert_3d.build_verdict`（两种 strict 模式）与 `apply_file_verification`，断言 `VERDICT_KNOWN_CHECKS` 契约一致且判据不误拒 | 上一轮深审实证：`apply_file_verification` 在文件级复验失败时产出 `verdict.pass=False`、`file_verification_pass=False`、`checks` 全真的**合法**报告，R33 却按单一内存语义重算，把 `verdict_reason` 误报为「`verdict.pass` 与按 `required_checks` 重算的结论不一致」。结论（FAIL）虽正确，但诊断把「诚实的不合格」伪装成「报告被篡改」，违背 R12/R18 的契约意图；且跨模块判据集合一致性此前只有手工核验、无回归保护 | PASS：合法不合格样本 reason 改为「文件级复验未通过，verdict 判定成品不合格（single_body）」且仍 FAIL；`pass=True` 但 `file_verification_pass=False` 的篡改报「复合重算不一致」；`verdict.pass` 为字符串/整数/None 一律拒绝；R33 的 5 类篡改样本全部仍被拒、未放宽判据；两种 `build_verdict` 模式仍 `(True, None)`；全量 **101 测试全过**（venv 3.12.3 与 3.14 各 101/101；3.13 缺依赖 reported 98 / 68 skipped / **0 error**）、8 模块编译通过；重生成 `target_final5_verify.json`（12/12 PASS）；`final5`/`e2e` SHA256 未变。本轮**不改任何几何** |
| R35 | 正确性/一致性/完整性 | 堵住「把 R27 文件级闭环字段整段删除即可退回旧口径」的降级绕过，并让报告/清单两处结论互相印证 | `verify_deliverable.py` 新增纯函数 `file_verification_contract()`：以 `manifest.file_verification`（`write_manifest` 与报告同源但独立落盘）判定本次运行是否做过文件级复验，要求两处存在性一致、`stl` 路径/`pass`/逐项 `checks` 相等、`verdict` 必带 `file_verification_pass`；`file_verification_consistent` 改为**始终写入**检查项（旧报告也保留，不再静默从 12 项退回 11 项），契约失败优先给精确诊断；新增 `--require-file-verification` 强制闭环开关与 `file_verification_contract_required` 指标。新增 9 项回归（含 CLI 透传、`final4` 旧报告兼容、两处不一致负例），修正 3 处失真夹具（真实 `write_manifest` 一定把 fv 写进清单） | 实证：把 `final5` 报告副本的 `file_verification` 整段删掉、或连 `verdict.file_verification_pass` 一起删，修复前独立复验静默退回 11 项口径、退出码 0 PASS。根因是 R27 的「旧报告无此字段则跳过」分支只看报告单侧，删字段即可伪装成 R27 之前的历史产物，把 R27/R32/R34 三层文件级校验全部绕过；清单此前只用于定位输出哈希，从未作为「该不该有这个字段」的第二证据源 | PASS：baseline 仍 rc=0 PASS；删字段 / 两字段同删 / fv 置字符串 / 清单删记录 / 两处 `pass`、`checks`、`stl` 不一致共 6 类样本全部 `FAIL file_verification_consistent`、rc=1；R32 同步篡改两处仍被原逐项核对拒绝、R33 伪造 verdict 仍被原契约拒绝，未放宽任何判据；`final4`（两处皆无）仍 PASS 但检查项固定 12 项，`--require-file-verification` 对旧报告 rc=1、对 `final5` rc=0；全量 **110 测试全过**（venv 3.12.3 与 3.14 各 110/110；3.13 缺依赖 reported 107 / 77 skipped / **0 error**）、8 模块编译通过；重生成 `target_final5_verify.json`（12/12 PASS，新增 `file_verification_contract_required=true`）；`final5`/`e2e` SHA256 未变。本轮**不改任何几何** |
| R36 | 正确性/边界情况/一致性/可读性 | 堵住「显式验收要求被 `--stl-only` 静默丢弃」与「`--json` 写盘崩溃 / 覆盖交付成品」，让验收工具的调用契约与证据写出安全可验证 | `verify_deliverable.py` 新增纯函数 `check_mode_contract()`（`--stl-only` 与 `--report` / `--manifest` / `--require-file-verification` 互斥，冲突抛 `ValueError` → CLI 退出码 2，`verify()` 库调用与 CLI 共用同一契约）与 `write_json_atomic()`（拒绝 `--json` 覆盖 STL/报告/清单，同目录临时文件 + `os.replace` 原子替换，异常清理临时文件并映射为退出码 2）；`--stl-only` 输出新增「仅几何复验…不等同于完整交付验收」醒目标注。新增 10 项回归（纯函数契约、库层、原子写、CLI 冲突 / 写盘失败 / 拒绝覆盖 STL 且字节不变） | 实证：`--stl-only --require-file-verification`、`--stl-only --report` 加一份明显篡改的报告，修复前一律 `PASS`、rc=0 —— `verify()` 在 `stl_only=True` 时直接 return，用户显式指定的强制闭环和证据文件被无声丢弃；`--json` 父目录不存在时 stdout 已打印 PASS 却抛裸 traceback、rc=1（与「验收不通过」同码）；`--json` 误指向 STL 会直接把 37MB 成品覆盖成一段 JSON，与 R13 曾记录的「覆盖原始 GLB」事故同型 | PASS：baseline / 强制闭环单独 / `--stl-only` 单独均 rc=0；两类冲突 rc=2、stderr 明确列出冲突项且无 traceback；完整模式 + 篡改报告仍 `FAIL` rc=1；`--json` 父目录不存在 rc=2 且无 traceback、指向 STL 副本 rc=2 且副本字节未变；全量 **120 测试全过**（venv 3.12.3 与 3.14 各 120/120；3.13 缺依赖 reported 117 / 87 skipped / **0 error**）、8 模块编译通过；重生成 `target_final5_verify.json` 走原子写成功（12/12 PASS）；`final5`/`e2e` SHA256 未变。自检中 1 例新增用例断言写错（把组合用例显示名当成真实 flag），修正夹具而非放宽判据；另修正一次编辑误写入字面转义符导致的语法错误。本轮**不改任何几何** |
| R37 | 正确性/边界情况/一致性 | 让畸形证据文件走结构化拒绝，杜绝「验收工具自己崩掉并把执行错误伪装成验收不通过」 | `verify_deliverable.py` 新增纯函数 `load_json_object()`：`json.load` 后显式要求顶层是 dict，否则抛 `ValueError`（中文可读信息）；`verify()` 用它替换两处裸 `json.load`；`extents_xyz` 的 `np.asarray` 用 try/except 包住并加 `isfinite` 校验，畸形值判该项 `FAIL` 而非让整个复验抛栈；`main()` 异常捕获补 `AttributeError` 兜底，全部映射为退出码 2；模块说明补第 10 类问题。新增 5 项回归（纯函数 5 类顶层畸形、正常完整模式仍 12/12、CLI 报告/清单顶层畸形 rc=2 无 traceback、5 类畸形 extents 判 FAIL） | 实证：把 `fidelity.json` 顶层换成 `[1,2]` / 字符串 / 数字 / `null`，修复前 `report.get` 抛未捕获 `AttributeError`，CLI 打出裸 traceback 并以 rc=1 结束 —— 与「验收不通过」同码，正是 R36 刚修掉的同类问题换个入口复现；`extents_xyz` 换成 `"abc"` / 嵌套对象会让 `np.asarray` 抛 `ValueError` 令复验直接崩。验收工具自身必须比被验收的数据更健壮 | PASS：4 类顶层畸形全部 rc=2、stderr 含「顶层不是 JSON 对象」、无 Traceback、stdout 无验收结论；5 类畸形 extents 全部 `extents_match_report=False` 且不抛异常；新增 `test_r37_clean_pair_still_passes` 确认正常完整模式仍 12/12（防误伤）；`final5` 严格 + 强制闭环 13/13 仍 PASS、rc=0，成品哈希未变。自检中 1 例失败是夹具把 `None` 同时当「未指定」哨兵与被测的顶层 null，改用 `_UNSET = object()` 显式哨兵修正夹具，未放宽判据。本轮**不改任何几何** |
| R38 | 边界情况/完整性/一致性 | 把 R36 自认的残留风险做实：`--json` 不得覆盖任何交付证据 | `verify_deliverable.py` 新增 `EVIDENCE_SUFFIXES` 与纯函数 `evidence_paths(stl_path)`（按 STL 派生 `<prefix>_fidelity.json` / `_manifest.json` / `_front.png` / `_back.png` / `_side.png` 与同目录 `run.log`，刻意排除 `*_verify.json`）；`write_json_atomic()` 在 protected 检查后增加「目标必须是 `.json`」通用护栏；`main()` 的 protected 换成 `evidence_paths(args.stl) + (args.report, args.manifest)`；docstring 补第 11 类问题与用法约束。新增 5 项回归（派生集合完整性、5 类非 .json 目标拒绝、CLI 覆盖 run.log/三视图 rc=2 且字节不变、自定义 `.txt` 证据受通用护栏保护、`*_verify.json` 仍可正常写出并解析） | 实证：`--stl-only --json <dir>/run.log` 会把同目录运行日志原子替换成 JSON 文本且仍打印 PASS、rc=0；三视图 PNG 同理。R36 的 protected 只派生 STL 与两个 JSON，CLI 又无法枚举调用方自定义证据清单，等于「证据写出安全」只覆盖了一部分。现在用「已知证据枚举 + 后缀护栏」双层封闭，且不误伤复验结果文件的正常覆写 | PASS：4 类证据文件被指向时全部 rc=2、stderr 含「不能覆盖」、字节逐字节不变；任意 `notes.txt` 受「必须是 .json 文件」拒绝且内容不变；`m_verify.json` 仍 rc=0 且可解析；全量 **130 测试全过**（venv 3.12.3 与 3.14 各 130/130；3.13 缺依赖 reported 127 / 97 skipped / **0 error**）、10 模块编译通过；重生成 `target_final5_verify.json` 恢复默认 12/12 口径、SHA256 与 R36 时完全一致 `46a6827a…`；`final5` / `e2e` SHA256 未变。本轮**不改任何几何** |
| R39 | 正确性/边界情况/一致性 | 把 R33/R37 在独立复验侧确立的严格布尔/有限数值契约补齐到**生成侧**，让 `build_verdict` 遇畸形指标时结构化拒绝而非抛栈或误判 | `convert_3d.py` 新增 `_finite_float()` / `_strict_true()` / `_strict_zero()` 三个纯函数；`build_verdict()` 改为显式校验 `report` 与 `final_mesh` 是 dict；IoU / `aspect_error_pct` / `min_iou` 只接受有限浮点数，缺失或非有限一律判该项 FAIL 并写入 `invalid_metrics` 明细；`watertight_indexed` 只接受 `True`/数值 1，`boundary_edges`/`nonmanifold_edges` 只接受数值 0（拒绝 `False == 0` 与字符串）；5 项 `checks` 恒为严格布尔，`required_checks`/`evaluated_on` 契约不变。新增 6 项回归（合法报告契约不误伤、8 类畸形指标、4 类非法阈值、6 类 truthy 误判 + 3 类合法数值 1、边界边布尔/字符串陷阱、用真实 `final5` 报告重算 verdict 与已落盘结论逐字段一致） | 实证：把 `final_mesh.silhouette_iou` 换成 `None`/`"abc"`，或把 `aspect_error_pct` 换成 `None`，修复前 `float()` / `<=` 抛 `TypeError`/`ValueError` **直接中断导出**；`watertight_indexed="false"` 或 `2` 被 `bool()` 判成水密 PASS（与 R33 在复验侧修掉的 truthy 同根因，但生成侧从未加固）；`boundary_edges=False` 因 Python `False == 0` 被判成「无边界边」。生成侧必须与复验侧同严，否则报告一旦被写成非标准类型，主链路会静默产出错误的 PASS | PASS：8 类畸形指标 + 4 类非法阈值全部返回结构化 FAIL、含 `invalid_metrics`、5 项 checks 均为严格 bool 且不抛异常；6 类 truthy 值全部判 `watertight=False`，`True`/`1`/`1.0` 不误伤；布尔/字符串边界边不再算 0；合法报告仍 12/12 契约、`apply_file_verification` 后仍 5 项 checks；用真实 `final5` 报告重算 verdict 与落盘 `checks`/`required_checks`/`evaluated_on`/`pass` **逐字段一致**且无 `invalid_metrics`；全量 **136 测试全过**（3.12.3 与 3.14 各 136/136；3.13 缺依赖 reported 133 / 103 skipped / **0 error**）、10 模块编译通过；`final5` 默认 12/12 与严格 13/13 PASS，STL / `e2e` / 三份证据 JSON 哈希未变。本轮**不改任何几何** |
| R40 | 正确性/一致性/边界情况 | 把复审推进到**报告元数据的生成源头**：让溯源哈希、schema 版本与指标口径由 `save_report` 权威生成，不再由输入决定 | `mesh_fidelity.save_report()` 重写元数据段：`schema_version` / `metric_dictionary` 强制取本模块常量；`input_mesh` / `reference` / `mesh` 指向的源文件存在时**强制重算**哈希并覆盖任何旧值/假值，不存在时显式写 `null`（不再静默省略字段）；被纠正的字段写入 `metadata_corrections`，不可核验的源文件写入 `source_hashes_unverifiable`（含路径与原因）；`generated_at_utc` 仍允许调用方注入固定值以做复现性测试。新增 6 项回归（3 类假哈希重算、schema/口径污染、时间可注入、源文件缺失显式 null + 合法 JSON、干净报告无审计噪音、用真实 `final5` 报告重写后关键字段逐字段一致） | 实证：传入 `input_mesh_sha256='FAKE_OLD_INPUT'` / `reference_image_sha256='0'*64` / `mesh_sha256='TAMPERED'`，旧实现用 `setdefault` 全部原样落盘；`schema_version='1.0'` 会把下游解析契约降级，`metric_dictionary` 可换成假口径；源文件不存在时哈希字段直接消失，读报告者无法区分「没算」与「源文件丢了」。R41 即将让复验侧消费这些字段，生成侧必须先保证新报告不会落下无法核验的值 | PASS：3 个假哈希全部被真实 SHA256 覆盖且 `metadata_corrections` 精确列出 3 项；schema/口径强制回权威值；固定时间戳不误伤；缺失源文件落 `null` + `source_hashes_unverifiable` 且 JSON 合法；干净报告与真实 `final5` 报告重写后无审计噪音、`silhouette_iou` / `final_mesh` / `verdict` / `file_verification` / 两份哈希逐字段一致；该文件 30/30，成品默认复验仍 12/12 PASS。自检中 1 例失败是用例自己新建临时目录却去读夹具目录里的文件，修正夹具，未放宽判据。本轮**不改任何几何** |
| R41 | 完整性/正确性/边界情况/一致性 | 把「哪张参考图 / 哪个输入模型产生这份 STL」的溯源字段从装饰变成**可验证据**，同时保持历史交付的 12 项口径逐字节不变 | `verify_deliverable.py` 新增 `SOURCE_PROVENANCE_ITEMS` 与纯函数 `source_provenance_checks(report, manifest)`：对 `input` / `reference_image` 两项做「报告哈希 == 清单哈希 == 磁盘重算哈希」三重印证，校验 64 位小写十六进制格式与报告/清单路径一致，源文件缺失、路径畸形、读盘 OSError 一律判 FAIL 并给中文诊断（不抛栈变 rc=2）；`verify()` 新增 `require_source_provenance` 参数，**仅在显式启用时**写入 `source_provenance_valid` 检查项、诊断明细与结果标记；`check_mode_contract()` 把新 flag 纳入 `--stl-only` 冲突；CLI 加 `--require-source-provenance` 并打印溯源结论。新增 7 项回归（默认输出零变化、干净证据 13 项全过、4 类篡改/删除、清单作独立第二证据源、路径不一致与源文件缺失、CLI 冲突 rc=2 与正常启用、真实 `final5` 三方一致） | 实证：把报告里 `input_mesh_sha256` 改成 `TAMPERED_INPUT`、`reference_image_sha256` 改成全零，或直接删掉两个字段，修复前独立复验**仍 12/12 PASS** —— 这两个字段此前没有任何消费方，R40 修的是「以后不再写错」，历史报告/外部替换仍需复验侧能查。清单的 `input` / `reference_image` 已各自带 SHA256，天然是第二证据源。做成 opt-in 而非默认硬门禁，是为了不把源文件已归档移走的历史交付误判为不合格 | PASS：启用后 `final5` 13/13 PASS、诊断显示三方哈希一致；4 类篡改/删除与清单单方篡改全部 FAIL 且 reason 可读；路径不一致/源文件缺失判 FAIL 不抛异常；`--stl-only --require-source-provenance` rc=2、stderr 含 flag 名、无 traceback；**默认结果写盘后与交付 `target_final5_verify.json` 逐字节相同（SHA256 均 `46a6827a…`）**；全量 **149 测试全过**（3.12.3 与 3.14 各 149/149；3.13 缺依赖 reported 146 / 110 skipped / **0 error**）、10 模块编译通过；严格 + 强制闭环 + 溯源三档 14/14 PASS；五份交付哈希未变。自检中 1 例失败是 CLI 在空目录启用完整模式缺报告/清单，改为指向完整证据，未放宽判据。本轮**不改任何几何** |
| R42 | 正确性/完整性/一致性 | 把残留风险第 13 条做实：让独立复验按**已落盘阈值**重算 `verdict` 的两项数值判据，堵住「数值与结论自相矛盾仍 PASS」 | `convert_3d.py` 把 `aspect_self_check` 的硬编码 `1.0` 提成模块常量 `ASPECT_SELF_CHECK_TOL_PCT`，并在 `build_verdict` 文档里明确「IoU 取 `final_mesh`（成品网格）、宽高比自检取顶层 `aspect_error_pct`（变换自检；加底座后包围盒必然变化）」这一刻意不同的评价对象；`verify_deliverable.py` 新增同值常量、纯函数 `_finite_number()` 与 `verdict_numeric_consistency(report, manifest, checks)`：从报告 `min_iou` 与清单 `parameters.min_iou` 取双源阈值（两处都有且不一致、或键存在但值畸形均判 FAIL；两处都无则兼容旧报告跳过），按 `final_mesh.silhouette_iou >= 阈值` 与 `aspect_error_pct <= 共享容差` 重算两项判据；`verdict_checks_valid()` 增加可选 `report`/`manifest` 参数并合并结果，`verify()` 传入。新增 7 项回归（两侧常量相等、纯函数 6 类畸形、阈值双源与缺字段兼容、4 类数值篡改集成拒、默认输出逐字节不变、合成旧夹具不误伤、final4/final5 真实样本仍 PASS） | 实证：把 `final_mesh.silhouette_iou` 改成 0.20、`min_iou` 改成 0.99、`aspect_error_pct` 改成 99，或删掉报告 `min_iou`，修复前独立复验**全部仍 12/12 PASS** —— R33/R34 只锁死判据集合、值类型与布尔汇总自洽，从不重算数值。深审发现 `min_iou=0.55` 其实早已写进报告与清单 `parameters`（残留 #13「阈值没有存入」的表述已过时），宽高比容差则是生成侧硬编码魔法数，复验侧具备重算条件却从未使用。做成**默认生效并合并进既有 `verdict_consistent`**，而不是再加一个 opt-in 检查项：数值判据是验收结论本身的一部分，不应默认放过；同时通过时 reason 仍为 None，保证默认输出与历史交付逐字节一致 | PASS：4 类数值篡改 + 「报告与清单阈值同时抬高」全部判 FAIL，`verdict_reason` 含「与重算不符（IoU 0.2 / 阈值 0.55）」等可读诊断；阈值双源不一致、键存在但畸形（含 NaN/字符串）、`verdict.checks` 缺项均结构化拒绝且不抛栈；两处阈值都无的合成旧夹具仍 12/12 PASS、不误伤；**默认结果写盘与交付 `target_final5_verify.json` 逐字节相同（46a6827a…）**，`final4` / `final5` 均 PASS 且 `verdict_reason=None`；全量 **156 测试全过**（3.12.3 与 3.14 各 156/156；3.13 缺依赖 reported 153 / 117 skipped / **0 error**）、10 模块编译通过；默认 12/12、严格 13/13、溯源 13/13 PASS，五份交付哈希未变。本轮**不改任何几何** |
| R43 | 完整性/正确性/边界情况/一致性 | 把「用户直接查看、但此前完全无校验」的三视图 PNG 与 `run.log` 纳入可验证闭环；同时修复本轮深审探针**真实误伤的交付证据** | `verify_deliverable.py` 新增 `EVIDENCE_INDEX_SCHEMA` / `EVIDENCE_ITEMS` / `evidence_index_path()`、零第三方依赖的 `png_container_valid()`（标准库逐 chunk 重算 CRC，校验签名/IHDR/IDAT/IEND/截断/多余字节）、`build_evidence_index()`（记录 STL 锚点与 4 项证据的 路径/字节数/SHA256/PNG 尺寸）、`evidence_index_checks()`（条目集合完整、文件名不得含路径穿越、磁盘哈希与基线一致、三视图哈希两两不同防复制冒充、尺寸一致、日志非空、清单畸形结构化 FAIL）；`_evidence.json` 加入 `EVIDENCE_SUFFIXES` 受 `--json` 保护；`check_mode_contract()` 把 `--require-evidence-index` 纳入 `--stl-only` 冲突并拒绝 `--write-evidence-index` 自写自验；CLI 新增 `--write-evidence-index`（独立动作）/ `--require-evidence-index`（第 13 项）/ `--evidence-index`。新增 8 项回归（PNG 容器 4 类损坏、基线完整性与干净正例、4 类证据篡改、基线自身篡改与目录穿越、参数契约、`--json` 保护、CLI 写/冲突、真实 `final5` 默认不变与启用 13/13）。生成 `target_final5_evidence.json` 基线 | **实证且是一次真实事故**：深审时在真实交付目录原地跑探针，把 `target_final5_front.png` 写成垃圾字节、删掉 `side.png`，独立复验**仍 12/12 PASS**；清单 `outputs` 只有 STL 一条，三视图与 `run.log` 连哈希都没有，既无法发现损坏、也没有恢复基准。R38 只保证「别被 `--json` 覆盖」，从不校验内容完好，这正是它的直接后果。修复后所有篡改实证改在**隔离副本目录**进行，不再碰交付文件 | PASS：4 类证据篡改（垃圾字节/删除/复制冒充/空日志）、基线改哈希·删条目·路径穿越·伪 schema·顶层数组、STL 锚点被改全部结构化 FAIL 且诊断可读；隔离副本上 `front=GARBAGE` 时 `evidence_index_valid=False`、`verify(require_evidence_index=True)` 拒绝；`--stl-only` 与自写自验两类冲突 rc=2、无 traceback；`--json` 指向基线 rc=2 且字节不变；真实 `final5` 默认仍 **12 项且与交付 `_verify.json` 逐字节相同（`46a6827a…`）**，启用门禁 13/13、四档组合 15/15 PASS；全量 **164 测试全过**（3.12.3 与 3.14 各 164/164；3.13 缺依赖 reported 161 / 125 skipped / **0 error**）、10 模块编译通过；五份既有交付哈希未变，新增第六份证据基线 `9c599949…`。自检中 2 处失败是测试自身缺陷（方法内裸引类属性、裸 `open` 触发资源告警），修测试代码，未放宽判据。本轮**不改任何几何** |
| R44 | 正确性/完整性/边界情况/一致性 | 把交付三视图从「哈希自证」升级为「与 STL 几何绑定」，堵住 R43 明确留下的「只验容器不验像素来源」 | `verify_deliverable.py` 新增 `RENDER_VIEW_AXES` / `RENDER_FG_DELTA` / `RENDER_RATIO_TOL_PCT` / `RENDER_MIN_FG_FRACTION`；零依赖 `_decode_png_luma()`（8-bit 非隔行 PNG 逐行反 filter + 亮度表，`decompress` 设上限防解压炸弹）、`png_foreground_bbox()`（四边亮度中位数估背景、前景包围盒比例与占比）、`render_binding_checks()`（front/back 期望 X/Z、side 期望 Y/Z，相对误差 >10% 或前景为空/占比过低均结构化拒）；`verify()` 把绑定结果并入既有 `evidence_index_valid`（**不新增检查项、默认输出零变化**，metrics 增 `render_binding`），CLI 增「渲染几何绑定」摘要行；`tests/test_verify_deliverable.py` 新增 7 项回归，并把 `import verify_deliverable as vd` 移出 trimesh 的 `try`，让缺依赖环境也能跑纯标准库解码回归 | **实证**：在隔离副本把 `side.png` 换成另一模型的 768² 合规渲染图，同步更新基线的 SHA256/字节数/尺寸，`evidence_index_checks()`（R43 口径）仍判通过——容器 CRC 完好、哈希自洽、三视图互异，`verify()` 仍 15/15 PASS；`png_container_valid` 从来只验容器，不验像素来自哪个模型。R43 事故后 front/side 正是从最终 STL 重渲染恢复的，恰恰需要一条不依赖落盘元数据的几何自证。绑定并入既有门禁而非再加 opt-in 开关，与 R42「数值结论不该默认放过」同一原则；零依赖实现保证 3.13 缺依赖环境仍可用，实测解码 0.2s/图 | PASS：真实 `final5` 绑定误差 front 0.06% / back 0.06% / side 4.42%（容差 10%）；换图+改基线集成实证中 R43 放行、R44 拒绝且**仅** `evidence_index_valid` 一项 FAIL、其余 12 项仍 True；默认 12/12 且与交付 `_verify.json` 逐字节相同（`46a6827a…`），严格 13/13、溯源 13/13、证据 13/13、四档组合 15/15 PASS；全量 **3.14 171/171**、3.12 168（128 skip）、3.13 168（129 skip、**0 error**）、10 模块编译通过；六份交付哈希未变。自检中 2 处失败均为夹具缺陷（副本 `file_verification.stl` 未同步改路径；缺依赖环境把 `vd` 绑在 trimesh 导入结果上），修夹具未放宽判据。本轮**不改任何几何** |
| R45 | 边界情况/正确性/一致性 | 修 R44 新增像素解码器的「畸形 IHDR → 裸 traceback」，把资源上限显式化，恢复「验收不通过 ≠ 执行错误」契约 | `verify_deliverable.py` 新增 `MAX_PNG_DIMENSION=4096` / `MAX_PNG_PIXELS=4M` / `MAX_PNG_RAW_BYTES=32MB`；`_decode_png_luma` 在分配缓冲区与调 C 层解压**之前**按 IHDR 声明值校验三项上限，超限返回含「上限」的结构化 FAIL；`decompress` 异常捕获扩到 `(zlib.error, OverflowError, ValueError, MemoryError)`；`main()` 异常白名单补 `OverflowError` / `MemoryError`，残余资源异常一律 rc=2 不裸 traceback。补 3 项回归（3 类超大尺寸结构化 FAIL、768² 正常图不误伤、隔离副本 CLI 无 traceback 且 rc=1） | **实证**：构造 CRC 完好的 IHDR `4294967295×4294967295` PNG，`png_container_valid` 判 True，但 `zlib.decompressobj().decompress(..., expected+1)` 的 `max_length` 是 C 层 `Py_ssize_t`，抛 `OverflowError: Python int too large to convert to C ssize_t`；`render_binding_checks` 未捕获、CLI 白名单也不含该类型，复验直接打印裸 Traceback，从「验收不通过 rc=1」退化成执行崩溃。`MAX_EVIDENCE_BYTES` 只限制输入文件字节，拦不住 IHDR 声明的像素规模，逐行反 filter 还会放大成 CPU/内存炸弹。容器层仍判「结构完好」是职责分离，拒绝理由应由解码层给出；与 R37 同一契约 | PASS：修复前同一支回归 **2 FAIL + 1 ERROR**（含 CLI 裸 Traceback 实测）；修复后 3/3 通过，3 类畸形尺寸均给出含「上限」的结构化诊断且不抛栈，768² 正常图不误伤；隔离副本 CLI `rc=1`、stderr 无 Traceback、`evidence_index_valid=False`、默认仍 12/12；全量 **3.14 174/174**、3.12 171（129 skip）、3.13 171（130 skip、**0 error**）、10 模块编译通过；五档 12/13/13/13/15 PASS、渲染绑定误差 0.06/0.06/4.42% 不变、六份交付哈希未变。本轮**不改任何几何、不改默认输出** |
| R46 | 一致性/正确性/边界情况/完整性 | 让证据基线「生成侧」与「复验侧」共用同一判据，并把缺依赖崩溃还原成 rc=2 执行错误 | `verify_deliverable.py` 新增 `MissingDependencyError`、`MAX_STL_TRIANGLES` / `MAX_STL_BYTES` 与零依赖 `stl_extents_from_file()`（按「文件大小 == 84 + 50×count」判二进制而非头 80 字节是否 `solid`，支持 ASCII，直接读 STL 本体算包围盒，不信任任何报告元数据）；`build_evidence_index()` 写出前复用 `render_binding_checks()`，绑定失败抛 `ValueError`（CLI 已捕获 → rc=2），基线 schema / 字段 / 既有交付逐字节不变；`geometry_checks()` 与 `verify()` 的 trimesh / numpy 导入包成结构化 `MissingDependencyError`，CLI 白名单纳入并映射 rc=2。补 8 项回归；R43 夹具从「占位 STL + 纯色小图」升级为几何自洽的迷你交付（合法 ASCII STL 10×10×40 + 三张 128² 深背景渲染图，前景比例同为 0.25），**不放宽产品判据** | **实证两条真实硬缺陷**：① 真实 Python 3.13（缺 trimesh）跑 CLI 打印裸 `ModuleNotFoundError` Traceback、rc=1 —— 把执行错误伪装成「验收不通过」；R25 只在 unittest 层用 skip 绕过，CLI 层从未验过。② `build_evidence_index()` 只验容器 CRC/哈希/互异，把侧视图换成另一模型的合规渲染图后仍打印 `[OK] rc=0` 写出基线，而 `--require-evidence-index` 必然 FAIL；R45 畸形 IHDR 图同样能生成。修复前同一支回归 **4 FAIL + 5 ERROR**（含上述两条实测）。生成侧与复验侧共用 `render_binding_checks` 且都从 STL 本体取几何（生成侧零依赖解析、复验侧 trimesh），不新增检查项、不新增 opt-in 开关 | PASS：修复后 R46 8/8 通过；真实 3.13 CLI `rc=2`、`[ERROR] ... MissingDependencyError: 几何复验需要 trimesh...`、无 Traceback；隔离副本「换图 → 写基线」被拒 rc=2 且原基线未被覆盖；隔离副本「正常 write → require」正向一致（rc=0、13 项 PASS、绑定 0.06/0.06/4.42%）；零依赖 STL 解析 0.43s、与 trimesh 包围盒数值一致；默认 12/12 且与交付 `_verify.json` 逐字节相同（`46a6827a…`），严格/溯源/证据 13/13、四档 15/15 PASS；全量 **3.14 182/182**、3.12 179（129 skip）、3.13 179（130 skip、**0 error**）、10 模块编译通过；八份交付哈希未变。自检中 5 个 ERROR 全为 R43 历史夹具用了占位 STL/纯色图，已升级夹具，未放宽判据。本轮**不改任何几何、不改默认输出、不重新生成交付基线** |
| R47 | 一致性/正确性/边界情况/可读性 | 修「写基线独立动作静默丢弃验收参数」—— R36 同类缺陷换到另一个动作模式，把冲突集合收归唯一真值 | `verify_deliverable.py` 的 `check_mode_contract()` 新增 `strict_single_body` / `json_path` 参数与 `write_evidence_index` 分支，枚举 8 类冲突（`--stl-only` / `--report` / `--manifest` / `--strict-single-body` / `--require-file-verification` / `--require-source-provenance` / `--require-evidence-index` / `--json`），任一命中即抛 ValueError 并列出全部冲突参数名；CLI 的 `--write-evidence-index` 分支删掉自己维护的 3 项 `others` 列表，改为调用同一函数（ValueError 由既有 try 映射 rc=2）；模块 docstring 的「注意」段同步列出完整互斥集合。补 4 项回归（8 类冲突 CLI 逐项、库层同集合、正常 write + 自定义 `--evidence-index` 路径、R43/R46 既有契约护栏） | **实证**：修复前在隔离副本跑 `--write-evidence-index` 配 `--require-source-provenance` / `--require-file-verification` / `--strict-single-body` / `--report` / `--manifest`，5 个用户显式要求的硬门禁全部被静默吞掉，CLI 仍打印 `[OK] 证据基线已生成`、rc=0；只有 `--require-evidence-index` / `--stl-only` / `--json` 被拒。根因是 write 分支自己列了 3 个冲突项且**完全不调用** `check_mode_contract`，库层只查「自写自验」，两层契约漂移 —— 与 R36「`--stl-only` 静默丢弃 `--report` 却仍 PASS rc=0」同一缺陷类别。修复前同一支回归 **9 FAIL + 3 ERROR**（3 个 ERROR 为夹具把 `stl_only` 同时作位置/关键字传入的 TypeError，已修夹具） | PASS：修复后 5 个被吞参数全部 rc=2、stderr 含参数名与「互斥」、无 Traceback；正常 write 仍 rc=0，`--evidence-index` 自定义路径仍生效；R43 8/8、R46 8/8 无回归；全量 **3.14 186/186**、3.12 183（129 skip）、3.13 183（130 skip、**0 error**）、10 模块编译通过；默认 12/12 且与交付 `_verify.json` 逐字节相同（`46a6827a…`），严格/溯源/证据 13/13、四档 15/15 PASS、渲染绑定 0.06/0.06/4.42% 不变、八份交付哈希未变。本轮**不改任何几何、不改默认输出、不重新生成交付基线** |
| R48 | 正确性/边界情况/一致性/可读性 | 修「写基线输出目标可覆写交付证据」—— R36/R38 的 protected 只加在 `--json` 分支，write 分支一份都没传 | `verify_deliverable.py` 新增 `write_index_protected_paths()`（放行默认 `_evidence.json`、加回 `--json` 刻意放行的 `_verify.json`，其余派生证据全保护）与 `guard_index_write_target()`（目标已存在时必须是记录相同 STL SHA256 的合法基线，否则拒绝覆写，覆盖自定义命名任意路径）；`write_json_atomic()` 增 `label` 参数，让两条分支共用护栏但给出正确参数名的诊断；CLI write 分支先跑内容护栏、再传 protected 与 `label="--evidence-index"`；模块 docstring「注意」段同步。补 5 项回归 | **实证**：隔离副本把 `--evidence-index` 指向 `_fidelity.json` / `_manifest.json` / `_verify.json` / 任意既有 JSON / 另一 STL 的合法基线，5 类全部 `[OK] rc=0` 静默覆写（原文件键被换成 `schema_version`/`stl`/`evidence`）。`.json` 后缀护栏只挡 `.stl/.png/.log`，挡不住同为 `.json` 的交付证据；protected 一份没传。根因与 R36（误指向 STL 覆盖成品）、R38（`--json` 覆盖 run.log/三视图）同类，只是换了动作分支后无人补。两层职责刻意不同：内容护栏覆盖自定义命名路径，protected 即使目标被删也能拦住 | PASS：修复前同一支回归 **6 FAIL + 1 ERROR**（含 5 类覆写实测）；修复后 5/5 通过，4 类交付 JSON、任意既有 JSON 与他人基线均 rc=2 + 含「拒绝」诊断且字节不变；目标被删除后 protected 仍 rc=2 且不创建假报告；默认 `_evidence.json` 属本次 STL 仍允许重新生成 rc=0；库层集合含 STL/run.log/报告/清单/`_verify.json`/三视图、唯独放行默认基线；正常 write → require 正向闭环 rc=0 / 13 项 PASS / 绑定 0.06、0.06、4.42%；R43 8/8、R46 8/8、R47 4/4 无回归；全量 **3.14 191/191**、3.12 188（129 skip）、3.13 188（130 skip、**0 error**）、10 模块编译通过；默认 12/12 且与交付 `_verify.json` 逐字节相同（`46a6827a…`），严格/溯源/证据 13/13、四档 15/15 PASS、八份交付哈希未变。自检中 3 处失败均为夹具/断言缺陷（单面 STL 使默认复验 rc=1；3.13 缺依赖 CLI 走 R46 `MissingDependencyError` 未到 `--json` 写出；正向副本报告/清单仍指向原绝对路径致 2 项误伤），改断言与夹具、未放宽判据。本轮**不改任何几何、不改默认输出、不重新生成交付基线** |
| R49 | 正确性/一致性/完整性 | 修 R46 引入的跨模块回归：主链路把「环境缺依赖」误报成「成品几何复验失败」 | `convert_3d.verify_exported_stl()` 新增 `dep_error = getattr(_file_verify, "MissingDependencyError", ImportError)`，`except (ImportError, dep_error)` 分支产出 `pass=False` / `skipped=False` / `dependency_missing=True` 与「环境缺依赖，不是成品几何问题」诊断；docstring 改写为「None 仅在 verify_deliverable 模块本身不可导入时出现」的准确契约；`tests/test_convert_file_verify.py` 补 2 项回归（缺依赖分类 + verdict 带走诊断、旧版 ImportError 与真实几何异常区分） | **实证**：真实 Python 3.13（缺 trimesh）调用 `verify_exported_stl` 得到 `pass=False`、`skipped=None`、`error="MissingDependencyError: 几何复验需要 trimesh…"`、`checks={}`，而函数 docstring 却承诺「缺依赖跳过、调用方不应把跳过当成成品失败」。根因是 R46 把 `geometry_checks` 的异常从 `ImportError` 改成 `RuntimeError` 子类，旧 `except ImportError` 成死代码，`except Exception` 把环境问题吞成普通的 `pass=False`。保持 fail-closed 不降级为 PASS，但必须机器可读地分类，否则 CI/排障会把「换解释器」当成「模型做坏了」 | PASS：3 项定向回归全过；真实 3.13 复现 `pass=False / skipped=False / dependency_missing=True` 且诊断含「环境缺依赖」；`apply_file_verification` 使 verdict FAIL 且 `file_verification_failure` 带该诊断；`_file_verify is None` 的历史 skip 语义不变、通用几何异常不带该标记；全量 3.14 **211/211**、3.12 208（136 skip）、3.13 208（137 skip、**0 error**）。本轮**不改几何、不改默认输出** |
| R50 | 正确性/一致性/边界情况 | 堵住「证据角色与文件名解绑」：正面渲染图可整体脱出哈希链而 13/13 仍 PASS | `verify_deliverable.py` 新增 `expected_evidence_files(stl_path)`（由 `_evidence_names` 派生「角色 → 文件名」唯一真值）；`evidence_index_checks()` 逐条要求 `item.file == expected_files[role]`，不符即 FAIL 并给出应为的文件名；生成侧仍复用同一派生函数。补 3 项回归（改指向 `decoy.png`、改指向另一视图文件、生成侧与复验侧映射一致） | **实证**：在隔离副本把 `front_view` 条目的 `file` 改成同目录新增的合规 `decoy.png` 并同步改字节数/SHA256，其余三视图原封不动，`verify(require_evidence_index=True)` 仍 **13/13 PASS**。旧实现只校验角色集合、文件名不得路径穿越、磁盘哈希与基线一致；文件名本身任意，等于「哪项证据真正被哈希链锁住」由基线自己说了算。R44 的几何绑定只查固定路径的三张图，无法发现基线把角色挪走 | PASS：修复前 13/13 PASS 的样本现 `evidence_index_valid=False`、诊断含「绑定了错误的文件」，且其余 12 项仍 True；3/3 回归通过；默认 12/12 与交付 `_verify.json` 仍逐字节相同（`46a6827a…`）。本轮**不改几何、不改默认输出、不重新生成交付基线** |
| R51 | 正确性/完整性/边界情况/一致性 | 把 R44「只比宽高比」的两类真实绕过做实并封闭 | `verify_deliverable.py` 新增 `RENDER_MAX_FILL_FRACTION=0.90` / `RENDER_MIN_ROW_WIDTH_CV=0.10` / `RENDER_MAX_EDGE_SPREAD=24` / `RENDER_CROSS_VIEW_TOL_PCT=5.0`；`png_foreground_bbox()` 在包围盒内做第二遍扫描，输出填充率、逐行宽度变异与四边亮度极差；`render_binding_checks()` 加入「是否轮廓 / 背景是否可靠」判据，并做三视图 Z 像素高度、正/背视图 X 跨度的互校，结果并入既有 `evidence_index_valid`（不新增检查项）。两处正例夹具从纯色矩形升级为轮廓状 `_make_silhouette_png()`。补 5 项回归 | **实证两条**：① 把 front 换成 `174×686` 纯色矩形（比例 0.25364 与 STL 完全一致）、同步改基线哈希 → 修复前 **13/13 PASS**，绑定误差仅 0.06%；② 换成 `152×600` 的轮廓图（比例仍 0.2533）→ 同样 **13/13 PASS**。根因是 R44 只用「前景包围盒宽高比」一个标量，任何凑对该标量的图都能冒充，而真实正交渲染的前景是复杂轮廓、且三视图共用 `ortho_scale = max(Z,水平)*1.12`。实测真实三视图填充率 0.464–0.505、行宽变异 0.364–0.480、四边亮度极差 2、前景高度均 686px、正/背宽度均 174px，阈值留足余量 | PASS：修复前两类样本均 PASS，修复后同步改基线仍被拒（分别命中「填充率/等宽矩形」与「前景高度/Z 尺度」），且**仅** `evidence_index_valid` 一项 FAIL；渐变背景结构化拒绝；真实交付绑定误差仍 0.06% / 0.06% / 4.42%；`tests.test_verify_deliverable` 全模块 **122/122** 通过（含 R43/R44/R45/R46/R47/R48 全部既有用例，夹具升级后无回归）；默认 12/12 与交付逐字节相同。**自检中 1 处失败**：`png_foreground_bbox` 新增形状指标后，R45 的「正常图」断言仍通过但 R43/R47/R48 正例夹具是矩形，会误判 FAIL —— 升级两处夹具为正经轮廓，未放宽任何判据 |
| R52 | 正确性/边界情况/一致性 | 修「证据相对路径按 CWD 解析」导致的合法交付误判 FAIL | `verify_deliverable.py` 新增 `_resolve_evidence_path(value, origin_path)`；`find_output_sha256` / `file_verification_contract` / `source_provenance_checks` 增加可选 `report_path` / `manifest_path`，路径分别按承载它的证据文件所在目录解析；`verify()` 把两份路径传下去，并让 `file_verification.stl` 的 `same_file` 也走同一解析器。补 4 项回归 | **实证**：把副本清单的 `outputs[].path` 与两处 `file_verification.stl` 改成相对文件名后，从 `E:\AI`（非交付目录）复验，`file_sha256_matches_manifest=False`、`manifest_stl_output_index=None`、整体 FAIL —— 但 STL、哈希、报告全部合法。旧实现把相对路径交给 `os.path.abspath`，即按当前工作目录解析；交付目录整体搬迁或清单改用相对路径（常见的可移植交付形态）就会误拒。绝对路径语义不变，`origin_path=None` 保持旧库调用兼容 | PASS：4/4 回归通过（全链路相对路径 + 异 CWD 12/12 PASS、清单定位、溯源三方、两处 fv.stl 契约）；篡改哈希仍被拒、绝对路径不受影响；默认输出与交付逐字节相同。**自检中 1 处失败**：首版只改了 3 个函数，漏掉 `verify()` 里 `same_file` 仍按 CWD 解析，导致 `file_verification_consistent=False` —— 补上第 4 处解析后通过，属实现遗漏而非夹具缺陷，如实记录 |
| R53 | 性能/正确性 | 消除几何复验对 37MB STL 的重复解析与重复体积计算 | `geometry_checks()` 改为 `raw = trimesh.load(process=False)` 一次加载 + `welded = raw.copy(); welded.process()`，不再 `trimesh.load(process=True)` 第二遍；单实体（`len(parts)==1`）时 `part_vol` 直接复用已算出的 `volume_raw`，多实体仍逐块重算。补 3 项结构回归（mock 断言 `trimesh.load` 恰好调用 1 次、多实体不被短路、真实交付 12 项指标逐字段与 `_verify.json` 相同） | 实测 `geometry_checks` 旧实现两次完整解析同一 STL（首轮 ~1.04s，其中 `process=True` 那次含 0.30s 解析），单实体又对 `split()` 出的唯一一块重算 `q.volume`（~0.32s）；这两段都是纯粹重复劳动。改为 copy+process 后，在 `final5` 上面数/顶点/水密/绕向/体积/`is_volume`/包围盒/euler 逐项等价。用结构断言而非计时断言锁定优化，避免 CI 时序抖动 | PASS：3/3 回归通过；真实交付 12 项几何指标与落盘 `_verify.json` **逐字段相等**（面 739612、体积 +34749.002、euler -90、连通块 1）；稳态 `geometry_checks` 2.20s（首调含 trimesh 导入 3.73s），消除一次完整解析与一次体积重算；全量 3.14 211/211。本轮**不改几何、不改默认输出** |
| R54 | 一致性/完整性/可读性 | 把 R48 自认的「两份 protected 靠回归锁定」做实，改为单一交付清单派生 | `verify_deliverable.py` 新增 `DELIVERY_ARTIFACTS`（7 项派生后缀 + 角色名）与 `delivery_artifact_paths(stl_path, allow=())`；`evidence_paths()` 只声明放行 `verify_result`，`write_index_protected_paths()` 只声明放行 `evidence_index`，其余全部从同一清单派生；删除 `EVIDENCE_SUFFIXES` 与手工「筛掉基线再补回 `_verify.json`」逻辑。补 3 项回归（两集合恰为全集减去各自合法输出、往清单加一项两种动作自动保护、合法/非法写出行为不变） | R48 明确记下：`evidence_paths`（手写 6 个后缀、刻意漏 `_verify.json`）与 `write_index_protected_paths`（从前者筛掉基线、手工补回 `_verify.json`）语义靠回归偶然锁定。将来新增一种派生产物，只要漏改一处就会出现「`--json` 能覆写、写基线不能」或反之的静默漂移，而 R36/R38/R48 三次事故都正是「换个分支没人补护栏」。现在调用方只声明「本次哪个文件是合法输出」，不再维护两份「哪些要保护」 | PASS：3/3 回归通过；R38 的 `evidence_paths` 集合断言、R48 的 `write_index_protected_paths` 库层契约、R43 的基线保护全部仍通过；`--json` 仍可写 `_verify.json`、写基线仍可写 `_evidence.json`，交叉覆写均 rc=2；全量 3.14 211/211。本轮**不改几何、不改默认输出、不重新生成交付基线** |
| R55 | 正确性/边界情况/完整性 | 显式参考图失效时拒绝静默降级 | `convert_3d.py` 在 `main()` 区分「显式 `--ref-image` / 自动发现 / `--no-fidelity` 明确 opt-out」三类：显式图不存在、不是文件、`mesh_fidelity` 不可用或解析抛异常，一律 `SystemExit(2)` 且在导出前停止；自动发现失败仍沿用旧告警降级。补 4 项 CLI 回归 | **实证**：`--ref-image` 指向不存在文件时仍 rc=0 导出 STL 且无 `_fidelity.json` —— 用户主动要求的保真验收被无声跳过，与「自动找图失败可兼容旧流程」性质完全不同。**自检中 1 处失败**：首版字符串型 `SystemExit` 实际退出码为 1，与参数/执行错误 rc=2 契约不符，已改为整型 2 | PASS：4/4 回归（显式缺失/损坏 ref 均 rc=2 且无 STL；`--no-fidelity` 仍 rc=0；自动发现损坏图仍降级）；主链路全量 38/38。本轮**不改几何、不改默认输出** |
| R56 | 正确性/完整性/边界情况 | 用 STL 投影轮廓 IoU 封堵异形状假图 | `verify_deliverable.py` 新增 `RENDER_SILHOUETTE_GRID=96` / `RENDER_MIN_SILHOUETTE_IOU=0.65` 与 `stl_silhouette_checks()`：从 STL 三角形正交光栅化 front/back/side 三方向掩膜，与 PNG 前景各自按包围盒归一化后算 IoU（含水平镜像以兼容正/背相机），仅在 `--require-evidence-index` 启用，结果并入既有 `evidence_index_valid`、不新增检查项；CLI 增「STL 投影轮廓 IoU」摘要。补 4 项回归 | **实证**：三张菱形假图同时满足 R51 的比例、填充率、行宽变异、背景同质性与三视图跨尺度互校，修复前 `render_binding_checks` 全过 —— 任何「形状统计量」都能被针对性凑齐，必须比较实际形状。实测真实交付归一化 IoU **0.8372 / 0.8602 / 0.8283**，菱形远低于 0.65 | PASS：4/4 回归（真实交付高 IoU、菱形端到端被拒、盒体投影矩形/菱形判别、非法栅格与缺图结构化拒绝）；复验模块全量通过；默认 12/12 与交付 `_verify.json` 仍逐字节相同（`46a6827a…`）。本轮**不改几何、不改默认输出**；性能开销见残留风险第 19 条 |
| R57 | 正确性/完整性/一致性 | 让 STL 导出失败不破坏既有成品 | `convert_3d.py` 新增 `export_mesh_atomic()`：同目录 `TemporaryDirectory` staging 导出 → STL 回读复验（并把 `fv["stl"]` 改写为最终交付路径）→ 伴生文件与主文件依次 `os.replace`；导出循环把 8 个格式分支统一为白名单 + 单一安全写盘，任何异常只在 `finally` 清理 staging。补 5 项回归 | **实证**：导出器先写 `PARTIAL-STL` 再抛 `RuntimeError` 时，既有完好 STL 被覆盖成不可恢复的半成品；且旧实现只有 STL 分支有回读复验，其它格式失败同样毁文件。staging 与目标同盘，`os.replace` 原子，不会出现「半个文件」的可见状态 | PASS：5/5 回归（失败保留原文件字节、成功替换且 `fv.stl` 指向交付路径、OBJ 伴生 `.mtl` 随主文件换入、5 种环境可用格式仍落地、CLI 重复导出无 staging 残留）；主链路全量 38/38；3mf/fbx/usdz 因缺 lxml/exporter 仍走 fail 分支，未伪装通过。本轮**不改几何、不改默认输出** |
| R58 | 正确性/完整性/边界情况 | 下载内容完整性与原子落地 | `meshy_client.py` 新增 `_validate_download()`（`.glb` 校验 `glTF` 魔数且头部声明长度 == 实际字节数；`.png`/`.jpg` 校验签名；其它仅要求非空）；`download()` 改用同目录唯一 `mkstemp(*.part)`，`finally` 清理，只有校验通过才 `os.replace`。新建 `tests/test_meshy_client.py`（首个输入链路回归文件）。补 5 项离线回归 | **实证**：签名 URL 过期时服务端可能返回 **HTTP 200 + JSON 错误页**，旧实现只看「文件非空」，实测把 `{\"error\":\"bad signature\"}` 原子替换成 `.glb` 并返回成功，损坏输入随后流入重建链路却无人报错；固定 `.part` 文件名还有并发下载互相踩踏风险。GLB 声明长度校验另抓传输截断 | PASS：5/5 回归（错误 JSON / 截断 GLB / 错误声明长度 / PNG 错误页均被拒且原文件字节不变；合法 GLB 与 PNG 被接受；中途断流无 `.part` 残留）；9/9 输入链路测试全过；全程无网络、不消耗积分。本轮**不改几何、不改默认输出** |
| R59 | 边界情况/正确性/可读性 | 429/5xx 的 `Retry-After` 健壮解析 | `meshy_client.py` 新增 `_retry_after_seconds()`：支持整数秒与 RFC 7231 HTTP-date（`parsedate_to_datetime`），非法/NaN/Inf/负数/超大值统一退回指数退避或夹到 `[0,30]`；`_request()` 去掉裸 `float(retry_after)`，`download()` 去掉局部 `import time as _time` 改用顶部导入。补 4 项回归 | **实证**：`Retry-After: Wed, 21 Oct 2015 07:28:00 GMT` 时 `float()` 抛 `ValueError`，恰恰在最需要退避的 429 场景让请求链崩溃并暴露裸栈；旧代码对负数/超大值也无上界 | PASS：4/4 回归（秒数 / HTTP-date / 非法值 / 越界值 + `_request` 端到端 429→成功、503 超大值夹到 30s）；9/9 输入链路测试全过；顺手修掉测试夹具 `HTTPError` 未关闭的 `ResourceWarning`。本轮**不改几何、不改默认输出** |

---

### R43 交付证据误伤与恢复记录（如实说明）

本轮深审的第一支探针**直接在真实交付目录原地篡改**：`target_final5_front.png` 被写成
垃圾字节、`target_final5_side.png` 被删除，随后的「恢复」又误把 `back.png` 的内容复制到
`front.png`。这是操作失误，不是设计好的实验，但它恰好以最硬的方式证实了缺口：
12/12 独立复验全程 PASS，且当时没有任何证据哈希可用于确认损失范围。

恢复依据：`print_ready/_verify/render_front_ortho.py`（原始正交渲染脚本，Blender 5.2）
从**未改动的 `target_final5.stl`** 重渲染三视图。以未被破坏的 `back.png` 做对照，
重渲染结果解码后像素**逐字节相同**（mean_abs_diff = 0.0），三个文件字节数也与原始
完全一致（391448 / 375144 / 366022），差异仅在 PNG 的 `tEXt Date` / `tEXt RenderTime`
两个元数据块及其 CRC（Blender 每次渲染写入当时时间）。因此 front/side 按同脚本同参数
重渲染放回，`back.png` 保持原始字节不动。

**诚实边界**：恢复后的 front/side **像素与原始一致，但文件字节不再等同原始**——
PNG 元数据时间戳是恢复时刻，原始两图的 SHA256 从未被任何清单/文档记录，无法逐字节
复原，也无法事后证明。这正是 R43 建立证据基线要杜绝的情况：`target_final5_evidence.json`
现已锁定三视图与 `run.log` 的 SHA256/字节数/尺寸，今后任何改动都会被发现，且提供了
可校验的恢复基准。本次事故同时改掉了后续所有探针的做法：一律在隔离副本目录操作。

---

## 三、最终版本相对初始版本的整体提升

| 维度 | 初始 | 最终 | 提升 |
|---|---|---|---|
| 正确性 | 正/背面可被 IoU 噪声选错；核心指标可被覆盖；导出失败返回 0；会覆盖输入 GLB；法线内向的水密网格会被当成合格成品；验收只评价内存网格；多实体也判"水密"、悬空碎块留在成品；底层门禁开关在产品入口被静默忽略 | 显式正背面判据；核心指标防篡改；退出码 1/2/3；同名输出自动跳过；**主链路导出后自动回读磁盘 STL 复验**（焊接闭合/绕向/正体积/面数/顶点/尺寸 7 项），失败返回 1；连通块/悬空碎块/退化面量化；**`--drop-floating-parts` 按拓扑剔除碎块 + `--strict-single-body` 主链路硬门禁，最终成品为单一连通实体**；三项门禁在 `fig.py`/控制中心均可用且默认关闭 | 从"可能产出错误朝向且无提示"到"错误可检测、可拒绝、可追溯、可修、可打印性有硬门禁，判定对象是落地文件、成品已消除悬空碎料，且入口不会静默丢掉用户要求、验收工具遇畸形证据不再崩、`--json` 不再覆盖日志与三视图、生成侧 verdict 不再因跳过指标抛栈或误判 truthy、假溯源哈希不再落盘且可被独立复验拒绝、三视图/日志被替换或删除可被证据基线查出" |
| 完整性 | 9 测试；无 verdict；无 manifest；无严格水密；无文件级复验 | **219 测试**（保真 30 + 独立复验 136 + 主链路闭环/连通块 38 + 输入链路 9 + 入口契约 6；全量 233 项）；5 项验收清单；完整运行清单与哈希；`--strict-watertight`；12 项独立复验 CLI（严格 13 项）+ `--strict-single-body` / `--require-file-verification`（按路径定位清单条目、逐项核对主链路文件级结论、`verdict` 按固定契约与复合语义重算汇总、报告/清单两处文件级结论交叉印证且字段不可整段删除、冲突参数显式拒绝、结构化结果原子写且不可覆盖证据、畸形证据结构化拒绝、`--json` 保护全部派生证据、生成侧 verdict 输入契约、报告溯源元数据权威生成、opt-in 溯源三重印证、**交付证据基线与零依赖 PNG 容器校验**）；`geometry_cleanup` 明细入报告与清单 | 回归覆盖 **+210 例**；产物可复核、可独立验收、可拒绝伪造，主链路强制闭环，三层 CLI 契约不再漂移，验收工具自身的隐藏假设、汇总字段与判据集合防篡改、畸形证据与证据写出边界、生成侧 verdict 畸形输入、报告溯源元数据与溯源三重印证、交付证据完整性与 PNG 容器损坏均有回归保护，主链路/复验两侧判据集合一致性有自动锁定，文件级闭环证据不再可被静默降级，用户显式传入的验收要求也不会被无声丢弃 |
| 一致性 | 注释/默认值/文档三处漂移；`extra` 一变量两义；报告无口径；新增底层开关不接上层入口 | `PRINT_DEFAULTS` + **`PRINT_FLAG_DEFAULTS` / `PRINT_FLAG_ARGS`** 单一真值（三层键名由回归测试锁定）；schema 2.0 + 10 项 `metric_dictionary`；文档标注版本；保真模块与 `fig.py` 统一"scipy 可选"约定 | 跨模块不再隐式依赖，指标解释唯一，新增参数不会只在底层生效 |
| 性能 | 拓扑 0.89s；视觉外壳逐行循环；采样 297 万点；朝向搜索重复过滤 | 拓扑 0.07s（12.5×）；视觉外壳 1.9×（密度自适应）；采样 52 万点（IoU 差 <0.001）；朝向搜索 1.1× | 报告/对齐阶段显著提速且指标等价 |
| 边界情况 | EXIF/RGBA/损坏图/空网格/NaN/非法参数/Blender 超时均会误判或崩溃 | 全部结构化处理或降级；缺 scipy/trimesh/rembg 分别降级或 SKIP；损坏 STL 的 NaN/Inf 由 `json_safe` 归一；多实体、悬空碎块、退化面单独量化；**空网格/清理后主体非闭合/体积非正一律回退原网格**；硬门禁缺 `--to stl` / `--formats stl` 时上下两层参数校验；控制中心非法布尔类型显式报错而非静默忽略 | 换机、异常输入、外部程序失败、损坏文件、非常规拓扑、错配的入口参数都不再中断链路或静默放过；畸形证据顶层/字段、`--json` 误指向非 JSON 证据也走显式拒绝；评估指标被跳过或写成非标准类型时主链路给出可读 FAIL 而非崩溃或误判；输入溯源的报告哈希、清单哈希与磁盘源文件三方不一致时可被 opt-in 门禁查出；三视图写成垃圾字节/被复制冒充/被删、日志变空、证据基线被篡改或目录穿越均走结构化拒绝 |
| 可复现性/环境兼容 | 无 manifest；硬依赖 scipy，换解释器即 `ModuleNotFoundError`（实测 14/32 用例报错）；报告与磁盘文件无独立核对；**最终成品只能靠绕过产品入口的底层命令生成** | manifest 记录命令/哈希；scipy 变可选且 7 个 ndimage 操作逐像素等价降级；明确项目 venv 复现命令；**主链路自动把文件级复验与清理明细写进报告、verdict 与 manifest**，旁路 CLI 交叉核对；`final5` 由完整可复现命令重跑生成；**R30 后 `fig.py print` 产品入口产出的 STL 与 `final5` SHA256 完全一致** | 同一份代码在 3.12.3(venv)/3.14/3.13(缺依赖) 三种环境下均可验证；最终成品报告内自证 12 项交叉一致，且用户按正常产品流程即可逐字节复现 |
| 最终 STL 精度 | `final2`：final_mesh IoU 0.8285、水密、边界/非流形 0、152.24mm | **`final5`**：final_mesh IoU 0.8281、水密、边界/非流形 0、152.24mm、739,612 面、**连通块 1（悬空块 0）**、体积 +34749.002mm³、verdict PASS、独立复验 12/12 | **轮廓相似度持平（-0.0004，噪声级）**；提升集中在可打印性（单实体）、正确性、鲁棒性、可复现性与正面朝向 |

**诚实结论**：59 轮迭代没有、也无法继续提高轮廓 IoU 数值 —— 单图重建的精度上限由参考图与重建器决定，
后处理只能不破坏它。本次实质收益是：修好了"背面被当正面"这一真实成品缺陷，堵住了覆盖输入、
失败静默通过、报告可伪造、异常中断、换解释器即崩等工程缺陷，并让每次转换留下可复核的命令、
哈希与验收结论。R25 是交付复核时发现的真实缺陷（此前"21 用例全过"只在项目 venv 成立），
R26 是更深层复审发现的文件级验收缺口（法线内向的水密网格此前会被判合格），
R27 是再深一层发现"R26 的复验只是旁路工具、主链路并未闭环"并把它接进导出流程，
R28 是复审落地模型连通性后发现"多实体同样判水密、6 个悬空碎块从未被任何验收发现"并补上量化与可选门禁，
R29 则把"检测到却不能修"的最高优先级残留真正解决：按拓扑连通性剔除碎块、主链路可硬拒绝，
并用完整命令重跑转换产出单实体的 `final5`；R30 复审上层入口时发现这份成品**无法从用户实际
使用的一条龙流程生成**，于是把三项门禁接到 `fig.py` 与控制中心，并用产品入口跑出与 `final5`
SHA256 完全一致的 STL，把"可复现"从文档承诺变成可验证事实。
R31 把复审对象从「产品链路」转向「验收工具本身」：实证发现 `verify_deliverable.py` 隐含
假定 STL 是清单第一个输出，而产品入口默认多格式导出会让合格成品被独立复验误判 FAIL；
按路径定位后修复，并补 6 项回归与 2 处夹具修正，`final5` 的验收结论与哈希均不变。
R32 把「独立性」推到内容层：实证发现独立复验只信任主链路汇总的 `pass`，逐项 `checks`
被写反或清空仍能 12/12 PASS；改为逐项核对并与自身重算的几何判据交叉比对，
补 7 项回归，`final5` 的验收结论与哈希仍不变。
R33 再换一侧复审 `verdict` 本身：`verdict_consistent` 用的是裸 `all(values())`，
把失败判据写成 `"false"`、整数 2，删掉判据（连 `required_checks` 一起删），
甚至把整个 `checks` 换成 `{"forged": True}`，修复前都仍能 12/12 PASS。现按
`build_verdict` 的固定 5 项契约校验结构、按 `required_checks` 重算汇总、拒绝非布尔值，
并把内存水密结论与磁盘 STL 重算结果交叉绑定；补 12 项回归与 2 处单一真值夹具，
`final5` 的验收结论与哈希仍不变。
R34 把上一轮深审发现却搁置的缺陷做实：`verdict.pass` 并非单纯的内存结论，
而是「内存判据 ∧ 文件级复验」（`apply_file_verification` 会叠加），R33 只按
前者重算，于是把主链路诚实产出的不合格报告误报成「汇总不一致」。现按复合语义
重算、给 `verdict.pass` 补严格布尔校验，并把「自洽地判定不合格」与「汇总被篡改」
分别诊断；同时把 `build_verdict` 两种模式与 `VERDICT_KNOWN_CHECKS` 的一致性
从手工核验固化为回归。补 6 项回归，`final5` 的验收结论与哈希仍不变。
R35 把复审推进到「两个证据文件是否互相印证」：实证发现独立复验只看报告单侧，
删掉 `report.file_verification`（或连同 `verdict.file_verification_pass`）就会静默退回
R27 之前的 11 项口径并照样 PASS；而 `write_manifest` 会把同一个 `file_verification`
写进清单，这份独立文件此前只被用来定位输出哈希。现以清单判定字段该不该存在、
要求两处逐项一致、检查项恒定写入，并补 `--require-file-verification` 让交付验收
可显式拒绝旧报告。补 9 项回归与 3 处夹具修正，`final5` 的结论与哈希仍不变。
R36 把复审推进到「用户显式传入的要求是否真的生效」：实证发现 `--stl-only` 与强制闭环 /
显式证据文件同时传入时，旧实现直接 return、把要求静默丢弃后仍输出 PASS；`--json` 则既会在
写盘失败时抛裸 traceback 并把退出码伪装成「验收不通过」，也可能误覆盖交付 STL。现改为
参数冲突显式拒绝（退出码 2）、原子写 + 证据文件保护，并给「仅几何复验」加上醒目标注。
补 10 项回归，`final5` 的结论与哈希仍不变。
R37 把复审推进到「证据文件本身畸形时验收工具会怎样」：实证把 `fidelity.json` 顶层换成
数组，旧实现抛未捕获 `AttributeError`、裸 traceback、rc=1（与验收不通过同码）；
`extents_xyz` 畸形值直接让复验崩掉。现显式校验顶层对象、把畸形数值判为该项 FAIL，
并让 `main()` 兜底把残余属性异常映射为 rc=2。补 5 项回归，`final5` 结论与哈希仍不变。
R38 把 R36 自己承认的残留风险做实：实证 `--json` 指向同目录 `run.log` 会原子替换日志
且仍 rc=0，三视图同理。现以 `evidence_paths()` 枚举全部派生证据，并加「目标必须
`.json`」通用护栏；`*_verify.json` 作为合法输出刻意排除。补 5 项回归，
`target_final5_verify.json` 恢复默认 12/12 口径且哈希与 R36 时完全一致 `46a6827a…`，
`final5` / `e2e` 哈希仍不变。
R39 把复审从「验收工具」换回「主链路生成侧」：实证 `build_verdict` 在 IoU / 宽高比
评估跳过（值为 `None`）时抛 `TypeError` 直接中断导出，`bool("false")` / `bool(2)` 会把
非水密报告判成水密，`False == 0` 会把布尔假值判成「无边界边」—— 都是 R33/R37 已在
复验侧堵住、生成侧却从未加固的同类问题。现用三个纯函数把有限数值与严格布尔/零值
契约补齐，畸形指标写入 `invalid_metrics` 明细并判 FAIL。补 6 项回归，用真实 `final5`
报告重算 verdict 与落盘结论逐字段一致；三环境 136/136，成品与全部证据哈希未变。
R40 把复审推进到此前 39 轮从未审过的**报告元数据生成源头**：实证 `save_report` 的
`setdefault` 让 `FAKE_OLD_INPUT` 这类假溯源哈希、`schema_version='1.0'` 与假指标口径
原样落盘，源文件缺失时哈希字段又静默消失。现强制以常量/磁盘哈希覆盖，并写
`metadata_corrections` / `source_hashes_unverifiable` 供审计；补 6 项回归，真实 `final5`
报告重写后关键字段逐字段一致。
R41 则补上这些字段**完全无人消费**的另一半：实证把报告里两个溯源哈希改成
`TAMPERED_INPUT` / 全零 / 整段删除，独立复验仍 12/12 PASS。现提供默认关闭的
`--require-source-provenance`，按「报告 ↔ 清单 ↔ 磁盘源文件」三重印证并纳入
`--stl-only` 冲突契约；启用后 `final5` 13/13、三档组合 14/14 PASS，
默认结果写盘与交付 `target_final5_verify.json` **逐字节相同**（`46a6827a…`）；
补 7 项回归，三环境 149/149，五份交付哈希未变。
R42 把上一轮明确留下的「数值评估内核 / 阈值可重算性」做实：实证 `verdict` 的两项
数值判据只校验布尔自洽，把 IoU 改成 0.20、阈值改成 0.99、宽高比误差改成 99
仍 12/12 PASS；同时发现 `min_iou` 其实已在报告与清单 `parameters` 落盘
（残留 #13 的「阈值没有存入」表述因此过时，本轮已改写）。现按双源阈值重算
两项判据，并把生成侧宽高比容差魔法数提成两侧共享常量由回归锁定。
该门禁**默认生效**且并入既有 `verdict_consistent`，不新增检查项；正常报告
`verdict_reason` 仍为 None，默认输出与交付 `target_final5_verify.json` 逐字节相同。
补 7 项回归，三环境 156/156，`final4` / `final5` 仍 PASS，五份交付哈希未变。
R43 把复审换到**交付证据生成链**，并如实记录了一次探针误伤真实三视图的事故：
实证 front 被写成垃圾字节、side 被删，复验仍 12/12 PASS，清单 outputs 只有 STL，
连恢复基准都没有。现以 `render_front_ortho.py` 从最终 STL 重渲染恢复（像素逐字节一致、
文件字节数一致，仅 PNG 元数据时间戳不同，已如实写入上节），并新增证据基线 +
`--require-evidence-index` opt-in 门禁：零依赖校验 PNG 容器 CRC、三视图哈希两两不同、
日志非空、路径不越界。补 8 项回归，三环境 164/164，默认输出与 `_verify.json`
逐字节相同，五份既有哈希未变，新增第六份基线。
R44 把上一条明确写下的「只验容器不验像素来源」做实：在隔离副本里把 side 图换成
另一模型的 768² 渲染图、同步更新基线的 SHA256/字节数/尺寸，`evidence_index_checks()`
仍判通过（容器 CRC 完好、哈希自洽、三视图互异），四档组合仍 15/15 PASS。现新增
零依赖 PNG 反滤波解码 + 前景包围盒比例绑定：背景取四边亮度中位数，前景比例与
独立几何复验得到的 STL 包围盒比例比对（front/back = X/Z、side = Y/Z，容差 10%）。
实测恢复后的三视图误差 0.06% / 0.06% / 4.42%，既堵住换图冒充，也**从几何上自证
R43 事故后重渲染恢复的 front/side 确实来自最终 STL**。绑定并入既有
`evidence_index_valid`，不新增检查项、默认输出与 `_verify.json` 逐字节相同；
补 7 项回归，三环境 171/171（缺依赖环境 168 含 skip、0 error），六份交付哈希未变。
R45 把复审对准**上一轮刚引入的新代码**：R44 的 `_decode_png_luma` 第一次处理像素，
`MAX_EVIDENCE_BYTES` 只限制输入文件字节，却没限制 IHDR 声明的像素规模。实证构造
CRC 完好的 `4294967295×4294967295` PNG，容器层判 True，`decompress` 的
`max_length` 因超出 C 层 `Py_ssize_t` 抛 `OverflowError`，`render_binding_checks`
与 CLI 白名单都未捕获 → 裸 Traceback。现以三项显式上限在分配缓冲区和调 C 层
之前拦截，并把资源/数值类残余异常统一映射为 rc=2。修复前后同一支回归从
「2 FAIL + 1 ERROR」转为 3/3 通过；三环境 174/174，六份交付哈希未变。
R46 把复审换到**「生成侧 ↔ 复验侧」契约层**：真实 3.13 缺依赖 CLI 裸 Traceback
+ rc=1，以及 `--write-evidence-index` 对换模型图打印 `[OK]` 写出复验必然 FAIL
的基线，是两条各自独立、又都属「自相矛盾」的硬缺陷（修复前回归
4 FAIL + 5 ERROR）。现新增零依赖 `stl_extents_from_file`（直接读 STL 本体，
支持二进制/ASCII，实测 0.43s 且与 trimesh 包围盒一致），让生成侧复用复验侧的
`render_binding_checks`；不信任任何报告元数据、不新增检查项、不新增开关，
基线 schema 与既有交付逐字段不变。缺依赖定义 `MissingDependencyError` 映射
rc=2 + 中文诊断。隔离副本正向验证「正常 write → require」rc=0 / 13 项 PASS，
三环境 182/182（缺依赖 179 含 skip、0 error），八份交付哈希未变。
R47 把复审换到**「独立动作模式的参数契约」**：`--write-evidence-index` 的
CLI 分支只列 3 个冲突项、且完全不调用 `check_mode_contract`，实证
`--require-source-provenance` / `--require-file-verification` /
`--strict-single-body` / `--report` / `--manifest` 五个显式硬门禁被静默丢弃
却仍打印 `[OK]` rc=0 —— 与 R36 完全同类。现把 8 类冲突集合收进
`check_mode_contract` 作为库层与 CLI 的唯一真值，消除两层漂移；修复前后
同一批组合从 rc=0 变为 rc=2 + 可读诊断，正常写基线不受影响。补 4 项回归，
三环境 186/186（缺依赖 183 含 skip、0 error），八份交付哈希未变。
R48 把复审换到**「输出目标覆写」**层面：`--json` 分支当年补了
`evidence_paths()` 全量保护，写基线分支却调用
`write_json_atomic(target, index)` 一份 protected 都没传。实证把
`--evidence-index` 指向报告/清单/复验结果/任意既有 JSON/另一 STL 的合法基线，
5 类全部 `[OK] rc=0` 静默覆写（修复前回归 6 FAIL + 1 ERROR）。现新增
`write_index_protected_paths()`（放行默认 `_evidence.json`、加回 `_verify.json`）
与 `guard_index_write_target()`（目标已存在时必须是记录相同 STL SHA256 的合法
基线），两层分别覆盖「派生路径」与「自定义命名任意路径」；`write_json_atomic`
诊断按 `label` 参数化。修复后 5/5 通过，目标被删除时 protected 仍能拦住，
正常 write → require 正向闭环 rc=0 / 13 项 PASS，三环境 191/191
（R48 时点；缺依赖 188 含 skip、0 error），八份交付哈希未变。
R49–R54 把复审推进到「前几轮改动自身的副作用」与「验收判据可被凑标量绕过」层面：
R49 修 R46 把缺依赖异常改成 RuntimeError 子类后主链路 `except ImportError` 失效的回归；
R50 实证基线角色可改指向任意合规 PNG 而 13/13 仍 PASS，补上角色 → 派生文件名绑定；
R51 实证「比例凑对的纯色矩形」「改绝对取景但比例不变」两类 13/13 绕过，补轮廓形状指标
与三视图同一正交相机下的像素尺度互校；R52 修证据相对路径按 CWD 解析导致的合法交付误拒；
R53 去掉几何复验的一次完整 STL 解析与一次重复体积计算；R54 把 R48 自认的两份手工
protected 列表改成 `DELIVERY_ARTIFACTS` 单一派生。六轮全部不改几何、不改默认输出。
R55–R59 再审到「输入链路与导出链路尚未覆盖的静默损坏」层面：
R55 实证显式参考图失效仍 rc=0 导出无保真报告的 STL，改为导出前 rc=2 拒绝；
R56 实证菱形假图凑齐全部形状统计量仍全过，改用 STL 三角形正交投影轮廓 IoU
（真实交付 0.8372 / 0.8602 / 0.8283、阈值 0.65）；
R57 实证导出器中途抛错把既有完好 STL 截成半成品，改为 8 种格式统一 staging 原子替换；
R58 实证 HTTP 200 的 JSON 错误页被当成合法 GLB 覆盖既有成品，补内容签名/长度校验与唯一临时文件；
R59 实证 Retry-After 用 HTTP-date 时 `float()` 裸抛 ValueError，改为有界健壮解析。
十一轮（R49–R59）全部不改几何、不改默认输出、不重新生成交付基线；
三环境终检 **3.14 233/233、3.12 230（149 skip）、3.13 230（150 skip、0 error）**，
10 模块 + 3 个测试文件编译通过，默认 12/12、严格 13/13、溯源 13/13、证据 13/13、
四档 15/15 全 PASS，渲染绑定 0.06% / 0.06% / 4.42% 不变，
STL 投影轮廓 IoU 0.8372 / 0.8602 / 0.8283，默认 `--json` 与交付 `_verify.json` 逐字节相同，
九份交付哈希全部未变。
**R25–R28、R30–R59 均不改变几何；R29 是唯一改变交付几何的一轮** ——
`final5.stl` 与 `final4.stl` 哈希不同，但 IoU 完全相同、三视图差异 <0.05%，且 `final4` 完整保留为历史对照，
没有事后改写历史报告或哈希链。`final4` 生成于 R24，其报告/清单不含 `file_verification`，
独立复验对旧报告（两处皆无）保持兼容，且 R35 后检查项固定 12 项、不再静默减少；`final5` 由 R29 完整链路生成，报告内自证、旁路复验按 12 项全通过。
若继续追求相似度数值，必须走多视图重建或更换参考图，不属于后处理迭代范围。

---

## 四、最终版本清单

- **最终 STL（R29 生成、R30 验证可从产品入口逐字节复现）：
  `E:\AI\print_ready\_verify2\final5\target_final5.stl`**（36.98 MB，739,612 面，
  单连通实体，SHA256 `5c02f890c9e0…`）
- 量化报告：`target_final5_fidelity.json`（含 `file_verification` 8 项与 `geometry_cleanup` 明细）、
  `target_final5_manifest.json`、**`target_final5_verify.json`（12/12 PASS）**、运行日志 `run.log`、
  **R43 新增 `target_final5_evidence.json`（三视图/日志的证据基线，SHA256 `9c599949…`）**
- 三视图：`target_final5_front.png` / `_back.png` / `_side.png`（768×768；front/side 于 R43
  从最终 STL 重渲染恢复，像素与原始一致，详见「R43 交付证据误伤与恢复记录」；
  **R44 起启用 `--require-evidence-index` 时会额外核验三视图像素轮廓与本次 STL
  的 X/Z、Y/Z 包围盒比例一致，实测误差 0.06% / 0.06% / 4.42%**）
- **产品入口复现证据**：`E:\AI\print_ready\_verify2\_r30_e2e\`（`e2e.stl` / `e2e_fidelity.json` /
  `e2e_manifest.json` / `run.log`）；其中 `e2e.stl` 与 `final5.stl` SHA256 完全相同
- 历史对照：`E:\AI\print_ready\_verify2\final4\target_final4.stl`（R24 生成，7 连通块，完整保留未改动）
- 代码：`mesh_fidelity.py`、`convert_3d.py`（含 `verify_exported_stl` / `apply_file_verification` /
  **`drop_floating_parts` / `enforce_single_body`**）、**`fig.py`（R30 `PRINT_FLAG_DEFAULTS` /
  `PRINT_FLAG_ARGS` 与 `cmd_print` 显式透传）**、**`control_server.py`（R30 `print_quality_flags`）**、
  `repair_mesh_blender.py`、**独立复验 CLI `verify_deliverable.py`（R31 `find_output_sha256`
  按路径定位清单条目；R32 `FV_SHARED_GEOMETRY_CHECKS` / `_flag_true` 逐项核对主链路结论；
  R33 `VERDICT_KNOWN_CHECKS` / `verdict_checks_valid` 按固定契约校验 verdict 结构并重算汇总；
  R34 按「内存判据 ∧ 文件级复验」复合语义重算并精确分类诊断；
  R35 `file_verification_contract` 以清单为第二证据源交叉印证、恒定保留检查项，
  并提供 `--require-file-verification` 强制闭环；
  R36 `check_mode_contract` 拒绝冲突参数组合、`write_json_atomic` 原子写且保护证据文件；
  R37 `load_json_object` 顶层对象校验；R38 `EVIDENCE_SUFFIXES` / `evidence_paths` 枚举派生证据
  并给 `--json` 加后缀护栏；R39 `_finite_float` / `_strict_true` / `_strict_zero`
  与 `build_verdict` 输入契约；R40 `save_report` 权威元数据与审计字段；
  R41 `SOURCE_PROVENANCE_ITEMS` / `source_provenance_checks` 三重印证与 opt-in 门禁；
  R42 `ASPECT_SELF_CHECK_TOL_PCT` / `verdict_numeric_consistency` 数值判据重算；
  R43 `png_container_valid` / `build_evidence_index` / `evidence_index_checks` 交付证据闭环；
  R44 `_decode_png_luma` / `png_foreground_bbox` / `render_binding_checks` 像素级几何绑定；
  R45 `MAX_PNG_DIMENSION` / `MAX_PNG_PIXELS` / `MAX_PNG_RAW_BYTES` 解码资源上限；
  R46 `MissingDependencyError` / `stl_extents_from_file` 生成侧绑定与缺依赖 rc=2；
  R47 `check_mode_contract` write 分支与 CLI 冲突集合归一；
  R48 `write_index_protected_paths` / `guard_index_write_target` 写基线目标保护；
  R49 `dependency_missing` 分类与 fail-closed 诊断；
  R50 `expected_evidence_files` 角色/文件名绑定；
  R51 轮廓形状指标与三视图像素尺度互校；R52 `_resolve_evidence_path` 按证据文件目录解析；
  R53 单次解析与体积复用；R54 `DELIVERY_ARTIFACTS` / `delivery_artifact_paths` 单一保护清单；
  R55 显式参考图 fail-closed 与退出码契约；R56 `stl_silhouette_checks` 正交投影轮廓 IoU；
  R57 `export_mesh_atomic` 全格式 staging 原子导出；
  R58 `_validate_download` 内容签名/GLB 长度校验与唯一 `.part`；
  R59 `_retry_after_seconds` 秒数/HTTP-date 有界解析）**
- 测试：`tests\test_mesh_fidelity.py`（30 用例）、`tests\test_verify_deliverable.py`（**136 用例**）、
  `tests\test_convert_file_verify.py`（**38 用例**）、**`tests\test_print_quality_flags.py`（6 用例）**、
  **`tests\test_meshy_client.py`（9 用例，首个输入链路离线回归）**；
  `discover -p "test_*.py"` 全量 **233 用例**（3.14 233/233；3.12 与 3.13 各 230、
  149/150 skipped、0 error）
- 文档：`docs\STL保真修复与复审报告.md`（v1 历史）、`docs\STL精度二次复审与修复报告.md`（v2）、本记录
- 复现命令（本机项目解释器，Python 3.12.3、依赖齐全）：
  ```
  C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe -W error::ResourceWarning ^
      -m unittest discover -s tests -p "test_*.py" -v
  ```
  依赖契约：`numpy`/`Pillow`/`trimesh` 必需（缺 `trimesh` 时相关用例 SKIP）；
  `scipy` 可选（自动走逐像素等价的 numpy 降级）；复杂背景参考图另需 `rembg`。
- 重跑最终版本（与 `final5` 完全相同的命令，见 manifest.command）：
  ```
  C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe convert_3d.py ^
      E:\AI\ComfyUI\output\figure_3d_5b299f5bbb1a_00001_.glb --to stl ^
      --out-dir E:\AI\print_ready\_verify2\final5 --out-prefix target_final5 ^
      --ref-image E:\AI\ComfyUI\output\figure_3d_5b299f5bbb1a_00001__3d_input.png ^
      --height 150 --base 0.03 --min-iou 0.55 --voxel-mm 0.25 ^
      --strict-watertight --no-crop-background ^
      --drop-floating-parts --strict-single-body
  ```
- **产品入口复现（R30 起可用，用户实际一条龙链路；实测输出 STL 与 `final5` 哈希完全一致）**：
  ```
  C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe fig.py print ^
      E:\AI\ComfyUI\output\figure_3d_5b299f5bbb1a_00001_.glb --formats stl ^
      --out-dir E:\AI\print_ready\_verify2\_r30_e2e --out-prefix e2e ^
      --ref-image E:\AI\ComfyUI\output\figure_3d_5b299f5bbb1a_00001__3d_input.png ^
      --model-height 150 --base 0.03 --min-iou 0.55 --voxel-mm 0.25 ^
      --no-crop-background --strict-watertight ^
      --drop-floating-parts --strict-single-body
  ```
  控制中心 `/api/run` 的 `auto` / `print` / `image_print` 可在 body 里传
  `strict_watertight` / `drop_floating_parts` / `strict_single_body` 布尔值启用同样开关。
- 独立复验（不依赖转换链路，可直接验收成品）：
  ```
  C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe verify_deliverable.py ^
      --stl E:\AI\print_ready\_verify2\final5\target_final5.stl --strict-single-body
  ```
  退出码 0=通过 / 1=不通过 / 2=输入错误、参数冲突、畸形证据或结构化结果写出失败（R36/R37）；
  加 `--json <path>` 可导出结构化结果（原子写；目标必须是 `.json`，且拒绝覆盖 STL/报告/
  清单/`run.log`/三视图/`*_evidence.json` 等派生证据，见 R36/R38/R43）；
  交付验收建议再加 `--require-file-verification`（R35），显式拒绝不带文件级闭环证据的旧报告；
  再加 `--require-source-provenance`（R41）可核验输入模型/参考图在报告、清单与磁盘上的
  SHA256 三方一致（源文件已归档移走的历史交付不适用，故默认关闭）；
  再加 `--require-evidence-index`（R43）可校验三视图与运行日志未被替换/删除/复制冒充；
  **R44 起该门禁还会解出 PNG 像素，把三视图前景轮廓比例与本次 STL 的 X/Z、Y/Z
  包围盒比例绑定，拒绝「换成别的模型渲染图并同步改基线」**；
  基线用 `--write-evidence-index` 单独生成（与任何复验动作互斥），
  `--evidence-index <path>` 可指定别处基线；
  注意 `--stl-only` 与 `--report` / `--manifest` / `--require-file-verification` /
  `--require-source-provenance` / `--require-evidence-index` 互斥（R36/R41/R43），
  且报告/清单顶层必须是 JSON 对象（R37）。

## 五、残留风险（按优先级）

1. **输入 GLB 已被派生网格替换**（R13 事故，无备份）。`final4` / `final5` 的
   `iou_as_imported=0.8517` 不能与 `final2` 的 0.2445 横向比较 —— 输入本身已预对齐。
   成品 IoU、水密、尺寸在 `final4` 与 `final5` 之间可比且持平。
2. **单图重建上限**：两侧长发末端仍有细条断环/镂空发束，面部为素模、五官起伏较浅。
   需多视图重建或局部修模，后处理无法补出。
3. **正背面判据基于几何起伏**：对极简/无五官模型（如纯几何体）可能失效，此时退回最小旋转角
   tie-break；报告会写 `front_back_resolution: null`，需人工看三视图。
4. **评估仍是单视角 2D 轮廓 IoU**，不是五官/服饰级特征度量；`--min-iou 0.55` 与
   `asym=0.12` 门禁阈值仍只由少量样本标定。
5. 体素 0.25mm 是精度/可打印性的显式权衡；`--voxel-mm 0.2` 更细但文件与耗时更大。
6. **复杂背景参考图仍依赖 `rembg`（间接依赖 scipy）**：缺该链路时 `reference_mask` 退化为
   `color_fallback`，掩膜口径不同、IoU 不可与 rembg 版本横向比较。白底去背图（本项目
   `final4` 所用）走确定性 `white_background` 分支，不受影响；报告会写明 `mask_method`，
   测试在 `color_fallback` 时对该类样本显式 SKIP。要给纯 numpy 环境完整的复杂背景能力，
   需另做不依赖 rembg 的分割器，超出本次迭代范围。
7. **落地网格仍有大量拓扑柄**：`final4` 焊接后 `euler_number=-78`（约 40 个柄），
   `final5` 剔碎块后为 **-90**（单实体，约 46 个柄），来源与两侧长发细条断环/镂空发束一致。
   几何仍闭合、水密、体积为正、**可打印**，但切片时会产生较多内部轮廓/岛，建议预览首层与
   内部填充后再出机。这属于重建侧遗留，后处理无法在不牺牲发丝锐度的前提下消除。
8. **历史产物的字段版本差异**：`final4` 生成于 R24，其 `fidelity.json` / `manifest.json`
   不含 R27 的 `file_verification`（刻意不回填，以免改写历史报告破坏哈希链），独立复验
   对两处皆无的旧报告保持兼容（R35 后检查项固定 12 项、不再静默退回 11 项），可用
   `--require-file-verification` 显式拒绝。**当前最终版本 `final5` 由 R29 完整链路重新生成，
   报告内自证，旁路复验 12/12 全通过**，该差异已不影响交付物。
9. **悬空碎块已在最终版本解决，但清理策略本身有边界**：`final4` 仍保留 7 连通块 / 6 个悬空
   碎块（968/656/200/40/12/12 面，共 3.255 mm³，2 个体积为 0）作为历史对照；`final5` 已按
   **拓扑连通性**剔除，`connected_parts=1`、`floating_parts=0`、退化面 0。需注意的是
   `--drop-floating-parts` 只保留最大连通块——若模型本来就设计为多个可分离部件（独立配件、
   分件打印），该开关会误删它们，因此保持**默认关闭**、由 `--strict-single-body` 单独提供
   硬拒绝能力；多件设计应分别导出，勿启用此开关。
10. **产品入口的三项门禁默认关闭**（R30）：这是为避免改变已有 UI/脚本的历史行为而刻意保留的
   兼容性选择。若控制中心前端未提供对应布尔项，`auto` / `image_print` 产出的仍可能是多实体，
   与 `final5` 不同；启用 `--strict-watertight` 后，水密化失败会让底层以退出码 3 拒绝导出，
   属于预期行为但会改变原本"仍出文件"的结果。若要求所有产品路径默认单实体，应显式调整
   `fig.PRINT_FLAG_DEFAULTS` 并同步控制中心默认项，同时重新标定三视图与回归用例。
11. **文件级独立复验只覆盖 STL**（R31 后明确的边界）：`verify_deliverable.py` 与主链路的
    `verify_exported_stl` 只对落地 STL 做焊接闭合/绕向/正体积/连通块复验；`fig.py print` 默认
    同时导出 obj/3mf/ply，这些格式仅校验"写盘未抛异常"，不做几何复验。R31 修掉的是「STL 不在
    清单首位导致哈希误判」，并未把验收口径扩展到其它格式；若把其它格式也视作交付物，
    需另做格式级复核。
12. **独立复验不重新计算主链路的「内存比对」类判据**（R32 后明确的边界）：
    `file_verification_consistent` 现在要求逐项 `checks` 全为真，并与独立复验自己能重算的
    4 项几何判据（焊接闭合/绕向/正体积/闭合实体）交叉比对；但 `faces_match_memory`、
    `vertices_match_memory`、`extents_match_memory` 需要与转换当时的内存网格比对，
    独立复验只依据磁盘文件无法重现其参照对象，因此只验证布尔值为真、不重算数值。
    若怀疑这三项被伪造，需连同转换时的内存网格快照或重跑完整转换来复核。
13. **`verdict` 数值判据现在可重算，但依赖阈值双源与共享容差**（R42 后边界收窄）：
    原先「阈值没有存入、无法重现」的表述已过时 —— `min_iou` 早已写进报告与清单
    `parameters`。R42 起 `verdict_numeric_consistency` 按双源阈值重算
    `final_mesh.silhouette_iou >= min_iou` 与 `aspect_error_pct <= 1.0%`，并把键存在
    但畸形、两处阈值不一致一并判 FAIL。剩余边界：① 宽高比容差仍是两侧各自的
    `ASPECT_SELF_CHECK_TOL_PCT = 1.0` 常量（由回归锁定相等），并未落盘；若将来
    调整容差却只改一侧，回归会报警但历史报告无法自证当时阈值。② 报告与清单
    `parameters.min_iou` 都缺失时，为兼容旧报告会跳过 IoU 数值重算；两处同时
    被替换成自洽的假值仍属第 14/16 条的签名链问题。③ IoU 取 `final_mesh`、
    宽高比自检取**顶层** `aspect_error_pct` 是刻意设计（前者评成品网格，后者评
    `aspect_correction` 变换是否执行成功；加底座后包围盒必然变化，`final_mesh`
    的 1.57% 不能拿来判变换失败），R42 只锁定两侧同一口径，不改变评价对象。
14. **R35 的交叉契约依赖两个证据文件同时可信**：`file_verification_contract` 能拒绝
    「只删报告字段」「只删清单字段」「两处结论不一致」，但若有人把 `fidelity.json` 与
    `manifest.json` **同时**替换成一套自洽且都不含 `file_verification` 的假文件，仅凭磁盘
    文件无法区分「历史产物」与「伪造」；此时磁盘 STL 的几何复验仍独立有效，且可用
    `--require-file-verification` 强制要求闭环证据。彻底封闭需要外部可信时间戳或签名链。
15. **`--json` 保护仍是「已知证据枚举 + 后缀护栏」，不是任意文件白名单**（R38 后边界收窄）：
    `evidence_paths()` 枚举 STL / `*_fidelity.json` / `*_manifest.json` /
    `*_evidence.json`（R43 补）/ 三视图 PNG / 同目录 `run.log`，
    `write_json_atomic()` 另拒绝任何非 `.json` 目标，因此 R36 实证的
    「覆盖 run.log 且 rc=0」已封闭（R38 新增 5 项回归锁定）。剩余边界：调用方自定义命名的
    **`.json` 证据文件**（例如自己维护的 `audit.json`）若被 `--json` 指向仍会被覆写，且
    `os.replace` 前不做内容备份；CLI 无法枚举任意证据清单，输出路径仍需由调用方选择。
16. **溯源三重印证是 opt-in，且不是签名链**（R41 新增边界）：`--require-source-provenance`
    默认关闭，历史交付与源文件已归档移走的场景不会被误判，但也不会**自动**获得溯源保护；
    它校验报告/清单/磁盘源文件三者哈希一致，却无法识别「报告、清单、源文件被同时替换成
    另一套自洽文件」的情况（与第 14 条同一根因），彻底封闭仍需外部可信时间戳或签名链。
    另外 `mesh_fidelity._file_sha256` 按 `(路径, mtime_ns, 大小)` 做 `lru_cache`：
    若源文件被等尺寸且 mtime 相同的内容替换，同进程内会命中旧缓存；跨进程或 mtime
    变化则不受影响。
17. **交付证据基线是 opt-in，且只保护「基线生成之后」**（R43 新增、R44 收窄边界）：
    `--require-evidence-index` 默认关闭，历史交付（final2/3/4）没有基线文件，不会被误判，
    但也**不会自动**获得保护；基线本身仍是普通 JSON，与第 14/16 条同一根因——
    「证据文件与基线被同时替换成另一套自洽文件」无法识别，彻底封闭仍需外部签名链。
    R44 已把原先写在此处的「`png_container_valid()` 只验容器、不验像素来源」补上：
    启用门禁时会零依赖解出 PNG 像素，按前景包围盒宽高比与 STL 的 X/Z（front/back）、
    Y/Z（side）比对（容差 10%），换一张别的模型渲染图并同步改基线会被拒。
    **新边界**：① 绑定是「整体比例」级，不是五官/轮廓形状级 —— 另一模型只要
    宽高比落在 10% 内仍能通过；彻底绑定需轮廓 IoU 或渲染器签名。② 前景判定依赖
    「深色背景 + 浅色模型」的渲染约定与四边中位数，浅色/渐变背景或模型贴边出画会
    失真；`_decode_png_luma` 只支持 8-bit 非隔行 灰/RGB/灰+A/RGBA，其它格式结构化
    拒绝（判 FAIL 而非崩）。③ 基线本身仍是普通 JSON，外部签名链仍未建立。
    R45 另补上解码器的资源上限（单边 4096px / 4M 像素 / 32MB 解压数据），
    超大 IHDR 结构化拒绝而非抛栈；这是 fail-closed 设计 —— 更大尺寸的合法
    渲染图同样会被拒（当前交付 768² 远低于上限），若将来提高渲染分辨率须
    同步调整常量并重建基线。
    R46 把**生成侧**也纳入同一判据：`--write-evidence-index` 现在会从 STL 本体
    解析包围盒并复用 `render_binding_checks`，换模型图/畸形 IHDR 图在生成时
    即以 rc=2 拒绝，不再产出「自相矛盾」基线；缺依赖解释器统一 rc=2，不会再被
    误读成「验收不通过」。**新边界**：生成侧 STL 解析是 fail-closed 的 —— 只支持
    标准二进制 STL 与含 `vertex` 行的 ASCII STL，非标准/加密/压缩 STL 或某轴
    零厚度的合法薄片会被拒（当前交付为标准二进制）；纯动作模式因此多了约 0.43s
    解析开销。生成侧与复验侧的包围盒分别来自零依赖解析与 trimesh，二者一致性
    目前靠回归锁定，尚未做成运行时双向互校。
    R47 把「写基线」独立动作的 8 类冲突收进 `check_mode_contract` 唯一真值，
    CLI 不再另写一份；**新边界**：`--evidence-index` 与写基线组合是允许的
    （它只指定输出路径，不改变复验语义），未来若新增任何会改变复验语义的
    CLI 参数，必须同步加进该冲突集合，否则会再次出现静默丢弃 —— 目前这条
    一致性靠回归锁定，未做成自动枚举 argparse 参数。
    R48 补上写基线**输出目标**的保护：派生证据与 `_verify.json` 一律不可覆写，
    目标已存在时还必须是记录相同 STL SHA256 的合法基线。**新边界**：这是
    fail-closed 设计 —— 目标若是已损坏/被手工改写/属于旧版本 STL 的基线，
    写基线会以 rc=2 拒绝，需人工删除或改名后才能重建；自定义命名的
    输出路径若指向与本次交付无关的新 `.json` 文件仍会被创建，与第 15 条
    边界同源。**R54 已把「两份保护集合靠回归锁定」这条收窄**：两份集合现在
    都从 `DELIVERY_ARTIFACTS` 派生，调用方只声明各自的合法输出；剩余边界是
    清单本身仍为代码内常量，若将来新增「不按 STL 前缀派生」的证据（例如
    全局清单文件），仍需人工把它的命名规则接入派生函数。
    另：R43 事故后 front/side 是重渲染恢复的，像素与原始一致但**字节不再等同原始**
    （PNG `tEXt` 时间戳不同），当时没有任何哈希记录可证；R44 已**从几何上证明
    恢复图确实来自最终 STL**（误差 0.06% / 4.42%），现基线以此为新的可信起点。
    R38 的 `--json` 保护也已补上 `*_evidence.json`，但调用方自定义命名的 `.json` 证据
    仍需自行选输出路径（第 15 条边界不变）。
18. **R49–R54 新增/收窄的边界**：① R49 只把「缺依赖」分类清楚，主链路仍以
    `pass=False` fail-closed；`_file_verify` 模块本身不可导入时仍按历史语义
    `pass=None / skipped=True`，两种「不可用」并不等价，调用方应按
    `dependency_missing` 区分。② R50 的角色绑定只覆盖**按 STL 前缀派生**的
    证据文件名；自定义命名证据（第 15 条）仍不在基线内。    ③ R51 的形状判据是
    「拒绝明显不像轮廓的图」，不是形状识别；R56 已用 STL 光栅化轮廓 IoU 把
    这条基本收窄（菱形/矩形假图被拒），但 96×96 栅格 + 0.65 阈值仍属
    「整体归一化轮廓」级绑定，非逐特征点一致：一张刻意渲染出相近轮廓的
    假模型图仍可能通过，彻底绑定仍需渲染器签名或外部签名链。阈值来自当前
    768² / 深色背景 / 共用 ortho_scale
    的渲染约定，若换渲染器（自动取景、浅色或渐变背景、每视图不同缩放）须
    重新标定并重跑三环境回归。④ R52 的相对路径按「承载它的证据文件目录」
    解析，不支持「相对路径指向证据目录之外且以别的目录为基准」的历史写法；
    `origin_path=None` 的库调用仍按 CWD 解析。⑤ R53 依赖 `raw.copy().process()`
    与 `trimesh.load(process=True)` 等价，由「真实交付 12 项指标逐字段不变」
    回归锁定；若升级 trimesh 改变 `process()` 语义，该回归会报警但不会自动修复。
    ⑥ R54 的两份保护集合已统一派生，但 `--json`/写基线仍是**允许各自一个合法
    输出**的 fail-open 面：把 `--evidence-index` 指向一个全新的 `.json` 文件仍会
    创建它（与第 15 条同源）。⑦ 证据链整体仍非外部签名链（第 14/16/17 条不变）。
19. **R55–R59 新增/收窄的边界**：① R55 只把「显式 `--ref-image`」升级为
    fail-closed；自动发现失败仍按历史语义降级，`--no-fidelity` 仍可显式跳过
    全部保真验收，调用方需自行承担。② R56 的轮廓 IoU 是**整体归一化轮廓**
    比对，96×96 栅格会抹掉细节，五官/发丝级差异不敏感；且它只在显式
    `--require-evidence-index` 时运行，实测给该档增加约 **4.5s**（2.29s →
    6.84s，其中 STL 投影 ~3.5s），默认 12 项输出与耗时不变。未做进一步优化
    的原因：降采样三角形、列包络近似、坐标去重等都会改变 IoU 判据数值或
    引入新依赖，收益不足以承担正确性风险，如实保留而非凑数改动。
    ③ R57 的伴生文件先于主文件 `os.replace`：若中途某个伴生文件替换失败，
    已换入的伴生会成为孤儿文件（主文件与既有成品均不受损）；进程被强杀仍
    可能留下 `.export_*` staging 目录，但不影响交付成品。④ R58 严格校验
    GLB 头部声明长度 == 实际字节数，对「写错 length 字段」的第三方导出器会
    误拒；这是刻意的 fail-closed，需放宽时应显式加开关。⑤ R59 把退避上限
    固定为 30s，服务端若要求更长等待仍会在 3 次重试后失败；HTTP-date 解析
    依赖本机时钟正确。⑥ 输入链路首次有离线回归保护，但仍无端到端联网冒烟
    （不消耗积分），Meshy API 契约变更只能靠官方变更日志发现。
