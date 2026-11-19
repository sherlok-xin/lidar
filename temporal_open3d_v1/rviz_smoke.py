import argparse
import hashlib
import json
import os
import pty
import signal
import socket
import subprocess
import sys
import time
import xmlrpc.client
from pathlib import Path

import rviz_review as rv


def port_free():
    with socket.socket() as chan:
        chan.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:chan.bind(("127.0.0.1",11439))
        except OSError:return False
    return True


def main():
    rv.guard()
    cli=argparse.ArgumentParser()
    cli.add_argument("--book",required=True,type=Path);cli.add_argument("--out",required=True,type=Path)
    opts=cli.parse_args()
    if not port_free():raise RuntimeError("11439 occupied: abort without contacting existing master")
    opts.out.mkdir(exist_ok=False,parents=True)
    casebook=json.loads(opts.book.read_text())["cases"]
    source=Path(__file__).with_name("rviz_review.py")
    env=os.environ.copy()
    core_file=(opts.out/"core.log").open("w")
    core=subprocess.Popen(["roscore","-p","11439"],stdout=core_file,stderr=subprocess.STDOUT,env=env,start_new_session=True)
    console=None;observed=[];closed=False
    deadline=time.monotonic()+15
    try:
        while True:
            if core.poll() is not None:raise RuntimeError("own roscore stopped")
            try:
                uri=xmlrpc.client.ServerProxy(rv.MASTER).getUri("/isolated_review_start_check")
                if uri[0]==1:break
            except OSError:pass
            if time.monotonic()>deadline:raise TimeoutError("own master startup")
            time.sleep(.2)
        import rospy
        from sensor_msgs.msg import PointCloud2
        rospy.init_node("mining_review_wire",anonymous=True,disable_signals=True)
        tty,slave=pty.openpty()
        controls=opts.out/"controls.jsonl"
        output=(opts.out/"player.log").open("w")
        console=subprocess.Popen([sys.executable,"-B",str(source),"play","--book",str(opts.book),
              "--log",str(controls)],stdin=slave,stdout=output,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        os.close(slave)
        def command(line):os.write(tty,(line+"\n").encode())
        def wait_seen(seq,timeout=12):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                if console.poll() is not None:raise RuntimeError("player exited")
                if controls.exists():
                    records=[json.loads(s) for s in controls.read_text().splitlines() if s.endswith("}")]
                    published=[r for r in records if r["event"]=="frame"]
                    if published and published[-1]["seq"]==seq:return
                time.sleep(.12)
            raise TimeoutError("publisher did not reach case "+str(seq))
        wait_seen(1)
        command("n");wait_seen(2);command("p");wait_seen(1)
        command("rate 3");command("play");wait_seen(2);command("pause")
        time.sleep(.7);command("status")
        for meta in casebook:
            command("seq "+str(meta["case"]));wait_seen(meta["case"])
            data=rv.clouds(rv.load_case(opts.book,meta))
            for key in rv.LAYERS:
                message=rospy.wait_for_message(rv.BASE+key,PointCloud2,timeout=5.)
                expected=rv.as_message(data[key],meta)
                if (message.data!=expected.data or message.header.stamp!=expected.header.stamp or
                    message.header.seq!=meta["case"] or message.header.frame_id!=meta["frame_id"] or
                    message.fields!=expected.fields or message.width!=len(data[key]) or
                    message.row_step!=len(data[key])*rv.DTYPE.itemsize or message.point_step!=rv.DTYPE.itemsize):
                    raise ValueError("wire mismatch "+key+" case "+str(meta["case"]))
                observed.append(dict(case=meta["case"],layer=key,width=message.width,sha256=hashlib.sha256(message.data).hexdigest()))
            selected=(["raw","reference","single","temporal","temporal_error","stable_core","smoothing_gain","past_context"]
                      if meta["domain"]=="uchile" else ["raw","reference","temporal","temporal_error","unavailable"])
            target=opts.out/("case_"+str(meta["case"]))
            with (opts.out/("viewer_"+str(meta["case"])+".log")).open("w") as viewer_log:
                subprocess.run([sys.executable,"-B",str(source),"view","--book",str(opts.book),"--case",
                            str(meta["case"]),"--layers",*selected,"--capture",str(target)],
                            env=env,stdout=viewer_log,stderr=subprocess.STDOUT,timeout=70,check=True)
        command("q")
        if console.wait(timeout=6)!=0:raise RuntimeError("player failed to close")
        closed=True
        rospy.signal_shutdown("own offline inspection completed")
    finally:
        if console is not None and console.poll() is None:
            console.terminate();console.wait(timeout=8)
        if core.poll() is None:os.killpg(core.pid,signal.SIGINT)
        core.wait(timeout=15)
        core_file.close()
        (opts.out/"wire.json").write_text(json.dumps(dict(complete=closed,wire=observed,
             count=len(observed),own_master_exit=core.returncode,port_free_after=port_free()),indent=2))


if __name__=="__main__":
    main()
