# Static PHP Builder GUI

This Python application provides a graphical user interface (GUI) to simplify the process of building static PHP executables using the [static-php-cli](https://github.com/crazywhalecc/static-php-cli) project.

## Features

*   GUI for selecting clone directory, PHP version, and common extensions (MySQL, SQLSRV, PgSQL).
*   Automates the cloning of `static-php-cli`.
*   Manages the download and extraction of PHP source code and required library dependencies.
*   Runs the `static-php-cli` build process.
*   Logs output to the GUI.

## Setup & Usage

1.  **Prerequisites:**
    *   Python 3.x
    *   Git
    *   Composer
    *   (For Windows) PowerShell is used for some elevated Composer operations if needed.
    *   (For Linux/macOS) Ensure you have necessary build tools installed (gcc, make, autoconf, etc.). If Composer runs into permission issues, you might need to adjust directory permissions for the `static-php-cli` clone location or run this application with `sudo`.

2.  **Configuration:**
    *   Library versions and their download URLs are managed via `config/lib.json`. You can update this file to use different versions of dependencies if needed.

3.  **Running the Application:**
    ```bash
    python main.py
    ```
    *   Select a directory where `static-php-cli` will be cloned.
    *   Choose your desired PHP version and any optional extensions.
    *   Click "Start Build".

## Key Recent Changes

*   **Archive Extraction:** The tool now uses Python's built-in `tarfile` and `zipfile` modules for extracting downloaded PHP and library sources, removing the previous dependency on a user-installed 7-Zip executable for this part of the process.
*   **Library Configuration:** Dependency library versions and download URLs are now primarily managed through the `config/lib.json` file, making it easier to update them without modifying the core Python code.
*   **Platform Considerations:**
    *   The application attempts to be platform-aware for tasks like locating the final PHP executable (`php.exe` vs. `php`).
    *   Composer install operations: If they require elevated privileges, the tool uses PowerShell on Windows. On Linux/macOS, it will attempt without elevation; if permissions are insufficient, users are advised in the logs to adjust directory permissions or run the entire application with `sudo`.

## Development

*   Unit tests are located in the `tests/` directory and can be run using `python -m unittest discover tests`.
