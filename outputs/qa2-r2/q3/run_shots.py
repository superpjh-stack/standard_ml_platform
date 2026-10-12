"""6개사 순서대로 서버(8214) 기동 → shots.py <label> <t> <role> → 종료. 사용: run_shots.py <label> <role> [tenants...]"""
import subprocess, sys
from qa_lib import Server, SP
label, role = sys.argv[1:3]
for t in sys.argv[3:] or ["ks", "sw", "krs", "pc", "ot", "kd"]:
    s = Server(t)
    try:
        subprocess.run([sys.executable, "shots.py", label, t, role], check=True)
    finally:
        s.close()
