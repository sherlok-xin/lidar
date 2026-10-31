"""Bounded ROS1 V2 indexed reader with exact PointCloud2 slot provenance.

Record-header parsing adapts the short ROS1 format helpers from
research_ops/scripts/ros1_sparse_audit.py and multisensor_audit.py (read-only
reference, 2026-10-30). No old executable workflow or write path is imported.
Only a finalized index and selected chunks are read; original files use rb.
"""
import sys
sys.dont_write_bytecode = True
import bz2
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import time
import numpy as np
from .cloud_schema import FrameData

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = PROJECT_ROOT / 'configs' / 'mapping_phase2.json'
DATATYPES = {1: ('i1', 1), 2: ('u1', 1), 3: ('i2', 2), 4: ('u2', 2),
             5: ('i4', 4), 6: ('u4', 4), 7: ('f4', 4), 8: ('f8', 8)}


def _u32(b):
    return struct.unpack('<I', b)[0]


def _u64(b):
    return struct.unpack('<Q', b)[0]


def _stamp_ns(b):
    sec, nsec = struct.unpack('<II', b)
    if nsec >= 10**9:
        raise ValueError('invalid ROS nanoseconds')
    return sec * 10**9 + nsec


def _fields(b):
    out = {}; pos = 0
    while pos < len(b):
        if pos + 4 > len(b):
            raise ValueError('short bag header field length')
        size = _u32(b[pos:pos + 4]); pos += 4
        if size < 2 or pos + size > len(b):
            raise ValueError('short/invalid bag header field')
        key, value = b[pos:pos + size].split(b'=', 1); pos += size
        key = key.decode('utf8')
        if key in out:
            raise ValueError('duplicate bag header key')
        out[key] = value
    return out


class _BudgetReader:
    def __init__(self, file, max_read_bytes):
        self.file = file; self.limit = max_read_bytes; self.bytes_read = 0
    def read(self, n):
        if n < 0 or self.bytes_read + n > self.limit:
            raise ValueError('actual read byte budget exceeded')
        data = self.file.read(n); self.bytes_read += len(data)
        return data
    def seek(self, *args): return self.file.seek(*args)
    def tell(self): return self.file.tell()


def _record(f, limit):
    pos = f.tell()
    if pos == limit:
        return None
    raw = f.read(4)
    if len(raw) != 4:
        raise ValueError('incomplete record header length')
    size = _u32(raw)
    if size > 1024**2 or f.tell() + size + 4 > limit:
        raise ValueError('invalid/incomplete record header')
    header = _fields(f.read(size)); raw = f.read(4)
    if len(raw) != 4:
        raise ValueError('incomplete record data length')
    length = _u32(raw); start = f.tell()
    if start + length > limit:
        raise ValueError('record payload exceeds file/chunk boundary')
    return {'offset': pos, 'header': header, 'data_offset': start,
            'data_length': length, 'end': start + length}


class _MessageReader:
    def __init__(self, b): self.b = memoryview(b); self.pos = 0
    def take(self, n):
        if n < 0 or self.pos + n > len(self.b):
            raise ValueError('serialized PointCloud2 is truncated')
        value = self.b[self.pos:self.pos + n]; self.pos += n; return value
    def u32(self): return _u32(self.take(4))
    def u8(self): return self.take(1)[0]
    def string(self): return bytes(self.take(self.u32())).decode('utf8')


def _default_mapping(height):
    raw = MAPPING_PATH.read_bytes(); obj = json.loads(raw)
    order = np.asarray(obj['phase_order_low_to_high'], dtype=np.int64)
    if order.shape != (80,) or not np.array_equal(np.sort(order), np.arange(80)):
        raise ValueError('frozen phase2 mapping file is not an 80-phase permutation')
    digest = hashlib.sha256(raw).hexdigest()
    return (order if height == 80 else np.arange(height, dtype=np.int64)), digest


