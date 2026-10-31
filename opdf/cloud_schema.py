"""Lossless slot-based PointCloud2 frame schema for OPDF-V1.

The 80-row image layout is a frozen geometric candidate, not certified beam IDs.
No invalid slot is removed and row padding remains in raw_data.
"""
from dataclasses import dataclass
from typing import Any
import numpy as np


@dataclass
class FrameData:
    xyz: np.ndarray
    intensity: np.ndarray
    valid_xyz_mask: np.ndarray
    raw_slot_id: np.ndarray
    height: int
    width: int
    point_step: int
    row_step: int
    header_stamp_ns: int
    record_stamp_ns: int
    frame_id: str
    source_bag: str
    source_record_locator: dict
    mapping_version: str
    source_fingerprint: dict
    field_schema: list
    is_bigendian: bool
    is_dense: bool
    raw_data: bytes
    phase_order: np.ndarray
    column_coverage_mask: np.ndarray
    seq: int = 0

    def __post_init__(self):
        for name in ('height', 'width', 'point_step', 'row_step'):
            value = getattr(self, name)
            if not isinstance(value, (int, np.integer)) or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        n = self.height * self.width
        if self.xyz.shape != (n, 3) or self.xyz.dtype.kind != 'f':
            raise ValueError('xyz must be floating (H*W,3)')
        for name in ('intensity', 'valid_xyz_mask', 'raw_slot_id'):
            if getattr(self, name).shape != (n,):
                raise ValueError(f'{name} must include every original slot')
        if self.valid_xyz_mask.dtype != np.bool_:
            raise ValueError('valid_xyz_mask must be bool')
        if not np.array_equal(self.valid_xyz_mask, np.isfinite(self.xyz).all(axis=1)):
            raise ValueError('valid mask must be exactly XYZ finiteness')
        if self.raw_slot_id.dtype != np.uint64 or not np.array_equal(
                self.raw_slot_id, np.arange(n, dtype=np.uint64)):
            raise ValueError('raw_slot_id must be original uint64 full slot order')
        order = np.asarray(self.phase_order)
        if order.shape != (self.height,) or order.dtype.kind not in 'iu' or not np.array_equal(
                np.sort(order), np.arange(self.height)):
            raise ValueError('phase_order must be an integer permutation of H')
        self.phase_order = order.astype(np.int64, copy=False)
        if self.column_coverage_mask.shape != (self.width,) or self.column_coverage_mask.dtype != np.bool_:
            raise ValueError('column_coverage_mask must be bool(W,)')
        if self.row_step < self.width * self.point_step:
            raise ValueError('row_step is shorter than delivered point slots')
        if len(self.raw_data) != self.height * self.row_step:
            raise ValueError('raw_data length must equal height*row_step')

    def metadata(self) -> dict[str, Any]:
        n = self.height * self.width
        return {
            'height': int(self.height), 'width': int(self.width), 'point_count': int(n),
            'point_step': int(self.point_step), 'row_step': int(self.row_step),
            'header_stamp_ns': int(self.header_stamp_ns),
            'record_stamp_ns': int(self.record_stamp_ns), 'seq': int(self.seq),
            'frame_id': self.frame_id, 'source_bag': self.source_bag,
            'source_record_locator': dict(self.source_record_locator),
            'mapping_version': self.mapping_version,
            'mapping_available': self.height == 80 and not self.mapping_version.startswith('UNAVAILABLE'),
            'mapping_scope': 'frozen geometric software-layout candidate; physical beams/timing UNKNOWN',
            'source_fingerprint': dict(self.source_fingerprint),
            'raw_message_sha256': self.source_fingerprint.get('raw_message_sha256'),
            'field_schema': [dict(f) for f in self.field_schema],
            'is_bigendian': bool(self.is_bigendian), 'is_dense': bool(self.is_dense),
            'raw_data_bytes': len(self.raw_data), 'finite_xyz_count': int(self.valid_xyz_mask.sum()),
            'invalid_xyz_count': int(n - self.valid_xyz_mask.sum()),
            'phase_order': self.phase_order.tolist(),
            'column_coverage_mask': self.column_coverage_mask.tolist(),
            'coverage_meaning': 'delivered software columns only; physical angular coverage UNKNOWN',
            'raw_slot_id': {'dtype': 'uint64', 'rule': 'arange(H*W); includes invalid slots'},
        }

    def to_image(self, values: np.ndarray) -> np.ndarray:
        """Map original flat slots to the frozen candidate HxW layout."""
        values = np.asarray(values)
        if values.ndim < 1 or values.shape[0] != self.height * self.width:
            raise ValueError('values first dimension must equal original slot count')
        shape = (self.width, self.height) + values.shape[1:]
        axes = (1, 0) + tuple(range(2, values.ndim + 1))
        return values.reshape(shape).transpose(axes)[self.phase_order]

    def from_image(self, image: np.ndarray) -> np.ndarray:
        """Invert to original flat slots, without filtering NaNs or unknowns."""
        image = np.asarray(image)
        if image.ndim < 2 or image.shape[:2] != (self.height, self.width):
            raise ValueError('image first dimensions must be H,W')
        original_rows = image[np.argsort(self.phase_order)]
        axes = (1, 0) + tuple(range(2, image.ndim))
        return original_rows.transpose(axes).reshape((self.height * self.width,) + image.shape[2:])

    def point_bytes(self) -> np.ndarray:
        """Exact original slot bytes; exclude but never discard raw row padding."""
        n = self.height * self.width
        if n == 0:
            return np.empty((0, self.point_step), dtype=np.uint8)
        rows = np.ndarray((self.height, self.width, self.point_step), dtype=np.uint8,
                          buffer=self.raw_data, strides=(self.row_step, self.point_step, 1))
        return rows.reshape(n, self.point_step).copy()
