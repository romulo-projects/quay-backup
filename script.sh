#!/bin/bash
QUAY_INSTANCE="quay-diolivei"
QUAY_NAMESPACE="diolivei"
QUAY_APP_POD=$(oc get pods -l app=quay -n $QUAY_NAMESPACE -o name | head -n 1)


echo "01-Back the QuayRegistry custom resource"
oc get quayregistry quay-diolivei -n diolivei -o yaml > quay-registry.yaml

echo "02-Backup the managed keys secret"
oc get secret -n $QUAY_NAMESPACE $QUAY_INSTANCE-quay-registry-managed-secret-keys -o yaml > managed_secret_keys.yaml

echo "03-Backup bundle secret"
oc get secret -n $QUAY_NAMESPACE  $(oc get quayregistry "${QUAY_INSTANCE}" -n "${QUAY_NAMESPACE}"  -o jsonpath='{.spec.configBundleSecret}') -o yaml > config-bundle.yaml

echo "04-Backup the /conf/stack/config.yaml file mounted inside of the Quay pods"
oc exec -it ${QUAY_APP_POD} -n ${QUAY_NAMESPACE} -- cat /conf/stack/config.yaml > quay_config.yaml
