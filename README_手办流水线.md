# 本地二次元手办生成流水线 · 使用说明

本机配置：i9-13900K / 64GB 内存 / RTX 4090 24GB / I盘大空间
全部组件跑在本地，**没有任何云端审核**，输出内容不受平台限制。

> **一句话**：中文描述 → 本地大脑写提示词 → 出图 → 图生3D → 可直接切片的水密 STL/3MF，一条命令。

---

## 一、目录结构

```
I:\AI\
├── 启动_手办流水线.bat          ← 双击：启动 ComfyUI + 自动环境自检
├── fig.py                       ← ★★ 统一入口（图生3D/出图/转换/自检 全在这）
├── ComfyUI\                     ← 主程序
│   ├── models\                  ← ★ 目录联接(Junction) → E:\AIModels\ComfyUI\models
│   │                             （NVMe SSD！放机械盘上加载要 2-3.5 分钟）
│   ├── models_hdd\              ← 权重原始副本（机械盘，可删）
│   ├── output\                  ← 所有生成结果（png / glb）
│   └── custom_nodes\ComfyUI-Manager  ← 图形界面装节点/模型
├── print_ready\                 ← 转换后的打印文件（obj/stl/3mf/ply）
├── pipeline_figure.py           ← 底层：提示词 → 出图 → 3D
├── convert_3d.py                ← 底层：GLB → OBJ/STL/3MF/PLY + 水密化
├── test_3d_enhanced.py          ← 图生3D（带法线/UV/减面/预览）
├── make_print_ready.py          ← 图生3D + RemeshMesh 实体化（打印向）
├── test_hunyuan3d.py            ← 图生3D 冒烟测试
├── workflow_pony_api.json       ← 可导入 ComfyUI GUI 的 Pony 出图工作流
└── README_手办流水线.md          ← 本文件

E:\AIModels\ComfyUI\models\     ← ★ 权重实际存放位置（NVMe SSD，29.7GB）
Ollama 模型在 I:\ollama\models\：
`dolphin-mixtral`（26 GB，文本大脑）/ `qwen3:27b` / `qwen2.5vl:7b` / `bge-m3` / `all-minilm`
```

---

## 二、启动

双击 `I:\AI\启动_手办流水线.bat`（自动起 ComfyUI + 跑自检），
或手动 `cd /i/AI && python fig.py serve`，浏览器打开 http://127.0.0.1:8188

**出图/出3D前请先关闭占显存的软件**：微信、QQ、Wallpaper Engine、NVIDIA Broadcast、
TourBox Console、Steam 等。24GB 显存里它们能占掉 20GB。

> 判断显存够不够：`nvidia-smi --query-gpu=memory.used,memory.total --format=csv`

---

## 三、★ 统一入口 `fig.py`（推荐只用这一个）

```bash
cd /i/AI
```

### 3.1 全自动（中文一句话出可打印手办）

```bash
python fig.py auto "银发红瞳双马尾少女，穿水手服，全身立绘，背景纯白" \
    --model pony --solidify --scale 140
```

4 个阶段全自动：大脑写 tags → 出图 → 图生3D → 转 STL/3MF/OBJ/PLY（带水密化）。

### 3.2 分步

```bash
# 只让大脑把中文转成英文 tags（不生图）
python fig.py prompt "银发红瞳双马尾少女，穿水手服"

# 只出图
python fig.py img "1girl, silver hair, red eyes, twintails, sailor uniform, full body, white background" \
    --model pony --width 832 --height 1216 --seed 12345

# 已有图片 → 3D 模型
python fig.py model "I:/AI/ComfyUI/output/fig_img_00001_.png"

# 3D 模型 → 打印格式（--solidify 做水密化）
python fig.py print "I:/AI/ComfyUI/output/figure_3d_00001_.glb" \
    --solidify --scale 140 --unit mm

# 环境自检
python fig.py doctor
```

### 3.3 常用参数

| 参数 | 默认 | 作用 |
|---|---|---|
| `--model` | pony | 出图模型：`pony`（二次元专精，快）/ `flux`（通用画质高，慢 10 倍）|
| `--width/--height` | 832×1216 | 出图尺寸 |
| `--steps` | 25 | 出图步数 |
| `--seed` | 123456 | 随机种子，换数字换造型（**对背景/姿态的影响远大于负面词**）|
| `--retry` | 4 | 背景或姿态不达标时最多换 seed 重抽几次 |
| `--check-bg` / `--no-check-bg` | 开 | 出图后自动检测背景板+姿态 |
| `--bg-limit` | 0.12 | 灰色背景板判定阈值（低饱和灰区占比）|
| `--asym-limit` | 0.12 | 正面姿态判定阈值（左右不对称度），超了会换 seed |
| `--resolution` | 3072 | 3D 精度，4096 更精细但更慢更吃显存 |
| `--steps3d` | 30 | 图生3D 步数 |
| `--faces` | 60000 | 3D 目标面数上限（减面后文件更小）|
| `--crease` | 60 | 折痕角，180=全平滑，30-60 保留硬边 |
| `--solidify` | 默认开 | 体素重建水密化，**打印必须**（`--no-solidify` 关闭）|
| `--iso-model` | isnet-anime | 背景分离模型，二次元角色专用 |
| `--iso-components` | 3 | 背景分离保留的最大连通块数 |
| `--scale` | 1.0 | 缩放倍数，原始模型单位约 1.0，×140 ≈ 25cm 高手办 |
| `--pitch` | 0.01 | 体素精度（相对包围盒对角线），0.006 更精细 |
| `--brain` | dolphin-mixtral | 用哪个本地模型写提示词 |

---

## 四、3D 打印流程

### 4.1 输出格式

