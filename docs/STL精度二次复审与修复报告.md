# STL 精度二次复审与修复报告

对象：`E:\AI` 现有项目；复审上一份 `docs/STL保真修复与复审报告.md` 与其产物。
结论先行：**上一版把"STL 精度不足"的主因判轻了**。真正的最终成品损坏点在后处理：默认 `Taubin×10` 在非流形网格上把好模型打出坑点/尖刺；同时缺少水密化，且第一次端到端复现用了低精度 3D 参数。已修复并用最终水密 STL 验证。

---

## 一、对上一份报告的纠错（按严苛标准）

| 原结论 | 复核结果 |
|---|---|
| "修复可量化、宽高比误差降为 0.00%" | **指标口径有问题**：宽高比误差 0 是被 `aspect_correction` 强制对齐后的结果，不能当作保真证据。已改为同时报告校正前误差，并标注"非保真证据"。 |
| "端到端 36 秒跑通证明链路有效" | 那次复现用了 `--resolution 2048 --octree-res 256 --steps3d 20`，**本身就是低精度配置**，产出的模型没有五官/服饰细节，不能证明精度。已用项目推荐高精度参数重跑，原始 Hunyuan 结果其实细腻完整。 |
| "角色特征从未被正确建出，后处理无法补救" | 对**沙发躺姿场景图**成立，但据此否定全部链路是错的。用项目内现有 Qwen 整图编辑把同一角色转成「正面站立纯白底」后，单图重建即可得到有脸、有发、有衣褶的模型。 |
| "所有产物非水密，只能留作 P0" | 当时只做了 trimesh 拓扑补洞，没有处理非流形边。用项目已有 Blender 做 `0.25mm` 体素重建后，最终网格 `边界边=0 / 非流形边=0 / 水密=True`，且轮廓 IoU 不下降。 |
| 未指出最终 STL 的坑点来源 | 逐段渲染定位到：**`Taubin×10` 在非水密/非流形网格上提前执行**，把顶点沿错误邻接关系拉坏。这是上一版最终 STL 精度差的最直接原因。 |
| 正/背面歧义只列风险未处理 | 已在 24 朝向搜索加入「同分候选选最小旋转角」，并在后续迭代中补上前表面细节判据，最终模型正面朝前。 |

---

## 二、本次新增修复（全部在现有项目内）

| 文件 | 修改 |
|---|---|
| `mesh_fidelity.py` | 用**三角面面积均匀采样 + 栅格化**替换"顶点散点+视觉外壳"的近似轮廓；报告网格提升到 512；增加边界边/非流形边/表面积/深高比指标；24 朝向搜索加最小旋转 tie-break；报告显式标注宽高比误差是校正后结果。 |
| `convert_3d.py` | **默认 `--smooth 0`**；非水密网格禁止提前 Taubin，推迟到水密化后；新增导出前 `--blender-repair`（默认自动）与 `--voxel-mm 0.25`，并做尺寸/轮廓回退检查；最终导出网格独立复评并写入同一 `*_fidelity.json`。 |
| `fig.py` | `--smooth` 默认同步为 0；透传 `--voxel-mm / --no-blender-repair / --repair-max-iou-drop`。 |
| `repair_mesh_blender.py`（新增） | 用项目已有 Blender 做去重/退化清理/补洞/法线重算；可选 mm 级体素重建；输出修复统计 JSON。 |
| `tests/test_mesh_fidelity.py` | 新增"最终目标角色 STL 必须水密、无非流形边、轮廓 IoU>0.80"回归；经 59 轮迭代扩展到 **219 用例全过**（保真 30 + 独立复验 136 + 主链路闭环/连通块 38 + 输入链路 9 + 产品入口契约 6；`discover -p "test_*.py"` 全量 233 项），含 EXIF/RGBA/空网格/NaN/参数边界/报告契约/默认值一致性/可选 scipy 降级等价性/法线外向与清单哈希负例/导出后文件级闭环与失败退出码/多实体悬空碎块量化与可选硬门禁/按拓扑剔碎块与主链路单实体硬门禁端到端/三层 CLI 开关一一对应与显式透传/独立复验按路径定位多格式清单条目并拒绝篡改哈希（R31）/逐项核对主链路文件级结论并与独立几何复验交叉比对（R32）/`verdict` 按固定判据契约校验结构、拒绝非布尔值与删减判据、重算汇总并与磁盘几何交叉绑定（R33）/按「内存判据 ∧ 文件级复验」复合语义重算 `verdict.pass`、精确分类不合格诊断、锁定主链路与复验两侧判据集合一致性（R34）/以清单为第二证据源交叉印证文件级闭环字段、拒绝整段删字段降级并提供强制开关（R35）/参数冲突显式拒绝、结构化结果原子写且禁止覆盖交付证据（R36）/畸形证据顶层校验与字段畸形判 FAIL（R37）/`--json` 保护全部派生证据并要求 `.json` 目标（R38）/生成侧 `build_verdict` 有限数值与严格布尔契约、畸形指标写 `invalid_metrics`（R39）/报告溯源元数据权威生成、假哈希与缺失源可审计（R40）/opt-in 输入溯源三重印证且默认输出逐字节不变（R41）/按双源阈值重算 `verdict` 两项数值判据、生成侧与复验侧容差常量锁定一致（R42）/交付证据基线与零依赖 PNG 容器 CRC 校验、三视图防复制冒充（R43）/零依赖 PNG 像素解码、前景轮廓与 STL 包围盒比例绑定并拒绝换图冒充（R44）/像素解码资源上限与畸形 IHDR 结构化拒绝（R45）/零依赖 STL 本体包围盒解析、生成侧与复验侧共用几何绑定判据及缺依赖 rc=2（R46）/写基线独立动作 8 类参数冲突归一、不再静默丢弃验收要求（R47）/写基线输出目标保护，拒绝覆写交付 JSON、任意既有文件与他人基线（R48）/主链路缺依赖异常分类与 fail-closed（R49）/证据角色与派生文件名绑定（R50）/渲染前景轮廓形状与三视图像素尺度互校，封堵比例正确的矩形与异取景图（R51）/证据相对路径按证据文件目录解析（R52）/几何复验单次解析与体积复用（R53）/两份保护集合由单一交付清单派生（R54）/显式参考图失效 fail-closed 且与退出码契约对齐（R55）/STL 正交投影轮廓 IoU 封堵异形状假图（R56）/8 种格式统一 staging 原子导出、失败不毁既有成品（R57）/下载内容魔数与 GLB 长度校验、唯一临时文件（R58）/Retry-After 秒数与 HTTP-date 有界解析（R59）。 |

---

## 三、新的验证结果（可复现）

### 3.1 先把参考图修对

用项目现有 `fig.py edit_image --method whole` 把沙发躺姿图转成同一角色的正面站立纯白底参考图：`ComfyUI/output/fig_edit_whole_45363770cbe4.png`。
门禁结果：`pass=true`，前景占比 18.2%、贴边 0、正面对称度 0.0279、低饱和背景 4.45%。

### 3.2 高精度重建 + 修复后处理

命令（项目推荐高精度参数）：
`fig.py image_print <新参考图> --engine hunyuan --resolution 3072 --octree-res 512 --steps3d 30 --remesh-res 512 --model-height 150 --base 0.03 --formats stl`

