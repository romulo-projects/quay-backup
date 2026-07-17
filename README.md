# Quay Backup

Ansible playbook to back up a Red Hat Quay instance running on OpenShift. It exports QuayRegistry and secrets, switches Quay to read-only, dumps the PostgreSQL database, then restores normal operation.

## Prerequisites

- [Ansible](https://docs.ansible.com/) (2.14+ recommended)
- [OpenShift CLI (`oc`)](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html)
- Valid login to the target cluster (`oc login`)
- Permissions to read Quay resources and exec into Quay/Postgres pods in the target namespace

## Usage

1. Edit `group_vars/all.yml` with your Quay instance values.
2. Ensure you are logged in:

```bash
oc whoami
```

3. Run the playbook:

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

## Project layout

```
.
├── ansible.cfg
├── group_vars/all.yml
├── inventory/hosts.yml
├── playbook-backup-quay.yml
└── backups/                 # backup output (gitignored contents)
```