| 格式 | 用途 |
|---|---|
| `.stl` | PrusaSlicer / Bambu Studio / Cura 直接切片 |
| `.3mf` | Bambu Studio 原生（带单位信息）|
| `.obj + .mtl` | Blender / Maya 继续加工 |
| `.ply` | 点云 / 网格通用 |

### 4.2 已验证的水密性数据

```
原始 GLB:   180950 顶点 / 192587 面    watertight=False
体素化后:   28833 顶点 /  58202 面    watertight=True
实际尺寸:   256 × 278 × 83 mm（--scale 140）
```

### 4.3 完整手办还需要

模型是**单体原型**，实际打印还要：

1. **分件**（在 Blender 里切成头/身/头发/手臂等独立件）——现在所有部位粘连
2. **加支撑**（头发内腔、裙摆内凹）
3. **切片**（用 Bambu Studio / PrusaSlicer 打开 3mf/stl）

---

## 五、模型说明

| 模型 | 作用 | 大小 | 说明 |
|---|---|---|---|
| **Flux.1-dev fp8** | 出图 | 17.25 GB | 通用画质天花板，手部/解剖更准，fp8 量化后 4090 跑得动 |
| **Pony V6 XL** | 出图 | 6.94 GB | 二次元专精，动漫风格还原最好，出图快 |
| **Hunyuan3D 2.1** | 图生3D | 7.37 GB | 腾讯开源，ComfyUI 核心原生支持，无需额外节点 |
| **dolphin-mixtral** | 文本大脑 | 26 GB | Mixtral 8×7B MoE，无限制，已接进 `fig.py auto` |
| qwen3:27b | 文本大脑 | 17 GB | 你原有的，更强，可 `--brain qwen3:27b` 切换 |

### ComfyUI 核心原生 3D 节点（无需装任何 custom node）

| 节点 | 作用 | 注意事项 |
|---|---|---|
| `VoxelToMesh` | 体素 → 网格 | threshold 0.6 常用 |
| `DecimateMesh` | 减面 | **只保留 (v,f,c)，会丢弃法线/UV，必须放在 UV/法线之前** |
| `UnwrapMesh` | UV 展开 | 只输出 (v,f,uvs,colors)，不含法线 |
| `MeshSmoothNormals` | 重建法线 | 会保留已有 UV，**必须放最后** |
| `RemeshMesh` | 体素重网格 | `sign_mode=solid` 出水密，但会削平薄发丝，手办慎用 |
| `RenderMesh` | 渲染预览 | 可视化检查模型质量 |
| `SaveGLB` / `MeshToFile3D` | 导出 | 支持 GLB/GLTF/OBJ/FBX/STL/PLY/USDZ |

**正确节点顺序**：`减面 → UV → 法线`。写反了法线和 UV 会被丢掉。

---

## 六、实测性能（RTX 4090，权重已迁到 NVMe）

| 环节 | 耗时 | 备注 |
|---|---|---|
| 大脑写提示词 | **7-8 秒** | dolphin-mixtral（Ollama 模型已迁 NVMe，冷加载 10s）|
| Pony 出图 832×1216 | **3 秒**（热）/ 10 秒（冷） | 二次元首选 |
| Flux 出图 896×1152 | ~3 分钟 | 画质更通用 |
| 背景分离 (isnet-anime) | 3-5 秒 | 二次元角色专用分割模型 |
| 背景板自动检测+重抽 | 每张 +1 秒 | 不达标自动换 seed，最多 4 次 |
| Hunyuan3D 2.1 图生3D | **33 秒** | 含 UV 展开与预览渲染 |
| 水密化（体素重建）| ~30 秒 | pitch=0.01 |
| **全流程 auto** | **约 1.5 分钟** | 中文 → 可切片 STL |

### ⚠️ 磁盘是这套流水线的头号瓶颈（比 GPU 更值得先管）

本机磁盘拓扑：**I:/H:/J:/K:/L: 是 SATA 机械盘**，**D:/E:/F: 是 NVMe SSD**。

权重放机械盘上时，ComfyUI 每次加载权重要 **2-3.5 分钟**
（读 6.94GB 按 58MB/s），采样本身只有 3 秒 —— 看起来像「出图变慢 10 倍」，
其实是 I/O 瓶颈。**GPU 满载 100% / 444W / 59°C 却变慢 → 就是磁盘问题，不是 GPU 问题。**

已做的处理：

- `I:\AI\ComfyUI\models`（29.7GB）已搬到 `E:\AIModels\ComfyUI\models`（NVMe）
- 原位置建**目录联接（Junction）**，路径完全不变，所有脚本照常工作
- **模型加载 3分20秒 → 4 秒**
- `I:\ollama\models`（53GB）已搬到 `E:\ollama\models`（NVMe），同样建 Junction
- **大脑冷加载 163 秒 → 10 秒**（dolphin-mixtral 26GB 从机械盘读 → NVMe 直读）

自己加新模型时，直接放进 `E:\AIModels\ComfyUI\models\<对应目录>` 即可。

### ⚠️ 显存是第二瓶颈（24GB 装不下「LLM + 扩散模型」）

实测踩过的坑：

| 现象 | 原因 | 处理 |
|---|---|---|
| 出图从 13 秒变 150 秒+ | Ollama 的 `llama-server.exe` 占住 **15.6GB** 显存，ComfyUI 被迫 CPU 卸载 | `fig.py` 已内置：大脑请求带 `keep_alive:0` + 结束后主动 `taskkill` 残留 runner |
| 出图慢但显存看起来够 | TourBox Console / NVIDIA Broadcast / Steam / Edge / NVIDIA Overlay 常驻占显存 | 关掉它们，或重启 ComfyUI |
| `fig.py auto` 卡在"等待显存释放" | 其他程序占着 | `fig.py doctor` 会打印当前已用/总量 |

