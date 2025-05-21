import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tarfile
import zipfile
import shutil
import os

from core.builder import PHPBuilder
from utils.logger import Logger # Assuming Logger can be instantiated directly for basic mocking
from utils.config_manager import ConfigurationManager # For type hinting mock

class TestPHPBuilder(unittest.TestCase):

    def setUp(self):
        """Set up for test methods."""
        # Mock Logger
        self.mock_logger = MagicMock(spec=Logger)
        
        # Instantiate PHPBuilder with the mocked logger
        self.builder = PHPBuilder(logger=self.mock_logger)
        
        # Set up a mock ConfigurationManager instance on self.builder.config_manager
        # This mock will be used by _get_library_version and potentially other methods.
        self.mock_config_manager = MagicMock(spec=ConfigurationManager)
        self.builder.config_manager = self.mock_config_manager

        # Temp directory for archive extraction tests
        self.test_temp_dir = Path(__file__).resolve().parent / "temp_phpbuilder_tests"
        if self.test_temp_dir.exists():
            shutil.rmtree(self.test_temp_dir)
        self.test_temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up after test methods."""
        if self.test_temp_dir.exists():
            shutil.rmtree(self.test_temp_dir)

    # --- Tests for _get_extensions ---
    def testGetExtensions_Default(self):
        """Test _get_extensions with default configuration (no special flags)."""
        config = {}
        extensions = self.builder._get_extensions(config)
        self.assertIn("openssl", extensions)
        self.assertNotIn("pdo_mysql", extensions)
        self.assertNotIn("sqlsrv", extensions)
        self.assertNotIn("pgsql", extensions)

    def testGetExtensions_WithMySQL(self):
        """Test _get_extensions when MySQL is enabled."""
        config = {'mysql': True}
        extensions = self.builder._get_extensions(config)
        self.assertIn("pdo_mysql", extensions)
        self.assertIn("mysqli", extensions)
        self.assertIn("mysqlnd", extensions)

    def testGetExtensions_WithSQLSRV(self):
        """Test _get_extensions when SQLSRV is enabled."""
        config = {'sqlsrv': True}
        extensions = self.builder._get_extensions(config)
        self.assertIn("sqlsrv", extensions)
        self.assertIn("pdo_sqlsrv", extensions)

    def testGetExtensions_WithPgSQL(self):
        """Test _get_extensions when PgSQL is enabled."""
        config = {'pgsql': True}
        extensions = self.builder._get_extensions(config)
        self.assertIn("pgsql", extensions)
        self.assertIn("pdo_pgsql", extensions)

    def testGetExtensions_AllSpecials(self):
        """Test _get_extensions with all special database flags enabled."""
        config = {'mysql': True, 'sqlsrv': True, 'pgsql': True}
        extensions = self.builder._get_extensions(config)
        self.assertIn("pdo_mysql", extensions)
        self.assertIn("sqlsrv", extensions)
        self.assertIn("pgsql", extensions)

    # --- Tests for _get_libraries ---
    def testGetLibraries_Default(self):
        """Test _get_libraries with default configuration."""
        config = {}
        libraries = self.builder._get_libraries(config)
        self.assertIn("openssl", libraries) # A common default library
        self.assertNotIn("pdo_sqlsrv", libraries) # sqlsrv is not default
        self.assertNotIn("postgresql", libraries) # pgsql is not default

    def testGetLibraries_WithSQLSRV(self):
        """Test _get_libraries when SQLSRV is enabled."""
        config = {'sqlsrv': True}
        libraries = self.builder._get_libraries(config)
        # Based on current PHPBuilder logic, 'sqlsrv' and 'pdo_sqlsrv' are added as library names
        self.assertIn("sqlsrv", libraries)
        self.assertIn("pdo_sqlsrv", libraries)

    def testGetLibraries_WithPgSQL(self):
        """Test _get_libraries when PgSQL is enabled."""
        config = {'pgsql': True}
        libraries = self.builder._get_libraries(config)
        self.assertIn("postgresql", libraries)
        
    # --- Tests for extract_tar_archive ---

    def _create_dummy_tar_gz(self, archive_path: Path, content_dir_name: str, file_name: str, file_content: str):
        """Helper to create a dummy .tar.gz file."""
        source_dir = self.test_temp_dir / "source_for_tar"
        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir()

        inner_content_dir = source_dir / content_dir_name
        inner_content_dir.mkdir()
        with open(inner_content_dir / file_name, "w") as f:
            f.write(file_content)

        with tarfile.open(archive_path, "w:gz") as tar:
            # Add the inner_content_dir directly, tar will store it as content_dir_name/...
            tar.add(inner_content_dir, arcname=content_dir_name)
        
        shutil.rmtree(source_dir) # Clean up source after tarring

    def testExtractTarArchive_ValidTarGz(self):
        """Test extract_tar_archive with a valid .tar.gz file."""
        archive_name = "test_lib-1.0.tar.gz"
        lib_name_for_extraction = "test_lib" # This is what target_path.name would be
        
        dummy_archive_path = self.test_temp_dir / archive_name
        target_extract_path = self.test_temp_dir / "extracted_libs" / lib_name_for_extraction
        
        # Ensure clean state for target_extract_path parent
        if target_extract_path.parent.exists():
            shutil.rmtree(target_extract_path.parent)
        target_extract_path.parent.mkdir(parents=True)

        # Create the dummy tar.gz
        # The content_dir_name inside the archive should match lib_name_for_extraction
        # or be something like test_lib-1.0 for _find_main_source_dir to work as expected
        archive_internal_dir = f"{lib_name_for_extraction}-1.0" 
        self._create_dummy_tar_gz(dummy_archive_path, archive_internal_dir, "data.txt", "hello world")

        self.assertTrue(dummy_archive_path.exists(), "Dummy archive should be created.")

        result = self.builder.extract_tar_archive(dummy_archive_path, target_extract_path)
        self.assertTrue(result, "Extraction should be successful.")
        
        # Verify extracted content
        # The logic in extract_tar_archive moves content from source_dir_in_archive to target_path
        expected_file = target_extract_path / "data.txt"
        self.assertTrue(expected_file.exists(), f"Expected file {expected_file} not found after extraction.")
        with open(expected_file, "r") as f:
            content = f.read()
        self.assertEqual(content, "hello world")

    def _create_dummy_zip(self, archive_path: Path, content_dir_name: str, file_name: str, file_content: str):
        """Helper to create a dummy .zip file."""
        source_dir = self.test_temp_dir / "source_for_zip"
        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir()

        inner_content_dir = source_dir / content_dir_name
        inner_content_dir.mkdir()
        with open(inner_content_dir / file_name, "w") as f:
            f.write(file_content)
        
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(inner_content_dir):
                for file in files:
                    file_path = Path(root) / file
                    # arcname should be relative to inner_content_dir's parent (source_dir)
                    # to mimic typical archive structures, e.g. "content_dir_name/file.txt"
                    zipf.write(file_path, arcname=Path(content_dir_name) / file)
        
        shutil.rmtree(source_dir)

    def testExtractTarArchive_ValidZip(self):
        """Test extract_tar_archive with a valid .zip file."""
        archive_name = "test_lib-2.0.zip"
        lib_name_for_extraction = "test_lib" # target_path.name

        dummy_archive_path = self.test_temp_dir / archive_name
        target_extract_path = self.test_temp_dir / "extracted_libs" / lib_name_for_extraction

        if target_extract_path.parent.exists():
            shutil.rmtree(target_extract_path.parent)
        target_extract_path.parent.mkdir(parents=True)

        archive_internal_dir = f"{lib_name_for_extraction}-2.0" # e.g., test_lib-2.0
        self._create_dummy_zip(dummy_archive_path, archive_internal_dir, "info.txt", "zip content")
        
        self.assertTrue(dummy_archive_path.exists(), "Dummy zip archive should be created.")

        result = self.builder.extract_tar_archive(dummy_archive_path, target_extract_path)
        self.assertTrue(result, "ZIP Extraction should be successful.")
        
        expected_file = target_extract_path / "info.txt"
        self.assertTrue(expected_file.exists(), f"Expected file {expected_file} not found after ZIP extraction.")
        with open(expected_file, "r") as f:
            content = f.read()
        self.assertEqual(content, "zip content")

    def testExtractTarArchive_UnsupportedFormat(self):
        """Test extract_tar_archive with an unsupported file type (e.g., .txt)."""
        dummy_file_path = self.test_temp_dir / "unsupported.txt"
        with open(dummy_file_path, "w") as f:
            f.write("This is not an archive.")
        
        target_extract_path = self.test_temp_dir / "extracted_unsupported" / "unsupported_lib"
        if target_extract_path.parent.exists():
            shutil.rmtree(target_extract_path.parent)
        target_extract_path.parent.mkdir(parents=True)

        result = self.builder.extract_tar_archive(dummy_file_path, target_extract_path)
        self.assertFalse(result, "Extraction should fail for unsupported format.")
        self.mock_logger.error.assert_called_with(f"Unsupported archive format: {dummy_file_path.name}")
        # Ensure target directory is empty or non-existent if extraction failed early
        self.assertFalse(any(target_extract_path.iterdir()), "Target directory should be empty after failed extraction.")

    def testExtractTarArchive_FindMainSourceDir_DirectMatch(self):
        """Test _find_main_source_dir when a directory directly matches lib_name."""
        temp_extract_dir = self.test_temp_dir / "find_dir_test_direct"
        temp_extract_dir.mkdir(exist_ok=True)
        
        lib_name = "my_library"
        (temp_extract_dir / lib_name).mkdir() # my_library/
        (temp_extract_dir / "another_dir").mkdir() # another_dir/

        found_dir = self.builder._find_main_source_dir(temp_extract_dir, lib_name)
        self.assertEqual(found_dir.name, lib_name)
        shutil.rmtree(temp_extract_dir)

    def testExtractTarArchive_FindMainSourceDir_VersionedMatch(self):
        """Test _find_main_source_dir when a directory matches lib_name-version."""
        temp_extract_dir = self.test_temp_dir / "find_dir_test_versioned"
        temp_extract_dir.mkdir(exist_ok=True)

        lib_name = "my_library"
        versioned_dir_name = f"{lib_name}-1.2.3"
        (temp_extract_dir / versioned_dir_name).mkdir() # my_library-1.2.3/
        (temp_extract_dir / "another_dir").mkdir()

        found_dir = self.builder._find_main_source_dir(temp_extract_dir, lib_name)
        self.assertEqual(found_dir.name, versioned_dir_name)
        shutil.rmtree(temp_extract_dir)

    def testExtractTarArchive_FindMainSourceDir_SingleDirFallback(self):
        """Test _find_main_source_dir when only one directory exists and it doesn't match name conventions."""
        temp_extract_dir = self.test_temp_dir / "find_dir_test_single"
        temp_extract_dir.mkdir(exist_ok=True)

        lib_name = "my_library" # The name we are looking for
        actual_dir_name = "source_code_pkg" # The actual single directory in the archive
        (temp_extract_dir / actual_dir_name).mkdir()

        found_dir = self.builder._find_main_source_dir(temp_extract_dir, lib_name)
        self.assertEqual(found_dir.name, actual_dir_name)
        shutil.rmtree(temp_extract_dir)

    def testExtractTarArchive_FindMainSourceDir_MultipleNonMatchingDirs(self):
        """Test _find_main_source_dir when multiple dirs exist but none match conventions (fallback to temp_extract_dir itself)."""
        temp_extract_dir = self.test_temp_dir / "find_dir_test_multi_fallback"
        temp_extract_dir.mkdir(exist_ok=True)

        lib_name = "my_library"
        (temp_extract_dir / "src").mkdir()
        (temp_extract_dir / "libfiles").mkdir()
        (temp_extract_dir / "docs").mkdir()

        found_dir = self.builder._find_main_source_dir(temp_extract_dir, lib_name)
        self.assertEqual(found_dir, temp_extract_dir) # Should return the temp_extract_dir itself
        shutil.rmtree(temp_extract_dir)


if __name__ == '__main__':
    unittest.main()
