import fcntl, json, subprocess, sys
from pathlib import Path
results = []
for directory in (Path('/tmp'), Path('/evidence')):
    path = directory / 'authored-lock-probe'
    with path.open('xb') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        child = subprocess.run([sys.executable, '-c', "import fcntl,sys; f=open(sys.argv[1],'rb'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)", str(path)], capture_output=True, text=True)
        results.append(dict(directory=str(directory), child_exit=child.returncode, excluded='BlockingIOError' in child.stderr, stderr=child.stderr))
    path.unlink()
print(json.dumps(results, indent=2))