> `fig.py auto` 的阶段 0 结束后会自动等待显存回落到 6GB 以上再出图，
> 并在显存不足时给出明确提示，而不是让你对着一张糊图发呆。

### 中文 → 英文 tags 的两段式翻译

小模型（Mixtral 8×7B）直接翻中文会出错：把「水手服」译成 `swimsuit`、「银发」译成
`yellow hair`、「红瞳」译成 `blue eyes`；把术语表塞进 system prompt 又会让它**复读术语表**。

`fig.py` 的做法：

1. **本地词典确定性翻译** —— 内置 `ZH_EN` 词典（120+ 词条：发色/发型/瞳色/服装/体型/动作/画质），
   正则额外处理「颜色+长度+头发」合并写法（`黑长发` → `black hair, long hair`）
2. **LLM 只做增量润色** —— system prompt 明确要求「不得改动已翻译的词」，
   输出只作为 extras 追加，与词典冲突的用 `_norm()` / `_collides()` 过滤
3. **词典命中项为权威** —— LLM 漏掉的词会被补回，标签顺序固定为
   `1girl, solo, anime character → 角色特征 → 画质项`

LLM 完全不可用时自动降级为「纯词典翻译」，出图照样能用。

---

## 七、图生3D 的现实说明

Hunyuan3D 2.1 能生成**可直接打开的网格模型**（.glb/.obj），实测能还原发型、
五官轮廓、领结、配饰、裙褶。适合：

- ✅ 角色立绘/半身像的立体化
- ✅ 手办原型验证、参考造型
- ✅ Blender 里继续加工

### 7.1 输入图要求（踩过坑，很关键）

| 要求 | 原因 |
|---|---|
| ✅ **全身/半身、主体完整不遮挡** | 面部大特写会让模型崩坏（眼睛变白洞、头发糊成片） |
| ✅ **纯色背景**（`white background, simple background`） | 复杂背景会被一起重建成几何体 |
| ✅ **先做背景分离**（`fig.py` 自动做） | 见下 |
| ❌ 背景里有机甲/武器/场景 | **实测：带巨大机甲的立绘 → 3D 出来是一块 1.95×1.95×0.13 的平板** |
| ❌ 面部大特写 | 模型崩坏 |

### 7.2 背景分离（rembg）为什么必须有 + 自动挑好图

Hunyuan3D 会把**整张图**都重建成几何体。Pony 很爱在角色背后加机甲/武器/场景，
一旦有，3D 结果就是一团含背景的乱块。

更隐蔽的问题：**Pony 经常在角色身后画一块灰色「影棚无缝背景纸」（seamless backdrop）**。
这块板 rembg 会判成前景，Hunyuan3D 会把它重建成**一整面墙**。

`fig.py` 的处理分两层：

**第一层：自动挑好图（出图阶段）**

出图后自动检测「低饱和灰区占比」（灰色背景板的颜色特征），超过阈值（默认 12%）就
**自动换 seed 重抽**（最多 4 次）。实验证明 **seed 对背景的影响远大于负面词**——
同一个提示词，seed 12345 出 88% 灰区，seed 777 只出 0.9%。

> ★ 只检测「灰色背景板」。**背景文字/彩色圆盘故意不在这里检测** ——
> 它们和角色身上的高饱和区域（红领结、红瞳）颜色完全相同，纯颜色分析无法区分
> （试过 rembg 掩膜、边缘连通、离散块计数三种方案，都会把干净图误判成脏图）。
> 这类污染交给**第二层的背景分离**处理，实测效果很好。

> CLI：`--check-bg`（默认开）/ `--no-check-bg`（关）/ `--bg-limit 0.12`（调阈值）/ `--retry 4`

**第二层：背景分离（图生3D 阶段）**

`fig.py model` / `fig.py auto` 在送入 Hunyuan3D 前自动执行五步处理：

1. **rembg (isnet-anime) 抠图** —— 用针对二次元角色训练的分割模型（而非通用 u2net），
   对动漫插画的主体分离更干净
2. **alpha 阈值二值化（>32）+ 轻微腐蚀** —— 抹掉低置信度灰影残影
3. **连通域主体提取 + 扁块过滤** —— 只保留最大的 3 个连通块，剔除背景碎片；
   宽高比 > 2.5 的扁块（背景板/色带）直接丢弃
4. **空洞填充（形态学闭运算）** —— 补回衣服镂空，避免 3D 出现贯穿的洞
5. **按角色包围盒裁切 + 8% 留白 + 缩放到长边 1024** —— 提升 3D 有效分辨率

> 实测：**背景里的红色日文文字会被这一层完全剔除**，送进 3D 的只有干净的角色。
> 唯一例外是**与角色重叠的圆形色块**（如角色身后的红色圆盘）——任何分割法都分不开，
> 但实测它的 3D 结果仍然是完整干净的人形，不影响可用性。

> CLI：`--iso-model isnet-anime`（默认）/ `--iso-model u2net`（通用）/ `--iso-components 3`（保留块数）/ `--no-isolate`（跳过）

### 7.3 UV 展开参数（踩过坑）

`UnwrapMesh` 的 `weld_distance` 是**顶点焊接半径（相对包围盒）**，
官方 tooltip 写明「出现 per-triangle charts 时调到 ~0.001」。

我一开始设成 `0.0002` —— **比顶点间距还小，焊接完全失效**，网格变成 triangle soup，
UV 每个三角形一个 chart（18 万面 → 13 万 charts），光这一步就要 **136 秒**，
还产出一张 5086×5207 的巨图。

改成 `weld_distance=0`（自动）+ 面数减到 6 万 + UV 分辨率 1024 之后：
**UV 展开 136 秒 → 几秒，atlas 5086×5207 → 1604×1606**。

### 7.4 性能对照（同一张图）

