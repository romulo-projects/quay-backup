# Quay Backup

Ansible workflow for a consistent disaster-recovery backup of Red Hat Quay on
OpenShift. It is designed for Quay Operator deployments with managed PostgreSQL
and managed NooBaa/ODF object storage.

**Target environment:** Red Hat Quay 3.15.2. Operational validation is pending
in homologation. Revalidate the complete backup and restore procedure after
upgrading Quay, OpenShift, the Quay Operator, Ansible, `oc`, PostgreSQL, or AWS
CLI.

## Safety properties

The main playbook:

- verifies Quay health, topology, RBAC, commands, and local free space before changing Quay;
- creates a cluster ConfigMap lock to prevent concurrent backups;
- writes into `<timestamp>.incomplete` and never overwrites an existing run;
- keeps `config-original.yaml` immutable and builds a separate read-only config;
- verifies read-only mode from the live pod configuration;
- restores the exact original config in an Ansible `always` section;
- creates a PostgreSQL custom-format dump and validates it with `pg_restore --list`;
- copies managed NooBaa blobs with TLS verification enabled by default;
- removes cluster-specific metadata from recovery YAML files;
- creates SHA-256 checksums and a completion manifest;
- only renames the directory to `<timestamp>` after all validations pass.

An interrupted controller process (power loss or `kill -9`) cannot execute an
Ansible `always` section. For this case, use `playbook-recover-quay.yml`.

## Prerequisites

- Ansible Core 2.14 or later;
- OpenShift CLI (`oc`) authenticated against the target cluster;
- `sha256sum` and `df` on the controller;
- AWS CLI when object-storage backup is enabled;
- permissions to read the Quay resources and pods, update the config bundle
  secret, execute commands in Quay/PostgreSQL pods, and create/delete ConfigMaps;
- enough local storage for the database dump and, when enabled, all blobs;
- the `quay-readonly` service key installed in the database and its `.kid` and
  `.pem` files present in the config bundle.

The playbook deliberately rejects external PostgreSQL or object storage. Back
up unmanaged services with the provider-supported mechanism.

## Configuration

Edit `group_vars/all.yml`. Important defaults:

| Variable | Default | Purpose |
|---|---:|---|
| `backup_root` | `backups/` | Local backup destination. |
| `backup_minimum_free_bytes` | 10 GiB | Minimum free space preflight threshold. |
| `backup_managed_noobaa_storage` | `true` | Copies the full managed blob bucket. |
| `s3_tls_verify` | `true` | Keeps S3 certificate verification enabled. |
| `s3_ca_bundle` | empty | Private CA bundle path for AWS CLI, when required. |
| `backup_lock_name` | `<quay>-backup-lock` | Cluster-wide concurrency lock. |

Size `backup_minimum_free_bytes` for the actual database and bucket. The 10 GiB
default is only a safety floor.

## Run a backup

Inspect the effective configuration and syntax first:

```bash
ansible-playbook playbook-backup-quay.yml --syntax-check
ansible-playbook playbook-backup-quay.yml --list-tasks
```

Run the complete disaster-recovery backup:

```bash
ansible-playbook playbook-backup-quay.yml
```

For an initial database/configuration-only homologation check, explicitly skip
the blob copy:

```bash
ansible-playbook playbook-backup-quay.yml \
  -e backup_managed_noobaa_storage=false
```

If the S3 route uses a private CA, run the complete backup with
`-e s3_ca_bundle=/absolute/path/to/ingress-ca.pem`. Do not disable TLS
verification except for a controlled, time-limited diagnostic.

## Output

A successful directory contains:

```text
backups/<timestamp>/
├── SHA256SUMS
├── backup.dump
├── config-bundle.yaml
├── config-original.yaml
├── config-readonly.yaml
├── managed-secret-keys.yaml
├── manifest.yml
├── quay-config.yaml
├── quay-registry.yaml
└── s3-blobs/                 # only when explicitly enabled
```

`config-original.yaml`, secrets, database contents, and blobs are sensitive.
Filesystem mode `0600/0700` is not encryption. Move completed backups to an
encrypted, access-controlled, immutable destination and apply a documented
retention policy.

Validate checksums from inside the backup directory:

```bash
sha256sum --check SHA256SUMS
```

## Emergency recovery after interruption

If the controller was interrupted, inspect Quay and the lock:

```bash
oc get configmap quay-registry-backup-lock -n quay -o yaml
oc get secret -n quay \
  "$(oc get quayregistry quay-registry -n quay -o jsonpath='{.spec.configBundleSecret}')" \
  -o jsonpath='{.data.config\.yaml}' | base64 -d
```

Restore the exact original configuration from the incomplete backup:

```bash
ansible-playbook playbook-recover-quay.yml \
  -e recovery_backup_dir=/absolute/path/to/backups/<timestamp>.incomplete
```

The recovery playbook waits for a new deployment generation, verifies the live
configuration is no longer read-only, and removes the stale lock.

## Homologation test plan

Use a disposable or recoverable Quay homologation environment.

1. Record the current QuayRegistry condition, deployment generation, config
   bundle checksum, repository count, and a known image digest.
2. Run the database/config backup with object storage disabled.
3. While it runs, confirm pushes fail during read-only mode and pulls continue.
4. Confirm the playbook restores normal mode and pushes work afterward.
5. Run `sha256sum --check SHA256SUMS` and `pg_restore --list backup.dump` using
   a PostgreSQL version compatible with the Quay database.
6. Confirm `quay-registry.yaml` has no `status`, UID, resourceVersion,
   finalizers, or managedFields; confirm exported secrets have no ownerReferences.
7. Confirm the ConfigMap lock exists only while the backup is running and is
   removed after normal-mode verification. Do not run concurrent backups.
8. Validate the emergency recovery playbook only in a planned maintenance
   exercise using a previously captured `config-original.yaml`; do not
   deliberately interrupt a running backup.
9. Enable NooBaa backup, validate TLS, compare the source/destination object
    counts and sizes, and repeat checksum validation.
10. Restore into a fresh homologation namespace/cluster following the supported
    Red Hat procedure: object storage, PostgreSQL, config bundle, managed keys,
    and QuayRegistry. Validate login, pull, push, tags, permissions, and image digests.
11. Record restore duration as the measured RTO and the backup timestamp/data
    gap as the measured RPO.

Do not approve production use until step 10 succeeds from an independently
stored backup.

## Clair database

This project does not back up Clair PostgreSQL. Clair can rebuild its database
by rescanning images, but security reports remain unavailable until rebuilding
finishes. If that recovery time is unacceptable, add and test a separate
Clair PostgreSQL backup matching your topology.

## Retention

Retention is intentionally not automated here because deleting backups without
knowing whether an off-host encrypted copy succeeded is unsafe. Implement
retention in the destination backup platform using at least:

- only `status: complete` manifests as eligible inputs;
- immutable/off-host copies before local expiration;
- daily/monthly retention targets;
- restore-test evidence;
- alerting for missed backups and checksum failures.

## References

- [Red Hat Quay 3.15 backup and restore](https://docs.redhat.com/en/documentation/red_hat_quay/3.15/html/red_hat_quay_operator_features/backing-up-and-restoring-intro)
- [Creating Quay service keys](https://docs.redhat.com/en/documentation/red_hat_quay/3.17/html-single/red_hat_quay_operator_features/index#creating-service-keys-quay-ocp)