def decode_pointcloud2(serialized, *, source_bag='', locator=None,
                       record_stamp_ns=0, fingerprint=None, phase_order=None,
                       mapping_version='phase2-candidate-v1') -> FrameData:
    r = _MessageReader(serialized)
    seq = r.u32(); sec = r.u32(); nsec = r.u32()
    if nsec >= 10**9:
        raise ValueError('invalid PointCloud2 header nanoseconds')
    frame_id = r.string(); height = r.u32(); width = r.u32(); count = r.u32()
    if count > 1024:
        raise ValueError('unreasonable field count')
    schema = []
    for _ in range(count):
        schema.append({'name': r.string(), 'offset': r.u32(),
                       'datatype': r.u8(), 'count': r.u32()})
    big = r.u8()
    if big not in (0, 1): raise ValueError('invalid endianness flag')
    step = r.u32(); row_step = r.u32(); data_size = r.u32()
    raw = bytes(r.take(data_size)); dense = r.u8()
    if dense not in (0, 1) or r.pos != len(serialized):
        raise ValueError('invalid dense flag or trailing serialized bytes')
    n = height * width
    if row_step < width * step or len(raw) != height * row_step:
        raise ValueError('PointCloud2 dimensions/row stride/data length disagree')
    if n and step == 0: raise ValueError('nonempty cloud needs a point stride')
    names = set(); intervals = []; by_name = {}
    for field in schema:
        name, offset, dt, items = (field[k] for k in ('name', 'offset', 'datatype', 'count'))
        if not name or name in names or dt not in DATATYPES or items < 1:
            raise ValueError('invalid/duplicate PointField name, datatype or count')
        end = offset + DATATYPES[dt][1] * items
        if end > step or any(offset < b and end > a for a, b in intervals):
            raise ValueError('unsafe PointField bounds or overlap')
        intervals.append((offset, end)); names.add(name); by_name[name] = field
    if n or schema:
        for name in ('x', 'y', 'z'):
            f = by_name.get(name)
            if f is None or f['datatype'] not in (7, 8) or f['count'] != 1:
                raise ValueError('XYZ must be declared scalar FLOAT32/FLOAT64')
    prefix = '>' if big else '<'
    def channel(name, default_nan=False):
        f = by_name.get(name)
        if f is None:
            if default_nan: return np.full(n, np.nan, dtype=np.float32)
            return np.empty(n, dtype=np.float32)
        if f['count'] != 1: raise ValueError(f'{name} must be scalar')
        if n == 0: return np.empty(0, dtype=np.float64 if f['datatype'] == 8 else np.float32)
        dtype = np.dtype(prefix + DATATYPES[f['datatype']][0])
        return np.ndarray((height, width), dtype=dtype, buffer=raw,
                          offset=f['offset'], strides=(row_step, step)).reshape(-1).copy()
    dtype = np.float64 if any(by_name.get(k, {}).get('datatype') == 8 for k in ('x', 'y', 'z')) else np.float32
    xyz = np.column_stack([channel(k) for k in ('x', 'y', 'z')]).astype(dtype, copy=False)
    intensity = channel('intensity', default_nan=True).astype(np.float32, copy=False)
    fp = dict(fingerprint or {}); fp['raw_message_sha256'] = hashlib.sha256(serialized).hexdigest()
    if phase_order is None:
        order, digest = _default_mapping(height); fp['mapping_sha256'] = digest
        if height != 80: mapping_version = f'UNAVAILABLE-height-{height}'
    else:
        order = np.asarray(phase_order)
    loc = dict(locator or {}); loc.setdefault('seq', seq)
    return FrameData(xyz=xyz, intensity=intensity, valid_xyz_mask=np.isfinite(xyz).all(axis=1),
                     raw_slot_id=np.arange(n, dtype=np.uint64), height=height, width=width,
                     point_step=step, row_step=row_step, header_stamp_ns=sec * 10**9 + nsec,
                     record_stamp_ns=int(record_stamp_ns), frame_id=frame_id, source_bag=str(source_bag),
                     source_record_locator=loc, mapping_version=mapping_version,
                     source_fingerprint=fp, field_schema=schema, is_bigendian=bool(big),
                     is_dense=bool(dense), raw_data=raw, phase_order=order,
                     column_coverage_mask=np.ones(width, dtype=bool), seq=seq)


def _read_tail_index(reader, path):
    size = path.stat().st_size
    if reader.read(13) != b'#ROSBAG V2.0\n': raise ValueError('requires ROS1 bag V2 magic')
    first = _record(reader, size); h = first['header']
    if h.get('op') != b'\x03': raise ValueError('missing bag header')
    index_pos = _u64(h['index_pos']); declared_chunks = _u32(h['chunk_count'])
    declared_connections = _u32(h['conn_count'])
    if index_pos < first['end'] or index_pos >= size:
        raise ValueError('finalized bag index is outside source file; no repair attempted')
    reader.seek(0); head = reader.read(min(size, 65536))
    fingerprint = {'source_bag': str(path.resolve()), 'size_bytes': size,
                   'mtime_ns': path.stat().st_mtime_ns, 'head_sha256': hashlib.sha256(head).hexdigest(),
                   'head_sha256_bytes': len(head), 'index_pos': index_pos,
                   'declared_chunks': declared_chunks, 'declared_connections': declared_connections,
                   'scope': 'local file stat + first64KiB + finalized tail index; not whole-file hash'}
    reader.seek(index_pos); conns = {}; chunks = []
    while reader.tell() < size:
        rr = _record(reader, size); hh = rr['header']; b = reader.read(rr['data_length'])
        if hh['op'] == b'\x07':
            cid = _u32(hh['conn']); d = _fields(b)
            if cid in conns: raise ValueError('duplicate finalized connection ID')
            conns[cid] = {'id': cid, 'topic': hh['topic'].decode(),
                          'type': d.get('type', b'').decode(),
                          'md5sum': d.get('md5sum', b'').decode(),
                          'message_definition': d.get('message_definition', b'').decode()}
        elif hh['op'] == b'\x06':
            if _u32(hh['ver']) != 1 or len(b) != _u32(hh['count']) * 8:
                raise ValueError('unsupported/malformed CHUNK_INFO')
            offset = _u64(hh['chunk_pos'])
            if not first['end'] <= offset < index_pos:
                raise ValueError('chunk offset is outside pre-index payload region')
            chunks.append({'offset': offset, 'start_ns': _stamp_ns(hh['start_time']),
                           'end_ns': _stamp_ns(hh['end_time']), 'counts': dict(struct.iter_unpack('<II', b))})
        else: raise ValueError('unexpected finalized index record')
        reader.seek(rr['end'])
    if len(chunks) != declared_chunks or len(conns) != declared_connections:
        raise ValueError('finalized index counts disagree with local bag header')
    offsets = [c['offset'] for c in chunks]
    if offsets != sorted(set(offsets)): raise ValueError('chunk offsets are not unique/increasing')
    return fingerprint, conns, chunks


