import os, shutil, subprocess, tempfile, sys, json

print("Python executable:", sys.executable)
print("Current working dir:", os.getcwd())
print("PATH contains gcc dir?:", any('gcc' in p.lower() or 'mingw' in p.lower() or 'msys' in p.lower() for p in os.environ.get("PATH","").split(os.pathsep)))
print("shutil.which('gcc') ->", shutil.which("gcc"))
try:
    r = subprocess.run(["gcc", "--version"], capture_output=True, text=True, shell=False, timeout=5)
    print("gcc --version (returncode):", r.returncode)
    print("gcc --version stdout (first line):", (r.stdout or r.stderr).splitlines()[0])
except Exception as e:
    print("Error running gcc --version:", e)

# Try compiling a simple small C file in a temporary directory (mimics your grader)
c_src = 'int main(){return 0;}'
with tempfile.TemporaryDirectory() as td:
    c_path = os.path.join(td, "test_temp.c")
    exe_path = os.path.join(td, "test_temp.exe")
    with open(c_path, "w", encoding="utf-8") as f:
        f.write(c_src)
    print("Temp dir:", td)
    try:
        cp = subprocess.run(["gcc", c_path, "-o", exe_path], capture_output=True, text=True, shell=False, timeout=10)
        print("compile returncode:", cp.returncode)
        print("compile stdout:", repr(cp.stdout)[:400])
        print("compile stderr:", repr(cp.stderr)[:400])
        exists = os.path.exists(exe_path)
        print("exe created?:", exists)
        if exists:
            try:
                rr = subprocess.run([exe_path], capture_output=True, text=True, shell=False, timeout=5)
                print("run returncode:", rr.returncode)
                print("run stdout/stderr:", (rr.stdout or rr.stderr)[:200])
            except Exception as e:
                print("running exe error:", e)
    except Exception as e:
        print("Compilation exception:", e)
