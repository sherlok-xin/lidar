"""Synthetic IO regression cases; never presented as measured LiDAR evidence."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import json
import struct
import tempfile
import unittest
import numpy as np
from opdf.io_rosbag import decode_pointcloud2, load_cached_frame, _BudgetReader


def string(s):
    b = s.encode(); return struct.pack('<I', len(b)) + b


def make_cloud(height=2, width=3, *, big=False, row_padding=0, fields=None, no_fields=False,
               point_step=32, nan_first=False, inf_last=False, extra_bytes=b''):
    """Deliberately nonzero slot/row padding detects accidental dtype-field copies."""
    schema = fields if fields is not None else [('x', 0, 7, 1), ('y', 4, 7, 1),
                                               ('z', 8, 7, 1), ('intensity', 16, 7, 1)]
    if no_fields: schema = []
    row_step = width * point_step + row_padding
    raw = bytearray([0xA5] * (height * row_step)); prefix = '>' if big else '<'
    xyz = np.zeros((height * width, 3), np.float32)
    for i in range(height * width):
        row, col = divmod(i, width); base = row * row_step + col * point_step
        xyz[i] = (i + .25, i + 1.5, -i - .75)
        if point_step >= 20:
            struct.pack_into(prefix + '3f', raw, base, *xyz[i])
            struct.pack_into(prefix + 'f', raw, base + 16, i + 5)
    if nan_first and height * width:
        struct.pack_into(prefix + 'I', raw, 0, 0x7FC01234); xyz[0, 0] = np.nan
    if inf_last and height * width:
        i = height * width - 1; row, col = divmod(i, width)
        struct.pack_into(prefix + 'f', raw, row * row_step + col * point_step + 8, np.inf)
        xyz[-1, 2] = np.inf
    b = struct.pack('<III', 42, 1789629247, 564411163) + string('fixture_sensor')
    b += struct.pack('<III', height, width, len(schema))
    for name, offset, dtype, count in schema:
        b += string(name) + struct.pack('<IBI', offset, dtype, count)
    b += struct.pack('<BIII', int(big), point_step, row_step, len(raw)) + raw + b'\x00' + extra_bytes
    return bytes(b), bytes(raw), xyz


class IORegressionTests(unittest.TestCase):
    def test_reduced_width_1729_default_frozen_mapping_exact_roundtrip(self):
        b, raw, xyz = make_cloud(80, 1729, nan_first=True)
        frame = decode_pointcloud2(b)
        self.assertEqual((frame.height, frame.width), (80, 1729))
        self.assertEqual(frame.xyz.shape, (138320, 3))
        self.assertEqual(frame.raw_slot_id.dtype, np.uint64)
        self.assertEqual(frame.phase_order.shape, (80,))
        self.assertEqual(int(frame.phase_order[0]), 24)
        self.assertTrue(frame.column_coverage_mask.all())
        self.assertIn('mapping_sha256', frame.source_fingerprint)
        self.assertEqual(frame.from_image(frame.to_image(frame.point_bytes())).tobytes(), raw)
        self.assertTrue(np.array_equal(frame.from_image(frame.to_image(frame.raw_slot_id)), frame.raw_slot_id))
        self.assertEqual(frame.valid_xyz_mask.sum(), len(frame.xyz) - 1)

    def test_row_padding_preserved_and_never_becomes_points(self):
        b, raw, xyz = make_cloud(row_padding=7)
        frame = decode_pointcloud2(b, phase_order=np.array([1, 0]))
        np.testing.assert_array_equal(frame.xyz, xyz)
        expected = b''.join(raw[r * 103:r * 103 + 96] for r in range(2))
        self.assertEqual(frame.point_bytes().tobytes(), expected)
        self.assertEqual(frame.raw_data, raw)
        self.assertEqual(len(frame.raw_data), 206)
        self.assertEqual(frame.from_image(frame.to_image(frame.point_bytes())).tobytes(), expected)

    def test_big_endian_values_nan_payload_and_raw_bytes(self):
        b, raw, xyz = make_cloud(big=True, row_padding=9, nan_first=True, inf_last=True)
        frame = decode_pointcloud2(b, phase_order=np.array([1, 0]))
        np.testing.assert_allclose(frame.xyz, xyz, equal_nan=True)
        self.assertTrue(frame.is_bigendian)
        np.testing.assert_array_equal(frame.valid_xyz_mask, [False, True, True, True, True, False])
        self.assertEqual(frame.point_bytes()[0, :4].tobytes(), b'\x7f\xc0\x12\x34')
        self.assertEqual(frame.raw_data, raw)
        np.testing.assert_array_equal(frame.intensity, np.arange(6) + 5)

    def test_empty_width_has_no_fabricated_points(self):
        b, raw, _ = make_cloud(80, 0)
        frame = decode_pointcloud2(b)
        self.assertEqual(frame.xyz.shape, (0, 3))
        self.assertEqual(frame.to_image(frame.xyz).shape, (80, 0, 3))
        self.assertEqual(frame.from_image(frame.to_image(frame.xyz)).shape, (0, 3))
        self.assertEqual(frame.point_bytes().shape, (0, 32))
        self.assertEqual(frame.metadata()['finite_xyz_count'], 0)
        self.assertEqual(frame.column_coverage_mask.shape, (0,))

    def test_completely_empty_no_field_message(self):
        b, _, _ = make_cloud(0, 0, no_fields=True, point_step=0)
        frame = decode_pointcloud2(b)
        self.assertEqual(frame.xyz.shape, (0, 3))
        self.assertFalse(frame.metadata()['mapping_available'])
        self.assertEqual(frame.point_bytes().shape, (0, 0))

    def test_wrong_height_marks_mapping_unavailable(self):
        b, _, _ = make_cloud(2, 3)
        frame = decode_pointcloud2(b)
        self.assertEqual(frame.mapping_version, 'UNAVAILABLE-height-2')
        self.assertFalse(frame.metadata()['mapping_available'])

    def test_unsafe_field_bounds_overlap_duplicate_and_type(self):
        cases = [
            [('x', 30, 7, 1), ('y', 4, 7, 1), ('z', 8, 7, 1)],
            [('x', 0, 7, 1), ('y', 2, 7, 1), ('z', 8, 7, 1)],
            [('x', 0, 7, 1), ('x', 4, 7, 1), ('z', 8, 7, 1)],
            [('x', 0, 99, 1), ('y', 4, 7, 1), ('z', 8, 7, 1)],
            [('x', 0, 7, 0), ('y', 4, 7, 1), ('z', 8, 7, 1)],
        ]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                decode_pointcloud2(make_cloud(fields=fields)[0])

    def test_truncated_message_and_trailing_bytes_are_rejected(self):
        b, _, _ = make_cloud()
        with self.assertRaises(ValueError): decode_pointcloud2(b[:-1])
        with self.assertRaises(ValueError): decode_pointcloud2(b + b'bad')

    def test_bad_stride_rejected(self):
        b, _, _ = make_cloud()
        # Locate known data length immediately before raw bytes; adjust row stride only.
        pos = len(b) - 1 - 192 - 4
        malformed = bytearray(b)
        struct.pack_into('<I', malformed, pos - 4, 95)
        with self.assertRaises(ValueError): decode_pointcloud2(bytes(malformed))

    def test_image_shape_and_phase_permutation_validation(self):
        b, _, _ = make_cloud()
        for order in [np.array([0, 0]), np.array([0.0, 1.0]), np.array([0, 1, 2])]:
            with self.subTest(order=order), self.assertRaises(ValueError):
                decode_pointcloud2(b, phase_order=order)
        frame = decode_pointcloud2(b, phase_order=np.array([1, 0]))
        with self.assertRaises(ValueError): frame.to_image(np.zeros((5, 3)))
        with self.assertRaises(ValueError): frame.from_image(np.zeros((3, 2)))
        ids = frame.to_image(frame.raw_slot_id)
        np.testing.assert_array_equal(ids, [[1, 3, 5], [0, 2, 4]])

    def test_cache_hash_and_provenance(self):
        b, _, _ = make_cloud()
        fixture_root = Path(__file__).parent
        with tempfile.TemporaryDirectory(dir=fixture_root, prefix='io-fixture-') as td:
            path = Path(td) / 'frame.ros1msg'; path.write_bytes(b)
            frame = decode_pointcloud2(b, source_bag='SYNTHETIC_TEST_ONLY',
                                      record_stamp_ns=123, locator={'test_offset': 99})
            path.with_suffix('.json').write_text(json.dumps(frame.metadata()))
            reread = load_cached_frame(path)
            self.assertEqual(reread.source_bag, 'SYNTHETIC_TEST_ONLY')
            self.assertEqual(reread.record_stamp_ns, 123)
            self.assertEqual(reread.source_record_locator['test_offset'], 99)
            path.write_bytes(b + b'corrupt')
            with self.assertRaisesRegex(ValueError, 'SHA256'): load_cached_frame(path)

    def test_cache_fingerprint_hash_fallback_and_alias_tampering(self):
        b, _, _ = make_cloud()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='io-fixture-') as td:
            path = Path(td) / 'frame.ros1msg'; path.write_bytes(b)
            frame = decode_pointcloud2(b, source_bag='SYNTHETIC_TEST_ONLY')
            metadata = frame.metadata()
            # Valid fingerprint-only provenance is accepted without a top-level alias.
            fingerprint_only = dict(metadata); fingerprint_only.pop('raw_message_sha256')
            self.assertEqual(load_cached_frame(path, fingerprint_only).raw_data, frame.raw_data)
            # A correct top-level alias must not hide a conflicting nested fingerprint.
            metadata['source_fingerprint'] = dict(metadata['source_fingerprint'])
            metadata['source_fingerprint']['raw_message_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                load_cached_frame(path, metadata)
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                load_cached_frame(path, {'source_fingerprint': metadata['source_fingerprint']})

    def test_read_budget_stops_before_extra_read(self):
        reader = _BudgetReader(io.BytesIO(b'0123456789'), 8)
        self.assertEqual(reader.read(5), b'01234')
        with self.assertRaisesRegex(ValueError, 'budget'): reader.read(4)
        self.assertEqual(reader.bytes_read, 5)


if __name__ == '__main__': unittest.main()
