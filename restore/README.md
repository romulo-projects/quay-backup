# Quay Restore

Playbook Ansible para restaurar um backup produzido pelo projeto `quay-backup`
em uma instância Red Hat Quay gerenciada pelo Quay Operator no OpenShift.

Validado com Red Hat Quay 3.15.2, PostgreSQL gerenciado e object storage
ODF/NooBaa.

## Escopo e segurança

O playbook restaura o dump PostgreSQL e, opcionalmente, os blobs S3. Ele foi
construído a partir do fluxo do playbook de backup original e do procedimento
de recuperação validado em homologação.

O playbook não exclui nenhum recurso do OpenShift. A remoção do `QuayRegistry`
antigo e a limpeza dos recursos gerenciados são deliberadamente manuais. O
restore só prossegue quando confirma que QuayRegistry, Secrets, PVCs, OBC e
ObjectBucket antigos não existem mais.
Antes de qualquer alteração no banco, o playbook exige:

- confirmação explícita contendo namespace e instância;
- checksums válidos;
- dump com `CREATE DATABASE` e marcador de conclusão;
- destino previamente limpo pelo operador responsável;
- PostgreSQL acessível;
- bucket de destino vazio;
- TLS do S3 validado por uma CA local.

Cópias sanitizadas de `config-bundle.yaml`,
`managed_secret_keys.yaml` e `quay-registry.yaml` são geradas em diretório
temporário `0700`. Metadados específicos do recurso antigo são removidos, os
dados dos Secrets são preservados e Quay, Clair e mirror são colocados em zero
réplicas quando estiverem gerenciados. O estado original é restaurado somente
depois do banco e do S3.

O sync S3 não usa `--delete` nem `--no-verify-ssl`.

## Pré-requisitos

- `ansible-core`, `oc`, `aws` e `sha256sum`;
- login válido no cluster;
- namespace existente e Quay Operator em execução;
- QuayRegistry anterior e seus recursos gerenciados removidos manualmente;
- backup contendo `backup.sql`, `SHA256SUMS` e, para S3, `s3_blobs/`;
- CA capaz de validar a rota S3.

Instalação das ferramentas Python:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuração

Edite `group_vars/all.yml` e configure:

- `quay_instance` e `quay_namespace`;
- `backup_root`, ou defina `QUAY_BACKUP_ROOT`;
- `backup_dir`, somente para escolher explicitamente um backup;
- `quay_database_name`, somente para exigir explicitamente um nome;
- `restore_s3`;
- `aws_ca_bundle`, somente se não quiser usar a CA do ingress do cluster;
- `start_quay_after_restore`;
- `resume_restore`, somente para continuar uma execução interrompida depois da
  criação dos recursos novos.

Use `start_quay_after_restore: true` para o fluxo completo restaurar, validar e
iniciar o Quay. Use `false` somente quando quiser inspecionar banco e bucket
antes de liberar a aplicação manualmente com o patch gerado.

Quando `backup_dir` estiver vazio, o diretório mais recente dentro de
`backup_root` será selecionado. Quando `quay_database_name` estiver vazio, o
nome será extraído do `CREATE DATABASE` em `backup.sql`. Se `aws_ca_bundle`
estiver vazio, a CA será obtida de
`openshift-config-managed/default-ingress-cert` e armazenada temporariamente
com modo `0600`.

Por padrão, o restore fica no subdiretório `restore/` deste repositório e
procura os backups em `../backups`, relativo a `restore/`. Para outra estrutura,
configure `backup_root` ou exporte `QUAY_BACKUP_ROOT`.

## Estrutura esperada após o backup

Cada execução do backup deve produzir um subdiretório próprio dentro de
`backups/`, no mesmo repositório que contém `restore/`:

