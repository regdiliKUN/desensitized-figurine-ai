# 脱敏手办 AI 工作流 · Desensitized Figurine AI Workflow

本地二次元手办生成 + **脱敏过审**工作流。一句话中文描述 → 本地大脑写提示词 → 出图 → 图生 3D → 可切片的水密模型；并内置一条「脱敏过审」分支：敏感原图 → 自动脱敏 → 过 Meshy 等建模 AI 审核 → 生成手办模型 → 还原回敏感样子。

> 全部组件跑在本地，**不依赖任何云端审核**，输出内容不受平台限制。

---

## 一、特性

- **全本地部署**：ComfyUI（Pony / Flux 出图）+ Hunyuan3D（图生 3D）+ Ollama（文本大脑），离线运行
- **一键启动器**：运行 `一键启动.bat`，启动 ComfyUI 和本地控制中心
- **图生图 img2img**：参考图 + 提示词重绘，强度可调（`--strength`）
- **手板制作增强**：自动扶正、加底座、抽壳、水密/尺寸/朝向诊断
- **脱敏过审工作流**：肤色检测 → 区域分级遮挡 → 输出可过审版本；配套 `restore` 把去敏化模型还原成敏感样子
- **控制中心**：通过本地服务操作出图、图生图、图生 3D、打印转换、打开文件夹和环境自检；脱敏和还原按钮尚未接入

---

## 二、环境要求

| 项目 | 说明 |
|------|------|
| 系统 | Windows 10 / 11 |
| GPU | NVIDIA，推荐 ≥ 16GB 显存（RTX 4090 24GB 实测流畅） |
| Python | 3.12+（ComfyUI 自带 venv） |
| 本地模型 | **本仓库不含模型权重**（约 31GB），需自行下载到 `ComfyUI/models` |
| 文本大脑 | Ollama + `dolphin-mixtral` / `qwen3:27b` 等本地模型 |

> 出图 / 出 3D 前请关闭占显存的软件（微信、QQ、Wallpaper Engine、Steam 等），24GB 显存里它们能占掉 20GB。

---

## 三、目录结构（本仓库）

```
E:\AI\
├── control_server.py       ← 本机控制服务（执行任务、文件选择、实时日志）
├── 启动器.html             ← 控制中心（浏览器界面）
├── 项目简报.html           ← 完整功能与设计记录
├── fig.py                  ← ★★ 统一入口（出图/图生3D/转换/脱敏/还原/自检）
├── convert_3d.py           ← GLB → OBJ/STL/3MF/PLY + 水密化 + 手板增强
├── launcher_exe.py         ← 一键启动器源码（PyInstaller 构建用）
├── 手办AI启动器.ico        ← PIL 程序化生成的手办主题图标
├── 一键启动.bat            ← 启动 ComfyUI 和控制中心
├── 启动ComfyUI.bat         ← 单独启动 ComfyUI 服务的 bat
├── .gitignore              ← 排除 ComfyUI/、模型、EXE、venv 等
└── README.md               ← 本文件
```

> `ComfyUI/` 目录（31GB 模型 + venv）和 `手办AI.exe`（33MB 二进制）已被 `.gitignore` 排除，不包含在本仓库中。

---

## 四、fig.py 命令速查

### 4.1 全自动流水线

```bash
python fig.py auto "银发红眼的少女，穿泳装，站在沙滩上"
```

一句话中文 → Ollama 翻译提示词 → ComfyUI 出图 → 背景检测 → Hunyuan3D 图生 3D → 平坦化 → 导出 GLB。

### 4.2 单步操作

| 子命令 | 用途 | 示例 |
|--------|------|------|
| `img` | 仅出图（txt2img） | `fig.py img "1girl, red eyes, swimsuit" --model pony` |
| `i2i` | 图生图（img2img） | `fig.py i2i "参考图.png" "1girl, swimsuit, beach" --strength 0.7` |
| `model` | 仅图生 3D | `fig.py model "output/img_001.png"` |
| `print` | GLB → 打印格式 | `fig.py print "model.glb" --height 100 --base 0.03 --hollow 0.4` |
| `desensitize` | 图像脱敏过审 | `fig.py desensitize "敏感图.png" --strength auto` |
| `restore` | 还原脱敏模型 | `fig.py restore "model.glb" --original "原图.png"` |
| `check` | 环境自检 | `fig.py check` |
| `serve` | 启动交互模式 | `fig.py serve` |

