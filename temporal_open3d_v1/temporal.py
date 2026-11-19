"""Causal observation-support features for fixed-sensor public mining sequences."""
import hashlib

import numpy as np
from scipy.spatial import cKDTree


FINE, COARSE, REGION = .10, .30, .60
GROUPS = {
    "S": ("x", "y", "z", "range", "log_intensity", "fine_count", "coarse_count",
          "neighbor_median", "neighbor_max", "linearity", "planarity", "surface_variation"),
    "F0": ("dx", "dy", "dz", "nn", "neighbor_median", "log_intensity_residual", "available"),
    "F1": ("fine_support", "coarse_support", "short_long_delta", "appearance", "disappearance",
           "recurrence", "soft_jaccard", "turnover", "history_fraction", "comparable_fraction"),
    "F2": ("static_residual", "translation_residual", "forward_coverage", "backward_coverage",
           "motion_norm", "improvement", "degenerate", "motion_available"),
    "F3": ("extent_delta", "centroid_residual", "eigen_ratio_delta", "normal_agreement",
           "stable_core", "periphery_update", "normal_available", "available"),
    "F4": ("translation_error", "smoothed_error", "gain", "mixing", "smoothing_displacement",
           "fit_confidence", "available"),
    "REC": ("decayed_support", "decayed_change", "last_supported_lag", "support_conflict"),
    "MASK": ("available", "history_fraction", "comparable_fraction", "motion_available"),
    "ACC": ("accumulated_fine", "accumulated_coarse", "observed_frames", "available"),
}
EXTRA = ("F0","F1","F2","F3","F4","REC","MASK","ACC")
NAMES = ("nn", "fine_support", "coarse_support", "translation_residual", "stable_core",
         "smoothed_prediction_gain", "decayed_support", "available")
FAMILY = {"S": ("S",), "T2": ("S","F0"), "TK": ("S","F1","F2","F3"),
          "TK_F4": ("S","F1","F2","F3","F4"), "TK_REC": ("S","F1","F2","F3","REC"),
          "TF": ("S","F1","F2","F3","F4","REC"), "MASK": ("S","MASK"),
          "ACC": ("S","ACC"), "COPY": ("S","F1","F2","F3","F4","REC"),
          "SHUFFLE": ("S","F1","F2","F3","F4","REC"),
          "DISTANT": ("S","F1","F2","F3","F4","REC"),
          "TK3": ("S","F1","F2","F3"), "LAG2": ("S","F0"), "LAG4": ("S","F0")}


def valid_rows(frame):
    return np.isfinite(frame["xyz"]).all(1) & np.isfinite(np.asarray(frame["intensity"]).reshape(-1))


def clean(frame):
    keep = valid_rows(frame)
    return np.asarray(frame["xyz"], dtype=np.float64)[keep], np.asarray(frame["intensity"]).reshape(-1)[keep]


def digest_seed(text):
    return int.from_bytes(hashlib.sha256(str(text).encode()).digest()[:4], "little")


def voxel_key(cells):
    values = np.asarray(cells, dtype=np.int64) + 1048576
    if np.any(values < 0) or np.any(values >= 2097152):
        raise ValueError("coordinate out of supported processed-unit grid; not wrapped")
    return (values[:,0] << 42) | (values[:,1] << 21) | values[:,2]


class Field:
    def __init__(self, xyz, scale, moments=False):
        self.scale = scale
        keys = voxel_key(np.floor(xyz / scale))
        self.keys, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
        inverse = inverse.reshape(-1)
        self.count = np.r_[0,counts].astype(np.float64)
        if moments:
            mean = np.stack([np.bincount(inverse, weights=xyz[:,axis]) / counts for axis in range(3)], 1)
            spread = xyz - mean[inverse]
            covariance = np.empty((len(counts),3,3))
            for first in range(3):
                for second in range(first+1):
                    term = np.bincount(inverse, weights=spread[:,first]*spread[:,second]) / counts
                    covariance[:,first,second] = covariance[:,second,first] = term
            eigen, basis = np.linalg.eigh(covariance)
            self.mean = np.vstack([np.zeros(3),mean])
            self.eigen = np.vstack([np.zeros(3),np.maximum(eigen,0)])
            self.normal = np.vstack([np.zeros(3),basis[:,:,0]])

    def addresses(self, xyz):
        if not len(self.keys):
            return np.zeros(len(xyz),dtype=np.int64)
        keys = voxel_key(np.floor(xyz / self.scale))
        loc = np.searchsorted(self.keys, keys).clip(0,len(self.keys)-1)
        return np.where(self.keys[loc] == keys, loc+1, 0)

    def q(self, xyz):
        return -np.expm1(-self.count[self.addresses(xyz)] / 3.)

    def smooth(self, xyz, central):
        side = np.zeros_like(central)
        for axis in range(3):
            offset = np.zeros(3)
            offset[axis] = self.scale
            side += self.q(xyz+offset) + self.q(xyz-offset)
        return side / 6.


