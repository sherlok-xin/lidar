"""Pointwise display guard regression; no synthetic fixture is real material GT."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import unittest,json
import numpy as np
from run_d1_pointwise_guard import compute_guard,NEW_NAMES

class PointwiseDisplayGuardTests(unittest.TestCase):
 def test_missing_scan_spatial_and_hard_each_defer(self):
  c=np.ones(4,bool);scan=np.array([True,False,True,True]);spatial=np.array([True,True,False,True]);hard=np.array([False,False,False,True]);r=compute_guard(c,scan,spatial,hard,c)
  np.testing.assert_array_equal(r[NEW_NAMES[0]],[True,False,False,False]);np.testing.assert_array_equal(r[NEW_NAMES[1]],[False,True,True,True]);np.testing.assert_array_equal(r[NEW_NAMES[2]],[False,True,True,True])
 def test_candidate_partition_and_original_immutable(self):
  c=np.array([False,True,True]);strict=np.ones(3,bool);before=c.copy();r=compute_guard(c,np.ones(3,bool),np.array([True,False,True]),np.zeros(3,bool),strict)
  np.testing.assert_array_equal(c,before);np.testing.assert_array_equal(r[NEW_NAMES[0]]|r[NEW_NAMES[1]],c);self.assertFalse((r[NEW_NAMES[0]]&r[NEW_NAMES[1]]).any());self.assertTrue(np.all(r[NEW_NAMES[2]][r[NEW_NAMES[1]]]))
 def test_no_non_candidate_new_suppression(self):
  c=np.array([False,True,False]);strict=np.array([True,True,False]);r=compute_guard(c,np.ones(3,bool),np.ones(3,bool),np.zeros(3,bool),strict)
  self.assertFalse((r[NEW_NAMES[0]]&~c).any());self.assertTrue(r[NEW_NAMES[2]][0]);self.assertFalse(r[NEW_NAMES[2]][2])
 def test_actual143_ledger_matches_source_flags_and_required_deferrals(self):
  root=Path(__file__).resolve().parents[1]
  baseline=json.loads((root/'evidence/d1_candidate143_points.json').read_text())['points']
  actual=json.loads((root/'outputs/d1_pointwise_guard/candidate_slots.json').read_text())
  old={(r['key'],r['raw_slot_id']):r for r in baseline};new={(r['key'],r['raw_slot_id']):r for r in actual}
  self.assertEqual(set(old),set(new));self.assertEqual(len(new),143)
  for key,row in new.items():
   source=old[key]['d1_features'];self.assertEqual(row['scan_available'],source['geometry__scan_available']);self.assertEqual(row['spatial_available'],source['geometry__spatial_available'])
   expected=row['scan_available']and row['spatial_available']and not row['hard_protect'];self.assertEqual(row['suppressible'],expected);self.assertEqual(row['deferred'],not expected)
   if row['deferred']:self.assertTrue(row['guarded_display_retained'])
  self.assertEqual(sum(r['suppressible']for r in actual),108);self.assertEqual(sum(r['deferred']for r in actual),35)
  for key in [('seq245846',84249),('seq245858',84182)]:self.assertTrue(new[key]['deferred']);self.assertTrue(new[key]['guarded_display_retained'])
 def test_invalid_slot_domain_and_non_strict_candidate_rejected(self):
  with self.assertRaises(ValueError):compute_guard(np.ones(2,bool),np.ones(3,bool),np.ones(2,bool),np.zeros(2,bool),np.ones(2,bool))
  with self.assertRaises(ValueError):compute_guard(np.ones(2,bool),np.ones(2,bool),np.ones(2,bool),np.zeros(2,bool),np.zeros(2,bool))

if __name__=='__main__':unittest.main()
