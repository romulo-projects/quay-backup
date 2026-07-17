# Quay Backup

Ansible playbook to back up a Red Hat Quay instance running on OpenShift. It exports QuayRegistry and secrets, switches Quay to read-only, dumps the PostgreSQL database, optionally syncs object storage blobs from NooBaa/ODF S3, then restores normal operation.

**Validated against:** Red Hat Quay **3.15.5**

## Prerequisites

### Binaries

| Binary | Purpose |
|---|---|
| [Ansible](https://docs.ansible.com/) (2.14+ recommended) | Runs the playbook |
| [OpenShift CLI (`oc`)](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) | Interacts with the cluster |
| [AWS CLI (`aws`)](https://aws.amazon.com/cli/) | Syncs S3 blobs when `s3_bucket_odf` is enabled |

### Cluster access

- Valid login to the target cluster (`oc login`)
- Permissions to read Quay resources, update the config bundle secret, and exec into Quay/Postgres pods in the target namespace
- When `s3_bucket_odf` is `true`: access to the NooBaa secret/configmap in the Quay namespace and to the `s3` route in `openshift-storage`

### Read-only service keys

Before running this playbook, the Quay database **must already be prepared** for read-only mode:

- Generate the `quay-readonly` service key pair
- Insert the key into the Quay database (`servicekey` table)
- Add the encoded `quay-readonly.kid` and `quay-readonly.pem` files to the config bundle secret

This playbook only injects the read-only config keys (`REGISTRY_STATE`, `INSTANCE_SERVICE_KEY_*`). It does **not** create the service keys or update the database.

Follow the official procedure:

[Creating service keys for Red Hat Quay on OpenShift Container Platform](https://docs.redhat.com/en/documentation/red_hat_quay/3.17/html-single/red_hat_quay_operator_features/index#creating-service-keys-quay-ocp)

## Usage

1. Edit `group_vars/all.yml` with your Quay instance values.
2. Ensure you are logged in:

```bash
oc whoami
```

3. Confirm required binaries are available:

```bash
oc version --client
aws --version
ansible-playbook --version
```

4. Run the playbook:

```bash
ansible-playbook playbook-backup-quay.yml
```

Backups are written under `backups/<timestamp>/`.

## Variables

Defined in `group_vars/all.yml`:

| Variable | Description |
|---|---|
| `quay_instance` | Name of the QuayRegistry custom resource. |
| `quay_namespace` | OpenShift namespace where Quay is installed. |
| `backup_dir` | Local directory for backup files (timestamped by default). |
| `quay_pod_label` | Label selector used to find the Quay application pod. |
| `quay_readonly_config` | Key/value pairs injected into the config bundle to put Quay in read-only mode. |
| `s3_bucket_odf` | When `true`, syncs NooBaa/ODF S3 blobs into `{{ backup_dir }}/s3_blobs`. |

### `quay_readonly_config` keys

| Key | Description |
|---|---|
| `REGISTRY_STATE` | Sets the registry state (`readonly`). |
| `INSTANCE_SERVICE_KEY_KID_LOCATION` | Path to the read-only service key ID file inside the Quay stack. |
| `INSTANCE_SERVICE_KEY_LOCATION` | Path to the read-only service key PEM file inside the Quay stack. |

### Backup file names

Defined in the playbook (`backup_files`):

| Key | File | Description |
|---|---|---|
| `quay_registry` | `quay-registry.yaml` | QuayRegistry CR export. |
| `managed_secret_keys` | `managed_secret_keys.yaml` | Managed secret keys. |
| `config_bundle` | `config-bundle.yaml` | Full config bundle secret. |
| `quay_bundle_config` | `quay_bundle_config.yaml` | Extracted `config.yaml` from the config bundle. |
| `quay_config` | `quay_config.yaml` | Live `config.yaml` from the Quay pod. |
| `quay_database_sql` | `backup.sql` | PostgreSQL dump. |

When `s3_bucket_odf` is enabled, object storage content is also synced to `s3_blobs/`.

## Project layout

```
.
├── ansible.cfg
├── group_vars/all.yml
├── inventory/hosts.yml
├── playbook-backup-quay.yml
└── backups/                 # backup output (gitignored contents)
```

## References

- [Creating service keys for Red Hat Quay on OpenShift Container Platform](https://docs.redhat.com/en/documentation/red_hat_quay/3.17/html-single/red_hat_quay_operator_features/index#creating-service-keys-quay-ocp)