- 原始 GLB：`276,230` 顶点 / `566,990` 面。直接渲染即有五官、发丝、衣褶、鞋子；证明上一版"重建不出特征"是低参数误判。
- 后处理（不再提前平滑）：导入态 IoU `0.2445` → 加底座前 `0.8713`（512 网格、真实表面轮廓）。
- Blender `0.25mm` 水密化：接受修复；轮廓 IoU `0.8213 → 0.8209`（256 网格），尺寸变化 <2%；水密 `False → True`；锐边 30° `2.142% → 1.655%`。
- **最终导出 STL**：`741,524` 面 / `37.08 MB` / `水密=True / 边界边=0 / 非流形边=0 / 体积 34,744.7 mm³`；最终网格轮廓 IoU `0.8285`（512 网格）。
- 三视图渲染：正面站立、侧面有真实体积（头/躯干/腿/底座层次清楚）、背面长发/躯干/裙/腿/底座完整；上一版遍布全身的坑点、脚底破洞与放射尖刺已消失。
- **仍可见的残留几何缺陷**：两侧长发末端存在细条状断环/镂空发束（正、侧、背面均可见），属于重建器对细长发丝的推测结果，非后处理引入；面部为素模，五官起伏较浅，无贴图细节（STL 本身不带颜色，需靠涂装或贴图工序）。底座在正交视图下呈扁平矩形轮廓，实为圆柱底座的正投影。

### 3.3 关键对照：坑点根因

- 仅旋转、不做平滑：表面细腻完整。
- `Taubin×10` 后：脚底破洞、发梢与衣服出现尖刺和坑点。
- 确认结论：**非流形网格上提前平滑是破坏源**，不是"模型本来就差"。

### 3.4 回归测试

本机项目解释器（Python 3.12.3、依赖齐全）：

```
C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe -W error::ResourceWarning ^
    -m unittest discover -s tests -p "test_mesh_fidelity.py" -v
C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe -W error::ResourceWarning ^
    -m unittest discover -s tests -p "test_*.py" -v
```

