"""Pinned upstream RandLA-Net graph, explicit input adapter and full-frame voting."""
from pathlib import Path
import hashlib
import os
import importlib.util
import difflib
import sys
import time
from types import SimpleNamespace
import numpy as np
from scipy.spatial import cKDTree
import torch

UPSTREAM = Path(os.environ.get("OPEN3D_ML_ROOT","third_party/Open3D-ML")).resolve()
COMMIT = "a3d0f7a51d4eef0b94b9000a7d74af05e2d54c4f"
MODEL_SHA = "8d7d3457ed653a5ead2ffbdca01388bf95e3cd9b102aea19965dae743ff17839"


class BackboneBase(torch.nn.Module):
    def __init__(self, **kwargs):
        super().__init__()
        self.cfg = SimpleNamespace(**kwargs)
        self.rng = np.random.default_rng(kwargs.get("seed"))


def upstream_class(output):
    source = UPSTREAM / "ml3d/torch/models/randlanet.py"
    body = source.read_bytes()
    assert hashlib.sha256(body).hexdigest() == MODEL_SHA
    original = body.decode()
    text = original
    for declaration in ("from .base_model import BaseModel",
                        "from ..dataloaders import DefaultBatcher",
                        "from ...datasets.augment import SemsegAugmentation",
                        "from ..modules.losses import filter_valid_label",
                        "from ...datasets.utils import DataProcessing",
                        "from ...utils import MODEL",
                        "MODEL._register_module(RandLANet, 'torch')"):
        assert text.count(declaration) == 1
        replacement = "from randla_core import BackboneBase as BaseModel" if declaration.endswith("import BaseModel") else ""
        text = text.replace(declaration, replacement)
    text = text.replace("self.augmenter = SemsegAugmentation(cfg.augment, seed=self.rng)", "self.augmenter = None")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    graph = output / "pinned_open3d_ml_randlanet.py"
    if not graph.exists():
        graph.write_text(text)
        (output / "compat.patch").write_text("".join(difflib.unified_diff(original.splitlines(True), text.splitlines(True), fromfile=str(source), tofile=graph.name)))
        (output / "upstream.LICENSE").write_bytes((UPSTREAM / "LICENSE").read_bytes())
    if graph.read_text() != text:
        raise RuntimeError("pinned graph mismatch")
    spec = importlib.util.spec_from_file_location("pinned_open3d_ml_randlanet", graph)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == graph.resolve()
    return module.RandLANet


def voxels(cloud, temporal, grid):
    xyz = np.asarray(cloud["xyz"], dtype=np.float32)
    intensity = np.ravel(cloud["intensity"]).astype(np.float32)
    code = np.asarray(cloud["code"]).ravel()
    valid = np.isfinite(xyz).all(1) & np.isfinite(intensity) & np.asarray(cloud["valid"]).ravel().astype(bool)
    rows = np.flatnonzero(valid)
    if not len(rows):
        return None
    point = xyz[rows]
    feat = intensity[rows, None]
    if temporal is not None:
        temporal = np.asarray(temporal, dtype=np.float32)
        assert temporal.shape == (len(code), 8) and np.isfinite(temporal).all()
        feat = np.column_stack((feat, temporal[rows]))
    cell, ids, counts = np.unique(np.floor(point / grid).astype(np.int64), axis=0, return_inverse=True, return_counts=True)
    means = lambda arr: np.stack([np.bincount(ids, weights=col, minlength=len(cell))/counts for col in arr.T], axis=1).astype(np.float32)
    points, features = means(point), means(feat)
    votes = np.stack([np.bincount(ids, weights=(code[rows] == label), minlength=len(cell)) for label in range(3)], axis=1)
    label = votes.argmax(axis=1).astype(np.uint8)
    proj = cKDTree(points).query(point,k=1)[1].astype(np.int32)
    return dict(points=points, feat=features, label=label, rows=rows, proj=proj,
                pre=np.bincount(code[rows],minlength=3), post=np.bincount(label,minlength=3))