class Observation:
    def __init__(self, frame):
        self.xyz, self.intensity = clean(frame)
        if not len(self.xyz):
            raise ValueError("empty or nonfinite observation")
        self.fine = Field(self.xyz,FINE)
        self.coarse = Field(self.xyz,COARSE)
        self.region = Field(self.xyz,REGION,True)
        self.tree = cKDTree(self.xyz)
        self.bounds = (self.xyz.min(0),self.xyz.max(0))

    def comparable(self, positions):
        lower,upper = self.bounds
        return (np.all((positions >= lower-FINE) & (positions <= upper+FINE),axis=1)
                & (self.region.count[self.region.addresses(positions)] > 0))


def columns(*vectors):
    return np.column_stack(vectors).astype(np.float32,copy=False)


def static_features(current, positions, intensity):
    distances, indices = current.tree.query(positions, k=list(range(1,min(8,len(current.xyz))+1)))
    neighbors = current.xyz[indices]
    offsets = neighbors-neighbors.mean(1,keepdims=True)
    eigen = np.maximum(0,np.linalg.eigvalsh(offsets.transpose(0,2,1) @ offsets / indices.shape[1]))
    denom = np.maximum(1e-9,eigen[:,-1])
    return columns(*positions.T,np.linalg.norm(positions,axis=1),np.arcsinh(intensity),
                   np.log1p(current.fine.count[current.fine.addresses(positions)]),
                   np.log1p(current.coarse.count[current.coarse.addresses(positions)]),
                   np.median(distances,axis=1),distances[:,-1],(eigen[:,2]-eigen[:,1])/denom,
                   (eigen[:,1]-eigen[:,0])/denom,eigen[:,0]/np.maximum(1e-9,eigen.sum(1)))


def lag_features(previous, xyz, intensity):
    distance, index = previous.tree.query(xyz,k=list(range(1,min(4,len(previous.xyz))+1)))
    residual = xyz-previous.xyz[index[:,0]]
    available = previous.comparable(xyz)
    out = columns(*residual.T,distance[:,0],np.median(distance,axis=1),
                  np.arcsinh(intensity)-np.arcsinh(previous.intensity[index[:,0]]),available)
    out[~available]=0
    return out


def transfer(points, world_current, world_history):
    transforms = [np.asarray(item,np.float64) for item in (world_current,world_history)]
    for matrix in transforms:
        if (matrix.shape!=(4,4) or not np.isfinite(matrix).all()
                or not np.allclose(matrix[3],[0,0,0,1])
                or not np.allclose(matrix[:3,:3].T @ matrix[:3,:3],np.eye(3),atol=1e-5)
                or not np.isclose(np.linalg.det(matrix[:3,:3]),1,atol=1e-5)):
            raise ValueError("expected proper rigid homogeneous transform")
    relative = np.linalg.solve(*transforms)
    return np.asarray(points) @ relative[:3,:3].T + relative[:3,3]


def past_shift(older, previous, points):
    idx0,idx1 = older.region.addresses(points),previous.region.addresses(points)
    supported = (older.region.count[idx0]>=6) & (previous.region.count[idx1]>=6)
    drift = previous.region.mean[idx1]-older.region.mean[idx0]
    norm = np.linalg.norm(drift,axis=1)
    supported &= norm <= REGION*.55
    supported &= (previous.region.eigen[idx1,1] > 1e-6)
    drift[~supported] = 0
    return drift,supported


