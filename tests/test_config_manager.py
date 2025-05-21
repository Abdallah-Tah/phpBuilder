import unittest
import json
import shutil
from pathlib import Path
from utils.config_manager import ConfigurationManager
# PathManager is not directly used by ConfigurationManager after initialization,
# but we need it to determine the project_root for testing.
# from utils.path_manager import PathManager # PathManager is not directly needed if we manually set project_root path


class TestConfigurationManager(unittest.TestCase):

    def setUp(self):
        """Set up for test methods."""
        # Determine the project root based on this test file's location
        # tests/test_config_manager.py -> project_root is tests/..
        # For testing, we'll create a temporary structure that mimics 'project_root/config/lib.json'
        self.test_project_root = Path(__file__).resolve().parent / "temp_test_project_root"
        self.test_config_dir = self.test_project_root / "config"
        
        # Ensure clean state
        if self.test_project_root.exists():
            shutil.rmtree(self.test_project_root)
        
        self.test_config_dir.mkdir(parents=True, exist_ok=True)

        self.dummy_lib_data = {
            "zlib": {"version": "1.2.11", "urls": {"main": "http://example.com/zlib.tar.gz"}},
            "openssl": {"version": "1.1.1k", "urls": {"main": "http://example.com/openssl.tar.gz"}}
        }
        with open(self.test_config_dir / "lib.json", "w") as f:
            json.dump(self.dummy_lib_data, f)

        # Dummy data for another section to test get_config
        self.dummy_source_data = {
            "php": {"version": "8.1.0"}
        }
        with open(self.test_config_dir / "source.json", "w") as f:
            json.dump(self.dummy_source_data, f)
        
        # Initialize ConfigurationManager with the temporary project root
        self.config_manager = ConfigurationManager()
        # Pass the Path object for the temporary project root
        self.config_manager.initialize(project_root=self.test_project_root)


    def tearDown(self):
        """Tear down after test methods."""
        if self.test_project_root.exists():
            shutil.rmtree(self.test_project_root)

    def testGetLibConfig_ExistingLibrary(self):
        """Test getting config for an existing library."""
        zlib_config = self.config_manager.get_lib_config("zlib")
        self.assertIsNotNone(zlib_config)
        self.assertEqual(zlib_config.get("version"), "1.2.11")

    def testGetLibConfig_NonExistingLibrary(self):
        """Test getting config for a non-existing library."""
        non_existing_config = self.config_manager.get_lib_config("nonexistinglib")
        self.assertEqual(non_existing_config, {}) # Expect an empty dict

    def testGetLibConfig_SpecificKey(self):
        """Test getting a specific key from a library's config."""
        openssl_version = self.config_manager.get_lib_config("openssl", "version")
        self.assertEqual(openssl_version, "1.1.1k")
        
        openssl_urls = self.config_manager.get_lib_config("openssl", "urls")
        self.assertEqual(openssl_urls, {"main": "http://example.com/openssl.tar.gz"})

    def testGetLibConfig_SpecificNonExistingKey(self):
        """Test getting a non-existing specific key from a library's config."""
        openssl_non_key = self.config_manager.get_lib_config("openssl", "nonexistingkey")
        self.assertIsNone(openssl_non_key) # get() on a dict returns None for missing keys

    def testGetConfig_WholeSection(self):
        """Test getting a whole configuration section (e.g., 'lib')."""
        all_lib_config = self.config_manager.get_config("lib")
        self.assertEqual(all_lib_config, self.dummy_lib_data)

        all_source_config = self.config_manager.get_config("source")
        self.assertEqual(all_source_config, self.dummy_source_data)

    def testGetConfig_NonExistingSection(self):
        """Test getting a non-existing configuration section."""
        non_existing_section = self.config_manager.get_config("nonexistingsection")
        self.assertEqual(non_existing_section, {}) # Expect an empty dict

    def testGetConfig_SpecificKeyFromSection(self):
        """Test getting a specific key from a general configuration section."""
        php_config_block = self.config_manager.get_config("source", "php")
        # This should return the dictionary associated with the 'php' key in 'source.json'
        self.assertEqual(php_config_block, {"version": "8.1.0"}) 

        # Test getting a non-existent key from an existing section
        non_existent_key = self.config_manager.get_config("source", "nonexistentkey")
        self.assertIsNone(non_existent_key) # get() on a dict returns None for missing keys

    def testProjectRootProperty(self):
        """Test the project_root property of ConfigurationManager."""
        # ConfigurationManager stores the project_root used during initialization
        self.assertEqual(self.config_manager.project_root, self.test_project_root)

    def testInitializationWithoutExplicitProjectRoot(self):
        """Test ConfigurationManager initialization when project_root is not explicitly passed."""
        # This test assumes that if project_root is None, ConfigurationManager
        # will try to determine it automatically (e.g., Path(__file__).resolve().parent.parent from its own location)
        # For this test, we need to ensure our dummy config files are NOT in the auto-detected path
        # to confirm it loads empty configs, or we'd need to mock Path(__file__) for ConfigurationManager.
        # Given the current structure, it's simpler to test that it loads an empty config if the auto-detected
        # path doesn't contain our dummy files.

        # Create a new instance without passing project_root
        cm_auto = ConfigurationManager()
        # We need to know where ConfigurationManager *thinks* the project root is.
        # The default logic is: Path(__file__).resolve().parent.parent relative to config_manager.py
        # Let's assume this default path won't have our temp_test_project_root/config structure.
        
        # To make this test robust, we can check if it loads empty for 'lib' if no config is found
        # at the auto-detected path. This requires knowing the auto-detection logic.
        # The current auto-detection is `Path(__file__).resolve().parent.parent` *relative to config_manager.py*
        
        # For simplicity, let's assume the auto-detected path won't have our dummy config files.
        # The test would be that it initializes and doesn't find 'lib', so it returns empty.
        # This is a bit implicit. A better test would mock Path(__file__) in config_manager.py
        # or ensure the auto-detected path is clean.

        # For now, let's just ensure it initializes without error and project_root is set.
        cm_auto.initialize() 
        self.assertIsNotNone(cm_auto.project_root, "Project root should be set even if not provided.")
        # And that it loads an empty 'lib' config if nothing is found there
        self.assertEqual(cm_auto.get_config("lib"), {}, "Should load empty lib config if nothing at auto-detected root.")


if __name__ == '__main__':
    unittest.main()
