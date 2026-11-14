# 二次元参考图转手办实拍：模型和流程调研

记录日期：2026-11-04。目标是生成**看起来像实体上色手办的图片**，不是生成可打印网格。效果与角色、姿态、遮挡、提示词、推理参数和所选模型均有关，以下技术并不保证角色与姿态完全一致。

## 流程选型

1. 输入准备：先挑清晰、完整的参考图。若源图是拍摄的亚克力立牌，周围桌面、立牌边缘、反光都被模型当作输入画面；裁切、透视校正或遮罩清理应在必要时单独进行，不应默认裁掉角色或更改比例。
2. 观察并确认：提取角色数、发型发色、服装颜色及部件、配饰、肢体位置、手脚遮挡、镜头与背景；识图只做可编辑参考，不确定项不得当作事实，用户核对。单张二维图对背面与遮挡部分没有完整证据。
3. 转换成实物风格：优先测试能直接接收参考图的编辑模型，指示只改呈现材质和照明（涂装树脂/PVC、实体模型表面、棚拍光照），尽量维持角色外观、镜头与构图。不要把“photo, 3d render”等选定目标一并放进负面词；不要把识图模型误判的动作当成硬性指令。
4. 复核：原图与结果并排看角色数、姿态与左右、手指及四肢、发色、服装与配件、材质及背景；任何偏差需要修正输入或重做。轮廓和姿势控制通常只能改善一致性，无法保证准确恢复被遮挡的解剖结构。
5. 展示图与图生模输入分开：前者以效果和光照为目标；后者可能需要更清楚的轮廓、简单背景、少遮挡、合适视角。单张复杂遮挡图不能凭空恢复不可见几何。

## 推荐：Qwen-Image-Edit-2509（待本机测试）

[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen-Image-Edit-2509) 说明该版本为图像编辑模型，声称改进角色/产品一致性、支持关键点和草图等图像条件；许可证标注 Apache 2.0。其能力描述属于模型作者信息，不构成本机效果保证。该编辑模型把图像用于语义和外观编辑；见 [ComfyUI 官方说明](https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit)。它**不是**目前 Ollama 中的 `qwen2.5vl:7b` 识图模型。

[Comfy-Org 发布的重打包权重目录](https://huggingface.co/Comfy-Org/Qwen-Image-Edit) 和 [Comfy-Org 官方 2509 工作流](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2509.json) 显示可用原生节点接入。至少需要：

| 文件 | 目录 | 标称大小 | 官方来源 |
| --- | --- | --- | --- |
| `qwen_image_edit_2509_fp8_e4m3fn.safetensors` | `ComfyUI/models/diffusion_models/` | 约 20.4 GB | [Comfy-Org 模型目录](https://huggingface.co/Comfy-Org/Qwen-Image-Edit/tree/main/split_files/diffusion_models) |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `ComfyUI/models/text_encoders/` | 约 9.38 GB | [Comfy-Org 编码器目录](https://huggingface.co/Comfy-Org/Qwen-Image/tree/main/split_files/text_encoders) |
| `qwen_image_vae.safetensors` | `ComfyUI/models/vae/` | 约 254 MB | [Comfy-Org VAE 目录](https://huggingface.co/Comfy-Org/Qwen-Image/tree/main/split_files/vae) |

大小按来源的十进制 GB/MB。仅上述三文件合计约 30 GB，未经证实能全部常驻本机 24 GB 显存；ComfyUI 可视情形卸载至系统内存，速度、峰值内存和有效质量应以实测为准。应使用已存在且校验完整的文件，下载中断文件不能冒充成功。

官方模板显示使用 `UNETLoader`、`CLIPLoader(type=qwen_image)`、`VAELoader` 与 `TextEncodeQwenImageEditPlus` 等节点；采样器及附加加速 LoRA 要跟随选定模板，并核验本机节点版本和模型路径，不应套用 Pony 的 `KSampler` 和否定词作为未经验证的等价替代。[官方模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2509.json)

## 结构控制与替代方案

[ControlNet 原始论文](https://arxiv.org/abs/2302.05543) 描述了边缘、深度、姿态等空间条件，可用于引导构图；检测器及模型都可能误判被遮挡的手脚。边缘条件尤其可能锁住原照片的亚克力边框和环境纹理。需选与基础模型架构匹配的控制模型，不能将 SDXL ControlNet 接到 Qwen 或 FLUX 并假设可用。

[Diffusers SDXL Canny 权重](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0) 标注 OpenRAIL++，其 fp16 safetensors 约 2.5 GB；它是 SDXL Canny 备选，是否能由当前 ComfyUI 加载及与现有 Pony 检查点兼容，需要单独测试。OpenRAIL++ 和各检查点许可证的使用限制应分别遵守。

[Anything2Real Alpha LoRA 作者卡](https://huggingface.co/lrzjason/QwenEdit-Anything2Real_Alpha) 将它描述为针对 Qwen-Image-Edit-2509 的插画到照片转换 LoRA，标注 Apache 2.0；作者说明这是有限数据训练的 alpha 版。它可能更偏向真人照片而非涂装手办，因此不作为默认项或保真保证。

## 本机已知边界

已有的 Pony img2img 是 VAE 编码加去噪，较低强度保留输入，较高强度可能改变轮廓；如果目标条件只描述画风而没有姿态约束，不能从文字稳定重建复杂姿态。当前检查发现 `models/controlnet` 和 `models/loras` 目录没有相关权重。以上为静态检查，安装与运行时结果仍需以本机实测为准。