```text
quay-backup/
├── backups/
│   └── <AAAAMMDDTHHMMSS>/
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
│                       ├── <prefixo-do-hash>/
│                       │   └── <hash-completo>
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

Arquivos obrigatórios para qualquer restore:

- `SHA256SUMS`;
- `backup.sql`;
- `config-bundle.yaml`;
- `managed_secret_keys.yaml`;
- `quay-registry.yaml`.

Quando `restore_s3: true`, o diretório `s3_blobs/` também é obrigatório. Os
arquivos `quay_bundle_config.yaml` e `quay_config.yaml` são úteis para auditoria,
mas não são consumidos diretamente pelo playbook de restore.

As configurações persistentes do bundle não são perdidas: o sanitizador preserva
integralmente `data` e `stringData` de `config-bundle.yaml` e remove somente
metadados do recurso antigo, como `uid`, `resourceVersion`, timestamps e
`ownerReferences`. O arquivo `quay_bundle_config.yaml` é uma cópia legível para
auditoria; o Secret completo e autoritativo restaurado é `config-bundle.yaml`.

O diretório `restore-work/` usado no teste manual não é necessário. O script
`prepare_restore.py` gera automaticamente manifests sanitizados em um diretório
temporário protegido e o remove ao final. Da mesma forma, `ingress-ca.pem` é
opcional: quando `aws_ca_bundle` estiver vazio, a CA é obtida do ConfigMap de
ingress do OpenShift. Outros diretórios do repositório não participam da
descoberta nem da execução do restore.

O arquivo `SHA256SUMS` deve conter os artefatos e blobs do backup. Antes do
restore, o playbook executa `sha256sum --check SHA256SUMS` e interrompe se algum
arquivo estiver ausente ou alterado. Mantenha o diretório do backup com modo
`0700` e os arquivos sensíveis com `0600`.

## Validação local

```bash
yamllint .
ansible-lint
ansible-playbook --syntax-check playbook-restore-quay.yml
```

## Execução

Execute todos os comandos desta seção a partir do diretório `restore/`. Isso
garante que o Ansible carregue `restore/ansible.cfg`, o inventário e as
variáveis específicas do restore:

```bash
cd restore
```

Selecione explicitamente o backup que será restaurado, especialmente quando
existir mais de um diretório em `../backups`:

```bash
export RESTORE_BACKUP_DIR="$(realpath ../backups/<AAAAMMDDTHHMMSS>)"
test -d "$RESTORE_BACKUP_DIR" && printf 'Backup selecionado: %s\n' "$RESTORE_BACKUP_DIR"
```

Os exemplos seguintes utilizam `RESTORE_BACKUP_DIR`. Se `backup_dir` não for
informado, o playbook continuará selecionando automaticamente o diretório mais
recente dentro de `backup_root`.

### Preflight sem alterações no cluster

Execute primeiro o preflight. Ele valida arquivos, checksums, nomes, manifests,
permissões, acesso ao cluster e compatibilidade no API Server. Depois exibe o
alvo e os recursos encontrados e encerra antes de qualquer criação ou restore:

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

O resultado contém `PREFLIGHT CONCLUÍDO; nenhum recurso do cluster foi
alterado.` e informa se o destino já está pronto. Enquanto o QuayRegistry atual
existir, mostrará que a limpeza manual ainda não foi concluída.

Use JSON no `-e` sempre que o valor contiver espaços. O formato
`-e 'restore_confirmation=PREFLIGHT ...'` não preserva corretamente a frase
completa em todas as versões do Ansible.

### Limpeza manual do ambiente antigo

O playbook não executa exclusões. Registre os recursos atuais antes de remover o
QuayRegistry:

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

Exclua somente o QuayRegistry. Não exclua o namespace, pois ele pode conter o
Quay Operator:

```bash
oc delete quayregistry "$QUAY_INSTANCE" \
  -n "$QUAY_NAMESPACE" --wait=true --timeout=10m
```

Aguarde a remoção dos recursos gerenciados:

```bash
oc get pods,pvc,obc,route,quayregistry -n "$QUAY_NAMESPACE"
oc get objectbucket "$OLD_OBJECT_BUCKET" --ignore-not-found

for pv in $OLD_PVS; do
  oc get pv "$pv" --ignore-not-found
done
```

Não remova finalizers à força. O config bundle restaurado não possui
`ownerReferences` e pode permanecer após a remoção do QuayRegistry. Remova
somente os Secrets exatos, se ainda existirem:

```bash
oc delete secret \
  "$CONFIG_SECRET" \
  "${QUAY_INSTANCE}-quay-registry-managed-secret-keys" \
  -n "$QUAY_NAMESPACE" --ignore-not-found --wait=true
