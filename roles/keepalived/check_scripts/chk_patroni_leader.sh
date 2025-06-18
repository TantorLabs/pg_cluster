#!/bin/bash

NODENAME=$(cat {{ patroni_config_dir }}/{{ inventory_hostname }}.yml | grep -E "^name:" | cut -d: -f2 | tr -d '[:blank:]')

if [[ -z "$NODENAME" ]]; then
   echo "Nodename is blank!"
   exit 1
fi

PATRONICTL_OUT=$(/opt/tantor/usr/bin/patronictl -c {{ patroni_config_dir }}/{{ inventory_hostname }}.yml list --format json)

if [[ -z "$PATRONICTL_OUT" ]]; then
   echo "No patronictl output!"
   exit 1
fi     

LEADER=$(echo $PATRONICTL_OUT | jq --raw-output ".[] | select ((.Role == \"Leader\") and (.State == \"running\")) | .Member")

if [[ "$NODENAME" == "$LEADER" ]]; then
    echo "Is leader!"
    exit 0
else
    echo "Is not leader!"
    exit 1
fi