→ 保真套件 **30 passed**，独立复验套件 **114 passed**，主链路闭环/连通块套件 **27 passed**，
产品入口契约套件 **6 passed**；改用 `-p "test_*.py"` 全量 **191 passed**，无资源泄漏告警。
另在 Python 3.14（有 scipy）与 Python 3.13（缺 scipy/trimesh）交叉验证：前者 191 全过，
后者 reported 188、130 skipped、0 error（3.12 亦为 188、129 skipped、0 error），
不再是原先的 14 个 `ModuleNotFoundError`（见迭代记录 R25）；
本轮 8 个核心模块编译通过。
R32 起独立复验逐项核对主链路 `file_verification.checks` 并与自身重算的 4 项几何判据交叉比对；
实证中把逐项 checks 写反或清空但保留 `pass: True` 的篡改样本，修复前 12/12 PASS、修复后
`FAIL file_verification_consistent` 且退出码 1；`final5` 的 8 项主链路结论逐项自洽、仍 PASS。
R33 起 `verdict_consistent` 按 `build_verdict` 的固定 5 项契约校验判据集合与严格布尔值、
依 `required_checks` 重算汇总并与 `verdict.pass` 比对、把 `watertight` 与磁盘 STL 重算结果
交叉绑定；实证中把判据写成 `"false"` / 整数 2、删减判据、或把 `checks` 换成
`{"forged": True}` 的 6 类篡改样本，修复前均 12/12 PASS、修复后全部 `FAIL` 且退出码 1，
而合法默认模式（required 仅 2 项）不误伤；`final5` 仍 12/12 PASS。
R34 起 `verdict.pass` 按「内存判据 ∧ `file_verification_pass`」复合语义重算（字段缺失时
退化为仅内存判据），并补 `verdict.pass` 严格布尔校验；主链路诚实产出的不合格报告
仍判 FAIL，但 `verdict_reason` 会准确指向「文件级复验未通过（含 `single_body` 等明细）」
而非误报「汇总不一致」，篡改则报「与复合重算结论不一致」。`build_verdict` 两种
strict 模式与 `VERDICT_KNOWN_CHECKS` 的一致性已固化为自动回归；`final5` 仍 12/12 PASS。
R35 起用 `file_verification_contract()` 把清单当作判定「本次是否做过文件级复验」的
第二证据源：实证把 `report.file_verification` 整段删掉（或连同 `verdict.file_verification_pass`
一起删）曾让独立复验静默退回 11 项口径、退出码 0 PASS。现要求报告/清单存在性一致、
两处 `stl`/`pass`/逐项 `checks` 相等、`verdict` 必带 `file_verification_pass`，且检查项
恒定写入（旧报告也保留）；新增 `--require-file-verification` 强制闭环。删字段、两字段同删、
fv 置字符串、清单删记录、两处 `pass`/`checks`/`stl` 不一致共 6 类样本全部 `FAIL`、rc=1；
R32 同步篡改两处与 R33 伪造 verdict 仍各自被原机制拒绝，未放宽判据；`final4` 仍 PASS。
R36 起复审推进到「用户显式传入的验收要求是否真的生效」：实证 `--stl-only` 与
`--require-file-verification` / `--report` / `--manifest` 同时传入时，旧实现直接 return、
静默丢弃要求后仍 `PASS`、rc=0（甚至传一份明显篡改的报告也照样 PASS）；`--json` 父目录
不存在时 stdout 已打印 PASS 却抛裸 traceback、rc=1，`--json` 误指向 STL 更会覆盖交付成品
（R13 同类事故）。现用 `check_mode_contract()` 把冲突显式拒绝为 rc=2、`write_json_atomic()`
做原子写并保护 STL/报告/清单，写出失败返回 rc=2 而非冒充验收不通过；`--stl-only` 输出
标注「仅几何复验…不等同于完整交付验收」。补 10 项回归，`final5` 结论与哈希不变。
R37 起复审「证据文件本身畸形时验收工具会怎样」：实证把 `fidelity.json` 顶层换成数组，
旧实现抛未捕获 `AttributeError`、CLI 打出裸 traceback 并以 rc=1 结束，与「验收不通过」
混淆；`extents_xyz` 换成字符串/嵌套对象同样让整个复验崩掉。现用 `load_json_object()`
显式校验顶层对象、把畸形数值判为该项 FAIL、`main()` 兜底把残余属性异常映射为 rc=2；
补 5 项回归，`final5` 结论与哈希不变。
R38 起把 R36 自己承认的残留风险做实：实证 `--stl-only --json <dir>/run.log` 会把同目录
运行日志原子替换成 JSON 且仍 rc=0，三视图 PNG 同理。现用 `evidence_paths()` 按 STL
派生全部已知证据（含 `run.log` 与三视图），并给 `write_json_atomic()` 加「目标必须是
`.json`」通用护栏；`*_verify.json` 作为合法输出刻意排除在保护集合外。补 5 项回归，
`final5` 结论、哈希与 12/12 的 `target_final5_verify.json` 均未变。
R39 起把复审从验收工具换回**主链路生成侧**：实证 `convert_3d.build_verdict` 把
`silhouette_iou` / `aspect_error_pct` 换成 `None` 或字符串时，`float()` / `<=` 抛
`TypeError`/`ValueError` 直接中断导出；`watertight_indexed="false"` 或 `2` 被 `bool()`
判成水密，`boundary_edges=False` 因 `False == 0` 被判成「无边界边」—— 都是 R33/R37
在复验侧已堵、生成侧从未加固的同类问题。现新增 `_finite_float` / `_strict_true` /
`_strict_zero` 三个纯函数：指标只接受有限浮点数，布尔/计数判据只接受严格真值或数值 0/1，
畸形输入判该项 FAIL 并写 `invalid_metrics` 明细，5 项 `checks`/`required_checks` 契约不变。
补 6 项回归；用真实 `final5` 报告重算 verdict 与落盘结论逐字段一致，
默认 12/12 与严格 13/13 仍 PASS，成品与全部证据哈希未变。
R40 起把复审推进到**报告元数据生成源头**：实证 `mesh_fidelity.save_report` 的 `setdefault`
让 `FAKE_OLD_INPUT` 这类假溯源哈希、`schema_version='1.0'` 与假指标口径原样落盘，
源文件缺失时哈希字段又静默省略。现把 schema/指标口径/三份哈希改为权威值强制覆盖，
被纠正项写 `metadata_corrections`、不可核验源写 `source_hashes_unverifiable`（显式 `null`），
时间仍允许注入以便复现性测试。补 6 项回归，真实 `final5` 报告重写后关键字段逐字段一致。
R41 起补上「这些字段完全无人消费」的另一半：实证把报告里 `input_mesh_sha256` 改成
`TAMPERED_INPUT`、`reference_image_sha256` 改成全零，或整段删除两者，独立复验**仍
12/12 PASS**。现新增默认关闭的 `--require-source-provenance` 与纯函数
`source_provenance_checks()`：对输入模型与参考图做「报告哈希 ↔ 清单哈希 ↔ 磁盘重算哈希」
三重印证，校验格式与路径一致，源文件缺失/路径畸形/读盘失败一律判 FAIL 并给中文诊断；
新 flag 同时纳入 `--stl-only` 冲突契约。补 7 项回归：启用后 `final5` 13/13、三档组合
14/14 PASS，**默认结果写盘与交付 `target_final5_verify.json` 逐字节相同（`46a6827a…`）**，
三环境 149/149，五份交付哈希未变。
R42 起把残留风险第 13 条做实：实证把 `final_mesh.silhouette_iou` 改成 0.20、
`min_iou` 改成 0.99、`aspect_error_pct` 改成 99，或删掉报告 `min_iou`，独立复验
**全部仍 12/12 PASS** —— R33/R34 只锁死判据集合与布尔汇总自洽，从不重算数值。
深审同时发现 `min_iou=0.55` 早已写进报告与清单 `parameters`（原残留表述过时，
已改写），故复验侧具备重算条件。现新增 `_finite_number` 与
`verdict_numeric_consistency()`：按「报告 ↔ 清单 parameters」双源阈值重算
`final_mesh.silhouette_iou >= min_iou` 与 `aspect_error_pct <= 容差`，
两处阈值不一致、键存在但值畸形（含 NaN/字符串）、`verdict.checks` 缺项均
结构化拒绝；两处阈值都缺则兼容旧报告跳过。`convert_3d.py` 把硬编码 `1.0`
提成 `ASPECT_SELF_CHECK_TOL_PCT`，与复验侧同值常量由回归锁定相等；
`build_verdict` 文档同时明确「IoU 评 `final_mesh`、宽高比自检评顶层变换结果」
这一刻意不同的评价对象。该门禁**默认生效并并入既有 `verdict_consistent`**，
不新增检查项；正常报告 `verdict_reason` 仍为 None，默认输出与交付
`target_final5_verify.json` 逐字节相同（`46a6827a…`）。补 7 项回归，
三环境 156/156，`final4` / `final5` 仍 PASS，五份交付哈希未变。
R43 起把复审换到**交付证据生成链**，并如实记录一次真实事故：深审探针在真实交付目录
原地篡改，把 `target_final5_front.png` 写成垃圾字节、删掉 `side.png`，独立复验**仍
12/12 PASS**；清单 `outputs` 只有 STL 一条，三视图与 `run.log` 连哈希都没有，
既无法发现损坏也没有恢复基准。R38 只保证「别被 `--json` 覆盖」，从不校验内容完好。
现以 `print_ready/_verify/render_front_ortho.py` 从**未改动的最终 STL** 重渲染恢复
（未损坏的 `back.png` 作对照：解码像素逐字节相同、三图字节数与原始一致，差异仅在
PNG 的 `tEXt Date`/`RenderTime` 元数据；front/side 因此像素一致但字节不再等同原始，
已如实写入迭代记录「R43 交付证据误伤与恢复记录」），并新增
`EVIDENCE_INDEX_SCHEMA` / `png_container_valid()`（零依赖逐 chunk CRC）/ 
`build_evidence_index()` / `evidence_index_checks()`：基线锁定三视图与日志的
路径/字节数/SHA256/PNG 尺寸，校验条目完整、路径不越界、三视图哈希两两不同防复制冒充、
日志非空、STL 锚点一致；CLI 加 `--write-evidence-index`（独立动作）与
`--require-evidence-index`（启用时新增第 13 项），并纳入 `--stl-only` 冲突与
`--json` 证据保护。补 8 项回归，三环境 164/164，默认输出与交付
`target_final5_verify.json` 逐字节相同，四档组合 15/15 PASS，五份既有哈希未变、
新增第六份基线 `target_final5_evidence.json`（`9c599949…`）。
R44 把上一段留下的「只验容器不验像素来源」做实：实证在隔离副本把 `side.png`
换成另一模型的 768² 合规渲染图并同步更新基线，旧 `evidence_index_checks()`
仍判通过、四档组合仍 15/15 PASS —— SHA256 只证明「文件与基线自洽」，不证明
像素来自本次 STL。现新增零依赖 `_decode_png_luma()`（逐行反 filter，解压设上限
防炸弹）、`png_foreground_bbox()`（四边亮度中位数估背景）与
`render_binding_checks()`（front/back 对齐 X/Z、side 对齐 Y/Z，容差 10%），
并入既有 `evidence_index_valid`，不新增检查项、默认输出逐字节不变。
实测 final5 误差 0.06% / 0.06% / 4.42%，既拒绝换图冒充，也**从几何上证明
R43 事故后重渲染恢复的 front/side 确实来自最终 STL**。补 7 项回归，三环境
171/171（缺依赖 168 含 skip、0 error）、10 模块编译，六份交付哈希未变。
R45 复审上一轮刚引入的解码器，实证一条回归：CRC 完好的 IHDR
`4294967295×4294967295` 能通过 `png_container_valid`，但 `decompress` 的
`max_length` 超出 C 层 `Py_ssize_t` 抛 `OverflowError`，`render_binding_checks`
与 CLI 异常白名单都未捕获，`--require-evidence-index` 直接打印裸 Traceback，
把「验收不通过 rc=1」退化成执行崩溃。现新增
`MAX_PNG_DIMENSION` / `MAX_PNG_PIXELS` / `MAX_PNG_RAW_BYTES` 三项上限，在
分配缓冲区与调 C 层之前拦截，并把资源/数值类残余异常统一映射 rc=2。修复前
同一支回归 2 FAIL + 1 ERROR，修复后 3/3 通过；三环境 174/174，六份交付哈希未变。
R46 把复审换到「生成侧 ↔ 复验侧」契约层，做实两条「自相矛盾」硬缺陷：
① 真实 Python 3.13（缺 trimesh）跑 CLI 打印裸 `ModuleNotFoundError` Traceback、
rc=1，把执行错误伪装成「验收不通过」——R25 只在 unittest 层用 skip 绕过，
CLI 层从未验过；② `build_evidence_index()` 只验容器 CRC/哈希/互异，实证把侧视图
换成另一模型的合规渲染图后仍打印 `[OK] rc=0` 写出基线，而
`--require-evidence-index` 必然 FAIL（R45 畸形 IHDR 图同样能生成）。修复前同一支
回归 4 FAIL + 5 ERROR。现新增零依赖 `stl_extents_from_file()`（按「文件大小 ==
84 + 50×count」判二进制而非头是否 `solid`，支持 ASCII，不信任任何报告元数据），
让生成侧复用复验侧的 `render_binding_checks`；缺依赖定义
`MissingDependencyError` 统一映射 rc=2。修复后 8/8 通过，真实 3.13 CLI rc=2
且无 Traceback；隔离副本「正常 write → require」正向一致（rc=0 / 13 项 PASS /
绑定 0.06、0.06、4.42%）；三环境 182/182（缺依赖 179 含 skip、0 error）、
10 模块编译、八份交付哈希未变。R43 历史夹具因占位 STL 报错，已升级为几何
自洽的迷你交付，未放宽判据。
R47 把复审换到「独立动作模式的参数契约」，做实 R36 同类硬缺陷：
`--write-evidence-index` 的 CLI 分支只列了 3 个冲突参数，且**完全不调用**
`check_mode_contract`，实证把 `--require-source-provenance` /
`--require-file-verification` / `--strict-single-body` / `--report` /
`--manifest` 与写基线同时传入，5 个用户显式要求的硬门禁被静默吞掉，
CLI 仍打印 `[OK] 证据基线已生成`、rc=0。修复前同一支回归
9 FAIL + 3 ERROR（3 个 ERROR 是夹具把 `stl_only` 同时作位置/关键字传入，
已修夹具）。现把 8 类冲突集合收进 `check_mode_contract` 作为库层与 CLI
的唯一真值，CLI 不再各写一份；修复后 5 个被吞参数均 rc=2、stderr 含
参数名与「互斥」、无 Traceback，正常 write 与 `--evidence-index` 自定义
路径仍 rc=0。补 4 项回归，R43 8/8 / R46 8/8 无回归；三环境 186/186
（缺依赖 183 含 skip、0 error）、10 模块编译、八份交付哈希未变，
默认输出与 `_verify.json` 仍逐字节相同。
R48 把复审换到「输出目标覆写」层面，做实 R36/R38 同类硬缺陷：
`--json` 分支当年补了 `evidence_paths()` 全量保护，
`--write-evidence-index` 分支却调用 `write_json_atomic(target, index)`
一份 protected 都没传。实证把 `--evidence-index` 指向
`_fidelity.json` / `_manifest.json` / `_verify.json` / 任意既有 JSON /
另一 STL 的合法基线，5 类全部 `[OK] rc=0` 静默覆写（原文件键被换成
`schema_version`/`stl`/`evidence`）；`.json` 后缀护栏只挡
`.stl/.png/.log`，挡不住同为 `.json` 的交付证据。修复前同一支回归
6 FAIL + 1 ERROR。现新增 `write_index_protected_paths()` 与
`guard_index_write_target()`，两层分别覆盖「派生路径」与「自定义命名
任意路径」；实证目标被删除后 protected 仍 rc=2 且不创建假报告。
补 5 项回归，R43 8/8 / R46 8/8 / R47 4/4 无回归；正常 write → require
正向闭环 rc=0 / 13 项 PASS，三环境 191/191（R48 时点；缺依赖 188 含 skip、
0 error）、10 模块编译、八份交付哈希未变，默认输出逐字节相同。
R31 起独立复验按路径定位清单中的 STL 条目；对多格式导出（`--to obj stl`）的实测样本，
修复前 `file_sha256_matches_manifest` 误判 FAIL、修复后转 PASS（该样本另有
`verdict_consistent` FAIL，是合成参考图宽高比不符导致的**真实**不合格，非误判）。
成品独立复验：`verify_deliverable.py --stl <STL>` 对 `final4` 返回 12/12 通过、退出码 0，
负例（法线朝内 / 开口网格 / 清单哈希不符）均被拒绝（见 R26）；
对 **`final5` 返回 12/12 通过、零告警**，加 `--strict-single-body` 仍 PASS。
R27 起主链路导出后自动回读磁盘 STL 复验（7 项）并把结论写进报告/verdict/清单，
旁路 CLI 增加第 12 项 `file_verification_consistent`；**R35 后该项恒定存在**，
两处皆无的旧报告按「合法跳过内容核对」兼容、不再静默减少检查项数，
`--require-file-verification` 可显式拒绝此类旧报告。
R28 补上连通块/悬空碎块/退化面量化；R29 进一步把「只告警」变成「可剔除 + 主链路硬拒绝」：
`--drop-floating-parts` 按拓扑连通性只保留最大连通块，`--strict-single-body` 让多实体直接
`verdict=FAIL` 且退出码非零，两者均有真实 CLI 端到端回归覆盖。
R30 复审上层入口时发现这三项门禁只存在于 `convert_3d.py`，**已交付的 `final5` 无法从用户
实际使用的一条龙流程生成**；现已接到 `fig.py` 与 `control_server.py`，并用 `fig.py print`
端到端产出了与 `final5.stl` **SHA256 完全一致**的 STL（8 项文件级复验全 True、
`connected_parts=1`、IoU 0.8281、退出码 0）。
R31 复审**验收工具自身**时发现：`verify_deliverable.py` 把 `outputs[0].sha256` 当成 STL 哈希，
而 `fig.py print` 默认 `--formats obj stl 3mf ply` 使 `outputs[0]` 为 obj —— 实证中转换
退出码 0、7 项文件级复验全 True 的合格成品被独立复验误判 FAIL（退出码 1）。现改为按
规范化路径定位清单条目，并补 6 项回归与 2 处夹具修正；`final5` 复验结论不变。
R32 再深一层：独立复验的 `file_verification_consistent` 只核对 `fv.pass` 与
`verdict.file_verification_pass` 两个汇总字段。实证把 `final5` 报告副本的逐项 checks 写反
（`single_body=False`、`welded_watertight=False`）或清空，只要保留 `pass: True`，独立复验
仍 12/12 PASS、退出码 0。现改为逐项核对 + 与独立重算的 4 项几何判据交叉比对，并补 7 项
回归与 1 处夹具修正；`final5` 复验结论不变。
R33 再换一侧：独立复验的 `verdict_consistent` 只做 `all(verdict["checks"].values())`，
既不看判据集合是否完整，也把 `"false"`、整数 2 这类非布尔真值当成通过。实证把
`verdict.checks.watertight` 改成 `"false"` / `2`、删掉判据（连同 `required_checks`）、
或把 `checks` 整体换成 `{"forged": True}`，修复前一律 12/12 PASS、退出码 0。现按
`VERDICT_KNOWN_CHECKS` 固定契约校验、用 `_is_bool_flag` 拒绝非布尔值、按
`required_checks` 重算汇总，并与磁盘几何交叉；补 12 项回归与 2 处单一真值夹具，
`final5` 复验结论与哈希不变。
R34 承接上一轮深审搁置的发现：`verdict.pass` 实为「内存判据 ∧ 文件级复验」的复合结论
（`apply_file_verification` 会把文件级结果叠加进来），R33 只按内存判据重算，导致主链路
诚实产出的不合格报告被误报为「汇总不一致」。现按复合语义重算、给 `verdict.pass` 补严格
布尔校验，并把「自洽地判定不合格」与「汇总被篡改」分别诊断；补 6 项回归（含直接调用
`build_verdict` / `apply_file_verification` 锁定跨模块契约）。R33 的 5 类篡改样本全部仍被拒，
未放宽任何判据；`final5` 复验结论与哈希不变。