| 配置 | 图生3D 总耗时 | GLB 大小 | 结果 |
|---|---|---|---|
| HDD 权重 + faces 20万 + weld 0.0002 | 210 秒+ | 14.66 MB | 糊 / 平板 |
| NVMe 权重 + faces 6万 + weld 0 | 33 秒 | 2.74 MB | 角色可辨认 |

---

## 七之二、★★ 3D 精度重做（商业级手办必读）

> ⚠️ **2026-11 实测修正（重要，先读这段）**
> 1. **当前 `fig.py` 默认并不走 RemeshMesh**：`cmd_model` 里
>    `high_precision = --remesh-solid`（默认 **关**），实际管线是
>    `VAEDecodeHunyuan3D(octree) → VoxelToMesh(surface net) → 法线`。
> 2. **不要默认开 `--remesh-solid`**：实测 RemeshMesh(solid) 会把四肢/绳子粘连成一团
>    （轮廓 IoU 从 0.86→0.34），`resolution=1024` 还能把 ComfyUI 跑崩
>    （`MeshSmoothNormals` 处理 472 万面时 access violation）。
> 3. **现在提精度靠 octree 档位 + 采样步数**（`--octree-res` / `--steps3d`），
>    当前默认已升到 **`--steps3d 50` + `--octree-res 512`**：
>
> | octree | 面数 | GLB | 锐边>30° | 仅解码耗时 | 说明 |
> |---|---|---|---|---|---|
> | 256 | 327,424 | 7.7 MB | 2.99% | ~10 s | 旧默认，表面橘皮/台阶 |
> | 384 | 726,616 | 17.3 MB | **1.55%** | ~39 s | 旧默认，目视明显干净 |
> | **512（现默认）** | 1,284,442 | 30.7 MB | **0.84%** | ~81 s | 现默认高精度，整跑 100s+ |
>
> 4. 诚实结论：**表面质量能提升，但五官/手指救不回** —— 这是单图生成模型的先验上限，
>    到不了 Meshy 的商业级；要更进一步需要多视角输入（Hunyuan3Dv2ConditioningMultiView）。
>    2026-11 实测：同一张原图，30 步/384 会把刘海和衣褶压成平滑壳；
>    50 步/512 能稳定补出可辨发束与衣摆起伏，但五官和手指仍受单图先验限制。
> 5. 其它单变量实测：latent resolution 4096/6144 会明显改变比例（体积 +23%），不建议默认；
>    steps/阈值/dpmpp2m 在噪声级无收益；`VoxelToMeshBasic` = 三角汤（非水密），不要用。
> 6. 输入侧：当前默认**不压阴影**（`--no-flatten` 默认 True），保持即可；背景分离链路无需改。
> 7. 3D 预览现在会输出**正面/背面/侧面三张图**（`*_preview.png` / `*_preview_back.png` /
>    `*_preview_side.png`），只看正面容易误判还原度。

### 8.1 问题现象

旧版模型放进切片软件后，表面是**明显的阶梯/马赛克状**，
完全达不到商业手办的精度要求（用户原话：「完全没法做化，作为商业化手办的模型使用」）。

### 8.2 根因诊断（用数据说话）

不是「面数不够」，而是**两级降精度叠加**：

| 环节 | 旧做法 | 问题 |
|---|---|---|
| 图生3D | `VoxelToMesh(surface net)` → `DecimateMesh(60000面)` | 表面本身是体素化的，天然带阶梯 |
| 打印格式 | 再做一次体素重建 `marching_cubes(pitch_ratio=0.01)` | **二次体素化**，把细腻表面碾成大块台阶 |

关键数字：旧版 `pitch_ratio=0.01` 对应 **150mm 手办只有 75 层**，横向再乘 3-4 个台阶宽
——这就是截图里「每个台阶约 2mm 高」的来源。

实测「相邻面夹角 >30° 的边占比」（阶梯感的直接指标）：

| 方案 | 锐边占比 | 水密 |
|---|---|---|
| 旧版 | **35.46%** | ✗ |
| 新版 | **0.07%** | ✓ |

### 8.3 新管线（三处改动）

**① 图生3D 改走 RemeshMesh 高精度路径**

```
VoxelToMesh(surface net) → RemeshMesh(solid, resolution=512) → [DecimateMesh] → UV → 法线
```

`RemeshMesh` 用窄带距离场 + Dual Contouring 重新提取均匀网格：
- `resolution=512` ≈ 100 万面（旧的 6 万面精细 17 倍）
- `sign_mode=solid` **直接产出水密实体**，不需要二次体素化
- `smooth_iters=3` 专门清理 DC 阶梯伪影（节点 tooltip 原文：*cleans DC staircase-like artifacts*）

**② 打印阶段取消二次体素化，改用 Taubin 平滑**

体素重建（`marching_cubes`）实测会把锐边占比从 0.43% 拉高到 **20%+**，
等于把 RemeshMesh 辛苦做出来的精细表面又碾了一遍。
现在改成 `Taubin 平滑(λ=0.5, ν=-0.53)` —— 保体积、不收缩、只清高频伪影：

| 平滑迭代 | 锐边占比 | 体积 | 水密 |
|---|---|---|---|
| 0 | 0.43% | 0.03321 | ✓ |
| 4 | 0.11% | 0.03319 | ✓ |
| **10（默认）** | **0.07%** | 0.03316 | ✓ |

**③ 不减面（或只在 ComfyUI 端减面）**

`DecimateMesh` 会**撕裂网格**（实测产生 10 万+ 条边界边，水密性彻底丢失）。
所以默认 `--faces 0`（不减面）。需要小体积时用 ComfyUI 端的 `DecimateMesh`
（在 `RemeshMesh` 之后执行，仍保持水密），不要在 Python 侧用 QEM 减面。

