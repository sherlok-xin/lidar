import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rviz_review as review


class DisplayMasks(unittest.TestCase):
    def test_indices_and_errors(self):
        case={"valid":np.array([1,1,1,0],bool),"xyz":np.array([[0,1,2],[2,3,4],[3,4,5],[np.nan,2,7]]),
              "original_index":np.array([17,291,982,1811]),"intensity":np.arange(4),"ref":np.array([1,3,4,1]),
              "code":np.array([1,2,0,0]),"features":np.zeros((4,8)),"available":np.array([1,0,0,0],bool),
              "module_available":np.array([[0,1,0],[0,0,0],[0,0,0],[0,0,0]],bool),
              "score_S":np.array([.99,.02,.99,np.nan]),"score_TF":np.array([.2,.02,.99,np.nan]),
              "history_xyz":np.array([[1,2,3]]),"history_intensity":np.array([7]),
              "history_index":np.array([876]),"history_lag":np.array([2])}
        cloud=review.clouds(case)
        np.testing.assert_array_equal(cloud["raw"]["original_index"],[17,291,982])
        np.testing.assert_array_equal(cloud["single_error"]["original_index"],[17,291])
        np.testing.assert_array_equal(cloud["temporal_error"]["original_index"],[291])
        np.testing.assert_array_equal(cloud["unavailable"]["original_index"],[291,982])
        np.testing.assert_array_equal(cloud["stable_core"]["original_index"],[17])
        self.assertEqual(len(cloud["smoothing_gain"]),0)
        self.assertTrue(np.isnan(cloud["past_context"]["score_s"][0]))
        self.assertEqual(int(cloud["past_context"]["original_index"][0]),876)
        self.assertEqual(int(cloud["past_context"]["history_lag"][0]),2)


if __name__=="__main__":
    unittest.main()
