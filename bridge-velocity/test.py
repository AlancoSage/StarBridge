#!/usr/bin/env python3
"""Security checks against the real released authentication APIs (requires Java 21+)."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

from build import MODULE, TARGET, DEPS, dependencies, java_tools, compile_sources

TEST_DEPS = {
    "limboauth-1.1.14.jar": ("https://github.com/Elytrium/LimboAuth/releases/download/1.1.14/limboauth-1.1.14.jar", "2502680c0c4cdfc51881e12c19cab2d2b666ab554f6056fa35458bb0f273480e"),
    "limboapi-1.1.26.jar": ("https://github.com/Elytrium/LimboAPI/releases/download/1.1.26/limboapi-1.1.26.jar", "8bcf9b76608875f0cf7008a76098d6941e86b4b72e61fdb72dc37da94eabe43b"),
    "velocity-3.3.0-436.jar": ("https://fill-data.papermc.io/v1/objects/06bb2a6ac16228a2f33a0336952624e6918a97535d36a3660725b18e2a6efdfb/velocity-3.3.0-SNAPSHOT-436.jar", "06bb2a6ac16228a2f33a0336952624e6918a97535d36a3660725b18e2a6efdfb"),
    "LibreLogin-0.24.0.jar": ("https://github.com/kyngs/LibreLogin/releases/download/0.24.0/LibreLogin.jar", "3df848d4058e63f37cf9fe997542fd49c84374440d116a34ac4052278aa77e4f"),
    "h2-2.2.224.jar": ("https://repo.maven.apache.org/maven2/com/h2database/h2/2.2.224/h2-2.2.224.jar", "b9d8f19358ada82a4f6eb5b174c6cfe320a375b5a9cb5a4fe456d623e6e55497"),
    "bcrypt-0.10.2.jar": ("https://repo.maven.apache.org/maven2/at/favre/lib/bcrypt/0.10.2/bcrypt-0.10.2.jar", "0b1fb99db605955de904d8e61782a53dddbadd12619a0cf37dd88b5d14a61957"),
    "bytes-1.5.0.jar": ("https://repo.maven.apache.org/maven2/at/favre/lib/bytes/1.5.0/bytes-1.5.0.jar", "b933631573148647943040d8d7496a64458b432610e6da2eb87ec3458814dee5"),
}


def main(java_home: str | None) -> None:
    java, javac = java_tools(java_home)
    paths = dependencies()
    folder = DEPS / "test-only"
    folder.mkdir(exist_ok=True)
    for name, (url, checksum) in TEST_DEPS.items():
        path = folder / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            request = urllib.request.Request(url, headers={"User-Agent": "VexBot-auth-api-test/0.1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(32 * 1024 * 1024 + 1)
            if len(payload) > 32 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != checksum:
                raise RuntimeError(f"Test dependency checksum mismatch: {name}")
            path.write_bytes(payload)
        paths.append(path)
    with tempfile.TemporaryDirectory(prefix="velocity-test-", dir=TARGET) as temporary:
        work = Path(temporary)
        sources = sorted((MODULE / "src/main/java").rglob("*.java")) + sorted((MODULE / "src/test/java").rglob("*.java"))
        compile_sources(javac, work / "classes", paths, sources)
        subprocess.run([java, "-Dlog4j.configurationFile=" + str(MODULE / "src/test/resources/log4j2.xml"),
                        "-Dcom.j256.simplelogging.level=ERROR", "-cp", os.pathsep.join(map(str, [work / "classes", MODULE / "src/main/resources", *paths])),
                        "cn.starbridge.velocity.SecurityCheck", str(work)], check=True, timeout=90)
    # Deployed jar must contain no optional authentication implementation, test class, or compile-only API.
    jar = TARGET / "VexBot-Velocity-0.1.1.jar"
    with zipfile.ZipFile(jar) as archive:
        classes = [name for name in archive.namelist() if name.endswith(".class")]
        assert classes and all(name.startswith(("cn/starbridge/velocity/", "cn/starbridge/lib/gson/")) for name in classes)
        assert not any("SecurityCheck" in name for name in classes)
        for name in classes:
            assert int.from_bytes(archive.read(name)[6:8], "big") <= 61, name
    print("Velocity packaged JAR isolation and Java 17 bytecode: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home")
    main(parser.parse_args().java_home)
