#!/usr/bin/env python3
"""Actual local Chrome DOM/screenshot verification, with all profiles in OPDF."""
from pathlib import Path
import os,subprocess,json,re
R=Path(__file__).resolve().parents[1];E=R/'evidence'
env=dict(os.environ)
for k,v in {'TMPDIR':str(R/'.cache/qa_chrome_tmp'),'XDG_CACHE_HOME':str(R/'.cache/qa_chrome_xdg'),'XDG_CONFIG_HOME':str(R/'.cache/qa_chrome_config')}.items():
 env[k]=v;Path(v).mkdir(parents=True,exist_ok=True)
base=['/usr/bin/google-chrome','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
      '--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run',
      '--no-default-browser-check','--disable-crash-reporter','--disable-breakpad',
      '--user-data-dir='+str(R/'.chrome-qa'),'--disk-cache-dir='+str(R/'.cache/qa_chrome_disk'),
      '--virtual-time-budget=2000','--window-size=1440,1080']
html=R/'outputs/v1b_real9_final/cases/aerosol_surface_ambiguity/review.html'
url=html.as_uri()+'?selftest=1'
cmd=base+['--dump-dom',url];run=subprocess.run(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=25)
(E/'qa_browser_dom.html').write_text(run.stdout);(E/'qa_browser_stderr.log').write_text(run.stderr)
rendered='data-rendered="true"' in run.stdout;passed='data-selftest="PASS"' in run.stdout
match=re.search(r'<div id="selftest">(.*?)</div>',run.stdout,re.S)
selftest=json.loads(match.group(1))if match else None
shot=base+['--screenshot='+str(E/'qa_browser.png'),url];s=subprocess.run(shot,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=25)
(E/'qa_browser_screenshot.log').write_text(s.stdout+s.stderr)
out={'date_local':'2026-10-31','actual_headless_chrome':True,'dom_command':cmd,'dom_exit':run.returncode,
     'dom_rendered':rendered,'dom_selftest_pass':passed,'selftest':selftest,
     'screenshot_command':shot,'screenshot_exit':s.returncode,'screenshot_exists':(E/'qa_browser.png').is_file(),
     'scope':'Actual generated final-run ROI page executed in Chrome; headless shared-camera projection check, not RViz/OS screen or independent semantics'}
(E/'qa_browser_check.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
assert run.returncode==0 and passed and rendered and selftest['shared_camera'] and s.returncode==0 and out['screenshot_exists']