def inspect_bag(bag_path, *, max_read_bytes=160 * 1024**2):
    path = Path(bag_path).resolve(); started = time.perf_counter()
    with path.open('rb') as f:
        reader = _BudgetReader(f, max_read_bytes); fp, conns, chunks = _read_tail_index(reader, path)
        return {'source_fingerprint': fp, 'connections': list(conns.values()),
                'chunk_count': len(chunks), 'actual_bytes_read': reader.bytes_read,
                'elapsed_seconds': time.perf_counter() - started,
                'inspection_scope': 'finalized index only; no full payload validation'}


def extract_frames(bag_path, output_dir, *, frames_per_window=3, max_frames=60,
                   max_read_bytes=160 * 1024**2) -> dict:
    path = Path(bag_path).resolve(); out = Path(output_dir).resolve()
    if not out.is_relative_to(PROJECT_ROOT): raise ValueError('outputs must stay inside opdf_v1')
    if not 1 <= max_frames <= 60 or frames_per_window < 1 or frames_per_window * 3 > max_frames:
        raise ValueError('three requested windows must fit max_frames<=60')
    if not 1 <= max_read_bytes <= 160 * 1024**2:
        raise ValueError('max_read_bytes must be in 1..160MiB')
    out.mkdir(parents=True, exist_ok=True); sample_dir = out / 'samples'; sample_dir.mkdir(exist_ok=True)
    manifest_path = out / 'manifest.json'
    if manifest_path.exists(): raise FileExistsError(f'refusing to overwrite {manifest_path}')
    manifest = {'method': 'three indexed sparse windows; no full decode or ROS nodes',
                'source_bag': str(path), 'output_dir': str(out), 'frames': [], 'failures': [],
                'max_frames': max_frames, 'max_read_bytes': max_read_bytes, 'status': 'RUNNING'}
    started = time.perf_counter(); reader = None; payload_bytes = 0
    before = path.stat()
    try:
        with path.open('rb') as f:
            reader = _BudgetReader(f, max_read_bytes)
            fp, conns, chunks = _read_tail_index(reader, path)
            manifest['source_fingerprint'] = fp
            cloud_ids = [cid for cid, c in conns.items() if c['topic'] == '/hesai/pandar_points'
                         and c['type'] == 'sensor_msgs/PointCloud2']
            if len(cloud_ids) != 1: raise ValueError('expected one declared raw PointCloud2 connection')
            cid = cloud_ids[0]; ranges = []; ordinal = 0
            for i, ch in enumerate(chunks):
                count = ch['counts'].get(cid, 0); ranges.append((ordinal, ordinal + count, i)); ordinal += count
            if ordinal < frames_per_window: raise ValueError('not enough indexed raw frames')
            starts = {'early': 0, 'middle': max(0, ordinal // 2 - frames_per_window // 2),
                      'late': ordinal - frames_per_window}
            wanted = {}
            for window, start in starts.items():
                for index in range(start, start + frames_per_window):
                    if index in wanted: raise ValueError('windows overlap; insufficient independent sequence positions')
                    wanted[index] = window
            selected = [(a, z, i) for a, z, i in ranges if any(a <= k < z for k in wanted)]
            manifest['selected_chunk_indices'] = [i for _, _, i in selected]
            manifest['indexed_raw_frame_count'] = ordinal
            for a, z, ci in selected:
                ch = chunks[ci]; reader.seek(ch['offset']); cr = _record(reader, fp['index_pos'])
                hh = cr['header']
                if hh.get('op') != b'\x05': raise ValueError('index does not point to a CHUNK')
                raw = reader.read(cr['data_length']); payload_bytes += len(raw)
                compression = hh['compression'].decode(); declared_size = _u32(hh['size'])
                if declared_size > 64 * 1024**2: raise ValueError('uncompressed chunk memory cap exceeded')
                if compression == 'none': data = raw
                elif compression == 'bz2': data = bz2.decompress(raw)
                else: raise ValueError(f'unsupported chunk compression: {compression}')
                if len(data) != declared_size: raise ValueError('chunk uncompressed size mismatch')
                stream = io.BytesIO(data); local_index = 0
                while stream.tell() < len(data):
                    rr = _record(stream, len(data)); h = rr['header']
                    if h.get('op') == b'\x02' and _u32(h['conn']) == cid:
                        absolute = a + local_index; local_index += 1
                        if absolute in wanted:
                            serialized = stream.read(rr['data_length']); record_ns = _stamp_ns(h['time'])
                            locator = {'connection_id': cid, 'topic': conns[cid]['topic'],
                                       'chunk_index': ci, 'chunk_file_offset': ch['offset'],
                                       'record_offset_in_uncompressed_chunk': rr['offset'],
                                       'message_offset_in_uncompressed_chunk': rr['data_offset'],
                                       'message_file_offset': cr['data_offset'] + rr['data_offset'] if compression == 'none' else None,
                                       'compression': compression, 'cloud_index_from_finalized_counts': absolute}
                            frame = decode_pointcloud2(serialized, source_bag=str(path), locator=locator,
                                                       record_stamp_ns=record_ns, fingerprint=fp)
                            window = wanted[absolute]; key = f'{window}_seq{frame.seq}'
                            dest = sample_dir / f'{key}.ros1msg'; meta_path = dest.with_suffix('.json')
                            if dest.exists() or meta_path.exists(): raise FileExistsError(f'refusing to overwrite {dest}')
                            dest.write_bytes(serialized); metadata = frame.metadata()
                            metadata.update({'key': key, 'window': window, 'serialized_bytes': len(serialized)})
                            meta_path.write_text(json.dumps(metadata, indent=2, allow_nan=False))
                            manifest['frames'].append({'path': str(dest.relative_to(out)), 'key': key,
                                                       'metadata_path': str(meta_path.relative_to(out)),
                                                       'seq': frame.seq, 'header_stamp_ns': frame.header_stamp_ns,
                                                       'record_stamp_ns': frame.record_stamp_ns, 'locator': locator,
                                                       'sha256': hashlib.sha256(serialized).hexdigest(),
                                                       'height': frame.height, 'width': frame.width, 'window': window})
                    stream.seek(rr['end'])
                if local_index != z - a: raise ValueError('chunk cloud count disagrees with finalized index')
            if len(manifest['frames']) != 3 * frames_per_window:
                raise ValueError('failed to extract every requested raw frame')
            after = path.stat()
            manifest['source_stat_unchanged'] = before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
            if not manifest['source_stat_unchanged']: raise ValueError('source stat changed during read')
            manifest['status'] = 'COMPLETE'
    except Exception as exc:
        manifest['status'] = 'FAILED'; manifest['failures'].append({'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        manifest['actual_bytes_read'] = reader.bytes_read if reader else 0
        manifest['chunk_payload_bytes_read'] = payload_bytes
        manifest['elapsed_seconds'] = time.perf_counter() - started
        manifest['manifest_path'] = str(manifest_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False))
    return manifest


def load_cached_frame(path, metadata=None) -> FrameData:
    path = Path(path)
    if metadata is None:
        sidecar = path.with_suffix('.json')
        if not sidecar.exists(): raise FileNotFoundError(f'cache provenance sidecar missing: {sidecar}')
        metadata = json.loads(sidecar.read_text())
    elif isinstance(metadata, (str, os.PathLike)):
        metadata = json.loads(Path(metadata).read_text())
    serialized = path.read_bytes(); sha = hashlib.sha256(serialized).hexdigest()
    expected = [metadata.get('raw_message_sha256'), metadata.get('sha256'),
                metadata.get('source_fingerprint', {}).get('raw_message_sha256')]
    if any(value and sha != value for value in expected):
        raise ValueError('cached serialized message SHA256 mismatch in provenance')
    return decode_pointcloud2(serialized, source_bag=metadata.get('source_bag', ''),
                             locator=metadata.get('source_record_locator', metadata.get('locator', {})),
                             record_stamp_ns=metadata.get('record_stamp_ns', 0),
                             fingerprint=metadata.get('source_fingerprint', {}),
                             phase_order=np.asarray(metadata['phase_order'], dtype=np.int64) if 'phase_order' in metadata else None,
                             mapping_version=metadata.get('mapping_version', 'phase2-candidate-v1'))
