import argparse
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image, ImageOps


def restore(model_path, image_path, output_path):
    source = trimesh.load(model_path, force='scene', process=False)
    meshes = source.to_mesh()
    if not isinstance(meshes, trimesh.Trimesh) or len(meshes.faces) == 0:
        raise ValueError('模型没有可用三角网格')
    if not np.isfinite(meshes.vertices).all():
        raise ValueError('模型包含无效顶点')
    x, z = meshes.vertices[:, 0], meshes.vertices[:, 2]
    if np.ptp(x) < 1e-9 or np.ptp(z) < 1e-9:
        raise ValueError('正面 X/Z 投影范围为零，无法投影；请先将模型竖直放置')
    uv = np.column_stack(((x-x.min())/np.ptp(x), (z-z.min())/np.ptp(z)))
    with Image.open(image_path) as img:
        texture = ImageOps.exif_transpose(img).convert('RGBA')
        texture.load()
    meshes.visual = trimesh.visual.texture.TextureVisuals(uv=uv, image=texture)
    output = Path(output_path)
    if output.exists():
        raise FileExistsError('输出文件已存在，拒绝覆盖: '+str(output))
    data = meshes.export(file_type='glb')
    with output.open('xb') as f:
        f.write(data)
    check = trimesh.load(str(output), force='scene', process=False)
    if not check.geometry or not any(getattr(g.visual, 'uv', None) is not None for g in check.geometry.values()):
        raise ValueError('输出校验失败：未检测到纹理坐标')
    print('输出:', output)
    print('顶点:', len(meshes.vertices), '三角面:', len(meshes.faces))
    print('完成正面投影。背面和侧面为拉伸投影，未恢复缺失几何；请检查模型朝向及对齐。')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('model')
    ap.add_argument('image')
    ap.add_argument('output')
    args = ap.parse_args()
    restore(args.model, args.image, args.output)
