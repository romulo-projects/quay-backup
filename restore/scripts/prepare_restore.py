#!/usr/bin/env python3
"""Prepare sanitized Quay restore manifests without printing secret data."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} não contém um objeto YAML")
    return value


def require_kind(value: dict[str, Any], kind: str, filename: str) -> None:
    if value.get("kind") != kind:
        raise ValueError(f"{filename} não contém kind: {kind}")


def sanitized_secret(
    source: dict[str, Any], name: str, namespace: str
) -> dict[str, Any]:
    require_kind(source, "Secret", name)
    result: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace},
        "type": source.get("type", "Opaque"),
    }
    if "data" in source:
        result["data"] = source["data"]
    if "stringData" in source:
        result["stringData"] = source["stringData"]
    if "data" not in result and "stringData" not in result:
        raise ValueError(f"Secret {name} não contém data ou stringData")
    return result


def write_private_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()

    registry_source = load_yaml(args.backup_dir / "quay-registry.yaml")
    config_source = load_yaml(args.backup_dir / "config-bundle.yaml")
    keys_source = load_yaml(args.backup_dir / "managed_secret_keys.yaml")

    require_kind(registry_source, "QuayRegistry", "quay-registry.yaml")
    source_metadata = registry_source.get("metadata", {})
    if source_metadata.get("name") != args.instance:
        raise ValueError(
            "O nome do QuayRegistry no backup não corresponde a quay_instance"
        )
    if source_metadata.get("namespace") != args.namespace:
        raise ValueError(
            "O namespace do QuayRegistry no backup não corresponde a quay_namespace"
        )

    spec = copy.deepcopy(registry_source.get("spec"))
    if not isinstance(spec, dict):
        raise ValueError("QuayRegistry não contém spec válido")
    components = spec.get("components")
    if not isinstance(components, list):
        raise ValueError("QuayRegistry não contém spec.components válido")

    component_map: dict[str, dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("kind"), str):
            raise ValueError("Componente inválido no QuayRegistry")
        component_map[component["kind"]] = component

    for required in ("quay", "postgres", "objectstorage"):
        if required not in component_map or component_map[required].get("managed") is not True:
            raise ValueError(f"O componente {required} deve estar managed: true")

    clair_managed = component_map.get("clair", {}).get("managed") is True
    clairpostgres_managed = (
        component_map.get("clairpostgres", {}).get("managed") is True
    )
    if clair_managed and not clairpostgres_managed:
        raise ValueError("clair managed: true exige clairpostgres managed: true")

    managed_consumers: list[str] = []
    start_patch: list[dict[str, Any]] = []
    for index, component in enumerate(components):
        kind = component["kind"]
        if kind == "horizontalpodautoscaler":
            original_managed = component.get("managed")
            component["managed"] = False
            if original_managed is True:
                start_patch.append(
                    {
                        "op": "replace",
                        "path": f"/spec/components/{index}/managed",
                        "value": True,
                    }
                )
        if kind in ("quay", "clair", "mirror") and component.get("managed") is True:
            original_overrides = copy.deepcopy(component.get("overrides"))
            overrides = component.get("overrides")
            if not isinstance(overrides, dict):
                overrides = {}
            overrides["replicas"] = 0
            component["overrides"] = overrides
            managed_consumers.append(kind)
            if isinstance(original_overrides, dict):
                start_patch.append(
                    {
                        "op": "replace",
                        "path": f"/spec/components/{index}/overrides",
                        "value": original_overrides,
                    }
                )
            else:
                start_patch.append(
                    {
                        "op": "remove",
                        "path": f"/spec/components/{index}/overrides",
                    }
                )

    config_name = spec.get("configBundleSecret")
    if not isinstance(config_name, str) or not config_name:
        raise ValueError("QuayRegistry não referencia spec.configBundleSecret")
    if config_source.get("metadata", {}).get("name") != config_name:
        raise ValueError("config-bundle.yaml não corresponde ao configBundleSecret")

    managed_keys_name = f"{args.instance}-quay-registry-managed-secret-keys"
    if keys_source.get("metadata", {}).get("name") != managed_keys_name:
        raise ValueError("managed_secret_keys.yaml não corresponde ao QuayRegistry")

    registry = {
        "apiVersion": registry_source.get("apiVersion", "quay.redhat.com/v1"),
        "kind": "QuayRegistry",
        "metadata": {"name": args.instance, "namespace": args.namespace},
        "spec": spec,
    }
    config = sanitized_secret(config_source, config_name, args.namespace)
    keys = sanitized_secret(keys_source, managed_keys_name, args.namespace)

    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(args.output_dir, 0o700)
    write_private_yaml(args.output_dir / "config-bundle.yaml", config)
    write_private_yaml(args.output_dir / "managed_secret_keys.yaml", keys)
    write_private_yaml(args.output_dir / "quay-registry.yaml", registry)
    start_patch_path = args.output_dir / "start-quay-patch.json"
    start_patch_path.write_text(json.dumps(start_patch), encoding="utf-8")
    os.chmod(start_patch_path, 0o600)

    print(
        json.dumps(
            {
                "config_bundle_secret": config_name,
                "managed_keys_secret": managed_keys_name,
                "managed_consumers": managed_consumers,
                "clair_managed": clair_managed,
                "clairpostgres_managed": clairpostgres_managed,
            }
        )
    )


if __name__ == "__main__":
    main()
