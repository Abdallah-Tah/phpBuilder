import os
import tarfile
import zipfile
import shutil
from pathlib import Path


def ensure_directories(base_dir):
    """Ensure required directories exist"""
    downloads = os.path.join(base_dir, 'downloads')
    source = os.path.join(base_dir, 'source')
    for path in [downloads, source]:
        os.makedirs(path, exist_ok=True)
    return downloads, source


def find_main_source_dir(temp_dir, lib_name):
    """Find the main source directory in extracted contents"""
    contents = os.listdir(temp_dir)

    # Look for exact match or version-specific folder
    for item in contents:
        item_path = os.path.join(temp_dir, item)
        if os.path.isdir(item_path):
            if item == lib_name or item.startswith(f"{lib_name}-"):
                return item_path

    # If no specific match found and only one directory exists, use that
    dirs = [d for d in contents if os.path.isdir(os.path.join(temp_dir, d))]
    if len(dirs) == 1:
        return os.path.join(temp_dir, dirs[0])

    # Otherwise return temp_dir itself
    return temp_dir


def extract_archive(archive_path, extract_to):
    """Extract an archive file to the specified directory"""
    print(f"Extracting {archive_path} to {extract_to}")
    os.makedirs(extract_to, exist_ok=True)
    temp_dir = os.path.join(extract_to, "__temp_extract__")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # Get library name from the folder name
        lib_name = os.path.basename(extract_to)
        if archive_path.endswith('.tar'):
            print(f"Extracting tar file: {archive_path}")
            with tarfile.open(archive_path, 'r:') as tar:
                tar.extractall(path=temp_dir)
        elif archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
            print(f"Extracting tar.gz/tgz file: {archive_path}")
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(path=temp_dir)
        elif archive_path.endswith('.tar.xz'):
            print(f"Extracting tar.xz file: {archive_path}")
            with tarfile.open(archive_path, 'r:xz') as tar:
                tar.extractall(path=temp_dir)
        elif archive_path.endswith('.tar.bz2'):
            print(f"Extracting tar.bz2 file: {archive_path}")
            with tarfile.open(archive_path, 'r:bz2') as tar:
                tar.extractall(path=temp_dir)
        elif archive_path.endswith(('.zip', '.jar')):
            print(f"Extracting zip/jar file: {archive_path}")
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
        else:
            print(f"Unknown archive format: {archive_path}")
            return False

        # Find the actual source directory
        source_dir = find_main_source_dir(temp_dir, lib_name)
        print(f"Found source directory: {source_dir}")

        # Move contents directly to target directory
        for item in os.listdir(source_dir):
            src_path = os.path.join(source_dir, item)
            dst_path = os.path.join(extract_to, item)

            # Remove existing before moving
            if os.path.exists(dst_path):
                if os.path.isdir(dst_path):
                    shutil.rmtree(dst_path)
                else:
                    os.remove(dst_path)

            # Move the item
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

        print(f"Successfully extracted {archive_path}")
        return True

    except Exception as e:
        print(f"Error extracting {archive_path}: {str(e)}")
        return False
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def extract_all_archives_in_folder(folder):
    """Extract all archives in a folder"""
    print(f"Checking for archives in: {folder}")
    archives_found = False
    for file in os.listdir(folder):
        if file.endswith(('.tar', '.tar.gz', '.tar.xz', '.tgz', '.tar.bz2', '.zip', '.jar')):
            archives_found = True
            archive_path = os.path.join(folder, file)
            print(f"Found archive: {file}")
            extract_archive(archive_path, folder)
    if not archives_found:
        print(f"No archives found in {folder}")


def main(base_dir=None):
    # Use provided base_dir or default to script location
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), 'static-php-cli')

    print(f"Starting extraction process in: {base_dir}")
    # First ensure all required directories exist
    downloads, source = ensure_directories(base_dir)
    print(f"Using source directory: {source}")

    # Process each source directory
    for dir_name in os.listdir(source):
        src_dir = os.path.join(source, dir_name)
        if os.path.isdir(src_dir):
            print(f"\nProcessing directory: {dir_name}")
            extract_all_archives_in_folder(src_dir)


if __name__ == "__main__":
    main()