```

Execute novamente o preflight e prossiga somente quando aparecer:

```text
Destino pronto para restore: sim
```

### Restore completo após a limpeza manual

Depois que você remover manualmente o QuayRegistry antigo e confirmar a limpeza
dos recursos gerenciados, execute o restore. O playbook recria os Secrets e o
QuayRegistry a partir do backup, mas não executa nenhuma exclusão.

Para restaurar, validar e iniciar o Quay automaticamente:

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

Se essas variáveis já estiverem corretas em `group_vars/all.yml`, basta informar
a confirmação:

```bash
ansible-playbook playbook-restore-quay.yml \
  -e backup_dir="$RESTORE_BACKUP_DIR" \
  -e '{"restore_confirmation":"RESTORE quay-example/quay-example"}'
```

Para inspecionar banco e S3 antes de iniciar a aplicação, use
`start_quay_after_restore: false`. Depois aplique o patch completo gerado pelo
playbook; ele restaura corretamente Quay, Clair, mirror e HPA quando aplicável:

```bash
oc patch quayregistry quay-example -n quay-example --type=json \
  --patch-file restore-state/quay-example-start-patch.json
oc wait quayregistry/quay-example -n quay-example \
  --for=condition=Available=true --timeout=15m
```

O playbook permanece bloqueado se o texto não corresponder exatamente aos
valores configurados.

### Retomada após falha

Use a retomada somente quando a execução falhar depois de criar QuayRegistry,
Secrets e OBC, mas antes de restaurar banco e S3. Não exclua os recursos nem
repita o modo normal. Corrija a causa e retome com confirmação específica:

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

A retomada exige que QuayRegistry, OBC e os dois Secrets novos existam. Ela
também confirma novamente que os consumidores estão parados e que o bucket está
vazio antes de substituir o banco novo ou enviar blobs.

Se a falha ocorrer depois de `Restore PostgreSQL dump` ou `Restore S3 blobs to
empty target bucket`, não use a retomada automaticamente. Valide banco e S3 e,
se estiverem corretos, inicie o Quay com o patch em `restore-state/`. A proteção
de bucket vazio bloqueará corretamente uma nova tentativa sobre dados já
restaurados.

### Validação do S3 no NooBaa

O NooBaa pode retornar `KeyCount: null` em `s3api list-objects-v2`. Por isso, o
playbook usa `aws s3 ls --recursive --summarize` e compara tanto a quantidade de
objetos quanto o total de bytes. O resultado esperado terá o seguinte formato:

```text
Total Objects: <quantidade-de-objetos>
Total Size: <total-em-bytes>
```

### Validação final

```bash
oc wait quayregistry/quay-example -n quay-example \
  --for=condition=Available=true --timeout=15m
oc get pods,pvc,obc,route,quayregistry -n quay-example
```

Valide o banco restaurado:

```bash
DB_POD="$(
  oc get pod -n quay-example -l quay-component=postgres \
    -o jsonpath='{.items[0].metadata.name}'
)"

oc exec -n quay-example "$DB_POD" -- \
  psql -d quay-example-quay-database -Atc \
  "SELECT 'usuarios', count(*)::text FROM public.\"user\"
   UNION ALL SELECT 'repositorios', count(*)::text FROM public.repository
   UNION ALL SELECT 'manifestos', count(*)::text FROM public.manifest
   UNION ALL SELECT 'tags', count(*)::text FROM public.tag;"
```

Finalize com login e pull de uma imagem conhecida:

```bash
podman login quay.apps.example.com
podman pull \
  quay.apps.example.com/example-user/example-repository:v1
```

Em produção com Clair gerenciado, o manifesto de backup deve conter tanto
`clair` quanto `clairpostgres` com `managed: true`. O banco do Clair é recriado
vazio pelo Operator e as imagens são examinadas novamente; relatórios de
vulnerabilidade ficam indisponíveis até o reprocessamento terminar.

O pull comprova o fluxo completo entre autenticação, metadados PostgreSQL,
manifesto e blobs S3.

## Dados sensíveis

Os backups incluem Secrets, credenciais e chaves privadas. Mantenha os arquivos
com modo `0600`, o diretório com `0700`, não versione backups e faça rotação das
chaves após exercícios em que os valores tenham sido expostos.
