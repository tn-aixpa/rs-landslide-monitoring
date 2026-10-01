import glob
import os


def delete_all_from_folder(folder: str):
    """
    Not recursive, only deletes files
    """
    files = glob.glob(f"{folder}/*")
    for f in files:
        os.remove(f)
