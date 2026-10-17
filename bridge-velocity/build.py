#!/usr/bin/env python3
"""Build the standalone Velocity companion with pinned compile dependencies (Java 17+)."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bridge-velocity"
TARGET = ROOT / "bridge" / "target"
DEPS = TARGET / "velocity-build-deps"
VERSION = "0.1.0"
MAVEN = "https://repo.maven.apache.org/maven2/"
DEPENDENCIES = {
    "velocity-api.jar": (
        "https://repo.papermc.io/repository/maven-public/com/velocitypowered/velocity-api/3.3.0-SNAPSHOT/velocity-api-3.3.0-20240916.013244-136.jar",
        "e692dc8ecf446e5dc1a4df43cd7d6c6fe632b9962d7fece23e37bf66a42e498a"),
    "guice-6.0.0.jar": (MAVEN + "com/google/inject/guice/6.0.0/guice-6.0.0.jar", "b4d4f7ec5e8fc17b4f98dee9d3f6cf6ae3ae13e2e5ed4b2f7bbf09bc4bb675d5"),
    "slf4j-api-2.0.12.jar": (MAVEN + "org/slf4j/slf4j-api/2.0.12/slf4j-api-2.0.12.jar", "a79502b8abdfbd722846a27691226a4088682d6d35654f9b80e2a9ccacf7ed47"),
    "adventure-api-4.17.0.jar": (MAVEN + "net/kyori/adventure-api/4.17.0/adventure-api-4.17.0.jar", "15c8c2eb1a69d8b1bc914f554353da8ee7cf074c05c8074da9898aee5c70d0d8"),
    "adventure-key-4.17.0.jar": (MAVEN + "net/kyori/adventure-key/4.17.0/adventure-key-4.17.0.jar", "8e5cf570612d6ccedf943ac1716a449de2dd5a90207b7de6f73c0236935b766e"),
    "examination-api-1.3.0.jar": (MAVEN + "net/kyori/examination-api/1.3.0/examination-api-1.3.0.jar", "c9237ffecb05428f6eff86216246ac70ce0b47b04c08ea7ca35020fde57f8492"),
    "examination-string-1.3.0.jar": (MAVEN + "net/kyori/examination-string/1.3.0/examination-string-1.3.0.jar", "7d01fc25a4bb3af0e1662685455f4541fbf4626216ea5846e455c1491e156b8c"),
    "gson-2.13.2.jar": (MAVEN + "com/google/code/gson/gson/2.13.2/gson-2.13.2.jar", "dd0ce1b55a3ed2080cb70f9c655850cda86c206862310009dcb5e5c95265a5e0"),
    "asm-9.8.jar": (MAVEN + "org/ow2/asm/asm/9.8/asm-9.8.jar", "876eab6a83daecad5ca67eb9fcabb063c97b5aeb8cf1fca7a989ecde17522051"),
    "asm-commons-9.8.jar": (MAVEN + "org/ow2/asm/asm-commons/9.8/asm-commons-9.8.jar", "3301a1c1cb4c59fcc5292648dac1d7c5aed4c0f067dfbe88873b8cdfe77404f4"),
}


def dependencies() -> list[Path]:
    DEPS.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (url, checksum) in DEPENDENCIES.items():
        path = DEPS / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            # The Bukkit build may already have downloaded the same pinned tools.
            existing = TARGET / name
            if existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest() == checksum:
                shutil.copyfile(existing, path)
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "Myrinbot-Velocity-build/0.1"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = response.read(16 * 1024 * 1024 + 1)
                if len(payload) > 16 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != checksum:
                    raise RuntimeError(f"Dependency checksum mismatch: {name}")
                temporary = path.with_suffix(".download")
                temporary.write_bytes(payload)
                temporary.replace(path)
        paths.append(path)
    return paths


def java_tools(java_home: str | None) -> tuple[str, str]:
    suffix = ".exe" if os.name == "nt" else ""
    home = java_home or os.environ.get("JAVA_HOME")
    javac = str(Path(home) / "bin" / ("javac" + suffix)) if home else shutil.which("javac")
    java = str(Path(home) / "bin" / ("java" + suffix)) if home else shutil.which("java")
    if not javac or not java:
        raise RuntimeError("Specify --java-home with a JDK 17+ installation")
    return java, javac


def compile_sources(javac: str, destination: Path, paths: list[Path], sources: list[Path]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, "--release", "17", "-proc:none", "-encoding", "UTF-8", "-cp",
                    os.pathsep.join(map(str, paths)), "-d", str(destination), *map(str, sources)], check=True)


def build(java_home: str | None) -> Path:
    java, javac = java_tools(java_home)
    paths = dependencies()
    with tempfile.TemporaryDirectory(prefix="velocity-build-", dir=TARGET) as temporary:
        work = Path(temporary)
        classes = work / "classes"
        compile_sources(javac, classes, paths, sorted((MODULE / "src/main/java").rglob("*.java")))
        tools = work / "tools"
        compile_sources(javac, tools, paths, [ROOT / "bridge/tools/ShadeJar.java"])
        resources = work / "resources"
        shutil.copytree(MODULE / "src/main/resources", resources)
        shutil.copytree(ROOT / "bridge/src/main/resources/META-INF/licenses", resources / "META-INF/licenses")
        output = TARGET / f"Myrinbot-Velocity-{VERSION}.jar"
        subprocess.run([java, "-cp", os.pathsep.join(map(str, [tools, *paths])), "ShadeJar", str(classes),
                        str(resources), str(DEPS / "gson-2.13.2.jar"), str(output), str(ROOT)], check=True)
    shutil.copyfile(output, TARGET / f"StarBridge-Velocity-{VERSION}.jar")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home")
    print(build(parser.parse_args().java_home))