---

## 四、最终产物

- 新参考图：`E:\AI\ComfyUI\output\fig_edit_whole_45363770cbe4.png`
- 本节记录的是二次复审当时（v2 初版）的产物：`print_ready/_verify2/final2/target_final2.stl` 及其报告/三视图。
- **当前最终版本为 `E:\AI\print_ready\_verify2\final5\target_final5.stl`**（R29 用完整链路重跑生成，
  R30 验证可从 `fig.py print` 产品入口逐字节复现；36.98 MB、739,612 面、SHA256 `5c02f890c9e0…`）：
  正面朝向正确、`verdict=PASS`、水密、
  边界/非流形边 0、**连通块 1 / 悬空块 0 / 退化面 0**、体积 +34749.002 mm³（法线朝外）、
  final_mesh IoU 0.8281、38.64×29.95×152.24 mm。
  含 `*_fidelity.json`（带 8 项 `file_verification` 与 `geometry_cleanup` 明细）、`*_manifest.json`、
  **`target_final5_verify.json`（12/12 PASS、零告警）**、正交三视图与运行日志；IoU 与 `final4`
  完全相同，三视图差异 <0.05%。
  `final4`（R24 生成，7 连通块）完整保留为历史对照，其报告/清单不含 R27 的
  `file_verification` 字段（刻意不回填以免破坏哈希链），独立复验对两处皆无保持兼容
  （R35 后检查项固定 12 项），可用 `--require-file-verification` 显式拒绝。
  产品入口复现证据在 `print_ready/_verify2/_r30_e2e/`（`e2e.stl` 哈希与 `final5` 相同）。
  逐轮依据见 `docs/STL精度迭代记录.md`（共 59 轮）。