### 8.4 新增参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--remesh-res` | 512 | RemeshMesh 体素分辨率。512≈100万面 / 768 / 1024 |
| `--smooth-iters` | 3 | DC 平滑迭代。清理阶梯伪影 |
| `--remesh-band` | 1.0 | 窄带宽度（体素单位）。越大缝隙桥接越强 |
| `--project-back` | 0.0 | 顶点投影回原表面比例。0.5 更保形 |
| `--low-precision` | 关 | 用旧的低精度路径（快但表面阶梯状） |
| `--faces` | **0** | 目标面数。0=不减面（推荐） |
| `--smooth` | **10** | Taubin 平滑迭代（Python 侧后处理） |
| `--model-height` | 0 | 成品高度(mm)。自动换算缩放，最实用的参数 |
| `--ref-model` | 无 | 参考网格，用于还原被 RemeshMesh 归一化的尺寸 |

### 8.5 ⚠️ 已知缺陷：RemeshMesh 尺寸归一化

`RemeshMesh` 内部把模型归一化到 `[-0.5, 0.5]` 立方体，且 **output 不做反归一化**
（`comfy_extras/mesh3d/postprocess/remesh.py` 末尾直接 `return dual_verts, ...`）。

后果：直接导出的 GLB 尺寸是 `1.00 × 1.00 × 0.68`，而不是真实比例。
但**绝对尺寸不影响形状**（只是整体缩放），用 `--model-height 150` 即可按真实高度输出。

如需还原与旧版完全一致的比例，用 `--ref-model` 指定一个参考网格。

### 8.6 高精度方案速查

```bash
# ★ 推荐：最高精度（440万面，锐边0.07%，水密，GLB 79MB）
python fig.py model 图.png --faces 0 --remesh-res 512 --smooth-iters 3
python fig.py print 模型.glb --model-height 150

# 轻量版：40万面（GLB 7MB，锐边0.71%，水密）
python fig.py model 图.png --faces 400000 --remesh-res 512 --smooth-iters 3
python fig.py print 模型.glb --model-height 150
```

---

## 七之三、★★ 源图质量：3D 的真正瓶颈（背景色块 + cel shading）

> 8.x 节把 3D 管线的精度从 35.46% 锐边降到 0.07%。但修完发现：
> **3D 精度已经不再是瓶颈了 —— 输入图才是。**

### 8.7 症状：3D 出来是「背面 + 背后顶着个红圆盘 + 表面蜂窝纹」

用 `fig.py` 跑出来的图，3D 结果有三个明显毛病：

| 症状 | 真实原因 |
|---|---|
| 3D 渲染出来是**背面** | Hunyuan3D 对「中心对称的正面立绘」做深度歧义判断，选了反面 |
| 背后顶着**一个巨大的红圆盘** | 源图背景里的红色圆形色块没被分离掉，被重建成实体 |
| 表面有**蜂窝/拉丝纹** | 二次元平涂阴影（cel shading）被当成几何深度 |

### 8.8 诊断数据（用 `_diag_source.py` 实测）

对比「干净参考图」和「实际分离后的图」：

| 指标 | 干净参考图 | 实际分离图 | 结论 |
|---|---|---|---|
| 高饱和红色像素占比 | 0.4% | **15.6%** | 红圆盘全被抠进来了 |
| 边缘 12% 区域高饱和红 | 0.0% | **3.8%** | 红圆盘在角色两侧露出 |
| 强饱和像素总占比 | 3.5% | **13.3%** | 整体过饱和 |

### 8.9 修复一：出图阶段禁止背景图形（根因）

Pony 即使在「白底」提示下也会画装饰性圆形色块。已在 `fig.py` 里改：

- **`STD_TAIL` 加 3D 友好词**：`flat shading, clean silhouette, minimal shading, no shadow details`
  → 抑制 cel shading，减少深度歧义
- **`DEFAULT_NEG` 加禁止项**：`background circle, background pattern, colored background,
  red circle, geometric pattern, polka dots, sunburst, radial pattern` + 
  `cel shading, gradient shading, mesh pattern, honeycomb pattern, texture details`

### 8.10 修复二：分离阶段自动剔除背景色块（`_drop_color_blobs`）

isnet-anime 会把高饱和的背景色块当成前景。**用颜色指纹剔除，不靠形状**：

> 关键判据（实测确定）：**绿蓝通道双低且彼此相等 = 纯暗红背景块**
>
> | 区域 | 均色 RGB | 结论 |
> |---|---|---|
> | 红圆盘 | `(0.62, 0.15, 0.17)` | G≈B 且都很低 → 纯暗红 |
> | 角色领结 | `(0.64, 0.37, 0.40)` | G/B 明显更高（混了白高光） |
> | 银发 | `(0.77, 0.68, 0.70)` | 低饱和 |

判定链：
1. `mask 内 + 饱和度>0.45 + G≤0.28 + B≤0.28 + |G−B|≤0.06` → 候选暗红像素
2. 连通域找面积 > 2% 的块，校验**纯度**（到均色的平均 RGB 距离 < 0.06）
3. 拿到**颜色指纹**后，**一次性清除全图同色像素**（含抗锯齿残边）

> ⚠️ 踩过的坑：不能只删「连通块本体」。圆盘被角色切成左右两半，
> 大部分又被 rembg 判成背景，真正要清的是「mask 内所有该纯色的像素」。
> 实测目标像素 78,295（占前景 31%），而单个连通块只有 33,308。

**安全阀**：
- `blob_min_frac=2%` 排除小装饰（红眼睛 0.03%、领结 0.34%）
- 剔除后主体不足 25% 则放弃本次剔除
- **回归验证**：干净参考图**完全不触发**剔除（领结原样保留）

实测效果：暗红残留从 **18.2% → 2.0%**（剩下的 2% 就是领结，是真·角色装饰）。

### 8.11 建议流程