def hierarchy(points,features):
    features = np.ascontiguousarray(np.column_stack((points, features)), dtype=np.float32)
    layers = {key: [] for key in ("coords","neighbor_indices","sub_idx","interp_idx")}
    for _ in range(4):
        sub = points[:len(points)//4]
        if not len(sub) or len(points)<16:
            raise ValueError("insufficient patch for four RandLA levels")
        neighborhood = cKDTree(points).query(points, k=16)[1]
        interpolation = cKDTree(sub).query(points,k=1)[1][:,None]
        for name,value in zip(layers,(points,neighborhood,neighborhood[:len(sub)],interpolation)):
            layers[name].append(np.ascontiguousarray(value))
        points = sub
    return {**layers, "features":features}


def patch(frame, indices, mean, scale):
    point = frame["points"][indices].copy()
    point[:,:2] -= point[:,:2].mean(axis=0)
    return hierarchy(point,np.clip((frame["feat"][indices] - mean)/scale,-12,12))


def batch(items):
    return {key: [torch.from_numpy(np.stack([item[key][level] for item in items])) for level in range(4)] if key != "features"
            else torch.from_numpy(np.stack([item[key] for item in items])) for key in items[0]}


def training_patch(frame,size,rng):
    point = frame["points"]
    near = cKDTree(point).query(point[rng.integers(len(point))], k=min(size,len(point)))[1]
    near = np.atleast_1d(near)
    if len(near)<size:
        near=np.r_[near, rng.choice(near,size-len(near),replace=True)]
    rng.shuffle(near)
    _,first = np.unique(near,return_index=True)
    labels = np.zeros(size,np.uint8)
    labels[first] = frame["label"][near[first]]
    return near,labels


def full_patches(points,size,rng):
    remaining=[np.arange(len(points))]
    tree=cKDTree(points)
    while remaining:
        chunk=remaining.pop()
        if len(chunk)>size:
            axis=np.ptp(points[chunk],axis=0).argmax()
            split=len(chunk)//2
            perm=np.argpartition(points[chunk,axis],split)
            remaining.extend((chunk[perm[:split]],chunk[perm[split:]]))
            continue
        if len(chunk)<size:
            neighbors=np.atleast_1d(tree.query(points[chunk].mean(axis=0),k=min(size,len(points)))[1])
            extra=np.setdiff1d(neighbors,chunk)
            supplement=extra[:size-len(chunk)]
            chunk=np.r_[chunk,supplement]
            if len(chunk)<size:
                chunk=np.r_[chunk,rng.choice(chunk,size-len(chunk))]
        yield rng.permutation(chunk)


@torch.inference_mode()
def full_predict(model,frame,n,mean,scale,size,seed,device,bs=6):
    raw=np.zeros((n,2),np.float32)
    if frame is None:
        return raw, np.full(n,np.nan,np.float32)
    rng=np.random.default_rng(seed)
    votes=np.zeros((len(frame["points"]),2),np.float32)
    patches=iter(full_patches(frame["points"],size,rng))
    import itertools
    while True:
        chosen=list(itertools.islice(patches,bs))
        if not chosen:
            break
        tensors=batch([patch(frame,ix,mean,scale) for ix in chosen])
        prob=model(tensors).softmax(-1).detach().cpu().numpy()
        for ix,values in zip(chosen,prob):
            ids,inv,cnt=np.unique(ix,return_inverse=True,return_counts=True)
            unique_values=np.stack([np.bincount(inv,weights=col)/cnt for col in values.T],axis=1)
            votes[ids]=0.95*votes[ids]+0.05*unique_values
    if not np.all(votes.sum(1)>0):
        raise RuntimeError("uncovered voxel")
    raw[frame["rows"]]=votes[frame["proj"]]
    mass=raw.sum(1)
    score=np.divide(raw[:,1],mass,out=np.full(n,np.nan,np.float32),where=mass>0)
    return raw,score