def mixing(history):
    if len(history)<3:
        return 0.,0.
    oldest,older,previous = history[-3:]
    evaluation = np.concatenate([previous.xyz[::max(1,len(previous.xyz)//2048)],
                                  older.xyz[::max(1,len(older.xyz)//2048)]])
    drift,supported = past_shift(oldest,older,evaluation)
    keep = previous.comparable(evaluation) & older.comparable(evaluation-drift) & supported
    if not keep.any():
        return 0.,0.
    test,source = evaluation[keep],(evaluation-drift)[keep]
    base = older.fine.q(source)
    deviation = older.fine.smooth(source,base)-base
    numerator = np.mean(deviation*(previous.fine.q(test)-base))
    denominator = np.mean(deviation*deviation)
    return float(np.clip(numerator/(denominator+.02),0,.5)), float(denominator/(denominator+.02))


def histories(current, xyz, intensity, history, need_f0=True):
    zero = {key:np.zeros((len(xyz),len(GROUPS[key])),np.float32) for key in EXTRA}
    if not history or not len(xyz):
        return zero
    previous = history[-1]
    if need_f0:
        zero["F0"] = lag_features(previous,xyz,intensity)
    fine = np.stack([item.fine.q(xyz) for item in history])
    coarse = np.stack([item.coarse.q(xyz) for item in history])
    comparable = np.stack([item.comparable(xyz) for item in history])
    count = comparable.sum(0)
    recent_ok = comparable[-1]
    available = (count>=min(3,len(history))) & recent_ok
    current_q = current.fine.q(xyz)
    support = fine>0
    sum_valid = lambda values: (values*comparable).sum(0)/np.maximum(count,1)
    fine_support = sum_valid(support)
    coarse_support = sum_valid(coarse>0)
    have = np.full(len(xyz),len(history)/9)
    update = current_q-fine[-1]
    if len(history)>1:
        pair = comparable[1:] & comparable[:-1]
        transitions = ((support[1:]!=support[:-1])*pair).sum(0)/np.maximum(pair.sum(0),1)
    else:
        transitions = np.zeros(len(xyz))
    observed_support = support & comparable
    prior = np.cumsum(observed_support,axis=0)>0
    returned = observed_support[-1] & (prior & ~support & comparable).any(0)
    union = np.maximum(current_q,fine)
    intersection = np.minimum(current_q,fine)
    short = min(3,len(history))
    recent = (fine[-short:]*comparable[-short:]).sum(0)/np.maximum(1,comparable[-short:].sum(0))
    zero["F1"] = columns(fine_support,coarse_support,recent-sum_valid(fine),np.maximum(update,0),
                         np.maximum(-update,0),returned,sum_valid(intersection/np.maximum(union,1e-6)),
                         transitions,have,count/len(history))
    if len(history)>=2:
        drift, motion = past_shift(history[-2],previous,xyz)
    else:
        drift,motion = np.zeros_like(xyz),np.zeros(len(xyz),bool)
    source = xyz-drift
    fixed = previous.tree.query(xyz,k=1)[0]
    ahead = previous.tree.query(source,k=1)[0]
    if len(history)>=2:
        backward_shift,back_ok = past_shift(history[-2],previous,previous.xyz)
    else:
        backward_shift,back_ok = np.zeros_like(previous.xyz),np.zeros(len(previous.xyz),bool)
    incoming = previous.xyz[back_ok]+backward_shift[back_ok]
    back_distance = current.tree.query(incoming,k=1)[0]
    back_region = current.region.addresses(incoming)
    threshold = FINE*2
    region = current.region.addresses(xyz)
    bins = len(current.region.count)
    back_count = np.bincount(back_region,minlength=bins)
    back_sum = np.bincount(back_region,weights=np.minimum(back_distance,threshold),minlength=bins)
    back_residual = back_sum[region]/np.maximum(1,back_count[region])
    reverse_support = np.bincount(back_region,weights=(back_distance<threshold),minlength=bins)
    reverse_fraction = reverse_support[region]/np.maximum(1,back_count[region])
    motion &= (back_count[region]>=3)
    robust = .5*(np.minimum(ahead,threshold)+back_residual)
    if len(history)>=2:
        full_region=current.region.addresses(current.xyz)
        full_drift,full_ok=past_shift(history[-2],previous,current.xyz)
        full_ok &= (back_count[full_region]>=3)
        full_forward=previous.tree.query(current.xyz[full_ok]-full_drift[full_ok],k=1)[0]
        total=np.bincount(full_region[full_ok],minlength=bins)
        close=np.bincount(full_region[full_ok],weights=(full_forward<threshold),minlength=bins)
        forward_fraction=close[region]/np.maximum(1,total[region])
    else:
        forward_fraction=np.zeros(len(xyz))
    zero["F2"] = columns(np.minimum(fixed,threshold),robust,forward_fraction,
                         reverse_fraction,np.linalg.norm(drift,axis=1),
                         np.minimum(fixed,threshold)-robust,~motion,motion)
    zero["F2"][~motion,1:6]=0
    old = previous.region.addresses(source)
    eig0,eig1 = previous.region.eigen[old],current.region.eigen[region]
    stable = (previous.region.count[old]>=6) & (current.region.count[region]>=6) & motion
    normal_ok = stable & ((eig0[:,1]-eig0[:,0])>1e-5) & ((eig1[:,1]-eig1[:,0])>1e-5)
    axes = np.abs(np.sum(previous.region.normal[old]*current.region.normal[region],axis=1))*normal_ok
    ratio = lambda eigen: eigen/np.maximum(eigen.sum(axis=1,keepdims=True),1e-9)
    shifted = previous.fine.q(source)
    core = np.minimum(current_q,shifted)
    zero["F3"] = columns(np.sqrt(eig1.sum(1))-np.sqrt(eig0.sum(1)),
                         np.linalg.norm(previous.region.mean[old]+drift-current.region.mean[region],axis=1),
                         np.linalg.norm(ratio(eig0)-ratio(eig1),axis=1),axes,core,
                         np.abs(current_q-shifted),normal_ok,stable)
    zero["F3"][~stable]=0
    alpha,reliability = mixing(history)
    smooth = previous.fine.smooth(source,shifted)
    error = np.abs(current_q-shifted)
    blended = shifted+alpha*(smooth-shifted)
    smoothed_error = np.abs(current_q-blended)
    active = motion & stable & (len(history)>=3) & (reliability>0)
    zero["F4"] = columns(error,smoothed_error,error-smoothed_error,np.full(len(xyz),alpha),
                         np.abs(blended-shifted),np.full(len(xyz),reliability),active)
    zero["F4"][~active]=0
    age = np.arange(len(history))[::-1,None]
    weights = (.7**age)*comparable
    denom = np.maximum(1e-9,weights.sum(0))
    fused = (weights*fine).sum(0)/denom
    lag = np.where(support & comparable,age+1,10).min(0)
    zero["REC"] = columns(fused,(weights*np.abs(current_q-fine)).sum(0)/denom,lag/10.,
                          (weights*(fine-fused)**2).sum(0)/denom)
    zero["MASK"] = columns(available,have,count/len(history),motion)
    zero["ACC"] = columns(np.log1p(np.stack([item.fine.count[item.fine.addresses(xyz)] for item in history]).sum(0)),
                          np.log1p(np.stack([item.coarse.count[item.coarse.addresses(xyz)] for item in history]).sum(0)),
                          have,available)
    for key in ("F1","F2","F3","F4","REC","ACC"):
        zero[key][~available] = 0
    return zero


def network_features(current, history):
    out = np.zeros((len(current["xyz"]),len(NAMES)),np.float32)
    valid = valid_rows(current)
    if not history or not valid.any():
        return out
    previous = [Observation(frame) for frame in history[-9:] if valid_rows(frame).any()]
    if len(previous)!=len(history[-9:]):
        return out
    obs = Observation(current)
    feature = histories(obs,obs.xyz,obs.intensity,previous)
    out[valid] = columns(feature["F0"][:,3],feature["F1"][:,0],feature["F1"][:,1],
                         feature["F2"][:,1],feature["F3"][:,4],feature["F4"][:,2],
                         feature["REC"][:,0],feature["MASK"][:,0])
    return out
