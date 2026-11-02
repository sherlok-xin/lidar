#!/usr/bin/env python3
"""Export real native collaboration routing metadata; never invent message text."""
from pathlib import Path
import datetime,hashlib,json
D=Path(__file__).resolve().parents[1]
def main():
    registry=json.loads((D/'thread_registry.json').read_text())
    start=json.loads((D/'evidence/frozen_baseline.json').read_text())['captured_at']
    since=datetime.datetime.fromisoformat(start);rows=[]
    for a in registry['agents']:
        source=Path(a['session_meta_file'])
        with source.open()as f:
            first=json.loads(next(f))
            if first['payload']['id']!=a['thread_id']:raise ValueError('Real UUID mismatch')
            for line_no,line in enumerate(f,2):
                try:r=json.loads(line)
                except json.JSONDecodeError:continue
                timestamp=r.get('timestamp')
                if not timestamp:continue
                try:
                    if datetime.datetime.fromisoformat(timestamp.replace('Z','+00:00'))<since:continue
                except ValueError:continue
                p=r.get('payload',{});kind=None;extra={}
                if r.get('type')=='response_item'and p.get('type') in ('function_call','custom_tool_call'):
                    name=p.get('name','')
                    if 'collaboration' not in name and name not in ('send_message','followup_task','spawn_agent','wait_agent','list_agents','interrupt_agent'):continue
                    kind='collaboration_call';extra={'name':name,'call_id':p.get('call_id')}
                    try:args=json.loads(p.get('arguments','{}'))
                    except (TypeError,json.JSONDecodeError):args={}
                    for key in ('target','task_name'):
                        if key in args:extra[key]=args[key]
                    extra['message_body_exported']=False
                elif r.get('type')=='event_msg' and p.get('type') in ('agent_message','agent_status'):
                    kind=p['type']
                    for key in ('author','recipient','event_id','agent_id','status'):
                        if key in p:extra[key]=p[key]
                if kind:
                    rows.append(dict(timestamp=timestamp,session_thread=a['thread_id'],
                        session_meta_path=str(source),source_line=line_no,
                        source_line_sha256=hashlib.sha256(line.encode()).hexdigest(),kind=kind,**extra))
    rows.sort(key=lambda x:(x['timestamp'],x['session_thread'],x['source_line']))
    dest=D/'communications/native_events.jsonl'
    dest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in rows))
    summary=dict(captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        since=start,threads=6,native_events=len(rows),message_bodies_exported=False,
        scope='Routing/hash/source line metadata only. LOG.md is MASTER paraphrase, not verbatim.',
        exported_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    (D/'communications/native_events_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))
if __name__=='__main__':main()
