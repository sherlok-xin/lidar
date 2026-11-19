import csv,json,hashlib,os,sys,collections
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datahub import read_frame
root=Path(os.environ['DERIVED_ROOT']);raw=Path(os.environ['DATA_ROOT'])
out={}
for f in sorted(root.glob('sequences/bag*/frames.jsonl')):
 rows=list(map(json.loads,f.read_text().splitlines()))
 assert len(rows)==3 and np.all(np.diff([r['source_message_ordinal'] for r in rows])==1)
 stored=valid=0
 for row in rows:
  for key in ('bag_record_stamp_ns','header_stamp_ns'):
   assert isinstance(row[key],str) and row[key].isdigit()
  complete=read_frame(row,data_root=raw,derived_root=root,valid_only=False)
  sliced=read_frame(row,data_root=raw,derived_root=root)
  ix=complete['source_point_index'];mask=complete['valid_mask']
  assert ix.dtype.kind in 'ui' and len(set(ix.tolist()))==len(ix)
  assert len(mask)==row['point_count_stored'] and int(mask.sum())==row['point_count_valid']
  np.testing.assert_array_equal(sliced['source_point_index'],ix[mask])
  np.testing.assert_array_equal(sliced['xyz'],complete['xyz'][mask])
  assert np.isfinite(sliced['xyz']).all() and not sliced['supervision_mask'].any()
  stored+=len(ix);valid+=int(mask.sum())
 out[f.parent.name.split('_')[1]]=dict(stored=stored,valid=valid,frames=len(rows),ordinals=[r['source_message_ordinal'] for r in rows],unlabeled=True)
print(json.dumps(out,indent=2))
