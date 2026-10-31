"""Integration regressions; fixtures are not experimental/semantic GT."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opdf.cloud_schema import FrameData
from opdf.pipeline import process_frame
from opdf import ground_lite, optical, geometry, decision


def frame_fixture(height=80, width=4, *, all_invalid=False, unavailable=False):
    n = height * width
    xyz = np.zeros((n, 3), np.float32)
    if n:
        xyz[:, 0] = np.tile(np.linspace(1, 2, width), height)
        xyz[:, 1] = np.linspace(-1, 1, n)
        xyz[:, 2] = -1.
    if all_invalid:
        xyz[:] = np.nan
    raw = np.zeros((n, 8), '<f4'); raw[:, :3] = xyz; raw[:, 4] = 5
    return FrameData(xyz=xyz, intensity=np.full(n, 5., np.float32),
        valid_xyz_mask=np.isfinite(xyz).all(1), raw_slot_id=np.arange(n,dtype=np.uint64),
        height=height,width=width,point_step=32,row_step=width*32,
        header_stamp_ns=123,record_stamp_ns=124,frame_id='fixture',source_bag='SYNTHETIC',
        source_record_locator={},mapping_version='UNAVAILABLE-test' if unavailable else 'fixture-layout',
        source_fingerprint={},field_schema=[],is_bigendian=False,is_dense=False,
        raw_data=raw.tobytes(),phase_order=np.arange(height,dtype=np.int64),
        column_coverage_mask=np.ones(width,bool))


def cfg():
    return {'ground':ground_lite.DEFAULT_CONFIG.copy(),'optical':optical.DEFAULT_CONFIG.copy(),
            'geometry':geometry.DEFAULT_CONFIG.copy(),'decision':decision.DEFAULT_CONFIG.copy(),
            'temporal':{'enabled':False}}


class PipelineRegressions(unittest.TestCase):
    def test_empty_and_all_invalid_abstain_without_fake_points(self):
        for f in (frame_fixture(width=0),frame_fixture(all_invalid=True)):
            r=process_frame(f,cfg())
            self.assertEqual(r['diagnostics']['status'],'ABSTAIN')
            self.assertFalse(np.any(r['arrays']['aerosol_candidate_mask']))
            self.assertEqual(len(r['arrays']['raw_slot_id']),len(f.xyz))

    def test_unavailable_or_wrong_height_retains_unknown(self):
        for f in (frame_fixture(height=2),frame_fixture(unavailable=True)):
            r=process_frame(f,cfg())
            self.assertEqual(r['diagnostics']['status'],'ABSTAIN')
            self.assertTrue(np.all(r['arrays']['labels'][f.valid_xyz_mask]==3))

    def test_temporal_request_falls_back_exactly_to_single_frame(self):
        f=frame_fixture();c=cfg();r0=process_frame(f,c)
        c['temporal']['enabled']=True;r1=process_frame(f,c)
        self.assertEqual(r1['diagnostics']['status'],'OK')
        self.assertFalse(r1['diagnostics']['m4']['available'])
        self.assertIn('M4_REQUESTED_BUT_UNAVAILABLE_SINGLE_FRAME_FALLBACK',r1['diagnostics']['quality_alerts'])
        np.testing.assert_array_equal(r0['arrays']['labels'],r1['arrays']['labels'])
        np.testing.assert_allclose(r0['arrays']['score_a'],r1['arrays']['score_a'],equal_nan=True)

    def test_module_failure_is_error_and_retains_valid_not_empty_success(self):
        f=frame_fixture()
        with patch('opdf.ground_lite.compute',side_effect=RuntimeError('fixture failure')):
            r=process_frame(f,cfg())
        self.assertEqual(r['diagnostics']['status'],'ERROR')
        self.assertIn('fixture failure',r['diagnostics']['error'])
        self.assertTrue(np.all(r['arrays']['retain_solid_mask']))
        self.assertTrue(np.all(r['arrays']['labels']==3))

    def test_invalid_ablation_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            process_frame(frame_fixture(),cfg(),ablation='unknown')


if __name__=='__main__':
    unittest.main()
