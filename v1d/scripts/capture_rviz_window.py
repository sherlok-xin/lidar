#!/usr/bin/env python3
"""Capture only an explicitly selected, real RViz X11 window (Noetic Python3.8)."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import time

def windows(display):
    x=C.CDLL('libX11.so.6'); W=C.c_ulong
    x.XOpenDisplay.argtypes=[C.c_char_p];x.XOpenDisplay.restype=C.c_void_p
    d=x.XOpenDisplay(display.encode())
    if not d:raise RuntimeError('Cannot connect to actual X11 display')
    x.XDefaultRootWindow.argtypes=[C.c_void_p];x.XDefaultRootWindow.restype=W
    root=x.XDefaultRootWindow(d)
    x.XQueryTree.argtypes=[C.c_void_p,W,C.POINTER(W),C.POINTER(W),C.POINTER(C.POINTER(W)),C.POINTER(C.c_uint)]
    x.XFetchName.argtypes=[C.c_void_p,W,C.POINTER(C.c_char_p)]
    x.XInternAtom.argtypes=[C.c_void_p,C.c_char_p,C.c_int];x.XInternAtom.restype=W
    x.XGetWindowProperty.argtypes=[C.c_void_p,W,W,C.c_long,C.c_long,C.c_int,W,C.POINTER(W),C.POINTER(C.c_int),C.POINTER(W),C.POINTER(W),C.POINTER(C.POINTER(C.c_ubyte))]
    x.XFree.argtypes=[C.c_void_p]
    atom=x.XInternAtom(d,b'_NET_WM_PID',0);rows=[]
    def walk(w,depth):
        name=C.c_char_p();title=''
        if x.XFetchName(d,w,C.byref(name)) and name:
            title=name.value.decode(errors='replace');x.XFree(C.cast(name,C.c_void_p))
        at=W();fmt=C.c_int();n=W();after=W();prop=C.POINTER(C.c_ubyte)();pid=None
        if x.XGetWindowProperty(d,w,atom,0,1,0,6,C.byref(at),C.byref(fmt),C.byref(n),C.byref(after),C.byref(prop))==0 and prop:
            if fmt.value==32 and n.value:pid=C.cast(prop,C.POINTER(W))[0]
            x.XFree(prop)
        if title:rows.append(dict(window=int(w),title=title,pid=int(pid) if pid else None))
        if depth<=0:return
        rr=W();pp=W();kids=C.POINTER(W)();count=C.c_uint()
        if x.XQueryTree(d,w,C.byref(rr),C.byref(pp),C.byref(kids),C.byref(count)):
            ids=[kids[i] for i in range(min(count.value,2048))]
            if kids:x.XFree(kids)
            for child in ids:walk(child,depth-1)
    walk(root,3)
    return x,d,rows

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pid',type=int);p.add_argument('--output');p.add_argument('--list',action='store_true');a=p.parse_args()
    x,d,rows=windows(os.environ.get('DISPLAY',':1'))
    if a.list:print(json.dumps(rows));return
    matches=[r for r in rows if r['pid']==a.pid and 'rviz' in r['title'].lower()]
    if len(matches)!=1:raise RuntimeError('Expected one own RViz window; matches='+repr(matches))
    r=matches[0];out=Path(a.output).resolve();base=Path(__file__).resolve().parents[1]
    try:out.relative_to(base)
    except ValueError:raise ValueError('Screenshot output must remain in V1-C')
    x.XRaiseWindow.argtypes=[C.c_void_p,C.c_ulong]
    # The client can be reparented into a window-manager frame. Raising only
    # its child does not necessarily uncover it; raise its own top ancestor.
    top=r['window'];W=C.c_ulong
    for _ in range(8):
        root=W();parent=W();kids=C.POINTER(W)();count=C.c_uint()
        if not x.XQueryTree(d,top,C.byref(root),C.byref(parent),C.byref(kids),C.byref(count)):break
        if kids:x.XFree(kids)
        if parent.value in (0,root.value):break
        top=parent.value
    x.XRaiseWindow(d,top);x.XRaiseWindow(d,r['window'])
    x.XSetInputFocus.argtypes=[C.c_void_p,C.c_ulong,C.c_int,C.c_ulong]
    x.XSetInputFocus(d,r['window'],2,0)
    x.XSync.argtypes=[C.c_void_p,C.c_int];x.XSync(d,0);time.sleep(.3)
    from PyQt5.QtWidgets import QApplication
    app=QApplication([]);app.processEvents();pix=app.primaryScreen().grabWindow(r['window'])
    if pix.isNull() or pix.width()<200 or pix.height()<200:raise RuntimeError('Actual RViz capture failed')
    out.parent.mkdir(parents=True,exist_ok=True)
    if not pix.save(str(out)):raise RuntimeError('Could not save actual RViz screenshot')
    r.update(width=pix.width(),height=pix.height(),display=os.environ.get('DISPLAY'),scope='actual own RViz X11 window only; no synthetic rendering')
    out.with_suffix('.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))

if __name__=='__main__':main()
