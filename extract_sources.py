import os
import tarfile
import zipfile
import shutil

# Paths relative to static-php-cli directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS = os.path.join(BASE_DIR, 'static-php-cli', 'downloads')
SOURCE = os.path.join(BASE_DIR, 'static-php-cli', 'source')


def extract_archive(archive_path, extract_to):
    # Extract archive to a temp directory first
    temp_dir = os.path.join(extract_to, "__temp_extract__")
    os.makedirs(temp_dir, exist_ok=True)
    try:
        if archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
            mode = 'r:gz'
        elif archive_path.endswith('.tar.xz'):
            mode = 'r:xz'
        elif archive_path.endswith('.tar.bz2'):
            mode = 'r:bz2'
        elif archive_path.endswith('.tar'):
            mode = 'r:'
        elif archive_path.endswith(('.zip', '.jar')):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            extracted = True
        else:
            print(f"Unknown archive format: {archive_path}")
            return False

        # Handle tar files
        if archive_path.endswith(('.tar', '.tar.gz', '.tar.xz', '.tgz', '.tar.bz2')):
            try:
                with tarfile.open(archive_path, mode) as tar:
                    tar.extractall(path=temp_dir)
                extracted = True
            except Exception as e:
                print(f"Error extracting {archive_path}: {str(e)}")
                return False

        # Move extracted files up if they are nested in a single subdirectory
        items = os.listdir(temp_dir)
        if len(items) == 1 and os.path.isdir(os.path.join(temp_dir, items[0])):
            nested_dir = os.path.join(temp_dir, items[0])
            for item in os.listdir(nested_dir):
                target_path = os.path.join(extract_to, item)
                if os.path.exists(target_path):
                    if os.path.isdir(target_path):
                        shutil.rmtree(target_path)
                    else:
                        os.remove(target_path)
                shutil.move(os.path.join(nested_dir, item), target_path)
        else:
            for item in items:
                target_path = os.path.join(extract_to, item)
                if os.path.exists(target_path):
                    if os.path.isdir(target_path):
                        shutil.rmtree(target_path)
                    else:
                        os.remove(target_path)
                shutil.move(os.path.join(temp_dir, item), target_path)
        return True
    except Exception as e:
        print(f"Error during extraction of {archive_path}: {str(e)}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def extract_all_archives_in_folder(folder):
    # Keep extracting as long as there are archives
    while True:
        archives = [f for f in os.listdir(folder) if f.endswith((
            '.tar.gz', '.tar.xz', '.tgz', '.tar.bz2', '.tar', '.zip', '.jar'))]
        if not archives:
            break
        for archive in archives:
            archive_path = os.path.join(folder, archive)
            print(f"Extracting {archive_path} to {folder}")
            if extract_archive(archive_path, folder):
                os.remove(archive_path)


def main():
    for src_dir in os.listdir(SOURCE):
        # Skip processing micro since we're using php bin/spc doctor --auto-fix
        if src_dir == "micro":
            continue

        src_path = os.path.join(SOURCE, src_dir)
        if os.path.isdir(src_path):
            # 1. Extract all archives found in the source folder (recursively)
            extract_all_archives_in_folder(src_path)
            # 2. If directory is empty or only contains archives, extract from downloads
            files = [f for f in os.listdir(src_path) if not f.endswith(
                ('.tar.gz', '.tar.xz', '.tgz', '.tar.bz2', '.tar', '.zip', '.jar'))]
            if not files:
                # Find the archive in downloads
                found = False
                for archive in os.listdir(DOWNLOADS):
                    # Skip micro file in downloads as well
                    if archive == "micro":
                        continue
                    if archive.lower().startswith(src_dir.lower()):
                        archive_path = os.path.join(DOWNLOADS, archive)
                        print(f"Extracting {archive_path} to {src_path}")
                        if extract_archive(archive_path, src_path):
                            os.remove(archive_path)
                        extract_all_archives_in_folder(src_path)
                        found = True
                        break
                if not found:
                    print(f"No archive found for {src_dir} in downloads.")


if __name__ == "__main__":
    main()