- 上一版 `print_ready/_verify` 下的沙发场景 STL 只证明"轮廓对齐"，**不应作为角色成品**。

---

## 四·补 迭代后的接口契约（v2）

59 轮迭代后新增/变更的可依赖行为（细节见 `docs/STL精度迭代记录.md`）：

| 类别 | 契约 |
|---|---|
| 报告 | `*_fidelity.json` 带 `schema_version=2.0`、`generated_at_utc`、`metric_dictionary`、输入/参考图/网格 `sha256`；`silhouette_samples`/`silhouette_seed` 可复现；`aspect_error_pct` 标 `aspect_error_is_evidence=False`，真实偏差看 `aspect_error_before_pct` |
| 验收 | 顶层 `verdict`（`pass` + 5 项 `checks` + `required_checks`），基于 `final_mesh` 而非加底座前网格判定 |
| 可复现 | 每次转换额外写 `<base>_manifest.json`：完整命令、解释器/平台、参数、输入与输出哈希、耗时、结论 |
| 门禁 | `--strict-watertight` 在成品非水密时退出码 3；`--min-iou` 不达标退出码 2；导出失败退出码 1；参数越界退出码 2 |
| 安全 | 输出路径与输入文件相同时跳过并报错，不再覆盖原始 GLB；`--out-dir` 不可写给出明确提示 |
| 参数 | `--height/--scale/--base/--hollow/--min-iou/--voxel-mm/--repair-max-iou-drop/--decimate/--smooth/--pitch` 全部有区间校验；`fig.py` 与 `convert_3d.py` 共享 `PRINT_DEFAULTS` 常量；三项布尔门禁另由 `fig.PRINT_FLAG_DEFAULTS` / `PRINT_FLAG_ARGS` 与 `control_server.PRINT_FLAG_ARGS` 三层同名映射锁定，键名一致性有回归测试 |
| 朝向 | `front_detail_score` 用前表面头部深度起伏解决绕 Z 180° 的正/背面歧义；报告写 `front_back_resolution`（含两个候选的细节得分与选中 index） |
| 降级 | Blender 修复超时/异常/空输出/保真模块缺失时一律回退原网格，并在报告写明原因；`iou_check=skipped` 不再静默显示"通过" |
| 输入 | 参考图统一走 `_load_rgb`：应用 EXIF 旋转、RGBA 透明区合成白底；损坏/全白/无主体图由门禁结构化拒绝 |
| 依赖 | `numpy`/`Pillow`/`trimesh` 必需（缺 `trimesh` 时相关用例 SKIP）；`scipy` **可选**，`_ndimage()` 缺依赖时返回 `_NumpyNdimage`，7 个 ndimage 操作与 scipy 逐像素等价；复杂背景参考图另需 `rembg`，否则 `mask_method` 会写成 `color_fallback` |
| 独立复验 | `verify_deliverable.py` 只依据磁盘 STL/报告/清单做 11 项检查：焊接后闭合、绕向一致、**有符号体积>0（法线朝外）**、`is_volume`、SHA256 与清单一致、面数/焊接顶点数/包围盒与报告一致、报告拓扑干净、`verdict` 自洽、schema 2.0；退出码 0/1/2，可导出标准 JSON（`json_safe` 把 NaN/Inf 归一为 None，`allow_nan=False`）。报告含 `file_verification` 时增加第 12 项交叉一致性检查，旧报告保持 11 项；**R31 起按规范化路径定位清单中的 STL 条目**（不再取 `outputs[0]`），找不到条目或哈希不符均判 FAIL，容忍 `None`/畸形条目，指标含 `manifest_stl_output_index`；**R32 起第 12 项不再只信汇总 `pass`**：要求主链路逐项 `checks` 非空且全为真，并与独立复验自己重算的 4 项几何判据逐项相等，畸形 fv 判 FAIL 而非抛栈，指标含 `file_verification_reason`；**R33 起 `verdict_consistent` 不再用裸 `all(values())`**：按 `VERDICT_KNOWN_CHECKS` 校验固定 5 项齐全、值必须为严格布尔、`required_checks` 覆盖永远必需项且声明项均存在、按 `required_checks` 重算汇总与 `verdict.pass` 一致、`watertight` 与磁盘 STL 重算结果交叉一致；畸形 `verdict`/`final_mesh` 判 FAIL 不抛栈，指标含 `verdict_reason`；**R34 起按复合语义重算 `verdict.pass`**：期望值 = 内存判据 ∧ `file_verification_pass`（字段缺失时退化为仅内存判据），`verdict.pass` 自身也须严格布尔；自洽地判定不合格仍 FAIL，但 reason 精确区分「文件级复验未通过 / 内存判据未通过 / 与复合重算不一致」；**R35 起第 12 项恒定存在且先做存在性契约**：以 `manifest.file_verification` 判定本次是否做过文件级复验，报告/清单必须同时有或同时无，两处 `stl` 路径、`pass`、逐项 `checks` 必须相等，`verdict` 必带 `file_verification_pass`，否则整段删字段无法再伪装成旧报告；指标含 `file_verification_contract_required`，`--require-file-verification` 可强制要求闭环证据；**R36 起调用契约与证据写出也受保护**：`check_mode_contract()` 使 `--stl-only` 与 `--report`/`--manifest`/`--require-file-verification` 互斥并显式报 rc=2（库调用同样生效），`write_json_atomic()` 先拒绝 `--json` 覆盖 STL/报告/清单，再写同目录临时文件并 `os.replace`，异常清理临时文件且写出失败映射为 rc=2；`--stl-only` 输出明确标注为「不等同于完整交付验收」；**R37 起证据文件顶层必须是 JSON 对象**（`load_json_object()`，畸形结构 rc=2 且无 traceback；`extents_xyz` 畸形判该项 FAIL 而非崩），**R38 起 `--json` 保护全部派生证据**（`evidence_paths()` 含 `run.log` 与三视图 PNG）且**目标必须是 `.json`**，复验结果 `*_verify.json` 仍可覆写；**R39 起生成侧 `build_verdict` 与复验侧同严**（`_finite_float`/`_strict_true`/`_strict_zero`，IoU/宽高比/阈值只接受有限浮点数，水密/边界边只接受严格真值与数值 0，畸形指标写入 `invalid_metrics` 并判 FAIL，不再抛栈中断导出）；**R40 起报告元数据由 `save_report` 权威生成**（溯源哈希强制重算覆盖假值，`schema_version`/`metric_dictionary` 不被输入污染，源文件缺失显式 `null` 并写 `metadata_corrections` / `source_hashes_unverifiable`）；**R41 起 `--require-source-provenance` 把溯源变成可验证据**（`SOURCE_PROVENANCE_ITEMS` / `source_provenance_checks` 按报告 ↔ 清单 ↔ 磁盘三方印证，默认关闭、默认输出零变化，启用时新增 `source_provenance_valid` 第 13 项且与 `--stl-only` 互斥）；**R42 起 `verdict` 数值判据默认可重算**（`verdict_numeric_consistency` 按报告/清单双源 `min_iou` 重算 `final_mesh.silhouette_iou >= 阈值`、按共享常量 `ASPECT_SELF_CHECK_TOL_PCT` 重算 `aspect_error_pct <= 容差`，阈值不一致/键畸形/数值与结论矛盾均判 `verdict_consistent=FAIL` 并给出含数值的诊断；不新增检查项，正常报告输出逐字节不变）；**R43 起交付证据完整性可显式核验**（`png_container_valid` 零依赖校验 PNG 容器 CRC/IHDR/IDAT/IEND，`--write-evidence-index` 生成含三视图与 `run.log` 的 SHA256/字节数/尺寸基线，`--require-evidence-index` 逐项校验并拒绝替换/删除/复制冒充/空日志/路径穿越/基线篡改，启用时新增 `evidence_index_valid` 第 13 项且与 `--stl-only` 互斥；`*_evidence.json` 亦受 `--json` 保护；默认关闭、默认输出零变化）；**R44 起该门禁新增像素级几何绑定**：`_decode_png_luma` 零依赖解码 8-bit 非隔行 PNG（逐行反 filter、解压设上限防炸弹），`png_foreground_bbox` 按四边亮度中位数取前景包围盒，`render_binding_checks` 把 front/back 的 X/Z、side 的 Y/Z 比例与独立复验得到的 STL 包围盒比对（容差 10%），换一张别的模型渲染图并同步改基线会被拒；结果并入既有 `evidence_index_valid`，不新增检查项、默认输出零变化，metrics 增 `render_binding`）；**R45 起像素解码有显式资源上限**（单边 4096px / 4M 像素 / 32MB 解压数据，超限结构化 FAIL；`OverflowError`/`MemoryError` 并入 CLI 白名单统一 rc=2，不再裸 traceback）；**R46 起 `--write-evidence-index` 与 `--require-evidence-index` 共用同一套几何绑定判据**：新增零依赖 `stl_extents_from_file()`（直接读 STL 本体算包围盒，支持标准二进制/ASCII，实测 0.43s），生成基线前复用 `render_binding_checks()`，换模型图/畸形 IHDR 图在生成时即 rc=2 拒绝且原基线不被覆盖；基线 schema、字段与既有交付逐字节不变、不新增检查项、不新增 opt-in 开关。另新增 `MissingDependencyError`：缺 `trimesh`/`numpy` 的解释器现在输出中文诊断 + rc=2，不再裸 Traceback + rc=1）；**R47 起 `--write-evidence-index` 与任何会改变复验语义的参数互斥**：`check_mode_contract()` 新增 `write_evidence_index` 分支与 `strict_single_body` / `json_path` 参数，统一枚举 8 类冲突（`--stl-only` / `--report` / `--manifest` / `--strict-single-body` / `--require-file-verification` / `--require-source-provenance` / `--require-evidence-index` / `--json`），CLI 删掉自己维护的 3 项列表改为调用同一函数，8 类均 rc=2 + 可读诊断；`--evidence-index` 自定义输出路径仍允许）；**R48 起写基线的输出目标受两层保护**：`write_index_protected_paths()` 放行默认 `_evidence.json`、加回 `--json` 刻意放行的 `_verify.json`，其余派生证据一律不可覆写；`guard_index_write_target()` 要求目标已存在时必须是记录相同 STL SHA256 的合法基线，否则 rc=2 拒绝覆写（覆盖自定义命名任意路径，也拒绝跨交付覆写他人基线）。`write_json_atomic()` 增 `label` 参数，两条分支共用护栏但诊断参数名正确；**R49 起** `verify_exported_stl` 显式识别 `MissingDependencyError` / `ImportError`，产出 `dependency_missing=True` 的结构化 fail-closed 结论（不降级为 PASS、也不伪装成成品几何缺陷）；**R50 起** `evidence_index_checks` 以 `expected_evidence_files()` 强制「角色 → 派生文件名」绑定，杜绝把某项证据改指向同目录合规 PNG 后脱出哈希链；**R51 起** 证据门禁新增前景填充率/逐行宽度变异/四边背景同质性三项轮廓判据，以及三视图 Z 像素高度、正/背 X 跨度的跨视图互校（同一正交相机约定，容差 5%），比例凑对的纯色矩形与改绝对取景的图不再能冒充；**R52 起** 清单输出、`file_verification.stl`、输入溯源三处路径按承载它的证据文件所在目录解析，交付目录搬迁/相对路径清单不再被误拒；**R53 起** `geometry_checks` 单次加载 + `copy()/process()`、单实体复用已算体积，指标逐字段不变；**R54 起** `DELIVERY_ARTIFACTS` / `delivery_artifact_paths()` 作为保护集合单一真值，`--json` 只放行 `_verify.json`、写基线只放行 `_evidence.json`；**R55 起** 显式 `--ref-image` 失效（不存在/损坏/模块不可用）一律 `SystemExit(2)` 且导出前停止，自动发现失败仍兼容降级、`--no-fidelity` 仍为有效 opt-out；**R56 起** `--require-evidence-index` 增 `stl_silhouette_checks()`（96×96 STL 三角形正交投影 vs PNG 前景归一化 IoU，阈值 0.65，含水平镜像兼容正/背），结果并入既有 `evidence_index_valid`、默认 12 项输出逐字节不变，实测真实交付 IoU 0.8372/0.8602/0.8283；**R57 起** `export_mesh_atomic()` 把 8 种格式统一为同目录 staging → 回读复验 → `os.replace` 原子替换，`fv.stl` 仍指向最终交付路径，伴生文件随主文件换入，失败只清理 staging；**R58 起** `meshy_client.download()` 以 `_validate_download()` 校验 `.glb` 魔数与头部声明长度、`.png`/`.jpg` 签名，改用唯一 `.part` 临时文件并 `finally` 清理；**R59 起** `_retry_after_seconds()` 统一解析整数秒与 RFC 7231 HTTP-date，非法/越界值退回指数退避或夹到 `[0,30]` |
| 主链路闭环 | R27 起 `convert_3d.py` 导出 STL 后自动调用 `verify_exported_stl` 回读**磁盘文件**，复用上述同一套几何判据并叠加「面数/焊接顶点/包围盒 vs 内存网格」3 项；结果写入 `fidelity_report["file_verification"]`、`verdict["file_verification_pass"]` 与 manifest，失败时打印原因并使退出码为 1。`verdict.checks` 仍固定 5 项（R18 契约不变）；`build_verdict` 的纯函数语义与 `apply_file_verification` 分离 |
| 连通性 | R28 起 `geometry_checks` 额外输出 `connected_parts` / `main_body_face_ratio` / `floating_parts` / `floating_parts_max_faces` / `floating_volume_ratio` / `degenerate_faces` 与结构化 `warnings`；主链路导出时打印并写入报告/清单。默认**只告警**（多实体不必然不合格），旁路的 `--strict-single-body` 可升级为硬检查。`is_watertight` 对多个互不相连的闭合体同样为 True，故此项不能由水密检查代替 |
| 单实体（R29） | `convert_3d.py` 新增 `--drop-floating-parts`：`drop_floating_parts` 按**拓扑连通性**保留最大连通块（不按面数阈值，故不会误删连在主体上的发丝）；空网格、异常、清理后主体非闭合或体积非正一律原样回退并写明原因。清洗发生在最终评估**之前**，保证 `final_mesh` 报告评价的就是导出的网格；明细写入 `geometry_cleanup` 与 manifest。新增 `--strict-single-body`：主链路 `enforce_single_body` 把 `single_body` 并入 `file_verification` 的 checks/pass，失败使 `verdict=FAIL` 且退出码 1；`validate_args` 拦截「启用硬门禁但 `--to` 不含 stl」。两开关默认关闭，多件设计勿启用 |
| 产品入口（R30） | `fig.py` 的 `print` / `all` / `image_print` / `auto` 共用 `add_print_opts`，现定义并显式透传 `--strict-watertight` / `--drop-floating-parts` / `--strict-single-body`；`--strict-single-body` 且 `--formats` 不含 stl 时入口直接返回 2 并给出可读原因，不启动子进程。`control_server.py` 的 `/api/run` 在 `auto`/`print`/`image_print` 分支用纯函数 `print_quality_flags(body)` 把布尔项（含 `"true"`/`1`/`None` 等）翻译成同名开关，非法类型显式 `ValueError`。三项默认全关以保持历史行为；`fig.py print` 端到端产出的 STL 与 `final5` SHA256 一致 |

