"""Product names; deployment identifiers remain compatible with existing installs."""
DISPLAY_NAME = "Myrinbot"
ARTIFACT_PREFIX = "Myrinbot"


def artifact_path(directory, filename):
    """Prefer the current artifact, then accept an existing deployment's filename."""
    path = directory / filename
    if path.is_file() or not filename.startswith(ARTIFACT_PREFIX + "-"):
        return path
    suffix = filename[len(ARTIFACT_PREFIX) + 1:]
    for prefix in ("AetherBot", "StarBridge"):
        legacy = directory / (prefix + "-" + suffix)
        if legacy.is_file():
            return legacy
    return path
