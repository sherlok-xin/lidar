import unittest,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate import op,ranking,risk

class Eval(unittest.TestCase):
    def test_tied_budget_and_missing(self):
        c=np.r_[np.ones(200),np.full(10,2),0];r=np.r_[np.ones(100),np.full(100,2),np.full(10,3),0];s=np.r_[np.full(200,.1),np.full(10,.81),.99];fid=np.arange(len(c))%4
        p,_=risk(c,r,s,fid);self.assertEqual(p['threshold'],.81);self.assertEqual(op(c,r,s,.81)['ignore_candidates'],1)
        s[:2]=.81;p,_=risk(c,r,s,fid);self.assertEqual(p['status'],'UNAVAILABLE');self.assertEqual(p['maximum_budget_recall'],0)
        o=op(np.array([1,2,0,1]),np.array([1,3,0,2]),np.array([np.nan,.7,.98,.2]),.5);self.assertEqual((o['tn'],o['person_den'],o['vehicle_den'],o['ignore_candidates']),(1,0,1,1))
    def test_rank_missing_and_empty(self):
        self.assertEqual(ranking(np.array([1,0]),np.array([.1,.99])),(None,None));ap,tr=ranking(np.array([2,1,2,0]),np.array([.4,.9,.4,.8]));self.assertNotEqual(ap,tr);self.assertAlmostEqual(ap,2/3)
if __name__=='__main__':unittest.main()
