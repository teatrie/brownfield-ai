"""
Reconstructs the canonical database schema for a given service.

This script:
1. Locates SQL migration files in the service repository.
2. Determines the RDS engine version from the service's Terraform configuration.
3. Maps the RDS version to a compatible MySQL Docker image.
4. Starts a temporary MySQL container with the matching version.
5. Uses Ariga Atlas to replay migrations and generate a canonical `current_schema.sql`.

Usage:
    python3 scripts/reconstruct_schema.py <service_name>
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import defopt

import docker

# Configuration
REPOS_DIR = "repos"

#: Environment variable naming the checked-out repo that holds the Terraform
#: describing the service's RDS instance. There is no default — infrastructure
#: layout is organisation-specific.
INFRA_REPO_ENV = "BROWNFIELD_INFRA_REPO"


def resolve_service_path(service_name: str, service_path: str | None = None) -> str:
    """
    Resolve the checkout directory holding the service's migrations.

    Args:
        service_name: Name of the service, used as the default `repos/` entry.
        service_path: Explicit path override, for services that live inside a
            monorepo rather than at `repos/<service_name>`.

    Returns:
        The resolved service directory.
    """
    resolved = service_path or os.path.join(REPOS_DIR, service_name)
    if not os.path.exists(resolved):
        print(f"Error: Service repository not found at {resolved}")
        print("Clone it under repos/, or pass --service-path for a service nested inside a monorepo.")
        sys.exit(1)
    return resolved


def resolve_infra_dir(infra_dir: str | None = None) -> str | None:
    """
    Resolve the Terraform checkout used to detect the RDS engine version.

    Args:
        infra_dir: Explicit path, or None to read `$BROWNFIELD_INFRA_REPO`.

    Returns:
        The infra directory, or None when none is configured.
    """
    resolved = infra_dir or os.environ.get(INFRA_REPO_ENV, "")
    if not resolved:
        return None
    if os.path.isabs(resolved) or os.path.sep in resolved:
        return resolved
    return os.path.join(REPOS_DIR, resolved)


def find_migration_dir(service_path: str) -> str | None:
    """Find the directory containing the most SQL migration files."""
    migration_dirs = {}

    # Walk through the directory to find .sql files
    for root, dirs, files in os.walk(service_path):
        sql_files = [f for f in files if f.endswith(".sql")]
        if sql_files:
            # Check for versioned files (heuristic: start with digit or V+digit)
            versioned = [f for f in sql_files if re.match(r"^(V\d|\d)", f, re.IGNORECASE)]
            if versioned:
                migration_dirs[root] = len(versioned)

    if not migration_dirs:
        # Fallback: any directory with SQL files
        for root, dirs, files in os.walk(service_path):
            sql_files = [f for f in files if f.endswith(".sql")]
            if sql_files:
                migration_dirs[root] = len(sql_files)

    if not migration_dirs:
        return None

    # Return the directory with the most SQL files
    best_dir = max(migration_dirs, key=lambda k: migration_dirs[k])
    return best_dir


def find_rds_version(infra_path: str, service_name: str) -> str | None:
    """Find the RDS engine version from Terraform files."""
    # Search for files containing the service name and 'aws_rds_cluster' or 'aws_db_instance'

    # Grep for service name in infra repo to narrow down files
    if not os.path.exists(infra_path):
        print(f"Warning: Infra repo not found at {infra_path}")
        return None

    matches = []
    for p in Path(infra_path).rglob("*.tf"):
        try:
            if service_name in p.read_text(encoding="utf-8", errors="ignore"):
                matches.append(str(p))
        except OSError:
            continue
    if not matches:
        print(f"Warning: Could not find references to {service_name} in {infra_path}")
        return None
    files = matches

    for file_path in files:
        if not file_path.endswith(".tf"):
            continue

        try:
            with open(file_path) as f:
                content = f.read()

            # Look for engine_version in aws_rds_cluster or aws_db_instance or module
            # Simplified regex for engine_version = "..."
            match = re.search(r'engine_version\s*=\s*"([^"]+)"', content)
            if match:
                return match.group(1)
        except OSError as e:
            print(f"Error reading {file_path}: {e}")
            continue

    return None


def map_rds_to_mysql(rds_version: str | None) -> str:
    """Map RDS engine version to MySQL Docker image tag."""
    if not rds_version:
        return "8.0"  # Default

    # Aurora MySQL mappings
    # 2.x -> 5.7
    # 3.x -> 8.0
    if rds_version.startswith("5.7"):
        return "5.7"
    if rds_version.startswith("8.0"):
        return "8.0"
    if rds_version.startswith("2."):  # Aurora 2.x compatible with MySQL 5.7
        return "5.7"
    if rds_version.startswith("3."):  # Aurora 3.x compatible with MySQL 8.0
        return "8.0"

    return "8.0"  # Default fallback


def wait_for_mysql(container: Any, max_retries: int = 30) -> bool:
    """Wait for MySQL to be ready.

    Args:
        container: Docker container object.
        max_retries: Maximum number of retries.

    Returns:
        True if MySQL is ready, False otherwise.
    """
    print("Waiting for MySQL to be ready...")

    for i in range(max_retries):
        exit_code, _ = container.exec_run(["mysqladmin", "ping", "-h", "127.0.0.1", "--protocol", "tcp", "-u", "root", "--silent"])
        if exit_code == 0:
            print("MySQL is ready.")
            return True
        time.sleep(2)
        print(".", end="", flush=True)

    print("\nMySQL failed to become ready.")
    return False


def main(service_name: str, *, service_path: str | None = None, infra_dir: str | None = None) -> None:
    """
    Reconstruct schema from migrations.

    Args:
        service_name: Name of the service
        service_path: Path to the service checkout (default: repos/<service_name>)
        infra_dir: Terraform checkout used for RDS version detection
            (default: $BROWNFIELD_INFRA_REPO; skipped when unset)
    """
    service_path = resolve_service_path(service_name, service_path)

    print(f"Analyzing service: {service_name}")

    # 1. Find Migrations
    migration_dir = find_migration_dir(service_path)
    if not migration_dir:
        print("Error: No migration directory found.")
        sys.exit(1)
    print(f"Found migration directory: {migration_dir}")

    # 2. Find RDS Version
    resolved_infra_dir = resolve_infra_dir(infra_dir)
    rds_version = None
    if resolved_infra_dir:
        print("Determining RDS version...")
        rds_version = find_rds_version(resolved_infra_dir, service_name)
    else:
        print(f"No infrastructure repo configured (--infra-dir / ${INFRA_REPO_ENV}); skipping RDS version detection.")

    if rds_version:
        print(f"Found RDS version in Terraform: {rds_version}")
    else:
        print("Could not determine RDS version from Terraform. Defaulting to MySQL 8.0.")

    mysql_version = map_rds_to_mysql(rds_version)
    print(f"Mapped to MySQL version: {mysql_version}")

    # 3. Start Docker Container
    container_name = f"{service_name}-schema-reconstruct"
    # Ensure cleanup of previous container
    client = docker.from_env()
    try:
        client.containers.get(container_name).remove(force=True)
    except docker.errors.NotFound:
        pass

    print(f"Starting MySQL {mysql_version} container: {container_name}")
    container = None
    try:
        container = client.containers.run(
            f"mysql:{mysql_version}",
            name=container_name,
            detach=True,
            environment={"MYSQL_ALLOW_EMPTY_PASSWORD": "yes", "MYSQL_DATABASE": "dev"},
        )
    except docker.errors.APIError:
        print("Failed to start Docker container.")
        sys.exit(1)

    if not wait_for_mysql(container):
        sys.exit(1)

    # 4. Prepare Migration Directory (Copy to temp and hash)
    print("Preparing migration directory...")
    # Use 'tmp' inside current directory if available (for Docker volume mounting), else default
    base_tmp_dir = os.path.join(os.getcwd(), "tmp")
    if os.path.exists(base_tmp_dir):
        temp_dir = tempfile.mkdtemp(dir=base_tmp_dir)
    else:
        temp_dir = tempfile.mkdtemp()

    try:
        # Check migration format
        is_flyway = False
        for item in os.listdir(migration_dir):
            if re.match(r"^V\d+__.*\.sql$", item):
                is_flyway = True
                break

        migration_url_params = "?format=flyway" if is_flyway else ""
        print(f"Detected migration format: {'Flyway' if is_flyway else 'Default'}")

        # Copy migrations to temp dir
        for item in os.listdir(migration_dir):
            s = os.path.join(migration_dir, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

        # Patch migrations for known issues (e.g. reserved keywords in MySQL 8)
        print("Patching migrations for compatibility...")
        for filename in os.listdir(temp_dir):
            if filename.endswith(".sql"):
                filepath = os.path.join(temp_dir, filename)
                with open(filepath) as f:
                    content = f.read()

                # Patch: `groups` is a reserved keyword in MySQL 8.0
                if "CREATE TABLE groups" in content:
                    print(f"  Patching 'groups' table in {filename}")
                    content = content.replace("CREATE TABLE groups", "CREATE TABLE `groups`")

                with open(filepath, "w") as f:
                    f.write(content)

        # Run atlas migrate hash
        print(f"Running atlas migrate hash on {temp_dir}...")

        # We need absolute path for volume mount
        abs_temp_dir = os.path.abspath(temp_dir)

        # If running inside Docker (detected via HOST_PWD), translate path
        host_pwd = os.environ.get("HOST_PWD")
        if host_pwd:
            # Assume we are mounted at /app
            if abs_temp_dir.startswith("/app"):
                volume_path = abs_temp_dir.replace("/app", host_pwd, 1)
                print(f"Running in Docker, translating path {abs_temp_dir} -> {volume_path}")
            else:
                print(f"Warning: HOST_PWD set but path {abs_temp_dir} does not start with /app")
                volume_path = abs_temp_dir
        else:
            volume_path = abs_temp_dir

        # Atlas hash command
        hash_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume_path}:/migrations",
            "arigaio/atlas",
            "migrate",
            "hash",
            "--dir",
            f"file:///migrations{migration_url_params}",
        ]
        # Atlas CLI: no Python SDK available, subprocess is acceptable per coding_standards.md
        subprocess.run(hash_cmd, check=True, capture_output=True, text=True, timeout=120)

        # 5. Run Atlas Inspect
        print("Running Atlas to inspect schema...")
        output_file = os.path.join(service_path, "current_schema.sql")

        try:
            # We need to capture stdout to write to file
            atlas_cmd = [
                "docker",
                "run",
                "--rm",
                "--network",
                f"container:{container_name}",
                "-v",
                f"{volume_path}:/migrations",
                "arigaio/atlas",
                "schema",
                "inspect",
                "--url",
                f"file:///migrations{migration_url_params}",
                "--dev-url",
                "mysql://root@127.0.0.1:3306/dev",
                "--output-format",
                "{{ sql . }}",
            ]

            print(f"Executing: {' '.join(atlas_cmd)}")
            # Atlas CLI: no Python SDK available, subprocess is acceptable per coding_standards.md
            result = subprocess.run(atlas_cmd, check=True, capture_output=True, text=True, timeout=300)
            schema_sql = result.stdout.strip()

            if not schema_sql:
                print("Warning: Atlas returned empty schema.")

            # Validation: Check if schema looks like valid SQL
            # It should contain CREATE TABLE or similar keywords, and should not be just "sql"
            if len(schema_sql.strip()) < 10 or "CREATE TABLE" not in schema_sql.upper():
                print(f"Error: Generated schema does not look valid. Content:\n{schema_sql[:200]}...")
                # If content is exactly "sql", it's likely a format string error
                if schema_sql.strip() == "sql":
                    print("Error: Atlas output 'sql' literal. This usually means incorrect --output-format usage.")
                sys.exit(1)

            with open(output_file, "w") as f:
                f.write(schema_sql)

            print(f"Success! Schema saved to: {output_file}")

        except subprocess.CalledProcessError:
            print("Error running Atlas inspect.")
            sys.exit(1)

    finally:
        # Cleanup temp dir
        shutil.rmtree(temp_dir)

        # Cleanup container
        print(f"Stopping container {container_name}...")
        if container is not None:
            try:
                container.remove(force=True)
            except docker.errors.NotFound:
                pass


if __name__ == "__main__":
    defopt.run(main)
