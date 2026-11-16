import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import completion as c


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.source=self.root/'source.png'
        pixels=np.zeros((96,128,3),dtype='uint8')
        pixels[:]=[120,170,210];pixels[20:60,30:80]=[210,90,30]
        Image.fromarray(pixels).save(self.source)
        self.data=dict(version=1,source=str(self.source),source_size=[128,96],
            padding=dict(left=32,right=0,top=16,bottom=0),joints={'neck':[40,30],'left_shoulder':[65,35]},
            strokes=[],hair=[dict(width=3,points=[[-10,15],[20,25]])],instruction='Extend the illustrated hair.',overlap=8,feather=3)

    def tearDown(self): self.temp.cleanup()

    def layers(self,data=None):
        p,im=c.validate_project(data or self.data)
        return p,im,c.make_layers(p,im)

    def test_native_coordinates_and_source_protection(self):
        p,im,layers=self.layers();self.assertEqual(layers['canvas'].size,(160,112))
        self.assertEqual(layers['mask'].getpixel((0,0)),255)
        self.assertEqual(layers['mask'].getpixel((32+40,16+40)),0)
        np.testing.assert_array_equal(np.asarray(layers['canvas'])[16:112,32:160],np.asarray(im))
        generated=Image.new('RGB',layers['canvas'].size,'red')
        result=Image.composite(generated,layers['canvas'],layers['mask'])
        protected=np.asarray(layers['mask'])==0
        np.testing.assert_array_equal(np.asarray(result)[protected],np.asarray(layers['canvas'])[protected])

    def test_erase_protects_and_feather_never_leaks(self):
        data=copy.deepcopy(self.data)
        data['strokes']=[dict(width=12,points=[[-10,40]],action='erase')]
        p,im,layers=self.layers(data)
        self.assertEqual(layers['mask'].getpixel((22,56)),255)
        self.assertEqual(layers['mask'].getpixel((32+80,16+60)),0)

    def test_guides_are_separate_from_source_and_mask(self):
        p,im,layers=self.layers();data=copy.deepcopy(self.data);data['joints']={};data['hair']=[]
        _,_,plain=self.layers(data)
        np.testing.assert_array_equal(np.asarray(layers['canvas']),np.asarray(plain['canvas']))
        np.testing.assert_array_equal(np.asarray(layers['mask']),np.asarray(plain['mask']))
        self.assertFalse(np.array_equal(np.asarray(layers['guide']),np.asarray(plain['guide'])))
        self.assertNotEqual(layers['pose'].getbbox(),None)
        self.assertEqual(layers['guide'].getpixel((22,31)),(255,255,255))

    def test_drawing_guides_alone_does_not_edit(self):
        data=copy.deepcopy(self.data);data['padding']={};data['hair']=[]
        with self.assertRaisesRegex(ValueError,'修改'): self.layers(data)

    def test_transparent_extension_saved_and_fully_selected(self):
        p,im,layers=self.layers()
        rgba=np.asarray(layers['expanded'])
        alpha=rgba[:,:,3]
        self.assertEqual(layers['expanded'].mode,'RGBA')
        self.assertTrue((alpha[:16]==0).all())
        self.assertTrue((alpha[16:,:32]==0).all())
        self.assertTrue((alpha[16:,32:]==255).all())
        self.assertTrue((np.asarray(layers['mask'])[alpha==0]==255).all())
        np.testing.assert_array_equal(rgba[16:,32:,:3],np.asarray(im))
        path,*_=c.prepare(self.data,self.root/'transparent-project')
        with Image.open(path.parent/'expanded.png') as saved:
            self.assertEqual(saved.mode,'RGBA')
            np.testing.assert_array_equal(np.asarray(saved),rgba)

    def test_default_only_transparency_is_selected(self):
        data=copy.deepcopy(self.data);data.pop('overlap')
        p,im,layers=self.layers(data)
        mask=np.asarray(layers['mask']);alpha=np.asarray(layers['expanded'])[:,:,3]
        self.assertEqual(p['overlap'],0)
        self.assertTrue((mask[alpha==255]==0).all())
        self.assertTrue((mask[alpha==0]==255).all())

    def test_rejects_stale_and_invalid_coordinates(self):
        for edit in [{'source_size':[1,1]},{'joints':{'neck':[float('nan'),4]}},
                     {'joints':{'neck':[-100,4]}},{'padding':{'left':-1}},{'seed':1.25},
                     {'megapixels':float('inf')},{'locked':['bad_joint']}]:
            data={**copy.deepcopy(self.data),**edit}
            with self.assertRaises(ValueError): c.validate_project(data)

    def test_roundtrip_records_hash_and_original_unchanged(self):
        before=self.source.read_bytes()
        path,p,im,layers=c.prepare(self.data,self.root/'project')
        loaded=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(loaded['source_sha256']),64)
        restored,_=c.validate_project(loaded)
        self.assertEqual(restored['joints'],p['joints'])
        self.assertEqual(before,self.source.read_bytes())
        self.assertTrue((path.parent/'pose.png').is_file())
        Image.new('RGB',(128,96),'green').save(self.source)
        with self.assertRaisesRegex(ValueError,'内容已改变'): c.validate_project(loaded)

    def test_workflows_connect_real_mask_and_controls(self):
        p,im,_=self.layers()
        names={k:k+'.png' for k in ['canvas','mask','guide','original','pose','lines']}
        names.update(width=512,height=512)
        wf=c.build_workflow(p,names,12,'smoke')
        self.assertEqual(wf['sample']['inputs']['latent_image'],['masked_latent',0])
        self.assertEqual(wf['positive']['inputs']['image2'],['ref2',0])
        self.assertNotIn('image3',wf['positive']['inputs'])
        p['instruction']='purple coat, follow the magenta outline'
        guided=c.build_workflow(p,names,12,'smoke')['positive']['inputs']['prompt']
        self.assertIn('purple coat',guided)
        self.assertIn('white outline',guided)
        self.assertNotIn('magenta outline',guided)
        p['engine']='sdxl';wf=c.build_workflow(p,names,12,'smoke')
        self.assertEqual(wf['5a']['class_type'],'VAEEncodeForInpaint')
        self.assertEqual(wf['pose_loader']['inputs']['control_net_name'],c.POSE_MODEL)
        self.assertEqual(wf['lines_apply']['inputs']['positive'],['pose_apply',0])
        self.assertEqual(wf['3']['inputs']['positive'],['lines_apply',0])

    def test_context_crop_contains_every_editable_pixel(self):
        mask=Image.new('L',(1000,1600))
        mask.paste(255,(400,0,600,100))
        crop=c.context_crop(mask)
        self.assertEqual(crop,(272,0,728,228))
        self.assertEqual(mask.crop(crop).getbbox(),(128,0,328,100))
        self.assertEqual(c.context_crop(Image.new('L',(100,100),255)),(0,0,100,100))

    def test_qwen_reference_and_sampling_dimensions_match(self):
        import math
        for size in [(512,388),(512,752),(3496,3100),(128,96),(8192,600)]:
            w,h=c.sampling_size(size,'qwen',.5)
            ratio=math.sqrt(1024*1024/(w*h))
            self.assertEqual((w,h),(round(w*ratio/8)*8,round(h*ratio/8)*8))
            self.assertEqual((w,h),c.sampling_size(size,'qwen',1.5))
        self.assertEqual(c.sampling_size((512,388),'sdxl',.5),(512,384))


if __name__=='__main__': unittest.main(verbosity=2)
