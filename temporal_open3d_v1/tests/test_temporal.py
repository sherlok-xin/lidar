import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import temporal as ft
import probes


def snapshot(xyz, intensity=None):
    values=np.asarray(xyz,np.float32)
    return {"xyz":values,"intensity":np.ones(len(values)) if intensity is None else intensity}


class ObservationTests(unittest.TestCase):
    def setUp(self):
        generator=np.random.default_rng(18)
        self.frame=snapshot(generator.normal(.45,.08,(1200,3)))

    def test_identity_and_missing(self):
        obs=ft.Observation(self.frame)
        same=ft.histories(obs,obs.xyz,obs.intensity,[obs]*9)
        np.testing.assert_allclose(same["F0"][:,:4],0,atol=1e-9)
        self.assertTrue((same["F1"][:,0]==1).all())
        np.testing.assert_allclose(same["F1"][:,7],0)
        np.testing.assert_allclose(same["F4"][:,2],0)
        missing=ft.network_features(self.frame,[])
        self.assertEqual(missing.shape,(1200,8))
        self.assertFalse(missing.any())
        ob=ft.network_features(self.frame,[snapshot(self.frame["xyz"]+20)]*3)
        self.assertFalse(ob[:,-1].any())

    def test_feature_context_independent_of_supervised_queries(self):
        obs=ft.Observation(self.frame)
        hist=[ft.Observation(snapshot(self.frame["xyz"]-amount)) for amount in (.015,.009,.005)]
        ids=np.arange(0,len(obs.xyz),11)
        full=ft.histories(obs,obs.xyz,obs.intensity,hist)
        part=ft.histories(obs,obs.xyz[ids],obs.intensity[ids],hist)
        for key in ft.EXTRA:
            np.testing.assert_allclose(full[key][ids],part[key],atol=1e-6,err_msg=key)

    def test_direction_and_invalid_rotation(self):
        cur=np.eye(4)
        cur[:3,:3]=np.array([[0,-1,0],[1,0,0],[0,0,1]])
        cur[:3,3]=[1,0,0]
        hist=np.eye(4); hist[:3,3]=[1,2,0]
        transformed=ft.transfer([[3,4,0]],cur,hist)
        np.testing.assert_allclose(transformed,[[6,-3,0]],atol=1e-9)
        cur[:3,:3]=np.diag([-1,1,1])
        with self.assertRaises(ValueError):
            ft.transfer([[0,0,0]],cur,hist)

    def test_wrong_roles_and_label_bearing_history(self):
        center=dict(event="mine/A",domain="uchile",role="train",ordinal=9,history=[],temporal_status="T0")
        row=dict(center,ordinal=8)
        with self.assertRaises(ValueError):
            probes.observation_list([row],center,lambda *args,**kwargs:dict(self.frame,code=[1]))
        for invalid in (dict(row,role="val"),dict(row,event="other"),dict(row,ordinal=9)):
            with self.assertRaises(ValueError):
                probes.observation_list([invalid],center,lambda *args,**kwargs:self.frame)
        with self.assertRaises(ValueError):
            probes.restriction(dict(center,domain="follow"))

    def test_empty_and_fallback_original_indices(self):
        def mock(row,labels):
            result=dict(self.frame)
            result["xyz"]=result["xyz"].copy()
            result["xyz"][18]=np.nan
            result.update(valid=np.isfinite(result["xyz"]).all(1),original_index=5+2*np.arange(1200),
                          code=np.ones(1200,np.uint8),ref=np.full(1200,5))
            return result
        row={"event":"mine","uid":"test","domain":"uchile","role":"test","ordinal":0,"history":[]}
        receipt=probes.build(row,mock)
        weights={}
        for model in probes.BASE:
            width=sum(len(ft.GROUPS[g]) for g in ft.FAMILY[model])
            weights[model]={"mean":np.zeros(width),"deviation":np.ones(width),"weight":np.zeros(width),
                            "bias":np.array([0.3 if model=="S" else -1.4])}
        with tempfile.TemporaryDirectory() as temp:
            probes.score(row,receipt,weights,Path(temp),197)
            with np.load(Path(temp)/"scores/197/test.npz") as data:
                np.testing.assert_array_equal(data["score_S"],data["score_TF"])
                self.assertTrue(np.isnan(data["score_S"][18]))
                np.testing.assert_array_equal(data["original_index"],5+2*np.arange(1200))
                self.assertFalse(data["avail_TF"].any())


if __name__=="__main__":
    unittest.main()
