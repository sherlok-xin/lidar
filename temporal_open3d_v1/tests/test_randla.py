import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from randla_core import voxels, full_patches, full_predict, training_patch


class Constant(torch.nn.Module):
    def forward(self, inputs):
        return torch.zeros((*inputs["features"].shape[:2],2))


class Check(unittest.TestCase):
    def test_coverage_padding_and_projection(self):
        rng=np.random.default_rng(123)
        xyz=rng.normal(size=(5303,3))
        xyz[12]=np.nan
        current=dict(xyz=xyz,intensity=np.ones(len(xyz)),code=np.r_[0,1,2,np.zeros(5300)].astype(np.uint8),
                     valid=np.ones(len(xyz),bool))
        grid=voxels(current,None,.01)
        patches=list(full_patches(grid["points"],4096,rng))
        self.assertEqual(len(np.unique(np.concatenate(patches))),len(grid["points"]))
        raw,score=full_predict(Constant(),grid,len(xyz),np.zeros(1),np.ones(1),4096,25,"cpu")
        self.assertEqual(raw[12].sum(),0)
        self.assertTrue(np.isnan(score[12]))
        np.testing.assert_allclose(score[np.isfinite(score)],.5)
        self.assertLess(raw.sum(1).max(),1)

    def test_unknown_dust_mapping_and_no_duplicate_loss(self):
        cloud=dict(xyz=np.ones((3,3)),intensity=np.zeros(3),valid=np.ones(3,bool),code=np.zeros(3,np.uint8))
        frame=voxels(cloud,np.zeros((3,8)),1.)
        _,labels=training_patch(frame,4096,np.random.default_rng(22));self.assertFalse((labels>0).any())
        cloud["code"][:]=2
        frame=voxels(cloud,np.ones((3,8)),1.)
        ix,labels=training_patch(frame,4096,np.random.default_rng(23))
        self.assertEqual((labels==2).sum(),1)
        self.assertEqual(np.unique(ix).size,1)
        self.assertEqual(frame["feat"][0,-1],1)


if __name__=="__main__":
    unittest.main()
