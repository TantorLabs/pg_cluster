#!/bin/bash

SYNC_VIP_ALWAYS_AVAILABLE_DEFAULT="false"
NODENAME=$(cat /etc/patroni/{{ inventory_hostname }}.yml | grep -E "^name:" | cut -d: -f2 | tr -d '[:blank:]')

if [[ -z "$NODENAME" ]]; then
   echo "Nodename is blank!"
   exit 1
fi

PATRONICTL_OUT=$(patronictl -c /etc/patroni/{{ inventory_hostname }}.yml list --format json)

if [[ -z "$PATRONICTL_OUT" ]]; then
   echo "No patronictl output!"
   exit 1
fi     

LEADER=$(echo $PATRONICTL_OUT | jq --raw-output ".[] | select ((.Role == \"Leader\") and (.State == \"running\")) | .Member")
SYNC=$(echo $PATRONICTL_OUT | jq --raw-output ".[] | select ((.Role == \"Sync Standby\") and (.State == \"running\")) | .Member")

if [[ "$NODENAME" == "$SYNC" ]]; then
    echo "Is sync!"
    exit 0
else
    if [[ -z "$SYNC" ]] && [[ "$NODENAME" == "$LEADER" ]]; then
          echo "Become sync!"
          exit 0
    else
          echo "Not become sync!"
          exit 1
    fi
fi
