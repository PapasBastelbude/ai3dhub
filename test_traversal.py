from pathlib import Path

TEMP_DIR = Path("uploads/temp").resolve()

def test_path(filename):
    print("filename:", filename)
    file_location = Path("uploads/temp") / filename
    print("resolved:", file_location.resolve())
    print("is_relative_to:", file_location.resolve().is_relative_to(TEMP_DIR))
    print("-----")

test_path("../../../etc/passwd")
test_path("normal.txt")