## 五、残留风险与后续顺序

1. **单图 3D 的天然上限仍在（当前最明显的精度短板）**：正面由参考图约束，侧面/背面是重建器的合理推测；两侧长发末端有明显细条断环/镂空发束，面部起伏偏浅，手指细节弱。这些是重建侧缺陷，后处理无法凭空补出。要进一步提升，优先用项目已有的多视图链路生成侧/背参考再重建；若要保留现状直接打印，可对断环发束做局部加厚/连接（手工修模或受控膨胀），但会牺牲一点发丝锐度，需先确认可接受。
2. **体素水密化是精度与可打印性的显式权衡**：`0.25mm` 对 150mm 手办是合适默认；更细可用 `--voxel-mm 0.2`（文件更大、耗时更长），不建议再粗。
3. **旧沙发 GLB 无挽救价值**：它是"沙发+人"场景块，新的正面站立参考图已取代它；不要再对它做轮廓对齐来自我安慰。
4. **门禁阈值仍需批量标定**：`asym=0.12` 目前由少数样本校准，合法的非对称站姿可能被误拦；可用 `--input-asym-limit` 临时放宽。
5. **评估仍以 2D 轮廓为主**：已比上一版更接近真实投影，但仍不是五官/服饰级特征度量；最终验收必须结合三视图渲染。
6. **复杂背景参考图仍依赖 `rembg`（间接依赖 scipy）**：缺该链路时掩膜口径变为 `color_fallback`，IoU 不可与 rembg 版本横向比较；白底去背图（当前成品所用）不受影响。报告已写入 `mask_method`，测试在该情形下显式 SKIP。
7. **落地网格仍有大量拓扑柄**：`final4` 焊接后 `euler=-78`（约 40 个柄），`final5` 剔碎块后
   `euler=-90`（单实体，约 46 个柄），来源与长发断环/镂空一致。几何仍闭合、水密、体积为正、
   可打印，但切片时内部轮廓较多，建议在切片软件预览首层与内部填充后再出机；属重建侧遗留。
