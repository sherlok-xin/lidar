"""Synthetic safety counterexamples, not measured semantic accuracy or GT."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
import numpy as np
from opdf.cloud_schema import FrameData
from opdf import ground_lite, optical, geometry, decision


def frame_from_image(image, intensity=20.0, coverage=None):
    image = np.asarray(image, dtype=np.float64)
    h, w = image.shape[:2]
    xyz = image.transpose(1, 0, 2).reshape(-1, 3).copy()
    if np.isscalar(intensity):
        values = np.full(h * w, intensity, np.float64)
    else:
        values = np.asarray(intensity, np.float64).T.reshape(-1).copy()
    packed = np.zeros((h * w, 32), np.uint8)
    for k in range(3):
        packed[:, 4 * k:4 * k + 4] = xyz[:, k].astype('<f4').view(np.uint8).reshape(-1, 4)
    packed[:, 16:20] = values.astype('<f4').view(np.uint8).reshape(-1, 4)
    return FrameData(xyz=xyz, intensity=values, valid_xyz_mask=np.isfinite(xyz).all(axis=1),
                     raw_slot_id=np.arange(h*w, dtype=np.uint64), height=h, width=w,
                     point_step=32, row_step=w*32, header_stamp_ns=1, record_stamp_ns=1,
                     frame_id='SYNTHETIC', source_bag='SYNTHETIC_NOT_REAL_BAG',
                     source_record_locator={}, mapping_version='synthetic-test-only',
                     source_fingerprint={}, field_schema=[], is_bigendian=False,
                     is_dense=False, raw_data=packed.tobytes(), phase_order=np.arange(h),
                     column_coverage_mask=np.ones(w, bool) if coverage is None else np.asarray(coverage, bool))


def shell(h=80, w=31, ranges=10.0, intensity=20.0):
    elevation = np.radians(np.linspace(-15, 15, h))[:, None]
    azimuth = np.radians(np.arange(w) * 0.2)[None, :]
    r = np.broadcast_to(np.asarray(ranges), (h, w))
    xyz = np.stack(np.broadcast_arrays(r*np.cos(elevation)*np.cos(azimuth),
                                        r*np.cos(elevation)*np.sin(azimuth),
                                        r*np.sin(elevation)), axis=-1)
    return frame_from_image(xyz, intensity)


def plane_image(*, quadrant_only=False, slope=0.0, bump=False):
    xy = np.linspace(1, 16, 64) if quadrant_only else np.linspace(-15, 15, 64)
    x, y = np.meshgrid(xy, xy)
    z = -1.5 + slope*x
    mask = (x > 4.0) & (x < 4.7) & (y > 4.0) & (y < 4.7)
    if bump:
        z[mask] += 0.15
    return np.stack((x, y, z), axis=-1), mask


def available_ground(frame):
    """Inject a reliable reference for isolated decision-gate counterexamples."""
    n = len(frame.xyz)
    return {'arrays': {'ground_available': np.ones(n, bool),
                       'ground_mask': np.zeros(n, bool),
                       'low_object_mask': np.zeros(n, bool),
                       'near_ground_mask': np.zeros(n, bool)}, 'diagnostics': {}}


def injected_aerosol_evidence(frame):
    """Construct an otherwise admissible multi-evidence case, then remove one cause."""
    n = len(frame.xyz)
    opt = {'arrays': {'optical_available': np.ones(n, bool), 'optical_weak_score': np.ones(n)}}
    geo = {'arrays': {'scan_available': np.ones(n, bool),
                       'spatial_available': np.ones(n, bool),
                       'scan_surface_score': np.zeros(n),
                       'scan_discontinuity_score': np.ones(n),
                       'spatial_surface_score': np.zeros(n),
                       'spatial_diffuse_score': np.ones(n),
                       'edge_protect_mask': np.zeros(n, bool)}}
    return opt, geo


class AlgorithmSafetyTests(unittest.TestCase):
    def test_low_intensity_solid_shell_not_aerosol(self):
        # Real feature computations: a dark angularly continuous surface must not
        # be deleted just because its sensor intensity is zero.
        f = shell(intensity=0.0)
        opt, geo = optical.compute(f, {}), geometry.compute(f, {})
        self.assertGreater(int(opt['arrays']['optical_available'].sum()), 0)
        self.assertGreater(int(geo['arrays']['spatial_available'].sum()), 0)
        labels = decision.classify(f, available_ground(f), opt, geo, {})['arrays']['labels']
        self.assertFalse(np.any(labels == decision.A))
        self.assertTrue(np.all(np.isin(labels, [decision.E, decision.U])))

    def test_relative_dim_outlier_still_cannot_override_solid_geometry(self):
        intensity = np.full((80, 31), 30.0)
        intensity[40, 15] = 0.0
        f = shell(intensity=intensity)
        opt, geo = optical.compute(f, {}), geometry.compute(f, {})
        slot = 15*80 + 40
        self.assertGreaterEqual(float(opt['arrays']['optical_weak_score'][slot]), 0.55)
        result = decision.classify(f, available_ground(f), opt, geo, {})
        self.assertNotEqual(result['arrays']['labels'][slot], decision.A)

    def test_each_required_evidence_is_needed_for_aerosol(self):
        f = shell(h=1, w=2)
        ground = available_ground(f)
        opt, geo = injected_aerosol_evidence(f)
        self.assertTrue(np.all(decision.classify(f, ground, opt, geo, {})['arrays']['labels'] == decision.A))
        for container_name, key in [('optical', 'optical_available'),
                                    ('geometry', 'scan_available'), ('geometry', 'spatial_available')]:
            with self.subTest(missing=key):
                oo, gg = injected_aerosol_evidence(f)
                (oo if container_name == 'optical' else gg)['arrays'][key][:] = False
                result = decision.classify(f, ground, oo, gg, {})['arrays']
                self.assertTrue(np.all(result['labels'] == decision.U))
                self.assertFalse(result['available_a'].any())

    def test_geometry_unavailable_keeps_unknown_even_when_intensity_is_weak(self):
        f = shell(h=1, w=2, intensity=0)
        opt, _ = injected_aerosol_evidence(f)
        result = decision.classify(f, available_ground(f), opt, {'arrays': {}}, {})['arrays']
        np.testing.assert_array_equal(result['labels'], np.full(2, decision.U))
        self.assertTrue(np.all(np.isnan(result['score_a'])))

    def test_ground_coverage_failure_never_hard_ground(self):
        image, _ = plane_image(quadrant_only=True)
        f = frame_from_image(image)
        result = ground_lite.compute(f, {})
        self.assertFalse(result['diagnostics']['reliable'])
        self.assertFalse(result['arrays']['ground_mask'].any())
        self.assertFalse(result['arrays']['ground_available'].any())
        opt, geo = injected_aerosol_evidence(f)
        labels = decision.classify(f, result, opt, geo, {})['arrays']['labels']
        self.assertTrue(np.all(labels == decision.U))

    def test_steep_surface_rejected_as_flat_ground(self):
        image, _ = plane_image(slope=0.8)
        result = ground_lite.compute(frame_from_image(image), {})
        self.assertFalse(result['diagnostics']['reliable'])
        self.assertFalse(result['arrays']['ground_mask'].any())

    def test_low_protrusion_survives_even_if_material_features_vote_aerosol(self):
        image, bump = plane_image(bump=True)
        f = frame_from_image(image)
        ground = ground_lite.compute(f, {})
        self.assertTrue(ground['diagnostics']['reliable'])
        bump_ids = bump.T.reshape(-1)
        self.assertTrue(ground['arrays']['low_object_mask'][bump_ids].all())
        self.assertFalse(ground['arrays']['ground_mask'][bump_ids].any())
        opt, geo = injected_aerosol_evidence(f)
        result = decision.classify(f, ground, opt, geo, {})['arrays']
        self.assertTrue(np.all(result['labels'][bump_ids] == decision.U))
        self.assertTrue(np.all(result['reason_code'][bump_ids] & decision.REASON_BITS['LOW_OBJECT_PROTECTED']))

    def test_edge_and_vegetation_ambiguity_mask_protects_against_aerosol_vote(self):
        # A material-ambiguous edge/vegetation proposal remains unknown, not a
        # fabricated entity class or a dust deletion.
        f = shell(h=1, w=2)
        opt, geo = injected_aerosol_evidence(f)
        geo['arrays']['edge_protect_mask'][:] = True
        result = decision.classify(f, available_ground(f), opt, geo, {})['arrays']
        self.assertTrue(np.all(result['labels'] == decision.U))
        self.assertTrue(np.all(result['reason_code'] & decision.REASON_BITS['EDGE_OR_LINE_PROTECTED']))

    def test_real_depth_edge_generates_protection(self):
        ranges = np.full((80, 31), 10.0)
        ranges[:, 16:] = 13.0
        f = shell(ranges=ranges)
        result = geometry.compute(f, {})['arrays']
        ids = np.zeros((80, 31), bool)
        ids[5:-5, 15:17] = True
        boundary = f.from_image(ids)
        self.assertTrue(result['scan_available'][boundary].all())
        self.assertTrue(result['edge_protect_mask'][boundary].all())

    def test_no_seam_wrap_and_reduced_delivered_width(self):
        f = shell(w=2)
        result = geometry.compute(f, {})
        self.assertFalse(result['diagnostics']['angular_seam_wrapped'])
        self.assertFalse(result['arrays']['scan_available'].any())
        self.assertLessEqual(int(result['arrays']['scan_valid_neighbor_count'].max()), 3)
        f2 = shell(w=17)
        out = geometry.compute(f2, {})['arrays']
        self.assertEqual(out['scan_surface_score'].shape, (80*17,))
        self.assertTrue(out['scan_available'].any())

    def test_coverage_holes_not_used_as_neighbor_observations(self):
        f = shell(w=17)
        f.column_coverage_mask[8] = False
        geom = geometry.compute(f, {})['arrays']
        opt = optical.compute(f, {})['arrays']
        absent = f.from_image(np.broadcast_to(np.arange(17) == 8, (80, 17)))
        self.assertFalse(geom['scan_available'][absent].any())
        self.assertFalse(opt['optical_available'][absent].any())

    def test_duplicate_point_pca_is_unavailable_not_dense_solid_or_aerosol(self):
        f = frame_from_image(np.broadcast_to([5., 0., 0.], (80, 12, 3)).copy())
        geom = geometry.compute(f, {})
        self.assertFalse(geom['arrays']['spatial_available'].any())
        self.assertTrue(np.any(geom['arrays']['reason_code'] & geometry.REASON_BITS['PCA_DEGENERATE']))
        opt, _ = injected_aerosol_evidence(f)
        result = decision.classify(f, available_ground(f), opt, geom, {})['arrays']
        self.assertTrue(np.all(result['labels'] == decision.U))

    def test_nan_inf_empty_and_all_invalid_preserve_slot_contract(self):
        for image in [np.empty((80, 0, 3)), np.full((80, 3, 3), np.nan),
                      np.full((80, 3, 3), np.inf)]:
            with self.subTest(shape=image.shape, finite=int(np.isfinite(image).sum())):
                f = frame_from_image(image)
                g, o, x = ground_lite.compute(f, {}), optical.compute(f, {}), geometry.compute(f, {})
                result = decision.classify(f, g, o, x, {})['arrays']
                self.assertEqual(result['labels'].shape, (len(f.xyz),))
                self.assertTrue(np.all(result['labels'] == decision.INVALID))
                self.assertFalse(result['available_a'].any())

    def test_missing_intensity_does_not_make_valid_xyz_invalid(self):
        f = shell(intensity=np.nan)
        opt, geom = optical.compute(f, {}), geometry.compute(f, {})
        result = decision.classify(f, available_ground(f), opt, geom, {})['arrays']
        self.assertFalse(opt['arrays']['optical_available'].any())
        self.assertFalse(np.any(result['labels'] == decision.INVALID))
        self.assertFalse(np.any(result['labels'] == decision.A))

    def test_ground_seed_and_pca_batching_are_deterministic(self):
        image, _ = plane_image(bump=True)
        f = frame_from_image(image)
        a, b = ground_lite.compute(f, {}), ground_lite.compute(f, {})
        self.assertEqual(a['diagnostics']['plane_z_ax_by_c'], b['diagnostics']['plane_z_ax_by_c'])
        np.testing.assert_array_equal(a['arrays']['ground_mask'], b['arrays']['ground_mask'])
        f = shell(w=17)
        a = geometry.compute(f, {'geometry': {'batch_size': 97}})['arrays']
        b = geometry.compute(f, {'geometry': {'batch_size': 4096}})['arrays']
        for key in ('spatial_available', 'spatial_surface_score', 'spatial_diffuse_score'):
            np.testing.assert_allclose(a[key], b[key], rtol=0, atol=0, equal_nan=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
