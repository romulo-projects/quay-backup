# Quay Restore

An Ansible playbook for restoring a backup produced by the `quay-backup`
project into a Red Hat Quay instance managed by the Quay Operator on OpenShift.

Validated with Red Hat Quay 3.15.2, managed PostgreSQL, and ODF/NooBaa object
storage.

## Scope and safety

The playbook restores the PostgreSQL dump and, optionally, the S3 blobs. It was
built from the original backup playbook workflow and from a recovery procedure
validated in a non-production environment.

The playbook does not delete any OpenShift resources. Removing the old
`QuayRegistry` and cleaning up its managed resources are deliberately manual
operations. The restore proceeds only after confirming that the old
QuayRegistry, Secrets, PVCs, OBC, and ObjectBucket no longer exist.

Before changing the database, the playbook requires:

- explicit confirmation containing the namespace and instance name;
- valid checksums;
- a dump containing `CREATE DATABASE` and the completion marker;
- a target previously cleaned by the responsible operator;
- an accessible PostgreSQL instance;
- an empty target bucket;
- S3 TLS validated by a local CA.

Sanitized copies of `config-bundle.yaml`, `managed_secret_keys.yaml`, and
`quay-registry.yaml` are generated in a temporary directory with mode `0700`.
Metadata specific to the old resources is removed, Secret data is preserved,
and managed Quay, Clair, and mirror components are scaled to zero replicas. The
original replica state is restored only after the database and S3 recovery.

The S3 synchronization does not use `--delete` or `--no-verify-ssl`.

## Prerequisites

- `ansible-core`, `oc`, `aws`, and `sha256sum`;
- a valid login to the cluster;
- an existing namespace with the Quay Operator running;
- the previous QuayRegistry and its managed resources removed manually;
- a backup containing `backup.sql`, `SHA256SUMS`, and, for S3, `s3_blobs/`;
- a CA capable of validating the S3 route.

Install the Python tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `group_vars/all.yml` and configure:

- `quay_instance` and `quay_namespace`;
- `backup_root`, or set `QUAY_BACKUP_ROOT`;
- `backup_dir`, only when explicitly selecting a backup;
- `quay_database_name`, only when explicitly requiring a database name;
- `restore_s3`;
- `aws_ca_bundle`, only when not using the cluster ingress CA;
- `start_quay_after_restore`;
- `resume_restore`, only when continuing an interrupted execution after the
  new resources have been created.

Use `start_quay_after_restore: true` for the complete restore, validation, and
Quay startup workflow. Use `false` only when you need to inspect the database
and bucket before manually releasing the application with the generated patch.

When `backup_dir` is empty, the most recent directory inside `backup_root` is
selected. When `quay_database_name` is empty, the name is extracted from the
`CREATE DATABASE` statement in `backup.sql`. When `aws_ca_bundle` is empty, the
CA is extracted from `openshift-config-managed/default-ingress-cert` and stored
temporarily with mode `0600`.

By default, the restore workflow is located in this repository's `restore/`
subdirectory and searches for backups in `../backups`, relative to `restore/`.
For a different layout, configure `backup_root` or export
`QUAY_BACKUP_ROOT`.

## Expected layout after backup

Each backup execution must produce its own subdirectory under `backups/`, in
the same repository that contains `restore/`:

```text
quay-backup/
├── backups/
│   └── <YYYYMMDDTHHMMSS>/
│       ├── SHA256SUMS
│       ├── backup.sql
│       ├── config-bundle.yaml
│       ├── managed_secret_keys.yaml
│       ├── quay-registry.yaml
│       ├── quay_bundle_config.yaml
│       ├── quay_config.yaml
│       └── s3_blobs/
│           └── datastorage/
│               └── registry/
│                   └── sha256/
│                       ├── <hash-prefix>/
│                       │   └── <full-hash>
│                       └── ...
├── group_vars/
│   └── all.yml
├── inventory/
│   └── hosts.yml
├── playbook-backup-quay.yml
└── restore/
    ├── README.md
    ├── ansible.cfg
    ├── group_vars/
    │   └── all.yml
    ├── inventory/
    │   └── hosts.yml
    ├── playbook-restore-quay.yml
    ├── requirements.txt
    └── scripts/
        └── prepare_restore.py
```

Files required for every restore:

- `SHA256SUMS`;
- `backup.sql`;
- `config-bundle.yaml`;
- `managed_secret_keys.yaml`;
- `quay-registry.yaml`.

When `restore_s3: true`, the `s3_blobs/` directory is also required. The
`quay_bundle_config.yaml` and `quay_config.yaml` files are useful for auditing,
but are not consumed directly by the restore playbook.