8. **历史交付物的字段版本差异已不影响当前成品**：`final4` 生成于 R24，报告/清单不含 R27 的
   `file_verification`（刻意不回填以保哈希链），独立复验对两处皆无保持兼容且检查项
   固定 12 项（R35）；**当前最终版本 `final5` 由 R29 完整链路重跑生成，报告内自证、
   旁路复验 12/12 全通过**。
9. **悬空碎块已在当前成品解决，但清理策略有边界**：`final4` 仍含 7 连通块 / 6 个悬空碎块
   （968/656/200/40/12/12 面，共 3.255 mm³）作为历史对照；`final5` 已按拓扑连通性剔除，
   `connected_parts=1`、`floating_parts=0`、退化面 0，IoU 与三视图几乎不变。
   `--drop-floating-parts` 只保留最大连通块，**若模型本就设计为多个可分离部件（独立配件、
   分件打印）会误删它们**，因此默认关闭，多件设计应分别导出。
10. **产品入口的三项质量门禁默认关闭**（R30 的兼容性选择）：`fig.py` 与控制中心都已具备能力，
    但控制中心前端未提供对应布尔项时，`auto` / `image_print` 产出的仍可能是多实体，与 `final5`
    不同。启用 `--strict-watertight` 后水密化失败会以退出码 3 拒绝导出（预期行为，但改变原本
    "仍出文件"的结果）。若要求所有产品路径默认单实体，需显式调整 `PRINT_FLAG_DEFAULTS` 并
    重新标定三视图与回归用例。