```bash
# 出图（提示词已内置 3D 友好词）
python fig.py img "1girl, silver hair, red eyes, twintails, sailor uniform, full body" --model pony

# 图生3D（分离阶段会自动剔背景色块）
python fig.py model 出图.png --remesh-res 512 --smooth-iters 3 --faces 0

# 打印格式
python fig.py print 模型.glb --model-height 150
```

---

## 七之四、修改已有图片（涂抹局部重绘）

启动器里「✏️ 修改已有图片」，或命令行：

```bash
# 局部重绘（推荐）：只替换涂抹区域，选区外像素逐像素保持原图
python fig.py edit_image "输入.png" "去掉底座上多余的散落麻绳，重建透明底座" \
    --method local --mask 遮罩.png

# 整图重生成：整张图都重画（姿势不变，但背景/细节会变）
python fig.py edit_image "输入.png" "把底座改成深蓝色" --method whole

# 不涂抹，按描述修改整图
python fig.py edit_image "输入.png" "把背景换成浅蓝渐变" --method ai
```

要点：

- 遮罩：白色 = 允许修改，黑色 = 保持原样；回贴时边缘会羽化过渡，不会出现生硬接缝。
- `local / auto / remove` = 局部重绘：Qwen 重画整张图，但只把**涂抹区域**贴回原图；
  `whole / ai` = 整图重生成。
- **种子与「马赛克噪点」**：旧版固定 `seed=123456`，Qwen-Image-Edit-2509 在这个种子下会把
  平滑背景整片生成成高频雪花噪点（看起来像「打码/马赛克」）。现在默认随机种子，并在每张
  生成后检测平坦区域的噪点放大倍数（正常 ≈1，失败样例 300~2000 倍）；超过 8 倍自动换种子
  重试，从最多 `--attempts`（默认 2）张里挑最好的。
- `fast`（cv2.inpaint 快速背景插值）已停用：它只会留下模糊色块。
- 结果保存到 `ComfyUI/output/fig_edit_local_*.png` / `fig_edit_whole_*.png`，**不覆盖原图**；
  启动器里会直接显示结果预览。
- 局部重绘效果好坏的要点：目标连边缘一起涂满、稍微涂宽一点；修改要求写清楚「改什么、保留什么」。
- **回贴质量（2026-11 优化）**：局部重绘不再直接把整图重绘结果羽化贴回，而是：
  1. **裁剪放大重绘**：按涂抹区域裁一块（带 50% 余量）放大到约 1MP 再交给 Qwen，像素集中花在目标区域，细节更锐；
  2. **颜色匹配**：用选区外一圈的均值/方差校正重绘区域，去掉「贴上去的色块/发灰」感；
  3. **Poisson 无缝融合**（OpenCV seamlessClone）：边缘按梯度过渡，不再有生硬的羽化带；
  4. **内区轻度锐化**（只锐化腐蚀后的内区，避免白边）。
  想退回旧行为可用 `--no-crop-local`。实测：泳圈上的白色字母去除后表面均匀、边缘无接缝。
- **多方案**：`同时生成方案数` 可选 1~3。同一张图+同一要求，Qwen 编辑本质上很稳定（换种子只差 ~1% 像素），
  所以多方案会用不同 cfg（4.0 / 5.4 / 3.2）+ 不同措辞来产生可见差异，生成后在页面下方给缩略图挑选。
  命令行：`--candidates 3`。
- **涂抹撤销/重做**：启动器里 `Ctrl+Z` 撤销、`Ctrl+Y`（或 `Ctrl+Shift+Z`）重做，**「清空涂抹」也能撤销**。
- **参考图槽位**：图生图和修改已有图片都支持「主图 + 多张参考图」。Qwen-Image-Edit-2509 原生
  最多吃 3 张图，所以模型实际用「主图 + 前 2 张参考图」，多选的会被忽略（界面有提示）。
  命令行：`--refs a.png b.png`。图生图的参考图只在 `--engine qwen` 下生效。
- **自然语言 + 优化 + 原意**：点「优化修改要求 / 优化提示词」后，提交时会把**优化后的提示词和你的
  原始意图**一起交给模型，避免优化把意图改歪。

---

## 七之五、启动器界面（4K / 宽屏布局）

- 顶部固定栏：功能导航（全自动 / 图生图 / 修图 / 去敏感 / 工具 / 日志）+ 服务状态胶囊。
- 主区是**砌体多栏**：宽屏 4 栏（≥2200px）、3 栏、2 栏、1 栏自适应；卡片不再按行对齐，
  短卡片不会在下方留一大片空白，一屏内可以同时看到所有功能。
- 新增「🖼️ 最近输出」卡片：显示 `ComfyUI/output` 里最新的出图/3D 预览，点缩略图放大。
- 快捷键：`Ctrl+Z / Ctrl+Y` 涂抹撤销重做；`Esc` 关闭大图预览。

---

## 七之六、Meshy 云端 3D（一键切换，本地 / 云 / 自动）
### 🔑 填写 / 更换 API key（启动器内）
「全自动生成手办」卡片里 Meshy 余额那一行有 **「🔑 填写/更换 API Key」** 按钮：
- 粘贴 Meshy 控制台生成的 key → **保存并测试**（写进 `E:\AI\meshy_config.json`，页面只显示 `msy_xx…xxxx`，不回显明文）；
- 支持 **测试连接**（查余额）、**清除 Key**；换新号时直接粘新 key 保存即可；
- 页面余额显示同步刷新；环境变量 `MESHY_API_KEY` 仍可覆盖文件里的 key。


启动器「🚀 全自动生成手办」卡片新增 **3D 引擎**下拉，一键切三种：
`本地 Hunyuan（免费）` / `Meshy 云（高精度）` / `自动（本地失败才回退云）`；
选云端时会出现「上传前脱敏」勾选和 Meshy 余额显示。