### 4.3 img2img 强度指南

| `--strength` | 效果 |
|--------------|------|
| `1.0` | 完全重画（几乎不保留原图） |
| `0.7` | 大幅修改但保留构图（**默认推荐**） |
| `0.5` | 适度修改，保留大部分细节 |
| `0.3` | 轻微调整（换颜色/小细节） |

### 4.4 脱敏过审工作流

```
敏感原图 ──fig.py desensitize──→ 脱敏版（可过 Meshy 审核）
                                      │
                                      ▼
                              Meshy / 建模 AI 生成 3D 模型
                                      │
                                      ▼
                              fig.py restore 还原纹理
                                      │
                                      ▼
                                  敏感样子手办模型
```

- **肤色检测**：HSV + YCbCr 双判据 + 二次元肤色扩展（浅粉/米白/小麦色）
- **区域分级**：按身体纵向比例分胸/腰/腹（高风险）和四肢（低风险）
- **遮挡方式**：马赛克 + 服装色覆盖，边缘柔化过渡
- **三档强度**：`auto`（自动）/ `full`（全覆盖）/ `minimal`（仅高风险区）

---

## 五、手板制作增强（convert_3d.py）

| 功能 | 参数 | 说明 |
|------|------|------|
| 自动扶正 | `--orient`（默认开） | 检测模型最长轴，旋转对齐到 Z 轴竖立 |
| 加底座 | `--base 0.03`（默认开） | 底部生成圆柱底座，厚度比例可调 |
| 抽壳 | `--hollow 0.4`（默认开） | 向内偏移生成内壳 + 翻转法线 + 底部开孔 |
| 诊断 | `--diagnose`（默认开） | 水密/尺寸/朝向/底面/锐边诊断报告 |

```bash
python fig.py print "model.glb" --height 100 --base 0.03 --hollow 0.4
```

---

## 六、一键启动器

### 使用方式

双击 `E:\AI\一键启动.bat`。启动器会检测并启动 ComfyUI，然后启动仅监听本机的控制服务并打开浏览器。可以创建指向该批处理文件的桌面快捷方式。

请使用启动器打开控制中心，直接双击 `启动器.html` 无法运行本地任务或打开文件夹。控制中心的去敏感化、还原 3D 按钮尚未接入；`launcher_exe.py` 是旧版启动器源码，不能启动新的控制服务。

出图和图生图目前使用英文提示词；完整一键生成支持中文描述，并依赖本地 Ollama、出图和 3D 模型。打印转换的默认成品目录为 `I:\AI\最终成品`，部署到其他路径时需调整脚本中的路径。

---

## 七、本地部署指南

### 7.1 安装 ComfyUI

```bash
cd E:\AI
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 7.2 下载模型

将以下模型放到 `ComfyUI/models/checkpoints/` 或 `ComfyUI/models/unet/`：

- **Pony Diffusion V6 XL** — 二次元出图主力模型
- **Flux.1-dev** — 高质量出图（可选）
- 各自配套的 VAE、CLIP 文本编码器

### 7.3 安装 Ollama

```bash
# 从 ollama.com 下载安装
ollama pull dolphin-mixtral
# 或
ollama pull qwen3:27b
```

### 7.4 安装 Hunyuan3D

参照 [Hunny3D](https://github.com/Tencent/Hunyuan3D-2) 官方仓库安装到 `E:\AI\ComfyUI\custom_nodes\` 下。

---

## 八、License

本仓库的原创代码与文档采用 [MIT 许可证](LICENSE)。

ComfyUI、Hunyuan3D、Ollama、Pony Diffusion 及其他第三方软件和模型权重仍适用各自的原始许可证。

---

## 九、致谢

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) — 节点式图像生成界面
- [Hunyuan3D-2](https://github.com/Tencent/Hunyuan3D-2) — 腾讯图生 3D 模型
- [Ollama](https://ollama.com) — 本地 LLM 运行时
- Pony Diffusion V6 XL — 二次元扩散模型
