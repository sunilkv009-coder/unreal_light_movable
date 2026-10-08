# Builds and runs the Camera Match solver unit tests (tests/camera_match/solver_tests.cpp).
# Needs a C++17 compiler (g++ or clang++). The solver has no Unreal dependencies.
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOLVER_DIR = os.path.join(ROOT, "CameraMatch", "Source", "CameraMatch", "Private")
SOURCES = [os.path.join(HERE, "camera_match", "solver_tests.cpp"), os.path.join(SOLVER_DIR, "CameraMatchSolver.cpp")]

# Close to Unreal's own strictness: shadowed variables and conversions are errors there.
FLAGS = ["-std=c++17", "-O1", "-Wall", "-Wextra", "-Wshadow", "-Wconversion", "-Werror"]


def main():
    compiler = next((c for c in (os.environ.get("CXX"), "g++", "clang++") if c and shutil.which(c)), None)
    if not compiler:
        print("SKIPPED: no C++ compiler found (set CXX, or install g++ or clang++).")
        return 0
    out_dir = tempfile.mkdtemp()
    exe = os.path.join(out_dir, "camera_match_solver_tests")
    build = subprocess.run([compiler, *FLAGS, "-I", SOLVER_DIR, *SOURCES, "-o", exe])
    if build.returncode != 0:
        print("BUILD FAILED")
        return build.returncode
    run = subprocess.run([exe])
    shutil.rmtree(out_dir, ignore_errors=True)
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