**已接入的 Meshy 官方 API**（`api.meshy.ai/openapi/v1`，Bearer key）：

| 环节 | 用途 |
|---|---|
| `POST /image-to-3d` | 图生3D 主链路（默认 `meshy-7.1`，mesh-only，可 `geometry_resolution=2k/4k` Ultra、`target_polycount`） |
| `GET /image-to-3d/{id}` | 轮询任务（PENDING/IN_PROGRESS/SUCCEEDED/FAILED，progress 0–100） |
| `GET /balance` | 查剩余积分（启动器余额、CLI `meshy_client.py balance`） |
| `POST /multi-image-to-3d` | **已接入** Meshy 官方多视图重建（1–4 视图，第一张 front） |
| `POST /image-to-image` | **已接入** `generate_multi_view=true`，自动生成 front/side/back 参考 |
| `POST /remesh` / `repair-printability` / `analyze-printability` | 重网格、打印修复，可后续按需接 |

**配置**：`E:\AI\meshy_config.json`（已加入 `.gitignore`，不会被 git 提交）：

```json
{ "api_key": "msy_...", "ai_model": "meshy-7.1", "geometry_resolution": "standard",
  "should_texture": false, "target_polycount": 300000, "desensitize_before_upload": false }
```

也可以用环境变量 `MESHY_API_KEY` 覆盖。**API key 不会打印到日志，也不会写进 HTML/JS。**

**命令行**：

```bash
# 云端高精度 3D（mesh-only，约 20 积分/次；300k 面更适合打印）
python fig.py model 图.png --engine meshy --meshy-poly 300000
# 敏感内容：上传前自动脱敏 → 生成 → 本地把原图正面贴图还原回来
python fig.py model 图.png --engine meshy --meshy-desensitize --meshy-strength auto
# 自动回退：本地 Hunyuan 失败才用 Meshy
python fig.py model 图.png --engine auto
```

### 多视图重建（推荐用于侧/背细节）

单张正面图无法知道背面，模型只能猜。`meshy-mv` 会先用 Meshy `image-to-image`
生成同一角色的 front/side/back，再送 `multi-image-to-3d` 重建：

```bash
# 首次：自动生成 3 视图 + 2K 多图重建，约 28 积分
python fig.py image_print 图.png --engine meshy-mv --formats stl --model-height 150

# 复用已有视图：跳过 image-to-image，约 25 积分
python fig.py image_print 图.png --engine meshy-mv \
  --mv-refs front=front.png left=side.png back=back.png
```

- 多图接口最细只支持 `geometry_resolution=2k`；4K 仅单图接口可用。
- 生成的视图保存在 `ComfyUI/output/_meshy_views/`，同目录 `*_views.json` 记录顺序与来源。
- 自动用轮廓 IoU 把最像原图的视图排到 front；显式 `--mv-refs` 时尊重你给的顺序。
- 余额不足会在提交前中止；当前进度日志会打印预计积分。
- 实测样本：3 视图 + 2K 重建，STL 轮廓 IoU 0.8925（旧单图 final5 为 0.8281），背面长发分组和侧视体积明显改善。

**工作流（敏感手办）**：
`本地预处理（抠图+方图）→ 最小程度脱敏（自动检测高风险区，画/块覆盖）→ Meshy 生成（过审）
→ 下载 GLB → restore_texture.py 把原图正面贴图投影回去 → 打印转换时自动 --solidify 水密化`。

**实测（2026-11-05，用户真实输入）**：
- 两次云端生成各消耗 **20 积分**（954→934→914），任务 40~60s 完成（排队另算），审核通过；
- mesh-only 默认 remesh 输出 **30,879 面 / 2.0MB**；`--meshy-poly 300000` 输出 **309,699 面 / 9.7MB**；
- Meshy 网格**非水密**，`fig.py print` 对 Meshy 模型会自动加 `--solidify --pitch 0.002`，
  实测输出 148 万面、水密通过、STL 约 74MB（150mm 成品）；
- 结果文件保留在 `E:\AI\ComfyUI\output\fig_meshy_*`，预览图 `*_preview.png`。

**限制（照实写）**：
1. Meshy 云端只保留结果 **3 天**，下载 URL 是带签名的临时链接 → 必须下载后存本地（已自动下载）。
2. 并发/限速按套餐：Pro 10 并发、Premium 30、Ultra 100；20 req/s；429 要按 `Retry-After` 退避（客户端已处理）。
3. 内容审核：敏感图先脱敏（`--meshy-desensitize`），审核失败会退积分但耗时；脱敏只用色块/像素化，不改轮廓。
4. 生成物是带贴图的 GLB，不是可打印实体：**必须**走本地 `convert_3d.py` 水密化/底座/缩放，不能直接切片。
5. 每重试一次都是新任务 + 20 积分；API 不支持原地重试。
6. 五官/手指仍可能被简化——云端模型更强但也不是万能；复杂遮挡/单图背面仍是先验上限。

---

## 七之七、多视图测试图（8 方位，单张/批量）

启动器新增「📐 多视图测试图」卡片，也可以命令行：

```bash
# 生成单张（front/back/left/right/front_left/front_right/back_left/back_right）
python fig.py multiview 主图.jpg --views front --prompt "手办实拍风格，干净白底，保持同一姿势与道具"
# 一次生成多张
python fig.py multiview 主图.jpg --views front back left right --prompt "..."
# 用已生成的其他视图做一致性参考（最多 2 张）
python fig.py multiview 主图.jpg --views right --refs out/front.png out/front_left.png
```

要点：

