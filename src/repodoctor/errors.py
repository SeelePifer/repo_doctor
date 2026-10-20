class RepoDoctorError(Exception):
    """Expected failure the CLI and API can show to the user."""


class GitError(RepoDoctorError):
    """Git is missing or the path is not a usable repository."""


class ModelError(RepoDoctorError):
    """Cursor could not run the model for this request."""


class SandboxError(RepoDoctorError):
    """Docker could not run the verification sandbox."""
