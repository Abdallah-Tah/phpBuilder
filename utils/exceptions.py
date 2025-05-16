class PHPBuilderError(Exception):
    """Base exception for all PHP builder errors"""
    pass


class ConfigurationError(PHPBuilderError):
    """Raised when there is a configuration-related error"""
    pass


class BuildError(PHPBuilderError):
    """Raised when there is an error during the build process"""
    pass


class DependencyError(PHPBuilderError):
    """Raised when there is a dependency-related error"""
    pass


class FileSystemError(PHPBuilderError):
    """Raised when there is a filesystem-related error"""
    pass


class ValidationError(PHPBuilderError):
    """Raised when validation fails"""
    pass


class CommandError(PHPBuilderError):
    """Raised when a command execution fails"""
    pass