- 8 个方位：前、后、左、右 + 左前 45°、右前 45°、左后 45°、右后 45°。
- 启动器里 **每张图都有独立的「▶️生成 / 🔁重生成」按钮**，并带「这张的单独要求」输入框，可以只改这一张。
- 每张左上角可勾选：**单选 / 多选**后点「🔁 重新生成选中（N）」批量重生成；批量会按「正面→左右→背面→斜侧」顺序跑，正面当锚点。
- 勾选「用已生成的其它视图做一致性参考」时，会自动挑最多 2 张已完成视图作为参考图（Qwen-2509 最多 3 图）。
- 结果保存为 `ComfyUI/output/fig_mv_<方位>_<uuid>.png`（3D 模式为 `fig_mv3d_<方位>_*.png`），页面内直接显示缩略图，点缩略图看大图。
- **两种方式**（卡片里可切）：
  - **🧊 3D 定格 + 渲染（推荐，姿势完全不变）**：先用原图建一次 3D 粗模（本地 Hunyuan 免费 / Meshy 带贴图约 30 积分彩色），
    再用 **Blender 无头渲染**把同一个模型绕竖轴转出 8 个方位——姿势/比例/道具由 3D 决定，**不可能被改成站姿**。
    每张图有独立「📸 渲染」按钮（几秒一张），勾选多张可批量渲染。对应命令：
    ```bash
    python fig.py mv3d 主图.png --stage build                 # 本地 Hunyuan 建粗模（免费）
    python fig.py mv3d 主图.png --stage build --engine meshy  # Meshy 带贴图建粗模（≈30 积分，彩色）
    python fig.py mv3d 主图.png --stage render --glb 粗模.glb --views front back left right
    ```
    依赖：本机已装 **Blender 5.2**（脚本自动找 `C:\Program Files\Blender Foundation\*\blender.exe`，
    也可在 `meshy_config.json` 里配 `blender_exe`）。渲染脚本：`E:\AI\render_views.py`。
    ⚠️ 输入必须是**有立体感的图**（手办渲染/实拍）：如果是"平面立牌照片/插画"，3D 重建会得到一张薄片，
    脚本会打印"粗模非常扁"的警告——先用「图生图」把立牌照转成手办渲染图，再走 3D 定格。
  - **🖼️ 纯 AI 重绘**：Qwen 直接"想象"其它角度。快，但复杂姿势/道具（如泳圈）可能被改掉，只适合简单姿态。
- 3D 模式下：先点「🧊 ① 生成 3D 粗模」（可切本地/Meshy 彩色）→ 每张点「📸 渲染」单独出图（几秒），
  勾选多张后点「重新生成选中」可批量渲染。
- 3D 重建质量决定细节（本地 Hunyuan 对复杂坐姿/遮挡偏糊；Meshy 带贴图会好很多）；这是单图/少量图 3D 重建的
  上限，和"多视图 2D 生成"不是一回事——高精度多视图建议直接用 Meshy 的 multi-image-to-3D 再渲染。

---

## 七之九、模型文件修改（导入自己的 3D 模型，用自然语言改）

启动器新增「🧩 模型文件修改」卡片（`fig.py model_edit`）：

1. **导入模型**：GLB / GLTF / OBJ / STL / 3MF / PLY（选完显示面数、顶点数、是否水密、尺寸）。
2. **写修改要求**（自然语言，如「把泳圈改成红色」「去掉背后的支架」）。
3. 选方式：
   - **外观/贴图修改（快，推荐）**：Blender 渲染正面 → Qwen 按文字改渲染图 → 把改后的图作为正面贴图**投影回模型**（`project_texture.py`），输出新 GLB。
     适合颜色/涂装/去文字/换图案；背面侧面是拉伸投影（跟随正面变化，但不是独立细节）。
   - **几何重建（Meshy，约 20 积分）**：渲染正面 → Qwen 改图 → Meshy 图生3D 重建，得到新模型。适合改形状/删物件；
     可勾「上传前脱敏」（敏感内容先遮盖再上传，回来只恢复外观贴图）。
4. 结果同时渲染正面/侧面预览图，直接显示在卡片里。

命令：
```bash
python fig.py model_edit 模型.glb --instruction "把泳圈改成红色" --edit-mode texture
python fig.py model_edit 模型.glb --instruction "去掉背后支架" --edit-mode rebuild [--meshy-desensitize]
```
⚠️ 依赖：Blender（渲染）、ComfyUI（Qwen 编辑）。贴图投影会自动判断竖直轴；若发现贴图左右反了，
说明模型正面朝 +Y（不是默认的 -Y），把模型转 180° 再导入即可。

## 八、常用排查

| 现象 | 处理 |
|---|---|
| 出图报 CUDA OOM | 关掉微信/QQ/Wallpaper/Broadcast/TourBox/Steam/Edge 等占显存的软件 |
| **出图突然变慢 10 倍** | Ollama 占着显存。`fig.py auto` 已自动处理；手动跑请给 Ollama 请求加 `keep_alive:0` 或 taskkill `llama-server.exe` |
| ComfyUI 启动后 8188 打不开 | 看命令行窗口报错；确认端口没被占用 |
| 3D 生成很慢/失败 | 降低 `--resolution` 到 2048、`--steps3d` 到 20 |
| 3D 结果很糊 | 输入图分辨率太低，或换纯色背景的正面全身图 |
| 提示词不生效 | Flux 用英文描述+逗号分隔；Pony 用 danbooru 标签式 |
| 3D 模型头发变平板 | 别用 `RemeshMesh(solid)`，改用 `--solidify` |
| 切片软件报非流形 | 必须加 `--solidify` 做体素重建 |
| 大脑把"水手服"翻成 swimsuit | 已内置词典+术语表修复；若仍错，`--brain qwen3:27b` |
| 大脑调用失败 | `ollama list` 确认模型在；会自动降级为纯词典翻译，不会中断流水线 |

---

## 九、安全提醒

Civitai / HuggingFace 的 API token 曾以明文发在对话里，建议用完后去各自平台**吊销重建**。