Persistent bundle settings are not lost. The sanitizer preserves all `data`
and `stringData` from `config-bundle.yaml` and removes only old resource
metadata such as `uid`, `resourceVersion`, timestamps, and `ownerReferences`.
The `quay_bundle_config.yaml` file is a readable audit copy; the complete and
authoritative Secret restored by the playbook is `config-bundle.yaml`.

The `restore-work/` directory used during manual testing is not required. The
`prepare_restore.py` script automatically generates sanitized manifests in a
protected temporary directory and removes it at the end. Likewise,
`ingress-ca.pem` is optional: when `aws_ca_bundle` is empty, the CA is obtained
from the OpenShift ingress ConfigMap. Other repository directories do not take
part in backup discovery or restore execution.

The `SHA256SUMS` file must cover the backup artifacts and blobs. Before the
restore, the playbook runs `sha256sum --check SHA256SUMS` and stops if any file
is missing or modified. Keep the backup directory at mode `0700` and sensitive
files at mode `0600`.

## Local validation

```bash
yamllint .
ansible-lint
ansible-playbook --syntax-check playbook-restore-quay.yml
```

## Execution

Run every command in this section from the `restore/` directory. This ensures
that Ansible loads `restore/ansible.cfg`, the restore inventory, and the
restore-specific variables:

```bash
cd restore
```

Explicitly select the backup to restore, especially when more than one
directory exists under `../backups`:

```bash
export RESTORE_BACKUP_DIR="$(realpath ../backups/<YYYYMMDDTHHMMSS>)"
test -d "$RESTORE_BACKUP_DIR" && printf 'Selected backup: %s\n' "$RESTORE_BACKUP_DIR"
```

The following examples use `RESTORE_BACKUP_DIR`. If `backup_dir` is omitted,
the playbook continues to select the most recent directory inside
`backup_root` automatically.

### Non-destructive preflight

Always run the preflight first. It validates files, checksums, names,
manifests, permissions, cluster access, and API Server compatibility. It then
reports the target and discovered resources and exits before creating or
restoring anything:

```bash
ansible-playbook playbook-restore-quay.yml \
  -e backup_dir="$RESTORE_BACKUP_DIR" \
  -e '{
    "quay_instance": "quay-example",
    "quay_namespace": "quay-example",
    "preflight_only": true,
    "resume_restore": false,
    "restore_confirmation": "PREFLIGHT quay-example/quay-example"
  }'
```

The result contains `PREFLIGHT CONCLUÍDO; nenhum recurso do cluster foi
alterado.` and reports whether the target is ready. While the current
QuayRegistry exists, it reports that manual cleanup is not complete.

Use JSON with `-e` whenever a value contains spaces. The format
`-e 'restore_confirmation=PREFLIGHT ...'` does not preserve the complete phrase
correctly in every Ansible version.

### Manual cleanup of the old environment

The playbook does not perform deletions. Record the current resources before
removing the QuayRegistry:

```bash
export QUAY_INSTANCE="quay-example"
export QUAY_NAMESPACE="quay-example"

export CONFIG_SECRET="$(
  oc get quayregistry "$QUAY_INSTANCE" -n "$QUAY_NAMESPACE" \
    -o jsonpath='{.spec.configBundleSecret}'
)"

export OLD_OBJECT_BUCKET="$(
  oc get obc "${QUAY_INSTANCE}-quay-datastore" -n "$QUAY_NAMESPACE" \
    -o jsonpath='{.spec.objectBucketName}'
)"

export OLD_PVS="$(
  oc get pvc -n "$QUAY_NAMESPACE" \
    -o jsonpath='{range .items[*]}{.spec.volumeName}{"\n"}{end}'
)"
```

Delete only the QuayRegistry. Do not delete the namespace because it may also
contain the Quay Operator:

```bash
oc delete quayregistry "$QUAY_INSTANCE" \
  -n "$QUAY_NAMESPACE" --wait=true --timeout=10m
```

Wait for the managed resources to be removed:

```bash
oc get pods,pvc,obc,route,quayregistry -n "$QUAY_NAMESPACE"
oc get objectbucket "$OLD_OBJECT_BUCKET" --ignore-not-found

for pv in $OLD_PVS; do
  oc get pv "$pv" --ignore-not-found
done
```

Do not forcibly remove finalizers. The restored config bundle does not have
`ownerReferences` and may remain after the QuayRegistry is removed. Delete
only the exact Secrets below if they still exist:

```bash
oc delete secret \
  "$CONFIG_SECRET" \
  "${QUAY_INSTANCE}-quay-registry-managed-secret-keys" \
  -n "$QUAY_NAMESPACE" --ignore-not-found --wait=true
```

Run the preflight again and proceed only when it reports:

```text
Destino pronto para restore: sim
```

### Complete restore after manual cleanup

After manually removing the old QuayRegistry and confirming that its managed
resources are gone, run the restore. The playbook recreates the Secrets and
QuayRegistry from the backup, but does not perform any deletions.

To restore, validate, and start Quay automatically:

```bash
ansible-playbook playbook-restore-quay.yml \
  -e backup_dir="$RESTORE_BACKUP_DIR" \
  -e '{
    "quay_instance": "quay-example",
    "quay_namespace": "quay-example",
    "preflight_only": false,
    "resume_restore": false,
    "start_quay_after_restore": true,
    "restore_confirmation": "RESTORE quay-example/quay-example"
  }'
```

If those variables are already correct in `group_vars/all.yml`, only the
confirmation is required:

```bash
ansible-playbook playbook-restore-quay.yml \
  -e backup_dir="$RESTORE_BACKUP_DIR" \
  -e '{"restore_confirmation":"RESTORE quay-example/quay-example"}'
```

To inspect the database and S3 before starting the application, use
`start_quay_after_restore: false`. Then apply the complete patch generated by
the playbook. The patch correctly restores Quay, Clair, mirror, and HPA when
applicable:

```bash
oc patch quayregistry quay-example -n quay-example --type=json \
  --patch-file restore-state/quay-example-start-patch.json
oc wait quayregistry/quay-example -n quay-example \
  --for=condition=Available=true --timeout=15m
```

The playbook remains blocked unless the confirmation text exactly matches the
configured values.

### Resuming after a failure

Use resume mode only when execution fails after creating the QuayRegistry,
Secrets, and OBC, but before restoring the database and S3. Do not delete the
resources or repeat normal mode. Correct the cause and resume with the specific
confirmation:

```bash
ansible-playbook playbook-restore-quay.yml \
  -e backup_dir="$RESTORE_BACKUP_DIR" \
  -e '{
    "quay_instance": "quay-example",
    "quay_namespace": "quay-example",
    "resume_restore": true,
    "start_quay_after_restore": true,
    "restore_confirmation": "RESUME RESTORE quay-example/quay-example"
  }'
```

Resume mode requires the new QuayRegistry, OBC, and both Secrets to exist. It
also confirms again that consumers are stopped and that the bucket is empty
before replacing the new database or uploading blobs.

If the failure occurs after `Restore PostgreSQL dump` or `Restore S3 blobs to
empty target bucket`, do not resume automatically. Validate the database and
S3 and, if they are correct, start Quay with the patch under `restore-state/`.
The empty-bucket protection correctly blocks another attempt over restored
data.

### S3 validation on NooBaa

NooBaa may return `KeyCount: null` for `s3api list-objects-v2`. Therefore, the
playbook uses `aws s3 ls --recursive --summarize` and compares both the number
of objects and the total bytes. Expected output has this format:

```text
Total Objects: <object-count>
Total Size: <total-bytes>
```

### Final validation

```bash
oc wait quayregistry/quay-example -n quay-example \
  --for=condition=Available=true --timeout=15m
oc get pods,pvc,obc,route,quayregistry -n quay-example
```

Validate the restored database:

```bash
DB_POD="$(
  oc get pod -n quay-example -l quay-component=postgres \
    -o jsonpath='{.items[0].metadata.name}'
)"

oc exec -n quay-example "$DB_POD" -- \
  psql -d quay-example-quay-database -Atc \
  "SELECT 'users', count(*)::text FROM public.\"user\"
   UNION ALL SELECT 'repositories', count(*)::text FROM public.repository
   UNION ALL SELECT 'manifests', count(*)::text FROM public.manifest
   UNION ALL SELECT 'tags', count(*)::text FROM public.tag;"
```

Finish by logging in and pulling a known image:

```bash
podman login quay.apps.example.com
podman pull \
  quay.apps.example.com/example-user/example-repository:v1
```

In production with managed Clair, the backup manifest must contain both
`clair` and `clairpostgres` with `managed: true`. The Clair database is
recreated empty by the Operator and images are scanned again. Vulnerability
reports remain unavailable until reprocessing finishes.

A successful pull validates the complete path across authentication,
PostgreSQL metadata, the manifest, and S3 blobs.

## Sensitive data

Backups contain Secrets, credentials, and private keys. Keep files at mode
`0600`, the backup directory at mode `0700`, never commit backups, and rotate
keys after exercises in which their values were exposed.
