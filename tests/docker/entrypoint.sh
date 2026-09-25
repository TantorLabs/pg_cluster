#!/bin/bash
set -euo pipefail

# entrypoint.sh — prepare the controller container before running tests
#
# 1. Generate SSH key if missing
# 2. Distribute it to all target nodes
# 3. Populate known_hosts

rm -f /tmp/controller-ready

SSH_KEY=/root/.ssh/id_ed25519
KNOWN_HOSTS=/root/.ssh/known_hosts

# Generate SSH key pair if not present
if [ ! -f "$SSH_KEY" ]; then
    ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -q
    chmod 600 "$SSH_KEY"
fi

PUB_KEY=$(cat "${SSH_KEY}.pub")

# Wait for all nodes to be reachable via SSH
NODES="pg-node1 pg-node2 pg-node3"
for node in $NODES; do
    echo "Waiting for ${node} SSH..."
    ready=false
    for i in $(seq 1 60); do
        if sshpass -p deploy ssh \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o ConnectTimeout=3 \
            deploy@${node} true 2>/dev/null; then
            ready=true
            break
        fi
        sleep 2
    done
    if [ "$ready" != true ]; then
        echo "Timed out waiting for ${node} SSH" >&2
        exit 1
    fi
done

# Distribute the public key to all nodes
for node in $NODES; do
    # Try deploy user with known password
    sshpass -p deploy ssh-copy-id \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -i "$SSH_KEY" \
        deploy@${node} 2>/dev/null

    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3 deploy@${node} true

    # Also set up root access
    sshpass -p deploy ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        deploy@${node} \
        "sudo mkdir -p /root/.ssh && echo '$PUB_KEY' | sudo tee /root/.ssh/authorized_keys > /dev/null && sudo chmod 600 /root/.ssh/authorized_keys" 2>/dev/null
done

# Populate known_hosts
for node in $NODES; do
    ssh-keyscan -H "$node" >> "$KNOWN_HOSTS" 2>/dev/null
done

touch /tmp/controller-ready
echo "Controller is ready."
exec "$@"
