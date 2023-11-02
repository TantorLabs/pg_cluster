#!/bin/bash
#set -ex

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
ASYNC=$(echo $PATRONICTL_OUT | jq --raw-output ".[] | select ((.Role == \"Replica\") and (.State == \"running\")) | .Member")

function become-async {
   if [[ "$NODENAME" == "$SYNC" ]]; then
         echo "Become async!"
         exit 0
      else
         if [[ -z "$SYNC" ]] && [[ "$NODENAME" == "$LEADER" ]]; then
            echo "Become async!"
            exit 0
         else
            echo "Not become async!"
            exit 1
         fi
   fi
}

if [[ -z "$NODENAME" ]]; then
   echo "Nodename is blank!"
   exit 1
fi

if [[ -z "$PATRONICTL_OUT" ]]; then
   echo "No patronictl output!"
   exit 1
fi      

if [[ " ${ASYNC[*]} " =~ "$NODENAME" ]]; then
   echo "Is async!"
   exit 0
else
   become-async
fi

