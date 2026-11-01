"""V1-C debug export regression; synthetic payloads are not scene truth."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json,unittest
import numpy as np
from opdf_c.sequence_io import CROOT,TOPICS,FIELDS,STAGE2,PALETTE,derived_points,inside

def fixture():
 n=6;xyz=np.arange(n*3,dtype=np.float32).reshape(n,3);xyz[0]=np.nan
 a={'xyz':xyz,'intensity':np.arange(n,dtype=np.float32),'labels':np.array([0,1,2,3,4,3],np.uint8),'valid_xyz_mask':np.array([False,True,True,True,True,True]),'raw_slot_id':np.arange(n,dtype=np.uint64)}
 for score,av in STAGE2.values():a[score]=np.array([np.nan,0,.25,.5,.75,1],np.float32);a[av]=np.array([False,True,False,True,True,True])
 return a

class SequencePayloadTests(unittest.TestCase):
 def test_entity_only_and_retained_are_distinct_exact_subsets(self):
  a=fixture();np.testing.assert_array_equal(derived_points(a,'entity_only')['raw_slot_id'],[1]);np.testing.assert_array_equal(derived_points(a,'retained')['raw_slot_id'],[1,3,5])
 def test_all_primary_subset_semantics(self):
  a=fixture();expected={'nonground':[1,2,3,5],'class_rgb':[1,2,3,4,5],'aerosol_strong':[2],'unknown':[3,5],'ground':[4]}
  for name,slots in expected.items():
   with self.subTest(layer=name):np.testing.assert_array_equal(derived_points(a,name)['raw_slot_id'],slots)
 def test_derived_layout_xyz_intensity_rgb_bits_and_raw_slots(self):
  a=fixture();p=derived_points(a,'class_rgb');self.assertEqual(p.dtype.itemsize,24);self.assertEqual(p.dtype.fields['raw_slot_id'][1],20)
  np.testing.assert_array_equal(np.column_stack([p[k]for k in ('x','y','z')]),a['xyz'][1:]);np.testing.assert_array_equal(p['intensity'],a['intensity'][1:])
  for row,label in zip(p,a['labels'][1:]):
   r,g,b=PALETTE[int(label)];self.assertEqual(int(row['rgb_bits']),(r<<16)|(g<<8)|b)
 def test_heatmap_unavailable_gray_and_real_xyz(self):
  a=fixture()
  for name in STAGE2:
   p=derived_points(a,name);np.testing.assert_array_equal(p['raw_slot_id'],[1,2,3,4,5]);self.assertEqual(int(p['rgb_bits'][1]),0x646464);np.testing.assert_array_equal(p['x'],a['xyz'][1:,0]);self.assertEqual(int(p['rgb_bits'][-1]),0xFF0000)
 def test_empty_aerosol_produces_zero_points(self):
  a=fixture();a['labels'][2]=3;p=derived_points(a,'aerosol_strong');self.assertEqual(p.shape,(0,));self.assertEqual(p.tobytes(),b'')
 def test_slot_overflow_rejected(self):
  a=fixture();a['raw_slot_id'][1]=2**32
  with self.assertRaises(ValueError):derived_points(a,'entity_only')
 def test_white_list_has_no_control_or_solid_topic(self):
  self.assertEqual(len(TOPICS),11);self.assertEqual(len(set(TOPICS)),11);self.assertFalse(any('solid'in x for x in TOPICS));self.assertEqual([f['offset']for f in FIELDS],[0,4,8,12,16,20])
 def test_write_scope_guard(self):
  self.assertEqual(inside(CROOT/'outputs'),CROOT/'outputs')
  with self.assertRaises(ValueError):inside(CROOT.parent/'outputs')

class RealSelectedManifestTests(unittest.TestCase):
 def test_real_thirty_contiguous_manifest(self):
  m=json.loads((CROOT/'samples/continuous30/manifest.json').read_text());rows=m['frames'];self.assertEqual(m['status'],'COMPLETE');self.assertEqual(len(rows),30);self.assertLessEqual(m['actual_bytes_read'],m['max_read_bytes']);self.assertTrue(m['source_stat_unchanged'])
  for x,y in zip(rows,rows[1:]):self.assertEqual(y['seq'],x['seq']+1);self.assertGreater(y['header_stamp_ns'],x['header_stamp_ns']);self.assertGreater(y['record_stamp_ns'],x['record_stamp_ns'])
  self.assertTrue(all(r['height']==80 for r in rows));self.assertEqual(rows[0]['seq'],245832);self.assertEqual(rows[-1]['seq'],245861)

if __name__=='__main__':unittest.main()