11. **文件级独立复验只覆盖 STL**（R31 后明确的边界）：`verify_deliverable.py` 与主链路的
    `verify_exported_stl` 只对落地 STL 做焊接闭合/绕向/正体积/连通块等复验；`fig.py print`
    默认同时导出 obj/3mf/ply，这些格式仅校验"写盘未抛异常"，不做几何复验。R31 修掉的是
    「STL 不在清单首位导致哈希误判」，并未把验收口径扩展到其它格式；若把 obj/3mf/ply
    也视作交付物，需另做格式级复核。
12. **独立复验不重新计算「内存比对」类判据**（R32 后明确的边界）：第 12 项会要求主链路
    逐项 `checks` 全为真并与独立重算的 4 项几何判据交叉比对，但
    `faces_match_memory` / `vertices_match_memory` / `extents_match_memory` 的参照对象是
    转换当时的内存网格，磁盘复验无法重现，只验证其布尔值。若怀疑这三项被伪造，
    需连同内存网格快照或重跑完整转换复核。
13. **`verdict` 的 IoU / 宽高比判据只校验布尔自洽，不重算数值**（R33/R34 后明确的边界）：
    R33/R34 锁死判据集合、值类型、复合汇总自洽与内存/磁盘水密交叉，但
    `silhouette_iou >= --min-iou`、`aspect_error_pct <= 1.0` 的阈值来自运行时参数，
    报告未落盘，独立复验无法重现数值。若要连数值也复核，需在报告里记录实际阈值。
14. **R35 的交叉契约依赖两个证据文件同时可信**（新增边界）：能拒绝「只删报告字段」
    「只删清单字段」「两处结论不一致」，但若 `fidelity.json` 与 `manifest.json` 被**同时**
    替换成一套自洽、且都不含 `file_verification` 的假文件，仅凭磁盘文件无法区分
    「历史产物」与「伪造」。此时磁盘 STL 的几何复验仍独立有效，且可用
    `--require-file-verification` 强制要求闭环证据；彻底封闭需要外部可信时间戳或签名链。
15. **`--json` 保护仍是「已知证据枚举 + 后缀护栏」，不是任意文件白名单**（R38 后边界收窄）：
    `evidence_paths()` 枚举 STL / `*_fidelity.json` / `*_manifest.json` / 三视图 PNG /
    同目录 `run.log`，`write_json_atomic()` 另拒绝任何非 `.json` 目标，因此 R36 实证的
    「覆盖 run.log 且 rc=0」已封闭。剩余边界：调用方自定义命名的 **`.json` 证据文件**
    （例如自己维护的 `audit.json`）若被 `--json` 指向仍会被覆写，且 `os.replace` 前不做
    内容备份；CLI 无法枚举任意证据清单，输出路径仍需由调用方选择。
    R48 已把**写基线动作**收窄：`--evidence-index` 目标已存在时必须是记录相同 STL
    SHA256 的合法基线，否则拒绝覆写；但 `--json` 分支仍保留上述边界，两条分支的
    保护集合（`evidence_paths` / `write_index_protected_paths`）各自语义靠回归锁定。

## 六、明确结论

1. 上一版的方向（门禁、参考图传递、朝向/比例、单位、报告）是对的，但**漏掉了真正毁掉最终 STL 的两个点：低精度验证参数 + 非流形网格上提前 Taubin 平滑**，并且没有完成水密化。
2. 现在链路已能产出**正面站立、表面完整、水密、单实体、尺寸一致、带量化报告**的 STL：最终轮廓 IoU 约 `0.82–0.83`（512 网格真实投影），加底座前 `0.8713`，且通过 219 项回归测试（全量 233 项）与 12 项文件级独立复验。59 轮迭代补上了报告契约、运行清单、参数边界、失败退出码、可选依赖降级、可打印性硬门禁、导出后文件级闭环、多实体/悬空碎块量化、按拓扑剔碎块与主链路单实体硬门禁、把三项门禁接到 `fig.py` / 控制中心使最终成品可从产品入口逐字节复现、R31 修掉独立复验对多格式清单的误判 FAIL、R32 让独立复验逐项核对主链路文件级结论、R33 把同类的汇总字段绕过在 `verdict` 侧也堵住，R34 修正 `verdict.pass` 复合语义并把跨模块契约固化为回归，R35 用清单作为第二证据源堵住「整段删字段降级」并交叉印证两处文件级结论，以及 R36 让验收工具的冲突参数显式拒绝、结构化证据原子写且不可覆盖交付成品，R37 让畸形证据文件走结构化拒绝而非裸 traceback，R38 把 `--json` 的证据保护补全到日志与三视图，R39 把严格数值/布尔契约补齐到主链路生成侧、让跳过或畸形指标不再中断导出或误判 PASS，R40 让报告溯源元数据不再被假值污染或静默省略，R41 让「报告/清单/磁盘」输入溯源可被显式核验且默认交付证据逐字节不变，R42 让 `verdict` 的两项数值结论可按双源阈值重算、把「数值与结论矛盾仍 PASS」堵住且默认输出仍逐字节不变，R43 把三视图/运行日志纳入可验证据基线、修复一次真实发生的证据误伤并让替换/删除/复制冒充可被拒，R44 把三视图像素轮廓与本次 STL 几何绑定、堵住「换图并同步改基线」并从几何上自证 R43 恢复图确来自最终 STL，R45 把新解码器的资源上限显式化、堵住畸形 IHDR 导致的裸 traceback，R46 让证据基线生成侧与复验侧共用几何绑定判据、把缺依赖崩溃还原成 rc=2 并堵住「自相矛盾基线」，R47 把写基线独立动作的 8 类参数冲突归一、堵住「静默丢弃验收要求」，R48 给写基线输出目标补上两层保护、堵住「覆写交付 JSON 与他人基线」，R49 修 R46 引入的主链路缺依赖误分类、R50 堵住证据角色解绑、R51 堵住「比例凑对的矩形/异取景图」两类 13/13 绕过、R52 修相对路径误拒、R53 消除几何复验重复解析、R54 把两份 protected 收归单一交付清单；R55 堵住显式参考图静默降级、R56 用 STL 投影轮廓 IoU 封堵菱形假图、R57 让导出中途失败不毁既有成品、R58 拒绝 HTTP 200 错误页冒充 GLB、R59 修 Retry-After 的 HTTP-date 崩溃（见 `docs/STL精度迭代记录.md`）。终检三环境 3.14 233/233、3.12 230（149 skip）、3.13 230（150 skip、0 error），10 模块 + 3 个测试文件编译通过，默认 12/12、强制文件级 12/12、严格/溯源/证据 13/13、四档 15/15 全 PASS，默认 `--json` 与交付 `_verify.json` 逐字节相同，九份交付哈希未变。R25–R28、R30–R59 均不改变几何；**R29 是唯一改变交付几何的一轮**，产出单实体 `final5`，IoU 与三视图基本不变，`final4` 完整保留为历史对照，未事后改写历史报告。
3. "STL 精度仍然不够"在**给定合格正面站立参考图**的前提下已解决；剩余差距主要来自单图 3D 对不可见面的推测，属于下一阶段（多视图重建）的问题。
